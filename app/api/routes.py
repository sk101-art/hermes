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
from app.services.schemas import SaveItemRequest
from app.storage.db import Database
from app.models.schemas import RefreshOperation

router = APIRouter()


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


@router.get("/runtime", summary="Runtime daemon and jobs operational overview")
@router.get("/runtime/overview", summary="Runtime operational overview alias")
def get_runtime(db: Database = Depends(get_db)):
    return runtime_service.get_runtime_overview(db=db)


@router.get("/runtime/failures", summary="Recent job failures")
def get_runtime_failures(
    limit: int = Query(10, ge=1, le=50, description="Max failed runs to return"),
    db: Database = Depends(get_db),
):
    return {"failures": runtime_service.get_recent_job_failures(limit=limit, db=db)}


@router.get("/sources", summary="Source adapters health and checkpoints")
def get_sources(db: Database = Depends(get_db)):
    return {"sources": runtime_service.get_source_health(db=db)}


@router.get("/inbox", summary="Active daily inbox items")
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


@router.get("/stories", summary="Top technology intelligence stories")
def get_stories(
    limit: int = Query(20, ge=1, le=50, description="Max stories (1-50)"),
    project: Optional[str] = Query(None, description="Filter by project relevance"),
    section: Optional[str] = Query(None, description="Filter by section"),
    db: Database = Depends(get_db),
):
    stories = intel_service.get_top_developments(limit=limit, project=project, section=section, db=db)
    return {"count": len(stories), "stories": [s.model_dump() for s in stories]}


@router.get("/stories/{cluster_id}", summary="Story cluster details")
def get_story_by_id(cluster_id: str, db: Database = Depends(get_db)):
    story = intel_service.get_story(cluster_id=cluster_id, db=db)
    if not story:
        raise HTTPException(status_code=404, detail=f"Story cluster '{cluster_id}' not found")
    return story.model_dump()


@router.get("/claims/{claim_id}", summary="Claim verification and evidence provenance")
def get_claim_by_id(claim_id: str, db: Database = Depends(get_db)):
    claim = claims_service.get_claim(claim_id=claim_id, db=db)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")
    return claim.model_dump()


@router.get("/projects", summary="List project technology profiles")
def get_projects(active_only: bool = Query(True, description="Only active projects"), db: Database = Depends(get_db)):
    projects = projects_service.list_projects(db=db, active_only=active_only)
    return {"count": len(projects), "projects": [p.model_dump() for p in projects]}


@router.get("/projects/{project_id}", summary="Project profile details")
def get_project_profile_by_id(project_id: str, db: Database = Depends(get_db)):
    profile = projects_service.get_project_profile(project_id_or_name=project_id, db=db)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return profile


@router.get("/projects/{project_id}/intelligence", summary="Project-specific intelligence & recommendations")
def get_project_intel(
    project_id: str,
    limit: int = Query(10, ge=1, le=50, description="Max recommendations (1-50)"),
    db: Database = Depends(get_db),
):
    intel = projects_service.get_project_intelligence(project_id_or_name=project_id, limit=limit, db=db)
    if not intel:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return intel.model_dump()


@router.get("/saved", summary="Saved personal library items")
def get_saved(
    limit: int = Query(20, ge=1, le=50, description="Max items (1-50)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    tag: Optional[str] = Query(None, description="Tag filter"),
    include_current: bool = Query(False, description="Hydrate and return current intelligence state alongside saved snapshot"),
    db: Database = Depends(get_db),
):
    items = saved_service.get_saved_items(limit=limit, offset=offset, tag=tag, include_current=include_current, db=db)
    return {"count": len(items), "saved_items": items}


@router.post("/saved", summary="Save a story cluster to personal library")
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


@router.delete("/saved/{saved_id}", summary="Remove an item from saved personal library")
def delete_saved(
    saved_id: str,
    db: Database = Depends(get_db),
):
    success, msg = saved_service.delete_saved_item(saved_id, db=db)
    if not success:
        raise HTTPException(status_code=404, detail=msg)
    return {"message": msg}


@router.get("/changes", summary="Recent intelligence changes and claim revisions")
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


@router.get("/search", summary="Search verified intelligence")
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

class RefreshRequest(BaseModel):
    scope: str
    idempotency_key: Optional[str] = None

@router.post("/projects", summary="Add a new project")
def create_project(req: ProjectCreate, db: Database = Depends(get_db)):
    try:
        proj = projects_service.add_project(
            name=req.name,
            path=req.path,
            description=req.description,
            db=db
        )
        return proj.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/projects/{project_id}/archive", summary="Soft-archive a project")
def archive_project(project_id: str, reason: Optional[str] = None, db: Database = Depends(get_db)):
    success = projects_service.archive_project(project_id=project_id, reason=reason, db=db)
    if not success:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"status": "success", "message": "Project archived successfully"}

@router.post("/projects/{project_id}/restore", summary="Restore an archived project")
def restore_project(project_id: str, db: Database = Depends(get_db)):
    success = projects_service.restore_project(project_id=project_id, db=db)
    if not success:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"status": "success", "message": "Project restored successfully"}

@router.post("/projects/{project_id}/scan", summary="Rescan a single project")
def scan_project(project_id: str, db: Database = Depends(get_db)):
    try:
        res = projects_service.scan_single_project(project_id=project_id, db=db)
        if res.get("status") == "failed":
            raise HTTPException(status_code=400, detail=res.get("error"))
        return res
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/runtime/refresh", summary="Enqueue background refresh operation", status_code=202)
def enqueue_refresh(req: RefreshRequest, response: Response, db: Database = Depends(get_db)):
    scope = req.scope
    idempotency_key = req.idempotency_key or ""

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


@router.get("/runtime/operations/{operation_id}", summary="Get refresh operation status")
def get_operation(operation_id: str, db: Database = Depends(get_db)):
    op = db.get_refresh_operation(operation_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found")
    return op.model_dump()


@router.get("/daily/status", summary="Get status of daily signal runs")
def get_daily_status(date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"), db: Database = Depends(get_db)):
    if date:
        run = db.get_daily_signal_run_by_date(date)
        return {"runs": [run.model_dump()] if run else []}
    else:
        cursor = db.conn.cursor()
        cursor.execute("SELECT * FROM daily_signal_runs ORDER BY runtime_date DESC LIMIT 30")
        rows = cursor.fetchall()
        runs = []
        for r in rows:
            runs.append({
                "id": r["id"],
                "runtime_date": r["runtime_date"],
                "status": r["status"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "new_signal_count": r["new_signal_count"],
                "updated_signal_count": r["updated_signal_count"],
                "carried_signal_count": r["carried_signal_count"],
                "briefing_id": r["briefing_id"],
                "error_summary": r["error_summary"],
            })
        return {"runs": runs}


