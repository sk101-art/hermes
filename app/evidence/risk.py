from typing import Dict, List, Optional
from datetime import datetime, timezone
from app.models.schemas import Claim, Event, Evidence, StoryCluster


def calculate_technology_risk(
    cluster: StoryCluster,
    events: List[Event],
    claims: List[Claim],
    evidence_map: Optional[Dict[str, List[Evidence]]] = None,
) -> float:
    """
    Computes a deterministic technology risk score [0.0 - 1.0].
    Distinct from technical quality; measures integration risk, contradiction risk,
    lack of reproducibility, and single-source dependency.
    """
    if not claims and not events:
        return 0.50

    # 1. Contradiction factor (0.0 - 0.40)
    contradicted_count = sum(1 for c in claims if c.status in ("contradicted", "mixed"))
    total_claims = len(claims) if claims else 1
    contra_ratio = contradicted_count / total_claims
    contra_factor = min(0.40, contra_ratio * 0.40)

    # 2. Reproducibility & artifact factor (0.0 - 0.25)
    # High risk if all claims are self-reported with no code or independent benchmark
    has_code = any(e.source == "github" or e.event_type in ("repository", "release") for e in events)
    has_benchmark = any("benchmark" in (e.title + " " + e.text).lower() for e in events)
    all_self_reported = all(c.self_reported for c in claims) if claims else True

    if not has_code and all_self_reported:
        repro_risk = 0.25
    elif not has_code:
        repro_risk = 0.15
    elif not has_benchmark:
        repro_risk = 0.08
    else:
        repro_risk = 0.02

    # 3. Source diversity / single-source dependency (0.0 - 0.15)
    sources = set(e.source for e in events)
    if len(sources) <= 1:
        diversity_risk = 0.15
    elif len(sources) == 2:
        diversity_risk = 0.08
    else:
        diversity_risk = 0.02

    # 4. Activity & staleness risk (0.0 - 0.20)
    now = datetime.now(timezone.utc)
    latest_event_time = None
    for e in events:
        t = e.published_at or e.discovered_at
        if t:
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if latest_event_time is None or t > latest_event_time:
                latest_event_time = t

    if latest_event_time:
        days_since_active = (now - latest_event_time).total_seconds() / 86400.0
        if days_since_active > 180:
            activity_risk = 0.20
        elif days_since_active > 90:
            activity_risk = 0.10
        elif days_since_active > 30:
            activity_risk = 0.05
        else:
            activity_risk = 0.01
    else:
        activity_risk = 0.10

    total_risk = contra_factor + repro_risk + diversity_risk + activity_risk
    return round(min(1.0, max(0.0, total_risk)), 4)
