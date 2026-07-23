import asyncio
import os

import requests
from openjiuwen.core.foundation.tool import tool
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent import ReActAgent, ReActAgentConfig
from openjiuwen.core.single_agent.schema.agent_card import AgentCard

DETECTIONS_SERVICE_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://detections:5003")
QUARANTINE_ITEMS_SERVICE_URL = os.environ.get("QUARANTINE_ITEMS_SERVICE_URL", "http://quarantine_items:5006")
UPDATE_EXPOSURE_PROFILE_SERVICE_URL = os.environ.get(
    "UPDATE_EXPOSURE_PROFILE_SERVICE_URL", "http://update_exposure_profile:5013"
)
GENERATE_TEACHABLE_MOMENT_SERVICE_URL = os.environ.get(
    "GENERATE_TEACHABLE_MOMENT_SERVICE_URL", "http://generate_teachable_moment:5009"
)

MODEL_NAME = "gpt-4o-mini"

SYSTEM_PROMPT = """\
You are Trace's cyber-safety coach, chatting with someone right after Trace flagged \
something in their post. Your audience is often a young person, but could be anyone \
who cares about their privacy — keep your language plain and warm, never condescending, \
and never assume a specific age.

Your two jobs:

1. ANSWER QUESTIONS, GROUNDED IN THEIR REAL DATA.
   Use your tools (get_detections, get_quarantine_status, get_exposure_profile) to \
   check what was actually flagged for this specific draft before answering. Never \
   invent details — if a tool call fails or returns nothing, say so plainly instead \
   of guessing.

2. RUN A SHORT INTERACTIVE SIMULATION so the risk is felt through a consequence, not \
   just explained. Pick ONE of these three simulation types based on what your tools \
   return, and only run one at a time:

   a. TARGETED PHISHING / IMPERSONATION — when a detection's category is "contact" or \
      "credentials" (e.g. a phone number, email, or access code was posted).
   b. IDENTITY THEFT VIA SECURITY-VERIFICATION QUESTIONS — when a detection's category \
      is "location", "document", or "metadata" (school, travel dates, or routine \
      details that double as bank/account security questions).
   c. PHYSICAL SAFETY RISK — stalking, ambush, or home burglary — when \
      get_exposure_profile's `stranger.inferences` contains a statement about a \
      routine or home pattern (kind "temporal" or "location", target "routine" or \
      "home"). This is about the CUMULATIVE picture across all of their posts, not \
      just this one — quote the actual inference statement, since it is already \
      grounded in their real post history.

   Run the simulation as a genuine back-and-forth, like a quiz — NEVER dump the whole \
   thing (setup, message, and explanation) in a single reply. It always takes at least \
   two of your turns, with the user answering in between:

   TURN 1 — SETUP + SIMULATED MESSAGE + A QUESTION, then STOP:
     - SETUP: one or two sentences on what someone could do with this specific detail \
       (cite the real flagged detail or inference, don't generalise).
     - SIMULATED MESSAGE: on its own line, a single example of what a scammer/stranger \
       might send them next (a fake verification text, a suspicious DM, etc.). ALWAYS \
       prefix this with "⚠️ Simulated message (not real):" so it is unmistakably \
       fictional, never something that could be mistaken for an actual incoming \
       message.
     - Then ask a short quiz-style question, e.g. "What would you do?" with 2-3 \
       lettered options (e.g. "A) ... B) ... C) ..."). Put a blank line between the \
       setup, the simulated message, and the question so they render as separate \
       paragraphs, not one block.
     - Do NOT reveal the tactic or explain anything yet. Wait for their answer.

   TURN 2 (once they've answered) — REACT, THEN REVEAL:
     - Briefly react to the specific option they picked — affirm it if it was a safe \
       instinct, gently point out the risk if it wasn't. Don't just say "correct" or \
       "wrong."
     - Then explain, in plain language, what tactic the simulated message was using \
       and why the specific detail they shared made it possible.

   If they reply with something other than an answer to the quiz (a new question, a \
   change of topic), it's fine to answer that first — pick the simulation back up \
   later rather than forcing the reveal on them.

   Keep the tone calm and educational, never designed to frighten. Do not repeat a \
   simulation you've already run in this conversation — move on to Q&A or a different \
   angle instead.

Keep replies short and conversational — a few sentences, like a chat message, not an \
essay. It's fine to end with a light follow-up question to keep the conversation going.
"""


class ChatError(Exception):
    """Raised when the agent or one of its grounding calls fails."""


def _fetch_teachable_moment_seed(draft_id, auth_headers):
    """Reuse generate_teachable_moment's existing template-based lesson as seed
    context, instead of duplicating the LESSONS copy in this service too."""
    try:
        resp = requests.get(
            f"{GENERATE_TEACHABLE_MOMENT_SERVICE_URL}/drafts/{draft_id}/teachable-moment",
            headers=auth_headers,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


def _render_seed_context(seed):
    if not seed or not seed.get("category"):
        return "No specific detection is flagged for this draft yet — Trace judged it safe to share."
    return (
        f"The riskiest finding for this draft: category={seed.get('category')}, "
        f"detail={seed.get('detail')!r}, exposure_score={seed.get('exposure_score')}. "
        f"Trace's own short explanation: {seed.get('explanation')!r} "
        f"Suggested safer action: {seed.get('safer_action')!r}"
    )


def _build_tools(draft_id, owner_id, auth_headers):
    def get_detections() -> dict:
        """Fetch this draft's detection records: category, exposure_score, detail, source_type."""
        try:
            resp = requests.get(
                f"{DETECTIONS_SERVICE_URL}/drafts/{draft_id}/detections",
                headers=auth_headers,
            )
        except requests.RequestException:
            return {"error": "failed to reach the detections service"}
        if resp.status_code != 200:
            return {"error": "failed to fetch detections"}
        return {"detections": resp.json()}

    def get_quarantine_status() -> dict:
        """Fetch this draft's quarantine items, if any: state, reason, cooldown_expiry."""
        try:
            resp = requests.get(
                f"{QUARANTINE_ITEMS_SERVICE_URL}/drafts/{draft_id}/quarantine",
                headers=auth_headers,
            )
        except requests.RequestException:
            return {"error": "failed to reach the quarantine service"}
        if resp.status_code != 200:
            return {"error": "failed to fetch quarantine status"}
        return {"quarantine_items": resp.json()}

    def get_exposure_profile() -> dict:
        """Fetch the user's cumulative exposure profile: cross-post trajectory and
        stranger-profile inferences (what a stranger could piece together across all
        of this user's posts, not just this one draft)."""
        try:
            resp = requests.get(
                f"{UPDATE_EXPOSURE_PROFILE_SERVICE_URL}/users/{owner_id}/profile",
                headers=auth_headers,
            )
        except requests.RequestException:
            return {"error": "failed to reach the exposure profile service"}
        if resp.status_code != 200:
            return {"error": "failed to fetch exposure profile"}
        return {"profile": resp.json().get("profile")}

    return [get_detections, get_quarantine_status, get_exposure_profile]


def _flatten_history(history, message):
    """agent.invoke() takes a single query string, not a role-tagged message list
    (verified against the installed openjiuwen==0.1.13.post1 source) — so client-held
    history is flattened into one string each turn rather than relying on openjiuwen's
    own Session/conversation_id state, which would only happen to survive across
    requests here because this service's gunicorn runs --workers 1 (accidental,
    fragile server state, not a real design choice)."""
    lines = []
    for turn in history or []:
        speaker = "User" if turn.get("role") == "user" else "Coach"
        content = (turn.get("content") or "").strip()
        if content:
            lines.append(f"{speaker}: {content}")
    lines.append(f"User: {message}")
    return "\n".join(lines)


def _build_agent(seed):
    card = AgentCard(name="teachable_moment_chat", description="Cyber-safety coach chat agent")
    agent = ReActAgent(card)
    config = (
        ReActAgentConfig()
        .configure_model_client(
            "openai",
            os.environ["OPENAI_API_KEY"],
            os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            MODEL_NAME,
        )
        .configure_prompt_template([
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + _render_seed_context(seed)},
        ])
    )
    # openjiuwen's ModelRequestConfig defaults temperature to 0.95, which made
    # tool-calling inconsistent across otherwise-identical turns during testing (the
    # agent sometimes skipped calling get_detections entirely, contradicting the
    # "ground every answer in real data" instruction). Lower and fixed, while still
    # leaving room for the "in your own words each time" conversational variety the
    # prompt asks for.
    config.model_config_obj.temperature = 0.2
    agent.configure(config)
    return agent


def _register_tools(agent, tool_fns):
    """Each request builds fresh tool closures bound to that request's own JWT, so
    the AgentCard/tool ids are left as their natural fresh-random defaults (never
    colliding across concurrent requests) rather than forced to a stable id — a
    stable id would let one thread's registration silently clobber another's
    mid-flight under gunicorn's --threads 8, leaking one user's auth headers into
    another user's tool calls. The tradeoff is that Runner.resource_mgr is a
    process-global registry, so every registration here MUST be undone in
    _unregister_tools (see the route's try/finally) or entries accumulate for the
    lifetime of the worker process."""
    for fn in tool_fns:
        wrapped = tool(fn)
        agent.ability_manager.add(wrapped.card)
        Runner.resource_mgr.add_tool(wrapped, tag=agent.card.id)


def _unregister_tools(agent):
    Runner.resource_mgr.remove_tool(tag=agent.card.id, skip_if_tag_not_exists=True)


def answer(draft_id, message, history, auth_headers, owner_id):
    """Build a fresh agent for this request, ground it in the user's real data, and
    return a reply string. Raises ChatError on agent/tool failure so the route can
    turn it into a 502."""
    seed = _fetch_teachable_moment_seed(draft_id, auth_headers)
    agent = _build_agent(seed)
    tool_fns = _build_tools(draft_id, owner_id, auth_headers)

    try:
        _register_tools(agent, tool_fns)
        query = _flatten_history(history, message)
        result = asyncio.run(agent.invoke({"query": query}))
    except Exception as exc:
        raise ChatError(f"agent invocation failed: {exc}") from exc
    finally:
        _unregister_tools(agent)

    if result.get("result_type") == "error":
        raise ChatError(result.get("output") or "agent returned an error")

    return result.get("output") or ""
