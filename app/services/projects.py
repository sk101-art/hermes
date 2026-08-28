from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import json
from pathlib import Path

from app.models.schemas import Project, RefreshOperation
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


def list_projects(db: Optional[Database] = None, active_only: bool = True) -> List[ProjectSummary]:
    """
    Lists summarized technology profiles for projects.
    Strict privacy: Exposes ONLY derived technologies and metadata, NO private source code or local filesystem paths.
    """
    if db is None:
        db = Database()

    projects = db.get_all_projects(active_only=active_only)

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

# Additional audited concern criteria (explanation-upgrade spec).
EXPLICIT_INCOMPATIBLE_DEP_REASON_CODES = frozenset({
    "incompatible_dependency",
})
EXPLICIT_INCOMPATIBLE_DEP_PREFIXES = (
    "incompatible_dependency:",
)

EXPLICIT_REMOVED_FEATURE_REASON_CODES = frozenset({
    "removed_feature",
})
EXPLICIT_REMOVED_FEATURE_PREFIXES = (
    "removed_feature:",
)

EXPLICIT_OPERATIONAL_INCOMPAT_REASON_CODES = frozenset({
    "operational_incompat",
})
EXPLICIT_OPERATIONAL_INCOMPAT_PREFIXES = (
    "operational_incompat:",
)

EXPLICIT_EVIDENCE_REGRESSION_REASON_CODES = frozenset({
    "evidence_regression",
})
EXPLICIT_EVIDENCE_REGRESSION_PREFIXES = (
    "evidence_regression:",
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
    Retrieves engineering concerns for a project with batch-resolved inputs.

    A match becomes a concern ONLY when one of these concrete criteria is met:
    vulnerability/CVE, breaking API/ABI change, deprecation/EOL, incompatible
    dependency version, removed/changed feature in use, verified high/critical
    canonical risk, operational incompatibility, or evidence-backed regression.

    A high impact score alone is NEVER a concern (removed by the
    explanation-upgrade spec).
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
        is_incompat_dep = _matches_explicit_codes(
            m.reason_codes, EXPLICIT_INCOMPATIBLE_DEP_REASON_CODES, EXPLICIT_INCOMPATIBLE_DEP_PREFIXES
        )
        is_removed_feature = _matches_explicit_codes(
            m.reason_codes, EXPLICIT_REMOVED_FEATURE_REASON_CODES, EXPLICIT_REMOVED_FEATURE_PREFIXES
        )
        is_operational_incompat = _matches_explicit_codes(
            m.reason_codes, EXPLICIT_OPERATIONAL_INCOMPAT_REASON_CODES, EXPLICIT_OPERATIONAL_INCOMPAT_PREFIXES
        )
        is_evidence_regression = _matches_explicit_codes(
            m.reason_codes, EXPLICIT_EVIDENCE_REGRESSION_REASON_CODES, EXPLICIT_EVIDENCE_REGRESSION_PREFIXES
        )

        # NOTE: high impact score alone is deliberately NOT a concern criterion.
        if not (
            is_vuln or is_breaking or is_deprec or is_assessed_risk
            or is_incompat_dep or is_removed_feature or is_operational_incompat
            or is_evidence_regression
        ):
            continue

        concern_type = (
            "vulnerability" if is_vuln else (
                "breaking_change" if is_breaking else (
                    "deprecation" if is_deprec else (
                        "assessed_risk" if is_assessed_risk else (
                            "incompatible_dependency" if is_incompat_dep else (
                                "removed_feature" if is_removed_feature else (
                                    "operational_incompat" if is_operational_incompat else "evidence_regression"
                                )
                            )
                        )
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
            "explanation": m.explanation.model_dump() if m.explanation else None,
            "explanation_version": m.explanation_version or "legacy_unexplained",
            "story_available": bool(cl is not None),
        })

    intel_available = bool(matches_summary or recs or risks or changes)

    return ProjectIntelligence(
        project_id=project.id,
        name=project.name,
        description=project.description,
        narrative=project.narrative.model_dump() if project.narrative else None,
        is_active=bool(project.is_active),
        last_indexed_at=project.last_indexed_at.isoformat() if project.last_indexed_at else None,
        technology_profile=prof or {},
        top_matches=matches_summary,
        recommendations=recs,
        risks=risks,
        recent_changes=changes,
        intelligence_available=intel_available,
    )


def get_project_match_comparison(
    project_id_or_name: str,
    cluster_id: str,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Canonical {project, subject, match} payload for one project/cluster match.

    Used by every surface that explains why an intelligence item matched a
    project (project detail cards, story-detail comparison table). Returns
    None when the project or the match does not exist.
    """
    if db is None:
        db = Database()

    project = resolve_project(project_id_or_name, db)
    if not project:
        return None

    match = db.get_project_match(project.id, cluster_id)
    if not match:
        return None

    cluster = db.get_cluster(cluster_id)
    events = db.get_cluster_events(cluster_id) if cluster else []
    claims = db.get_claims_by_cluster(cluster_id) if cluster else []

    subject = {
        "cluster_id": cluster_id,
        "title": cluster.canonical_title if cluster else cluster_id,
        "story_available": bool(cluster is not None),
        "event_count": len(events),
        "claim_count": len(claims),
        "sources": list(cluster.sources) if cluster else [],
    }

    return {
        "project": {
            "project_id": project.id,
            "name": project.name,
            "description": project.description,
            "narrative": project.narrative.model_dump() if project.narrative else None,
            "languages": list(project.languages),
            "frameworks": list(project.frameworks),
            "databases": list(project.databases),
            "topics": list(project.topics),
        },
        "subject": subject,
        "match": {
            "cluster_id": match.entity_id,
            "match_type": match.match_type,
            "relevance_score": round(match.relevance_score, 4) if match.relevance_score is not None else None,
            "impact_score": round(match.impact_score, 4) if match.impact_score is not None else None,
            "recommendation": match.recommendation,
            "reason_codes": list(match.reason_codes),
            "explanation": match.explanation.model_dump() if match.explanation else None,
            "explanation_version": match.explanation_version or "legacy_unexplained",
            "evaluated_at": match.evaluated_at.isoformat() if match.evaluated_at else None,
        },
    }


def enqueue_project_scan(project_id: str, db: Database) -> RefreshOperation:
    """Enqueues a targeted asynchronous 'project_scan' operation for one project.

    The daemon worker executes the scan in the background; the caller only
    receives the queued operation record (API surfaces return 202 Accepted).
    """
    now = datetime.now(timezone.utc)
    op = RefreshOperation(
        id=f"refresh:project_scan:{now.timestamp()}",
        scope="project_scan",
        target_id=project_id,
        status="queued",
        requested_at=now,
        trigger="user_requested",
    )
    db.save_refresh_operation(op)
    return op


def add_project(
    name: str,
    path: str,
    description: Optional[str] = None,
    db: Optional[Database] = None,
    approved_via_picker: bool = False,
) -> Project:
    """Adds a new project and enqueues an asynchronous initial scan.

    The scan runs as a background 'project_scan' refresh operation so the API
    call returns promptly; last_scan_status tracks progress ('pending' until
    the worker picks it up).

    ``approved_via_picker=True`` marks paths already validated by the
    native-picker approval flow (safety + policy ceiling + approvals ledger);
    such paths are exempt from the legacy allowed-roots check, which only
    gates manually supplied paths.
    """
    if db is None:
        db = Database()

    name_clean = name.strip()
    if not name_clean:
        raise ValueError("Project name must not be empty.")
    project_id = f"project:{name_clean.lower().replace(' ', '_')}"
    if db.get_project(project_id):
        raise ValueError(f"Project '{name_clean}' already exists.")

    from app.context.scanner import is_path_safe_and_inside_allowed_roots
    p_path = Path(path).resolve()
    if not approved_via_picker and not is_path_safe_and_inside_allowed_roots(p_path):
        raise ValueError(f"Project path '{path}' is not an existing directory within allowed workspace roots.")

    proj = Project(
        id=project_id,
        name=name_clean,
        path=str(p_path).replace("\\", "/"),
        description=description,
        is_active=True,
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_scan_status="pending",
    )
    db.save_project(proj)

    # Enqueue asynchronous initial scan instead of blocking the caller.
    enqueue_project_scan(proj.id, db)
    return db.get_project(proj.id)


def update_project(
    project_id: str,
    name: Optional[str] = None,
    path: Optional[str] = None,
    description: Optional[str] = None,
    db: Optional[Database] = None,
    approved_via_picker: bool = False,
) -> Project:
    """Updates a project's mutable fields and enqueues an asynchronous re-scan.

    Raises ValueError when the project does not exist or the new path fails
    path-safety validation. Like add_project, the follow-up scan is queued so
    the API call returns promptly (202 at the HTTP layer).

    ``approved_via_picker=True`` exempts the path from the legacy allowed-roots
    check (see add_project); manually supplied paths are still gated by it.
    """
    if db is None:
        db = Database()

    proj = db.get_project(project_id)
    if not proj:
        raise ValueError(f"Project '{project_id}' not found.")

    from app.context.scanner import is_path_safe_and_inside_allowed_roots

    if name is not None:
        name_clean = name.strip()
        if not name_clean:
            raise ValueError("Project name must not be empty.")
        proj.name = name_clean

    if path is not None:
        p_path = Path(path).resolve()
        if not approved_via_picker and not is_path_safe_and_inside_allowed_roots(p_path):
            raise ValueError(f"Project path '{path}' is not an existing directory within allowed workspace roots.")
        proj.path = str(p_path).replace("\\", "/")

    if description is not None:
        proj.description = description

    proj.updated_at = datetime.now(timezone.utc)
    proj.last_scan_status = "pending"
    db.save_project(proj)

    # Enqueue asynchronous re-scan instead of blocking the caller.
    enqueue_project_scan(proj.id, db)
    return db.get_project(proj.id)


def archive_project(
    project_id: str,
    reason: Optional[str] = None,
    db: Optional[Database] = None,
) -> bool:
    """Idempotently soft-archives a project (is_active = 0, status = 'archived').

    Archiving an already-archived project is a no-op that still succeeds, so
    the DELETE endpoint is safe to retry.
    """
    if db is None:
        db = Database()

    proj = db.get_project(project_id)
    if not proj:
        return False

    if proj.status == "archived" and not proj.is_active:
        return True  # already archived: idempotent success

    proj.is_active = False
    proj.status = "archived"
    proj.archived_at = datetime.now(timezone.utc)
    proj.archive_reason = reason or "User requested archive"
    db.save_project(proj)
    return True


def restore_project(
    project_id: str,
    db: Optional[Database] = None,
) -> Optional[RefreshOperation]:
    """Restores a soft-archived project and enqueues an asynchronous re-scan.

    Mirrors add_project: the scan runs as a background 'project_scan' refresh
    operation so the API call returns promptly. Returns the queued refresh
    operation, or None if the project was not found.
    """
    if db is None:
        db = Database()

    proj = db.get_project(project_id)
    if not proj:
        return None

    proj.is_active = True
    proj.status = "active"
    proj.archived_at = None
    proj.archive_reason = None
    proj.last_scan_status = "pending"
    db.save_project(proj)

    # Enqueue asynchronous re-scan instead of blocking the caller.
    return enqueue_project_scan(proj.id, db)


def scan_single_project(
    project_id: str,
    db: Optional[Database] = None,
) -> Dict[str, Any]:
    """Indexes a single project folder, updates profile, matches, and embeddings."""
    if db is None:
        db = Database()

    proj = db.get_project(project_id)
    if not proj:
        raise ValueError(f"Project '{project_id}' not found.")

    if proj.status == "archived":
        raise ValueError(f"Project '{project_id}' is archived and cannot be scanned.")

    from app.services.folder_access import is_folder_access_revoked
    if is_folder_access_revoked(proj.path):
        raise ValueError(f"Folder access for project '{project_id}' has been revoked.")

    from app.context.scanner import scan_project_files, compute_project_context_hash
    from app.context.profiler import build_project_technology_profile
    from app.context.narrative import extract_narrative_from_docs
    from app.context.embeddings import get_or_create_project_embedding, unload_embedder
    from app.context.matcher import match_project_with_cluster
    import numpy as np

    p_dir = Path(proj.path)
    if not p_dir.exists():
        proj.last_scan_status = "scan_failed"
        proj.last_scan_error = "Directory does not exist"
        db.save_project(proj)
        return {"status": "failed", "error": "Directory does not exist"}

    now = datetime.now(timezone.utc)
    proj.last_scan_started_at = now
    db.save_project(proj)

    try:
        # Exclude other active project paths to prevent overlap
        other_active_projects = [p for p in db.get_all_projects(active_only=True) if p.id != proj.id]
        exclude_paths = [Path(p.path) for p in other_active_projects]

        files, stats = scan_project_files(proj.id, p_dir, exclude_paths=exclude_paths)
        context_hash = compute_project_context_hash(files)

        # Clear old files for this project
        db.conn.execute("DELETE FROM project_files WHERE project_id = ?", (proj.id,))
        for pf in files:
            db.save_project_file(pf)

        profile, meta = build_project_technology_profile(proj.id, proj.name, files)

        # Structured narrative extraction (persisted independently from tags)
        narrative = extract_narrative_from_docs(files, user_description=proj.description)
        proj.narrative = narrative

        # Save project fields
        proj.languages = list(meta.get("languages", []))
        proj.frameworks = list(meta.get("frameworks", []))
        proj.libraries = list(meta.get("libraries", []))
        proj.databases = list(meta.get("databases", []))
        proj.infrastructure = list(meta.get("infrastructure", []))
        proj.models = list(meta.get("models", []))
        proj.tools = list(meta.get("tools", []))
        proj.topics = list(meta.get("topics", []))
        proj.keywords = list(meta.get("keywords", []))
        proj.context_hash = context_hash
        proj.last_indexed_at = now
        proj.last_scan_status = "completed"
        proj.last_scan_completed_at = now
        proj.last_scan_error = None
        db.save_project(proj)
        db.save_project_profile(profile)

        # Update embeddings and matches
        get_or_create_project_embedding(proj.id, profile.profile_text, profile.profile_hash, db)
        p_emb = db.get_project_embedding(proj.id, "sentence-transformers/all-MiniLM-L6-v2")
        
        # Rescan matches for this project
        db.clear_project_matches(proj.id)
        active_clusters = db.get_all_clusters()
        for cl in active_clusters:
            events = db.get_cluster_events(cl.id)
            claims = db.get_claims_by_cluster(cl.id)
            assessment = db.get_technology_assessment(cl.id)
            tech_state = db.get_technology_state(cl.id)

            match = match_project_with_cluster(
                project=proj,
                profile=profile,
                project_embedding=p_emb,
                cluster=cl,
                cluster_events=events,
                cluster_claims=claims,
                assessment=assessment,
                tech_state=tech_state,
                db=db,
            )
            if match:
                db.save_project_match(match)

        unload_embedder()
        return {
            "status": "completed",
            "files_scanned": len(files),
            "stats": stats,
        }
    except Exception as e:
        proj.last_scan_status = "scan_failed"
        proj.last_scan_error = str(e)
        db.save_project(proj)
        return {"status": "failed", "error": str(e)}

