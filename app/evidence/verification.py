import math
from typing import List, Optional, Tuple
from app.models.schemas import Claim, Evidence

VERIFICATION_WEIGHTS = {
    "quality": 0.35,
    "independence": 0.25,
    "reproducibility": 0.20,
    "diversity": 0.10,
    "quantity": 0.10,
}

HYSTERESIS_DELTA = 0.02


def is_independent_evidence(evidence: Evidence) -> bool:
    """
    Canonical determination of whether an individual evidence record represents
    an independent reproduction or sufficiently independent evidence.
    """
    return (
        getattr(evidence, "evidence_type", None) == "independent_reproduction"
        or getattr(evidence, "independence_score", 0.0) >= 0.85
    )


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


def derive_status_with_policy(
    claim: Claim,
    final_score: float,
    supporting: List[Evidence],
    contradicting: List[Evidence],
    contra_weight: float,
    previous_status: Optional[str] = None,
) -> str:
    """
    Applies assertion-level verification policies and status hysteresis.
    """
    # 1. Retraction and Supersession override
    if getattr(claim, "superseded_by", None) or not getattr(claim, "is_current", True):
        return "superseded"

    has_retraction = any(e.evidence_type in ("retraction_notice", "withdrawal") for e in (supporting + contradicting))
    if has_retraction or claim.status == "retracted":
        return "retracted"

    # 2. Contradiction handling
    if contradicting:
        if supporting and contra_weight >= 0.35:
            return "mixed"
        elif contra_weight >= 0.45:
            return "contradicted"
        else:
            return "weakly_supported"

    if not supporting:
        return "unverified"

    # 3. Assertion level specific thresholds & caps
    assertion_level = getattr(claim, "assertion_level", "artifact_fact") or "artifact_fact"
    unique_sources = len({e.source for e in supporting})

    # Thresholds with hysteresis
    t_strong = 0.70
    t_sup = 0.50
    t_weak = 0.30

    if previous_status == "strongly_supported":
        t_strong -= HYSTERESIS_DELTA
    elif previous_status == "supported":
        t_sup -= HYSTERESIS_DELTA
        t_strong += HYSTERESIS_DELTA
    elif previous_status == "weakly_supported":
        t_weak -= HYSTERESIS_DELTA
        t_sup += HYSTERESIS_DELTA

    if final_score >= t_strong:
        # Policy rules for strongly_supported
        if assertion_level in ("self_reported_claim", "performance_claim"):
            # Requires independent corroboration (>= 2 independent sources or independent reproduction)
            has_independent = any(is_independent_evidence(e) for e in supporting)
            if unique_sources >= 2 or has_independent:
                return "strongly_supported"
            else:
                return "supported"
        elif assertion_level == "research_claim":
            # Preprint alone caps at supported
            has_peer_or_repro = any(e.evidence_type in ("peer_reviewed_paper", "independent_reproduction") for e in supporting)
            if has_peer_or_repro or unique_sources >= 2:
                return "strongly_supported"
            else:
                return "supported"
        elif assertion_level == "community_observation":
            # Community observation without independent artifact caps at weakly_supported or supported
            if unique_sources >= 2:
                return "supported"
            return "weakly_supported"
        else:
            # artifact_fact (Release, DOI, Repo, Model Hub) can reach strongly_supported with authoritative primary artifact
            return "strongly_supported"

    elif final_score >= t_sup:
        if assertion_level == "community_observation" and unique_sources < 2:
            return "weakly_supported"
        return "supported"

    elif final_score >= t_weak:
        return "weakly_supported"
    else:
        return "unverified"


def compute_verification(
    claim: Claim,
    evidence_list: List[Evidence],
    previous_status: Optional[str] = None,
) -> Tuple[float, str]:
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

    # Contradiction penalty calculation
    contra_weight = 0.0
    if contradicting:
        contra_weight = sum(e.quality_score * e.independence_score * e.reproducibility_score for e in contradicting)
        raw_score -= (contra_weight * 0.50)

    final_score = max(0.0, min(1.0, raw_score))

    prev_st = previous_status or getattr(claim, "status", None)
    status = derive_status_with_policy(
        claim=claim,
        final_score=final_score,
        supporting=supporting,
        contradicting=contradicting,
        contra_weight=contra_weight,
        previous_status=prev_st,
    )

    return round(final_score, 4), status
