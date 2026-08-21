from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from app.services import claims as claims_service
from app.services import intelligence as intel_service
from app.services import projects as projects_service
from app.services import runtime as runtime_service
from app.services import saved as saved_service
from app.storage.db import Database

router = APIRouter()


def get_db():
    return Database()


@router.get("/health", summary="Health check")
def health(db: Database = Depends(get_db)):
    return runtime_service.get_health(db=db)


@router.get("/runtime", summary="Runtime daemon and jobs status")
def get_runtime(db: Database = Depends(get_db)):
    return runtime_service.get_runtime_status(db=db)


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
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date in YYYY-MM-DD format"),
    db: Database = Depends(get_db),
):
    briefing = intel_service.get_morning_brief(date_str=date, db=db)
    if not briefing:
        raise HTTPException(status_code=404, detail=f"No briefing found for date '{date or 'today'}'")
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
def get_projects(db: Database = Depends(get_db)):
    projects = projects_service.list_projects(db=db)
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
