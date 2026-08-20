import math
from typing import List, Tuple
from app.models.schemas import Claim, Evidence

VERIFICATION_WEIGHTS = {
    "quality": 0.35,
    "independence": 0.25,
    "reproducibility": 0.20,
    "diversity": 0.10,
    "quantity": 0.10,
}


def calculate_evidence_independence(evidence_list: List[Evidence]) -> List[Evidence]:
    """
    Computes independence scores and applies echo penalties for correlated or same-source evidence.
    """
    seen_sources = set()
    seen_urls = set()

    updated = []
    for ev in evidence_list:
        ev_copy = ev.model_copy()
        base_ind = ev_copy.independence_score

        # Check for duplicate URLs or domains (echo penalty)
        if ev_copy.url and ev_copy.url in seen_urls:
            base_ind *= 0.40  # Exact URL duplicate / echo
        elif ev_copy.source in seen_sources:
            base_ind *= 0.75  # Same source family correlation

        ev_copy.independence_score = max(0.10, min(1.0, base_ind))
        if ev_copy.url:
            seen_urls.add(ev_copy.url)
        seen_sources.add(ev_copy.source)
        updated.append(ev_copy)

    return updated


def compute_verification(claim: Claim, evidence_list: List[Evidence]) -> Tuple[float, str]:
    """
    Calculates the transparent deterministic verification score and derives conservative claim status.
    Returns: (verification_score, status)
    """
    if not evidence_list:
        return 0.0, "unverified"

    # Evaluate independence and echo penalties
    scored_evidence = calculate_evidence_independence(evidence_list)

    supporting = [e for e in scored_evidence if e.stance == "supports"]
    contradicting = [e for e in scored_evidence if e.stance == "contradicts"]
    context_only = [e for e in scored_evidence if e.stance in ("context", "neutral")]

    if not supporting and not contradicting:
        return 0.20, "unverified"

    # Supporting component averages
    if supporting:
        avg_q = sum(e.quality_score for e in supporting) / len(supporting)
        avg_ind = sum(e.independence_score for e in supporting) / len(supporting)
        avg_rep = sum(e.reproducibility_score for e in supporting) / len(supporting)

        unique_sources = len({e.source for e in supporting})
        diversity_score = min(1.0, unique_sources / 3.0)

        # Saturating quantity formula: diminishing returns with log2
        quantity_sat = min(1.0, math.log2(len(supporting) + 1) / 2.5)
    else:
        avg_q = 0.0
        avg_ind = 0.0
        avg_rep = 0.0
        diversity_score = 0.0
        quantity_sat = 0.0

    raw_score = (
        avg_q * VERIFICATION_WEIGHTS["quality"]
        + avg_ind * VERIFICATION_WEIGHTS["independence"]
        + avg_rep * VERIFICATION_WEIGHTS["reproducibility"]
        + diversity_score * VERIFICATION_WEIGHTS["diversity"]
        + quantity_sat * VERIFICATION_WEIGHTS["quantity"]
    )

    # Contradiction penalty
    contra_weight = 0.0
    if contradicting:
        contra_weight = sum(e.quality_score * e.independence_score for e in contradicting)
        raw_score -= (contra_weight * 0.40)

    final_score = max(0.0, min(1.0, raw_score))

    # Derive conservative status
    if contradicting:
        if supporting and contra_weight >= 0.40:
            status = "mixed"
        elif contra_weight >= 0.50:
            status = "contradicted"
        else:
            status = "weakly_supported"
    else:
        if final_score >= 0.70:
            # If self-reported and only 1 single source with no external validation, cap to supported
            if claim.self_reported and len(supporting) == 1 and diversity_score <= 0.35:
                status = "supported"
            else:
                status = "strongly_supported"
        elif final_score >= 0.50:
            status = "supported"
        elif final_score >= 0.30:
            status = "weakly_supported"
        else:
            status = "unverified"

    return round(final_score, 4), status
