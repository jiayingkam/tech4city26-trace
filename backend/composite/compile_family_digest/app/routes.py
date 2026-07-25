import html
import json
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
CATEGORIES = ("face", "location", "document", "metadata", "contact", "financial")


class DigestCopy(BaseModel):
    summary_paragraph: str
    reflection_line: str


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _category_breakdown_from_rows(profile_rows):
    breakdown = {category: 0 for category in CATEGORIES}
    for row in profile_rows:
        row_breakdown = row.get("category_breakdown") or {}
        for category in CATEGORIES:
            breakdown[category] += int(row_breakdown.get(category, 0) or 0)
    return breakdown


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
    return {
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "total_flags": total_flags,
        "category_breakdown": category_breakdown,
        "privacy_health_trajectory": trajectory,
        "has_activity": bool(profile_rows) and total_flags > 0,
    }


def _fallback_digest_copy(summary):
    if not summary["has_activity"]:
        return {
            "summary_paragraph": (
                "Trace did not find notable privacy exposures in your posts from the past seven days."
            ),
            "reflection_line": "A quiet week still counts: a quick check before posting helps keep it that way.",
        }

    top_category = max(summary["category_breakdown"], key=summary["category_breakdown"].get)
    top_count = summary["category_breakdown"][top_category]
    return {
        "summary_paragraph": (
            f"Over the past seven days, Trace recorded {summary['total_flags']} privacy flag(s). "
            f"The most common category was {top_category}, with {top_count} flag(s)."
        ),
        "reflection_line": "Before sharing, pause on the small details that could identify where you are or who you are with.",
    }


def _generate_digest_copy(summary):
    if not os.environ.get("OPENAI_API_KEY"):
        return _fallback_digest_copy(summary)

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=os.environ.get("DIGEST_LLM_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        api_key=os.environ["OPENAI_API_KEY"],
    )
    structured_llm = llm.with_structured_output(DigestCopy)
    result = structured_llm.invoke([
        {
            "role": "system",
            "content": (
                "You write short privacy self-digests for Trace. Use only the numbers provided "
                "in the structured summary. Do not calculate, infer, add, or mention numbers "
                "that are not present. Do not include raw content, captions, or per-post detail. "
                "Return one plain-language paragraph and one teachable-moment-style reflection line."
            ),
        },
        {"role": "user", "content": json.dumps(summary, sort_keys=True)},
    ])
    return result.model_dump()


def _format_date_range(window_start, window_end):
    return f"{window_start:%d %b %Y, %H:%M UTC} to {window_end:%d %b %Y, %H:%M UTC}"


def _render_digest_email(summary, digest_copy, window_start, window_end):
    rows = "\n".join(
        f"<tr><td style=\"padding:6px 0;\">{html.escape(category.title())}</td>"
        f"<td style=\"padding:6px 0;text-align:right;\">{count}</td></tr>"
        for category, count in summary["category_breakdown"].items()
    )
    return f"""<!doctype html>
<html>
  <body style="font-family:Arial,sans-serif;color:#1f2937;line-height:1.5;">
    <h1 style="font-size:20px;margin-bottom:4px;">Your Trace weekly digest</h1>
    <p style="margin-top:0;color:#4b5563;">{html.escape(_format_date_range(window_start, window_end))}</p>
    <p>{html.escape(digest_copy["summary_paragraph"])}</p>
    <p><strong>Reflection:</strong> {html.escape(digest_copy["reflection_line"])}</p>
    <h2 style="font-size:16px;margin-top:24px;">Category breakdown</h2>
    <table style="border-collapse:collapse;width:100%;max-width:420px;">
      <tbody>
        {rows}
      </tbody>
    </table>
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
        f"{EXPOSURE_PROFILES_SERVICE_URL}/users/{owner_id}/exposure-profiles",
        params={"window_start": _iso(window_start), "window_end": _iso(window_end)},
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 200:
        return None, (jsonify({"error": "failed to fetch exposure profile"}), 502)
    return resp.json(), None


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
