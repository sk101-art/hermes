from datetime import datetime, timezone
from typing import Optional
from app.models.schemas import Claim

# Staleness half-life in days per claim type / assertion level
HALF_LIFE_DAYS = {
    "release": 45,
    "availability": 60,
    "performance": 120,
    "community_observation": 90,
    "architecture": 180,
    "research_result": 365,
    "research_claim": 365,
    "scholarly_identity": 99999,  # Permanent DOI identity
    "artifact_fact": 180,
}


def calculate_claim_staleness(claim: Claim, now: Optional[datetime] = None) -> float:
    """
    Computes a deterministic staleness score [0.0 - 1.0] based on claim type,
    assertion level, and elapsed time since last verified or created.
    """
    if not now:
        now = datetime.now(timezone.utc)

    # Permanent scholarly identity facts do not become stale
    if claim.claim_type == "scholarly_identity" or "doi" in claim.metadata:
        return 0.0

    ref_date = claim.last_verified_at or claim.created_at
    if ref_date.tzinfo is None:
        ref_date = ref_date.replace(tzinfo=timezone.utc)

    elapsed_days = max(0.0, (now - ref_date).total_seconds() / 86400.0)

    # Determine half life
    half_life = HALF_LIFE_DAYS.get(claim.claim_type) or HALF_LIFE_DAYS.get(getattr(claim, "assertion_level", "artifact_fact"), 180)

    # Asymptotic staleness curve: 1 - 2^(-t / half_life)
    if half_life >= 99999:
        return 0.0

    staleness = 1.0 - (0.5 ** (elapsed_days / half_life))
    return round(min(1.0, max(0.0, staleness)), 4)


def classify_staleness_tier(staleness_score: float) -> str:
    """Classifies staleness score into a human-readable tier."""
    if staleness_score < 0.30:
        return "fresh"
    elif staleness_score < 0.70:
        return "aging"
    else:
        return "stale"
