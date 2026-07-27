import os
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate


class GroupExplanation(BaseModel):
    explanation: str = Field(
        description="One comprehensive sentence (or two, if genuinely needed) explaining "
        "what this cluster of findings reveals TOGETHER — not a restatement of each one."
    )


_SYSTEM = (
    "You are a privacy analyst. You are shown several findings that were flagged in the SAME "
    "spot of a photo — e.g. a passport's photo, name, and number, or a boarding pass's name, "
    "flight, and seat, all overlapping in one region. Your job is to explain what they reveal "
    "when combined, in plain language, addressed directly to the person who posted the photo. "
    "You never invent facts beyond what is given."
)

_HUMAN = """\
Findings in this one overlapping region:
{findings}

Write ONE comprehensive explanation of what a stranger could learn from this cluster taken \
together — not a list, not a restatement of each item one by one. Explain the COMBINED \
significance: why having all of this in one place is worse than any single detail alone.

Rules:
1. Second person ("you"/"your"), plain language, no jargon.
2. Ground it strictly in the findings given — do not add anything not implied by them.
3. One to two sentences, no bullet points, no restating each detail as its own clause.
4. If several findings clearly form one real-world object (an ID card, a boarding pass), you \
may name that object once, but the point is still the combined risk, not an inventory."""


def synthesise_group_explanation(findings: list[dict]) -> str:
    """Combine a cluster of same-spot findings into one grounded, synthesized sentence.

    `findings` is a list of {"category": str, "detail": str} dicts. Falls back to a plain
    joined sentence on any failure so a flaky LLM call never breaks the results page.
    """
    if not findings:
        return ""
    if len(findings) == 1:
        return findings[0].get("detail") or ""

    fallback = _fallback_join(findings)

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(GroupExplanation)
    chain = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)]) | structured_llm

    try:
        formatted = "\n".join(
            f"- {f.get('category', 'detail')}: {f.get('detail', '')}" for f in findings
        )
        result = chain.invoke({"findings": formatted})
        return result.explanation.strip() or fallback
    except Exception:
        return fallback


def _fallback_join(findings: list[dict]) -> str:
    """Deterministic, no-LLM fallback — same shape as before this feature existed."""
    details = [f.get("detail", "").rstrip(". ") for f in findings if f.get("detail")]
    if not details:
        return ""
    if len(details) == 1:
        return details[0]
    return f"{', '.join(details[:-1])}, and {details[-1]} — all visible in the same spot."
