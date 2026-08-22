from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.models.schemas import Project
from app.services.intelligence import get_recent_changes
from app.services.schemas import ProjectIntelligence, ProjectSummary
from app.storage.db import Database


def resolve_project(project_id_or_name: str, db: Database) -> Optional[Project]:
    """Safely resolves project by ID or case-insensitive name."""
    if not project_id_or_name:
        return None
    p_clean = project_id_or_name.strip()
    return (
        db.get_project(p_clean)
        or db.get_project(f"project:{p_clean.lower()}")
        or db.get_project_by_name(p_clean)
    )


def list_projects(db: Optional[Database] = None) -> List[ProjectSummary]:
    """
    Lists summarized technology profiles for all active projects.
    Strict privacy: Exposes ONLY derived technologies and metadata, NO private source code or local filesystem paths.
    """
    if db is None:
        db = Database()

    projects = db.get_all_projects(active_only=True)
    match_counts = db.get_project_match_counts()
    summaries = []
    for p in projects:
        summaries.append(
            ProjectSummary(
                project_id=p.id,
                name=p.name,
                description=p.description,
                is_active=bool(p.is_active),
                languages=list(p.languages),
                frameworks=list(p.frameworks),
                libraries=list(p.libraries),
                databases=list(p.databases),
                infrastructure=list(p.infrastructure),
                models=list(p.models),
                tools=list(p.tools),
                topics=list(p.topics),
                keywords=list(p.keywords),
                last_indexed_at=p.last_indexed_at.isoformat() if p.last_indexed_at else None,
                matches_count=match_counts.get(p.id, 0),
            )
        )
    return summaries


def get_project_profile(
    project_id_or_name: str,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves structured technology profile for a specific project without raw file contents or filesystem paths."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return None

    profile = db.get_project_profile(project.id)
    matches = db.get_project_matches(project.id)
    return {
        "project_id": project.id,
        "name": project.name,
        "description": project.description,
        "is_active": bool(project.is_active),
        "languages": list(project.languages),
        "frameworks": list(project.frameworks),
        "libraries": list(project.libraries),
        "databases": list(project.databases),
        "infrastructure": list(project.infrastructure),
        "models": list(project.models),
        "tools": list(project.tools),
        "topics": list(project.topics),
        "keywords": list(project.keywords),
        "profile_hash": profile.profile_hash if profile else None,
        "last_indexed_at": project.last_indexed_at.isoformat() if project.last_indexed_at else None,
        "matches_count": len(matches),
    }


# Explicit audited sets of concern reason codes (exact match or structured prefix)
EXPLICIT_VULNERABILITY_REASON_CODES = frozenset({
    "vulnerability",
    "security_vulnerability",
    "cve",
    "security_advisory",
})
EXPLICIT_VULNERABILITY_PREFIXES = (
    "vulnerability:",
    "cve:",
    "security_vulnerability:",
    "security_advisory:",
)

EXPLICIT_BREAKING_CHANGE_REASON_CODES = frozenset({
    "breaking_change",
    "incompatible_api",
    "major_version_bump",
})
EXPLICIT_BREAKING_CHANGE_PREFIXES = (
    "breaking_change:",
    "incompatible_api:",
    "major_version_bump:",
)

EXPLICIT_DEPRECATION_REASON_CODES = frozenset({
    "deprecation",
    "deprecated_api",
    "end_of_life",
    "eol",
})
EXPLICIT_DEPRECATION_PREFIXES = (
    "deprecation:",
    "deprecated_api:",
    "end_of_life:",
    "eol:",
)


def _matches_explicit_codes(codes: List[str], exact_set: frozenset, prefixes: tuple) -> bool:
    for code in codes:
        c_clean = str(code).strip().lower()
        if c_clean in exact_set:
            return True
        if any(c_clean.startswith(p) for p in prefixes):
            return True
    return False


def _evaluate_canonical_risk(
    tech_state: Optional[Any],
    has_claims: bool,
    has_events: bool,
) -> Tuple[str, Optional[str], Optional[float]]:
    """
    Evaluates canonical risk according to Phase 2 rules:
    - No technology state -> ('not_assessed', None, None)
    - State exists but no claims & no events -> ('insufficient_data', None, tech_state.risk_score)
    - State exists with claims or events:
        - If risk_score is None -> ('insufficient_data', None, None) (missing score cannot produce assessed RiskLevel)
        - If risk_score is present -> ('assessed', risk_level, risk_score)
    """
    if tech_state is None:
        return "not_assessed", None, None

    r_score = tech_state.risk_score
    if not has_claims and not has_events:
        return "insufficient_data", None, r_score

    if r_score is None:
        return "insufficient_data", None, None

    r_level = (
        "critical" if r_score >= 0.7
        else ("high" if r_score >= 0.4
              else ("medium" if r_score >= 0.2 else "low"))
    )
    return "assessed", r_level, r_score


def get_project_recommendations(
    project_id_or_name: str,
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves top actionable advisory items for a project with batch-resolved cluster availability."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return []

    limit = max(1, min(limit, 50))
    matches = db.get_project_matches(project.id)
    # Sort by relevance score
    matches.sort(
        key=lambda m: (m.relevance_score if m.relevance_score is not None else -1.0),
        reverse=True,
    )

    top_matches = matches[:limit]
    cluster_ids = list({m.entity_id for m in top_matches})
    clusters_map = {c.id: c for c in db.get_clusters_by_ids(cluster_ids)}

    recs = []
    for m in top_matches:
        cl = clusters_map.get(m.entity_id)
        recs.append({
            "cluster_id": m.entity_id,
            "title": cl.canonical_title if cl else m.entity_id,
            "relevance_score": round(m.relevance_score, 4) if m.relevance_score is not None else None,
            "impact_score": round(m.impact_score, 4) if m.impact_score is not None else None,
            "match_type": m.match_type,
            "recommendation": m.recommendation,
            "reason_codes": list(m.reason_codes),
            "story_available": bool(cl is not None),
        })
    return recs


def get_project_risks(
    project_id_or_name: str,
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves breaking changes, deprecations, vulnerabilities, canonical assessed risks,
    or high project impact matches for a project with batch-resolved inputs.
    Strictly separates high project impact from canonical assessed risk.
    """
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return []

    limit = max(1, min(limit, 50))
    matches = db.get_project_matches(project.id)
    if not matches:
        return []

    # Batch resolution of clusters, technology states, and claim/event counts
    cluster_ids = list({m.entity_id for m in matches})
    clusters_map = {c.id: c for c in db.get_clusters_by_ids(cluster_ids)}
    states_map = {ts.cluster_id: ts for ts in db.get_technology_states_by_cluster_ids(cluster_ids)}
    claims_count_map = db.get_claim_counts_by_cluster_ids(cluster_ids)
    events_count_map = db.get_event_counts_by_cluster_ids(cluster_ids)

    risks = []
    for m in matches:
        c_id = m.entity_id
        cl = clusters_map.get(c_id)
        ts = states_map.get(c_id)
        has_claims = claims_count_map.get(c_id, 0) > 0
        has_events = events_count_map.get(c_id, 0) > 0
        risk_status, risk_level, risk_score = _evaluate_canonical_risk(ts, has_claims, has_events)

        is_vuln = m.match_type == "vulnerability" or _matches_explicit_codes(
            m.reason_codes, EXPLICIT_VULNERABILITY_REASON_CODES, EXPLICIT_VULNERABILITY_PREFIXES
        )
        is_breaking = m.match_type == "breaking_change" or _matches_explicit_codes(
            m.reason_codes, EXPLICIT_BREAKING_CHANGE_REASON_CODES, EXPLICIT_BREAKING_CHANGE_PREFIXES
        )
        is_deprec = m.match_type == "deprecation" or _matches_explicit_codes(
            m.reason_codes, EXPLICIT_DEPRECATION_REASON_CODES, EXPLICIT_DEPRECATION_PREFIXES
        )
        is_assessed_risk = risk_status == "assessed" and risk_level in ("high", "critical")
        is_high_impact = m.impact_score is not None and m.impact_score >= 0.70

        if not (is_vuln or is_breaking or is_deprec or is_assessed_risk or is_high_impact):
            continue

        concern_type = (
            "vulnerability" if is_vuln else (
                "breaking_change" if is_breaking else (
                    "deprecation" if is_deprec else (
                        "assessed_risk" if is_assessed_risk else "high_project_impact"
                    )
                )
            )
        )

        risks.append({
            "cluster_id": c_id,
            "title": cl.canonical_title if cl else c_id,
            "concern_type": concern_type,
            "match_type": m.match_type,
            "recommendation": m.recommendation,
            "impact_score": round(m.impact_score, 4) if m.impact_score is not None else None,
            "relevance_score": round(m.relevance_score, 4) if m.relevance_score is not None else None,
            "risk_status": risk_status,
            "risk_level": risk_level,
            "risk_score": round(risk_score, 4) if risk_score is not None else None,
            "reason_codes": list(m.reason_codes),
            "story_available": bool(cl is not None),
        })

    risks.sort(
        key=lambda r: (
            r["impact_score"] if r["impact_score"] is not None else -1.0,
            r["relevance_score"] if r["relevance_score"] is not None else -1.0,
        ),
        reverse=True,
    )
    return risks[:limit]


def get_project_changes(
    project_id_or_name: str,
    hours: int = 168,
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recent intelligence changes matching technologies in the project via canonical Phase 9 service."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return []

    return get_recent_changes(hours=hours, project=project.id, limit=limit, db=db)


def get_project_intelligence(
    project_id_or_name: str,
    limit: int = 10,
    db: Optional[Database] = None,
) -> Optional[ProjectIntelligence]:
    """Aggregates technology profile, matches, recommendations, risks, and recent changes with batch resolution."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return None

    prof = get_project_profile(project.id, db)
    recs = get_project_recommendations(project.id, limit=limit, db=db)
    risks = get_project_risks(project.id, limit=limit, db=db)
    changes = get_project_changes(project.id, hours=168, limit=limit, db=db)

    matches = db.get_project_matches(project.id)
    matches.sort(
        key=lambda m: (m.relevance_score if m.relevance_score is not None else -1.0),
        reverse=True,
    )
    top_matches = matches[:limit]
    cluster_ids = list({m.entity_id for m in top_matches})
    clusters_map = {c.id: c for c in db.get_clusters_by_ids(cluster_ids)}

    matches_summary = []
    for m in top_matches:
        cl = clusters_map.get(m.entity_id)
        matches_summary.append({
            "cluster_id": m.entity_id,
            "title": cl.canonical_title if cl else m.entity_id,
            "relevance_score": round(m.relevance_score, 4) if m.relevance_score is not None else None,
            "impact_score": round(m.impact_score, 4) if m.impact_score is not None else None,
            "match_type": m.match_type,
            "recommendation": m.recommendation,
            "reason_codes": list(m.reason_codes),
            "story_available": bool(cl is not None),
        })

    intel_available = bool(matches_summary or recs or risks or changes)

    return ProjectIntelligence(
        project_id=project.id,
        name=project.name,
        description=project.description,
        is_active=bool(project.is_active),
        last_indexed_at=project.last_indexed_at.isoformat() if project.last_indexed_at else None,
        technology_profile=prof or {},
        top_matches=matches_summary,
        recommendations=recs,
        risks=risks,
        recent_changes=changes,
        intelligence_available=intel_available,
    )
