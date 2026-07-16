import math
import os
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from .extraction import Observation

_SINGAPORE_POPULATION = 6_000_000

_SYSTEM = (
    "You are a privacy analyst estimating population subsets. "
    "Reason carefully about how constraints intersect — each additional constraint "
    "further narrows the candidate group."
)

_ESTIMATE_PROMPT = """\
How many people in Singapore (population ~6 million) could simultaneously satisfy ALL of the \
following constraints?

Constraints:
{constraints}

Think step-by-step:
1. Start from the full Singapore population (~6 million).
2. Apply each constraint in turn, estimating the fraction it eliminates.
3. Report your final estimate as the integer `k_estimate`.

Reference anchors (use these for calibration):
- "works in the CBD" → ~200,000
- "lives in Tampines" → ~250,000
- "takes the MRT to Dhoby Ghaut daily" → ~50,000
- "works in CBD + lives in Tampines" → ~15,000
- "works in CBD + lives in Tampines + has a dog" → ~1,500
- Five or more specific intersecting constraints often drops below 500

k_estimate must be at least 1."""


class _Estimate(BaseModel):
    k_estimate: int
    reasoning: str


def _estimate_k(constraints: list[str]) -> int:
    if not constraints:
        return _SINGAPORE_POPULATION

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(_Estimate)
    chain = (
        ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _ESTIMATE_PROMPT)])
        | structured_llm
    )

    try:
        bullet_list = "\n".join(f"- {c}" for c in constraints)
        result = chain.invoke({"constraints": bullet_list})
        return max(1, result.k_estimate)
    except Exception:
        return max(1, _SINGAPORE_POPULATION // (2 ** len(constraints)))


def _fmt_detection(det: dict) -> str:
    category = det.get("category", "unknown")
    detail = det.get("detail", "")
    return f"{category}: {detail}" if detail else category


def compute_delta(
    prior_detections: list[dict],
    new_observations: list[Observation],
    new_draft_detections: list[dict],
) -> dict:
    """
    Compute anonymity delta from k_before (history only) to k_after (history + draft).

    prior_detections:     detection records from all previous posts by this user
    new_observations:     Observation objects extracted from the draft's text content
    new_draft_detections: detection records already recorded for the current draft (image scan)
    """
    prior_constraints = [_fmt_detection(d) for d in prior_detections if d.get("detail")]

    new_text_constraints = [obs.constraint for obs in new_observations]
    new_image_constraints = [_fmt_detection(d) for d in new_draft_detections if d.get("detail")]
    new_constraints = new_text_constraints + new_image_constraints

    k_before = _estimate_k(prior_constraints)
    k_after = _estimate_k(prior_constraints + new_constraints)

    delta_bits = (
        math.log2(k_before) - math.log2(k_after)
        if k_before > 0 and k_after > 0
        else 0.0
    )
    delta_bits = round(max(0.0, delta_bits), 2)

    # Leave-one-out attribution over text observations only —
    # those are the ones the author can still edit before posting.
    contributors = []
    for obs in new_observations:
        remaining = [c for c in new_text_constraints if c != obs.constraint] + new_image_constraints
        k_without = _estimate_k(prior_constraints + remaining)
        contribution = (
            math.log2(k_without) - math.log2(k_after)
            if k_without > 0 and k_after > 0
            else 0.0
        )
        contributors.append({
            "surface": obs.surface,
            "constraint": obs.constraint,
            "kind": obs.kind,
            "target": obs.target,
            "contribution_bits": round(max(0.0, contribution), 2),
        })

    contributors.sort(key=lambda x: x["contribution_bits"], reverse=True)

    if k_after <= 1_000 or delta_bits >= 5:
        risk_level = "high"
    elif k_after <= 10_000 or delta_bits >= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "k_before": k_before,
        "k_after": k_after,
        "delta_bits": delta_bits,
        "risk_level": risk_level,
        "top_contributors": contributors,
    }
