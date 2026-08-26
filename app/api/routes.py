import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.runtime.state import load_runtime_config
from app.runtime.timezone import runtime_date_string
from app.services import claims as claims_service
from app.services import intelligence as intel_service
from app.services import projects as projects_service
from app.services import runtime as runtime_service
from app.services import saved as saved_service
from app.services.schemas import (
    ClaimDetail,
    ProjectIntelligence,
    ProjectSummary,
    RecentJobFailureRecord,
    RuntimeOverviewResponse,
    SaveItemRequest,
    SearchResult,
    SourceOperationalRecord,
    StoryDetail,
)
from app.storage.db import Database
from app.models.schemas import DailySignalRun, Project, RefreshOperation

router = APIRouter()


# --- Response envelope models -------------------------------------------------
# Explicit response_model declarations give every endpoint a stable, documented
# contract (OpenAPI schema + runtime validation) instead of ad-hoc dicts.
class RuntimeFailuresResponse(BaseModel):
    failures: List[RecentJobFailureRecord]


class SourcesResponse(BaseModel):
    sources: List[SourceOperationalRecord]


class InboxResponse(BaseModel):
    count: int
    inbox_items: List[Dict[str, Any]]


class StoriesResponse(BaseModel):
    count: int
    stories: List[SearchResult]


class ProjectsResponse(BaseModel):
    count: int
    projects: List[ProjectSummary]


class SavedResponse(BaseModel):
    count: int
    saved_items: List[Dict[str, Any]]


class ChangesResponse(BaseModel):
    count: int
    changes: List[Dict[str, Any]]


class SearchResponse(BaseModel):
    query: str
    mode: str
    count: int
    results: List[SearchResult]


class DailyStatusResponse(BaseModel):
    runs: List[DailySignalRun]


class MessageResponse(BaseModel):
    status: Optional[str] = None
    message: str


class SaveItemResponse(BaseModel):
    message: str
    saved_item: Optional[Dict[str, Any]] = None


def get_db_path() -> str:
    return os.getenv("HERMES_DB_PATH", "data/tech_intel.db")


def get_db():
    return Database(db_path=get_db_path())


@router.get("/health", summary="Health check")
def health(db: Database = Depends(get_db)):
    return runtime_service.get_health(db=db)


@router.get("/health/ready", summary="Readiness check", include_in_schema=False)
def readiness(db: Database = Depends(get_db)):
    db.conn.execute("SELECT 1").fetchone()
    return {
        "status": "ready",
        "database_path": str(db.db_path),
        "test_instance_id": os.getenv("HERMES_TEST_INSTANCE_ID"),
    }


@router.get("/runtime", summary="Runtime daemon and jobs operational overview", response_model=RuntimeOverviewResponse)
@router.get("/runtime/overview", summary="Runtime operational overview alias", response_model=RuntimeOverviewResponse)
def get_runtime(db: Database = Depends(get_db)):
    return runtime_service.get_runtime_overview(db=db)


@router.get("/runtime/failures", summary="Recent job failures", response_model=RuntimeFailuresResponse)
def get_runtime_failures(
    limit: int = Query(10, ge=1, le=50, description="Max failed runs to return"),
    db: Database = Depends(get_db),
):
    return {"failures": runtime_service.get_recent_job_failures(limit=limit, db=db)}


@router.get("/sources", summary="Source adapters health and checkpoints", response_model=SourcesResponse)
def get_sources(db: Database = Depends(get_db)):
    return {"sources": runtime_service.get_source_health(db=db)}


@router.get("/inbox", summary="Active daily inbox items", response_model=InboxResponse)
def get_inbox(
    unseen_only: bool = Query(False, description="Filter only unseen items"),
    project: Optional[str] = Query(None, description="Filter by project relevance"),
    section: Optional[str] = Query(None, description="Filter by inbox section"),
    limit: int = Query(20, ge=1, le=50, description="Max results (1-50)"),
    db: Database = Depends(get_db),
):
    items = intel_service.get_today_inbox(
        unseen_only=unseen_only,
        project=project,
        section=section,
        limit=limit,
        db=db,
    )
    return {"count": len(items), "inbox_items": items}


@router.get("/briefing", summary="Daily morning briefing")
def get_briefing(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    db: Database = Depends(get_db),
):
    if date is not None:
        date_clean = date.strip()
        try:
            parsed = datetime.strptime(date_clean, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != date_clean:
                raise ValueError()
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date format '{date}'. Expected valid calendar date in YYYY-MM-DD format.")
        target_date = date_clean
    else:
        config = load_runtime_config()
        target_date = runtime_date_string(datetime.now(timezone.utc), config)

    briefing = intel_service.get_morning_brief(date_str=target_date, db=db)
    if not briefing:
        raise HTTPException(status_code=404, detail=f"No briefing found for date '{target_date}'")
    return briefing


@router.get("/stories", summary="Top technology intelligence stories", response_model=StoriesResponse)
def get_stories(
    limit: int = Query(20, ge=1, le=50, description="Max stories (1-50)"),
    project: Optional[str] = Query(None, description="Filter by project relevance"),
    section: Optional[str] = Query(None, description="Filter by section"),
    db: Database = Depends(get_db),
):
    stories = intel_service.get_top_developments(limit=limit, project=project, section=section, db=db)
    return {"count": len(stories), "stories": [s.model_dump() for s in stories]}


@router.get("/stories/{cluster_id}", summary="Story cluster details", response_model=StoryDetail)
def get_story_by_id(cluster_id: str, db: Database = Depends(get_db)):
    story = intel_service.get_story(cluster_id=cluster_id, db=db)
    if not story:
        raise HTTPException(status_code=404, detail=f"Story cluster '{cluster_id}' not found")
    return story.model_dump()


@router.get("/claims/{claim_id}", summary="Claim verification and evidence provenance", response_model=ClaimDetail)
def get_claim_by_id(claim_id: str, db: Database = Depends(get_db)):
    claim = claims_service.get_claim(claim_id=claim_id, db=db)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")
    return claim.model_dump()


@router.get("/projects", summary="List project technology profiles", response_model=ProjectsResponse)
def get_projects(active_only: bool = Query(True, description="Only active projects"), db: Database = Depends(get_db)):
    projects = projects_service.list_projects(db=db, active_only=active_only)
    return {"count": len(projects), "projects": [p.model_dump() for p in projects]}


@router.get("/projects/{project_id}", summary="Project profile details")
def get_project_profile_by_id(project_id: str, db: Database = Depends(get_db)):
    profile = projects_service.get_project_profile(project_id_or_name=project_id, db=db)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return profile


@router.get("/projects/{project_id}/intelligence", summary="Project-specific intelligence & recommendations", response_model=ProjectIntelligence)
def get_project_intel(
    project_id: str,
    limit: int = Query(10, ge=1, le=50, description="Max recommendations (1-50)"),
    db: Database = Depends(get_db),
):
    intel = projects_service.get_project_intelligence(project_id_or_name=project_id, limit=limit, db=db)
    if not intel:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return intel.model_dump()


@router.get("/saved", summary="Saved personal library items", response_model=SavedResponse)
def get_saved(
    limit: int = Query(20, ge=1, le=50, description="Max items (1-50)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    tag: Optional[str] = Query(None, description="Tag filter"),
    include_current: bool = Query(False, description="Hydrate and return current intelligence state alongside saved snapshot"),
    db: Database = Depends(get_db),
):
    items = saved_service.get_saved_items(limit=limit, offset=offset, tag=tag, include_current=include_current, db=db)
    return {"count": len(items), "saved_items": items}


@router.post("/saved", summary="Save a story cluster to personal library", response_model=SaveItemResponse)
def save_item(
    req: SaveItemRequest,
    db: Database = Depends(get_db),
):
    success, msg, item = saved_service.save_cluster_item(
        story_cluster_id=req.story_cluster_id,
        inbox_item_id=req.inbox_item_id,
        user_note=req.user_note,
        tags=req.tags,
        db=db,
    )
    if not success:
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "saved_item": item}


@router.delete("/saved/{saved_id}", summary="Remove an item from saved personal library", response_model=MessageResponse)
def delete_saved(
    saved_id: str,
    db: Database = Depends(get_db),
):
    success, msg = saved_service.delete_saved_item(saved_id, db=db)
    if not success:
        raise HTTPException(status_code=404, detail=msg)
    return {"message": msg}


@router.get("/changes", summary="Recent intelligence changes and claim revisions", response_model=ChangesResponse)
def get_changes(
    hours: int = Query(24, ge=1, le=720, description="Hours to look back (default 24)"),
    importance_min: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$", description="Min importance"),
    project: Optional[str] = Query(None, description="Filter by project relevance"),
    limit: int = Query(20, ge=1, le=50, description="Max results (1-50)"),
    db: Database = Depends(get_db),
):
    changes = intel_service.get_recent_changes(
        hours=hours,
        importance_min=importance_min,
        project=project,
        limit=limit,
        db=db,
    )
    return {"count": len(changes), "changes": changes}


@router.get("/search", summary="Search verified intelligence", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    project: Optional[str] = Query(None, description="Project context filter/boost"),
    source: Optional[str] = Query(None, description="Source filter"),
    days: Optional[int] = Query(None, ge=1, le=365, description="Published within N days"),
    limit: int = Query(10, ge=1, le=50, description="Max results (1-50)"),
    verified_only: bool = Query(False, description="Filter verified only"),
    min_maturity: Optional[str] = Query(None, description="Min maturity stage"),
    max_risk: Optional[str] = Query(None, description="Max risk level"),
    mode: str = Query("hybrid", pattern="^(hybrid|lexical|semantic)$", description="Search mode"),
    explain: bool = Query(False, description="Include score explanation"),
    db: Database = Depends(get_db),
):
    results = intel_service.search_intelligence(
        query=q,
        project=project,
        source=source,
        days=days,
        limit=limit,
        verified_only=verified_only,
        min_maturity=min_maturity,
        max_risk=max_risk,
        mode=mode,
        explain=explain,
        db=db,
    )
    return {
        "query": q,
        "mode": mode,
        "count": len(results),
        "results": [r.model_dump() for r in results],
    }


class ProjectCreate(BaseModel):
    name: str
    path: str
    description: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    description: Optional[str] = None

class RefreshRequest(BaseModel):
    scope: str
    idempotency_key: Optional[str] = None

# Scopes the daemon worker knows how to execute (must mirror runner dispatch).
VALID_REFRESH_SCOPES = {
    "daily_refresh",
    "inbox_refresh",
    "morning_brief",
    "health_check",
    "recheck",
    "project_scan",
    "search_refresh",
    "story_recheck",
}

@router.post("/projects", summary="Add a new project and enqueue async initial scan", status_code=202, response_model=Project)
def create_project(req: ProjectCreate, response: Response, db: Database = Depends(get_db)):
    """Creates the project profile and queues a targeted background scan.

    Returns 202 Accepted immediately; scan progress is tracked on the project
    (last_scan_status) and via /runtime/operations/{operation_id}.
    """
    try:
        proj = projects_service.add_project(
            name=req.name,
            path=req.path,
            description=req.description,
            db=db
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return proj.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/projects/{project_id}", summary="Update a project and enqueue async re-scan", status_code=202, response_model=Project)
def update_project(project_id: str, req: ProjectUpdate, response: Response, db: Database = Depends(get_db)):
    """Updates mutable project fields and queues a targeted background re-scan.

    Returns 202 Accepted immediately; the scan never blocks the request.
    """
    try:
        proj = projects_service.update_project(
            project_id=project_id,
            name=req.name,
            path=req.path,
            description=req.description,
            db=db,
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return proj.model_dump()
    except ValueError as e:
        msg = str(e)
        code = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)

@router.delete("/projects/{project_id}", summary="Idempotently soft-archive a project", response_model=MessageResponse)
def archive_project(project_id: str, reason: Optional[str] = None, db: Database = Depends(get_db)):
    """Idempotent archive: DELETE succeeds whether or not the project was
    already archived. Only unknown project IDs return 404."""
    success = projects_service.archive_project(project_id=project_id, reason=reason, db=db)
    if not success:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"status": "success", "message": "Project archived successfully"}

@router.post("/projects/{project_id}/restore", summary="Restore an archived project and enqueue async re-scan", status_code=202, response_model=RefreshOperation)
def restore_project(project_id: str, response: Response, db: Database = Depends(get_db)):
    op = projects_service.restore_project(project_id=project_id, db=db)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    response.status_code = status.HTTP_202_ACCEPTED
    return op.model_dump()

@router.post("/runtime/refresh", summary="Enqueue background refresh operation", status_code=202, response_model=RefreshOperation)
def enqueue_refresh(req: RefreshRequest, response: Response, db: Database = Depends(get_db)):
    scope = (req.scope or "").strip()
    idempotency_key = req.idempotency_key or ""

    # Validate scope up front: reject unknown scopes with 422 so clients get a
    # truthful error instead of an operation that can never execute.
    if scope not in VALID_REFRESH_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown refresh scope '{scope}'. Valid scopes: {sorted(VALID_REFRESH_SCOPES)}",
        )

    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT * FROM refresh_operations WHERE scope = ? AND status IN ('queued', 'running') LIMIT 1",
        (scope,)
    )
    row = cursor.fetchone()
    active_op = db._row_to_refresh_operation(row) if row else None

    if active_op:
        if active_op.idempotency_key == idempotency_key:
            response.status_code = status.HTTP_202_ACCEPTED
            return active_op.model_dump()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An active refresh operation is already running/queued in scope '{scope}'."
            )

    now = datetime.now(timezone.utc)
    op = RefreshOperation(
        id=f"refresh:{scope}:{now.timestamp()}",
        scope=scope,
        status="queued",
        requested_at=now,
        idempotency_key=idempotency_key,
    )
    db.save_refresh_operation(op)
    
    response.status_code = status.HTTP_202_ACCEPTED
    return op.model_dump()


@router.get("/runtime/operations/{operation_id}", summary="Get refresh operation status", response_model=RefreshOperation)
def get_operation(operation_id: str, db: Database = Depends(get_db)):
    op = db.get_refresh_operation(operation_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found")
    return op.model_dump()


@router.get("/daily/status", summary="Get status of daily signal runs", response_model=DailyStatusResponse)
def get_daily_status(date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"), db: Database = Depends(get_db)):
    if date:
        run = db.get_daily_signal_run_by_date(date)
        return {"runs": [run.model_dump()] if run else []}
    else:
        cursor = db.conn.cursor()
        cursor.execute("SELECT * FROM daily_signal_runs ORDER BY runtime_date DESC LIMIT 30")
        rows = cursor.fetchall()
        # Both paths return identical canonical DailySignalRun fields so clients
        # can consume either response shape interchangeably.
        runs = [db._row_to_daily_signal_run(r).model_dump() for r in rows]
        return {"runs": runs}


