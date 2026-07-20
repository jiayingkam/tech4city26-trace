import math
from .extraction import Observation

K_BASELINE = 6_000_000


def _bits_to_k(bits: float) -> int:
    """Arithmetic: how many people in Singapore remain after `bits` of narrowing."""
    return max(1, int(K_BASELINE / (2 ** bits)))


def compute_delta(
    prior_observations: list[Observation],
    new_observations: list[Observation],
) -> dict:
    """
    Compute anonymity delta from k_before (history only) to k_after (history + draft).

    new_observations must include ALL observations for this draft — both text-derived and
    image-derived (converted from scan_draft detections by the caller). Every bit that moves
    k must appear in new_observations so that delta_bits == sum(obs.contribution_bits).

    k is purely arithmetic — the LLM never outputs k, only contribution_bits per observation.
    This guarantees identical results for identical inputs across repeated calls.
    """
    prior_bits = sum((obs.contribution_bits or 0.0) for obs in prior_observations)
    new_bits = sum((obs.contribution_bits or 0.0) for obs in new_observations)

    k_before = _bits_to_k(prior_bits)
    k_after = _bits_to_k(prior_bits + new_bits)

    # Direct sum — never derived from k, so the invariant
    # delta_bits == sum(obs.contribution_bits for obs in new_observations) always holds.
    delta_bits = round(new_bits, 2)

    # Leave-one-out attribution: pure arithmetic, zero extra LLM calls
    contributors = []
    for obs in new_observations:
        k_without = _bits_to_k(prior_bits + new_bits - (obs.contribution_bits or 0.0))
        contribution = round(
            max(0.0, math.log2(k_without) - math.log2(k_after))
            if k_without > 0 and k_after > 0 else 0.0,
            2,
        )
        contributors.append({
            "surface": obs.surface,
            "constraint": obs.constraint,
            "kind": obs.kind,
            "target": obs.target,
            "contribution_bits": round(obs.contribution_bits or 0.0, 2),
            "leave_one_out_bits": contribution,
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
