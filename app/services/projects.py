from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.models.schemas import Project
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
    Strict privacy: Exposes ONLY derived technologies and metadata, NO private source code.
    """
    if db is None:
        db = Database()

    projects = db.get_all_projects(active_only=True)
    summaries = []
    for p in projects:
        summaries.append(
            ProjectSummary(
                project_id=p.id,
                name=p.name,
                languages=list(p.languages),
                frameworks=list(p.frameworks),
                libraries=list(p.libraries),
                databases=list(p.databases),
                infrastructure=list(p.infrastructure),
                topics=list(p.topics),
                last_indexed_at=p.last_indexed_at.isoformat() if p.last_indexed_at else None,
            )
        )
    return summaries


def get_project_profile(
    project_id_or_name: str,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves structured technology profile for a specific project without raw file contents."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return None

    profile = db.get_project_profile(project.id)
    return {
        "project_id": project.id,
        "name": project.name,
        "description": project.description,
        "languages": project.languages,
        "frameworks": project.frameworks,
        "libraries": project.libraries,
        "databases": project.databases,
        "infrastructure": project.infrastructure,
        "models": project.models,
        "tools": project.tools,
        "topics": project.topics,
        "keywords": project.keywords,
        "profile_hash": profile.profile_hash if profile else None,
        "last_indexed_at": project.last_indexed_at.isoformat() if project.last_indexed_at else None,
    }


def get_project_recommendations(
    project_id_or_name: str,
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves top actionable recommendations for a project."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return []

    limit = max(1, min(limit, 50))
    matches = db.get_project_matches(project.id)
    # Sort by relevance score
    matches.sort(key=lambda m: m.relevance_score, reverse=True)

    recs = []
    for m in matches[:limit]:
        cl = db.get_cluster(m.entity_id)
        if not cl:
            continue
        recs.append({
            "cluster_id": m.entity_id,
            "title": cl.canonical_title,
            "relevance_score": round(m.relevance_score, 4),
            "match_type": m.match_type,
            "recommendation": m.recommendation,
            "reason_codes": list(m.reason_codes),
        })
    return recs


def get_project_risks(
    project_id_or_name: str,
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves breaking changes, deprecations, or high-risk matches for a project."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return []

    limit = max(1, min(limit, 50))
    matches = db.get_project_matches(project.id)

    risks = []
    for m in matches:
        if m.match_type in ("breaking_change", "vulnerability", "deprecation") or m.impact_score >= 0.70:
            cl = db.get_cluster(m.entity_id)
            if not cl:
                continue
            risks.append({
                "cluster_id": m.entity_id,
                "title": cl.canonical_title,
                "match_type": m.match_type,
                "recommendation": m.recommendation,
                "impact_score": round(m.impact_score, 4),
                "relevance_score": round(m.relevance_score, 4),
                "reason_codes": list(m.reason_codes),
            })

    risks.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)
    return risks[:limit]


def get_project_changes(
    project_id_or_name: str,
    hours: int = 24,
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recent intelligence changes matching technologies in the project."""
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return []

    limit = max(1, min(limit, 50))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    matches = db.get_project_matches(project.id)
    matching_cluster_ids = {m.entity_id for m in matches}

    all_changes = db.get_recent_intelligence_changes(days=int(max(1, hours / 24)), limit=100)
    proj_changes = []

    for ch in all_changes:
        if ch.detected_at >= cutoff and ch.cluster_id in matching_cluster_ids:
            proj_changes.append({
                "id": ch.id,
                "cluster_id": ch.cluster_id,
                "change_type": ch.change_type,
                "importance": ch.importance,
                "description": ch.description,
                "old_value": ch.old_value,
                "new_value": ch.new_value,
                "detected_at": ch.detected_at.isoformat(),
            })

    return proj_changes[:limit]


def get_project_intelligence(
    project_id_or_name: str,
    limit: int = 10,
    db: Optional[Database] = None,
) -> Optional[ProjectIntelligence]:
    """Aggregates technology profile, matches, recommendations, risks, and recent changes."""
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
    matches_summary = []
    for m in matches[:limit]:
        cl = db.get_cluster(m.entity_id)
        matches_summary.append({
            "cluster_id": m.entity_id,
            "title": cl.canonical_title if cl else m.entity_id,
            "relevance_score": round(m.relevance_score, 4),
            "match_type": m.match_type,
            "recommendation": m.recommendation,
        })

    return ProjectIntelligence(
        project_id=project.id,
        name=project.name,
        technology_profile=prof or {},
        top_matches=matches_summary,
        recommendations=recs,
        risks=risks,
        recent_changes=changes,
    )
