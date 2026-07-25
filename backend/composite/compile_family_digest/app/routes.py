import html
import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from pydantic import BaseModel

from trace_auth import forwarded_auth_headers

bp = Blueprint("compile_family_digest", __name__)

DOWNSTREAM_TIMEOUT_S = 130
EXPOSURE_PROFILES_SERVICE_URL = os.environ.get("EXPOSURE_PROFILES_SERVICE_URL", "http://exposure_profiles:5005")
USERS_SERVICE_URL = os.environ.get("USERS_SERVICE_URL", "http://users:5001")
RESEND_API_URL = "https://api.resend.com/emails"
CATEGORIES = ("face", "location", "document", "metadata", "contact", "financial", "credentials")
FIXED_HEADLINE = "Hey there! Your Trace Weekly Digest is here! 🔍"
CATEGORY_ICONS = {
    "face": "👤",
    "location": "📍",
    "document": "📄",
    "metadata": "🔍",
    "contact": "📱",
    "financial": "💳",
    "credentials": "🔑",
}
CATEGORY_MEANINGS = {
    "location": (
        "help someone figure out the places you visit, live near, or spend time regularly"
    ),
    "face": "identify people in your life — friends, family, or yourself — without their knowledge",
    "metadata": "reveal hidden details like exactly where and when a photo was taken",
    "contact": "expose ways for strangers to reach you directly",
    "document": "leak personal information from IDs, forms, or screens in the background",
    "financial": "hint at spending habits or financial details you wouldn't share openly",
    "credentials": "give others access to your accounts or personal logins",
}
CATEGORY_RISKS = {
    "face": (
        "Face clues can carry extra risk because they may connect a post to real people, "
        "friends, or familiar places."
    ),
    "location": (
        "Location clues carry higher risk because they can help someone build a picture "
        "of where you spend your time."
    ),
    "document": (
        "Document clues can carry extra risk because names, schools, schedules, or private "
        "details may be visible in the background."
    ),
    "metadata": (
        "Metadata clues can carry extra risk because they may quietly reveal when or where "
        "something was captured."
    ),
    "contact": (
        "Contact clues can carry extra risk because they may make it easier for someone to "
        "message or target you directly."
    ),
    "financial": (
        "Financial clues can carry extra risk because they may reveal purchases, accounts, "
        "or family routines."
    ),
    "credentials": (
        "Credential clues carry higher risk because they could give others access to accounts "
        "or personal logins."
    ),
}
CATEGORY_NARRATIVES = {
    "face": (
        "Face was the main theme this week. It is one of the clues people notice quickly, "
        "especially when friends, uniforms, or familiar surroundings are also in the frame. "
        "The good news is everything was caught before posting. Keep that streak going 👍"
    ),
    "location": (
        "Location was the main theme this week — and it is one of the sneakier ones, since "
        "it often hides in the background of a photo rather than the caption itself. The good "
        "news is everything was caught before posting. Keep that streak going 👍"
    ),
    "document": (
        "Document details were the main theme this week. These can be easy to miss when they "
        "are sitting on a desk, screen, notebook, or noticeboard in the background. The good "
        "news is everything was caught before posting. Keep that streak going 👍"
    ),
    "metadata": (
        "Metadata was the main theme this week. It can feel invisible, but timestamps and file "
        "details may still say more than expected. The good news is everything was caught before "
        "posting. Keep that streak going 👍"
    ),
    "contact": (
        "Contact details were the main theme this week. Even small bits of contact info can make "
        "it easier for someone to reach, target, or connect accounts. The good news is everything "
        "was caught before posting. Keep that streak going 👍"
    ),
    "financial": (
        "Financial details were the main theme this week. Receipts, cards, payment screens, and "
        "purchase clues can reveal more about routines than they seem to. The good news is "
        "everything was caught before posting. Keep that streak going 👍"
    ),
    "credentials": (
        "Credentials were the main theme this week. Login details and access codes are especially "
        "sensitive because they can open the door to accounts directly. The good news is everything "
        "was caught before posting. Keep that streak going 👍"
    ),
}
CATEGORY_PROMPTS = {
    "face": [
        "When friends or family show up in a photo, what makes it okay to share?",
        "What would you check differently before posting a face or group photo next time?",
    ],
    "location": [
        "When does sharing where you are feel useful, and when does it start to feel too revealing?",
        "What would you check differently next time a photo might show where you spend time?",
    ],
    "document": [
        "What kinds of papers, screens, or school details do you think are worth checking before posting?",
        "How would you decide whether a background detail is harmless or too personal?",
    ],
    "metadata": [
        "How much do you think a photo can reveal even when the caption says very little?",
        "What hidden details would you want to check differently before you post?",
    ],
    "contact": [
        "What contact details feel okay to share online, and what should stay private?",
        "What would you do differently if a photo accidentally showed a phone number, email, or handle?",
    ],
    "financial": [
        "What money-related details would you want to keep out of photos or videos?",
        "What would you check differently before posting something that includes receipts, cards, or payment screens?",
    ],
    "credentials": [
        "What kinds of passwords, codes, or login details should never appear in a post?",
        "What would you do differently if you noticed a login detail in the background before posting?",
    ],
}


class DigestPromptCopy(BaseModel):
    score_explanation: str
    discussion_prompts: list[str]


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _category_breakdown_from_rows(profile_rows):
    breakdown = {category: 0 for category in CATEGORIES}
    for row in profile_rows:
        row_breakdown = row.get("category_breakdown") or {}
        for category in CATEGORIES:
            breakdown[category] += int(row_breakdown.get(category, 0) or 0)
    return breakdown


def _rows_from_profile(profile):
    weekly_digest = (profile.get("profile") or {}).get("weekly_digest")
    if not weekly_digest:
        return []
    return [{
        "window_start": weekly_digest.get("window_start"),
        "window_end": weekly_digest.get("window_end"),
        "total_flags": weekly_digest.get("total_flags", 0),
        "category_breakdown": weekly_digest.get("category_breakdown") or {},
        "privacy_health_score": weekly_digest.get("privacy_health_score"),
    }]


def _trajectory_from_rows(profile_rows):
    points = []
    for row in profile_rows:
        score = row.get("privacy_health_score")
        if score is None:
            continue
        points.append({
            "window_start": row.get("window_start"),
            "window_end": row.get("window_end"),
            "privacy_health_score": score,
        })
    return points


def _build_digest_summary(profile_rows, window_start, window_end):
    category_breakdown = _category_breakdown_from_rows(profile_rows)
    total_flags = sum(category_breakdown.values())
    trajectory = _trajectory_from_rows(profile_rows)
    active_category_breakdown = _active_categories(category_breakdown)
    dominant_category = _top_category(active_category_breakdown)
    return {
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "total_flags": total_flags,
        "category_breakdown": category_breakdown,
        "active_category_breakdown": active_category_breakdown,
        "generalized_category_summary": {
            category: _category_volume_label(count, total_flags)
            for category, count in active_category_breakdown.items()
        },
        "dominant_category": dominant_category,
        "privacy_health_trajectory": trajectory,
        "latest_privacy_health_score": trajectory[-1]["privacy_health_score"] if trajectory else None,
        "has_activity": bool(profile_rows) and total_flags > 0,
    }


def _active_categories(category_counts):
    return {
        category: count for category, count in category_counts.items() if count > 0
    }


def _top_category(active_categories):
    return max(active_categories, key=active_categories.get) if active_categories else "general"


def _generalized_category_summary(summary):
    generalized = summary.get("generalized_category_summary")
    if generalized is not None:
        return generalized
    total_flags = summary.get("total_flags", 0)
    return {
        category: _category_volume_label(count, total_flags)
        for category, count in (summary.get("active_category_breakdown") or {}).items()
    }


def _dominant_category(summary):
    if summary.get("dominant_category"):
        return summary["dominant_category"]
    active_breakdown = summary.get("active_category_breakdown") or {}
    return _top_category(active_breakdown)


def _category_volume_label(count, total):
    if total > 0 and count == total and total > 1:
        return "mostly"
    if count <= 2:
        return "a few"
    return "several"


def _score(summary):
    score = summary.get("latest_privacy_health_score")
    if score is None:
        return 100 if not summary["has_activity"] else 70
    return int(score)


def _score_rating(score):
    if score >= 80:
        return "Great week — your privacy game is strong 💪"
    if score >= 60:
        return "Decent week — a few things to keep an eye on 👀"
    if score >= 40:
        return "Mixed week — some patterns worth talking about 🤔"
    return "Tough week — a good one to reflect on together 💬"


def _score_explanation(summary):
    if not summary["has_activity"]:
        return "No categories fired this week, so the score stayed high."

    dominant = _dominant_category(summary)
    if dominant == "general":
        return (
            "General privacy clues pulled the score down because small details can add up over time. "
            "The good news is Trace caught them before they went public."
        )
    meaning = CATEGORY_MEANINGS.get(dominant, "expose sensitive information")
    return (
        f"{dominant.title()} clues pulled the score down because they could {meaning}. "
        "The good news is Trace caught them before they went public."
    )


def _category_volume_word(count):
    return "few" if count <= 2 else "number of"


def _category_line(category, count):
    icon = CATEGORY_ICONS.get(category, "•")
    name = category.title()
    volume = _category_volume_word(count)
    meaning = CATEGORY_MEANINGS.get(category, "expose sensitive information")
    return (
        f"{icon} {name}: A {volume} posts this week had {category}-related clues "
        f"that could {meaning}."
    )


def _category_lines(active_categories):
    return {
        category: _category_line(category, count)
        for category, count in active_categories.items()
    }


def _narrative(summary):
    if not summary["has_activity"]:
        return (
            "This was a pretty calm week for privacy clues. Trace did not spot patterns that would make it easy "
            "for someone to learn where you go, who you are with, or how to reach you. Keep that streak going 👍"
        )

    dominant = _dominant_category(summary)
    if dominant == "general":
        return (
            "This was a useful week to keep practicing the pause-before-posting habit. "
            "Small clues can add up over time, even when each one seems harmless on its own."
        )
    return CATEGORY_NARRATIVES[dominant]


def _discussion_prompts(summary):
    dominant = _dominant_category(summary)
    if dominant == "general":
        return [
            "What kind of small detail do you think is easiest to miss before posting?",
            "What helps a post feel safe to share, even when it includes everyday moments?",
        ]
    return CATEGORY_PROMPTS[dominant]


def _fallback_digest_copy(summary):
    score = _score(summary)
    active_categories = summary.get("active_category_breakdown") or {}
    return {
        "headline": FIXED_HEADLINE,
        "score_section": {
            "score": score,
            "rating": _score_rating(score),
            "explanation": _score_explanation(summary),
        },
        "category_breakdown": _category_lines(active_categories),
        "narrative": _narrative(summary),
        "discussion_prompts": _discussion_prompts(summary),
    }


def _generate_digest_copy(summary):
    if not summary["has_activity"] or not os.environ.get("OPENAI_API_KEY"):
        return _fallback_digest_copy(summary)

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=os.environ.get("DIGEST_LLM_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        api_key=os.environ["OPENAI_API_KEY"],
    )
    structured_llm = llm.with_structured_output(DigestPromptCopy, method="function_calling")
    messages = [{"role": "user", "content": _build_llm_digest_prompt(summary)}]
    try:
        result = structured_llm.invoke(messages)
    except Exception:
        return _fallback_digest_copy(summary)
    fallback = _fallback_digest_copy(summary)
    llm_copy = result.model_dump()
    digest_copy = fallback
    digest_copy["score_section"]["explanation"] = (
        llm_copy.get("score_explanation") or fallback["score_section"]["explanation"]
    )
    digest_copy["discussion_prompts"] = llm_copy.get("discussion_prompts", [])[:2]
    while len(digest_copy["discussion_prompts"]) < 2:
        fallback_index = len(digest_copy["discussion_prompts"])
        digest_copy["discussion_prompts"].append(fallback["discussion_prompts"][fallback_index])
    return digest_copy


def _build_llm_digest_prompt(summary):
    prompt_input = _llm_digest_input(summary)
    category_lines = prompt_input["category_lines_text"] or "No categories fired this week."
    return f"""You are writing a weekly privacy digest for a teenager and their family.
Be warm, encouraging, and specific to the data below. Write like a trusted friend,
not a security system. Short sentences. Light personality.

FIXED DATA — use exactly as provided, do not rephrase or summarise differently:
- Headline: "{FIXED_HEADLINE}"
- Period: {prompt_input["period"]}
- Score: {prompt_input["privacy_health_score"]}/100
- Score label: "{prompt_input["score_label"]}"
- Category breakdown (already written — copy exactly):
{category_lines}

YOUR JOB — write only these two sections:

1. SCORE_EXPLANATION (2 sentences max):
   - Sentence 1: Which category drove the score down and why it matters.
     Be specific to "{prompt_input["top_category"]}" — what does this type of leak enable in real life?
   - Sentence 2: One encouraging note — something was caught before it went public.
   - Never mention specific locations, numbers, names, or post content.
   - Never use: "pattern", "seems like", "it appears", "related to",
     "privacy management", "review window"

2. DISCUSSION_PROMPTS (exactly 2):
   - Both must be specific to "{prompt_input["top_category"]}" exposure this week
   - Frame as genuine curiosity, not a quiz
   - First prompt: about how they think about sharing {prompt_input["top_category"]} info online
   - Second prompt: about what they'd do differently going forward
   - Do NOT start with "How do you feel about" — find a more specific opener

Respond with ONLY valid JSON, no other text:
{{
  "score_explanation": "2 sentences max",
  "discussion_prompts": ["prompt 1", "prompt 2"]
}}"""


def _llm_digest_input(summary):
    score = _score(summary)
    active_categories = summary.get("active_category_breakdown") or {}
    top_category = _dominant_category(summary)
    category_lines = _category_lines(active_categories)
    return {
        "period": f"{summary['window_start']} to {summary['window_end']}",
        "privacy_health_score": score,
        "score_rating": _score_rating(score),
        "score_label": _score_rating(score),
        "score_driver_hint": _score_explanation(summary),
        "total_flags": summary["total_flags"],
        "active_categories": active_categories,
        "category_emoji": CATEGORY_ICONS,
        "category_meaning": CATEGORY_MEANINGS,
        "category_lines": category_lines,
        "category_lines_text": "\n".join(category_lines.values()),
        "generalized_category_summary": _generalized_category_summary(summary),
        "dominant_category": top_category,
        "top_category": top_category,
        "has_activity": summary["has_activity"],
    }


def _format_date_range(window_start, window_end):
    if window_start.year == window_end.year:
        return f"{window_start:%d %b} – {window_end:%d %b %Y}"
    return f"{window_start:%d %b %Y} – {window_end:%d %b %Y}"


def _render_digest_email(summary, digest_copy, window_start, window_end):
    category_items = "\n".join(
        f"<p style=\"margin:0 0 12px 0;\">{html.escape(sentence)}</p>"
        for sentence in digest_copy["category_breakdown"].values()
    ) or "<p style=\"margin:0 0 12px 0;\">No categories fired this week.</p>"
    prompt_items = "\n".join(
        f"<p style=\"margin:0 0 10px 0;\">&quot;{html.escape(prompt)}&quot;</p>"
        for prompt in digest_copy["discussion_prompts"]
    )
    score_section = digest_copy["score_section"]
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f8fafc;">
    <main style="font-family:Arial,sans-serif;color:#1f2937;line-height:1.5;max-width:560px;margin:0 auto;padding:28px 20px;background:#ffffff;">
      <h1 style="font-size:22px;line-height:1.25;margin:0 0 6px 0;">{html.escape(digest_copy["headline"])}</h1>
      <p style="margin:0 0 24px 0;color:#4b5563;">{html.escape(_format_date_range(window_start, window_end))}</p>

      <h2 style="font-size:16px;margin:0 0 6px 0;">Your score</h2>
      <p style="font-size:26px;line-height:1.1;margin:0 0 6px 0;"><strong>{score_section["score"]}/100</strong></p>
      <p style="margin:0 0 8px 0;">{html.escape(score_section["rating"])}</p>
      <p style="margin:0 0 24px 0;">{html.escape(score_section["explanation"])}</p>

      <h2 style="font-size:16px;margin:0 0 8px 0;">What Trace noticed this week</h2>
      {category_items}

      <h2 style="font-size:16px;margin:24px 0 8px 0;">The bigger picture</h2>
      <p style="margin:0 0 24px 0;">{html.escape(digest_copy["narrative"])}</p>

      <h2 style="font-size:16px;margin:0 0 8px 0;">💬 Let's talk about it</h2>
      {prompt_items}
    </main>
  </body>
</html>"""


def _send_digest_email(to_email, subject, html_content):
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL")
    if not api_key or not from_email:
        return False, "resend is not configured"

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }
    resp = requests.post(
        RESEND_API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code not in (200, 202):
        return False, "failed to send digest email"
    return True, None


def _get_current_user(auth_headers):
    resp = requests.get(f"{USERS_SERVICE_URL}/me", headers=auth_headers, timeout=DOWNSTREAM_TIMEOUT_S)
    if resp.status_code == 404:
        return None, (jsonify({"error": "user not found"}), 404)
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch user"}), 502)
    return resp.json(), None


def _get_profile_rows(owner_id, window_start, window_end, auth_headers):
    resp = requests.get(
        f"{EXPOSURE_PROFILES_SERVICE_URL}/users/{owner_id}/profile",
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code == 404:
        return [], None
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch exposure profile"}), 502)
    return _rows_from_profile(resp.json()), None


@bp.post("/digest/generate")
def generate_digest():
    """Generate and email the caller's trailing-seven-day privacy digest.
    Self-digest only: the owner is taken from the authenticated JWT identity.
    The route reads only aggregate exposure profile rows, then asks the LLM
    for wording over that structured summary.
    ---
    tags:
      - Digest
    security:
      - BearerAuth: []
    responses:
      200:
        description: Digest email sent.
      502:
        description: Failed to fetch user or exposure profile data.
      503:
        description: A downstream service is still starting up, or email is not configured.
    """
    owner_id = get_jwt_identity()
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=7)
    auth_headers = forwarded_auth_headers(request)

    try:
        user, error = _get_current_user(auth_headers)
        if error:
            return error
        profile_rows, error = _get_profile_rows(owner_id, window_start, window_end, auth_headers)
        if error:
            return error

        summary = _build_digest_summary(profile_rows, window_start, window_end)
        digest_copy = _generate_digest_copy(summary)
        html_content = _render_digest_email(summary, digest_copy, window_start, window_end)
        sent, send_error = _send_digest_email(
            user["email"],
            "Your Trace weekly digest",
            html_content,
        )
    except requests.exceptions.RequestException:
        return jsonify({"error": "a service is still starting up, please try again shortly"}), 503

    if not sent:
        return jsonify({"error": send_error}), 503

    return jsonify({
        "status": "sent",
        "email": user["email"],
        "window_start": summary["window_start"],
        "window_end": summary["window_end"],
        "total_flags": summary["total_flags"],
    }), 200


@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
