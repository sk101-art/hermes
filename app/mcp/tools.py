import json
from typing import Any, Dict, List, Optional

from app.mcp.schemas import (
    AddSavedNoteInput,
    AddSavedTagInput,
    ClaimInput,
    MorningBriefInput,
    ProjectIntelligenceInput,
    RecentChangesInput,
    SavedItemInput,
    SavedItemsInput,
    SearchInput,
    StarItemInput,
    StoryInput,
    TodayInboxInput,
    TopDevelopmentsInput,
)
from app.services import claims as claims_service
from app.services import intelligence as intel_service
from app.services import projects as projects_service
from app.services import runtime as runtime_service
from app.services import saved as saved_service
from app.storage.db import Database


def tool_health(db: Optional[Database] = None) -> Dict[str, Any]:
    """Health check tool returning service and database status."""
    try:
        return runtime_service.get_health(db=db)
    except Exception as e:
        return {"status": "error", "message": f"Health check failed: {str(e)}"}


def tool_search_intelligence(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Search HERMES verified technology intelligence database using hybrid retrieval."""
    try:
        validated = SearchInput(**args)
        results = intel_service.search_intelligence(
            query=validated.query,
            project=validated.project,
            source=validated.source,
            days=validated.days,
            limit=validated.limit,
            verified_only=validated.verified_only,
            min_maturity=validated.min_maturity,
            max_risk=validated.max_risk,
            mode=validated.mode,
            explain=False,
            db=db,
        )
        return {
            "query": validated.query,
            "mode": validated.mode,
            "count": len(results),
            "results": [r.model_dump() for r in results],
        }
    except Exception as e:
        return {"error": "Invalid search parameters or internal error", "detail": str(e)}


def tool_get_top_developments(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve top-ranked technology developments from current intelligence."""
    try:
        validated = TopDevelopmentsInput(**args)
        results = intel_service.get_top_developments(
            limit=validated.limit,
            project=validated.project,
            section=validated.section,
            db=db,
        )
        return {
            "count": len(results),
            "developments": [r.model_dump() for r in results],
        }
    except Exception as e:
        return {"error": "Failed to get top developments", "detail": str(e)}


def tool_get_today_inbox(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve today's active calibrated inbox items."""
    try:
        validated = TodayInboxInput(**args)
        items = intel_service.get_today_inbox(
            unseen_only=validated.unseen_only,
            project=validated.project,
            section=validated.section,
            limit=validated.limit,
            db=db,
            surface_date=validated.date,
        )
        return {"count": len(items), "inbox_items": items}
    except Exception as e:
        return {"error": "Failed to retrieve inbox items", "detail": str(e)}


def tool_get_morning_brief(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve structured daily morning briefing."""
    try:
        validated = MorningBriefInput(**args)
        briefing = intel_service.get_morning_brief(date_str=validated.date, db=db)
        if not briefing:
            return {"status": "not_found", "message": f"No briefing found for date '{validated.date or 'today'}'"}
        return briefing
    except Exception as e:
        return {"error": "Failed to get morning briefing", "detail": str(e)}


def tool_get_story(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve full structured intelligence for a StoryCluster."""
    try:
        validated = StoryInput(**args)
        story = intel_service.get_story(cluster_id=validated.cluster_id, db=db)
        if not story:
            return {"status": "not_found", "message": f"Story cluster '{validated.cluster_id}' not found"}
        return story.model_dump()
    except Exception as e:
        return {"error": "Failed to retrieve story details", "detail": str(e)}


def tool_get_claim(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve claim details with evidence provenance and longitudinal revision history."""
    try:
        validated = ClaimInput(**args)
        claim = claims_service.get_claim(claim_id=validated.claim_id, db=db)
        if not claim:
            return {"status": "not_found", "message": f"Claim '{validated.claim_id}' not found"}
        return claim.model_dump()
    except Exception as e:
        return {"error": "Failed to retrieve claim details", "detail": str(e)}


def tool_list_projects(db: Optional[Database] = None) -> Dict[str, Any]:
    """List summarized technology profiles for all indexed reference projects (privacy protected)."""
    try:
        summaries = projects_service.list_projects(db=db)
        return {"count": len(summaries), "projects": [p.model_dump() for p in summaries]}
    except Exception as e:
        return {"error": "Failed to list projects", "detail": str(e)}


def tool_get_project_intelligence(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve derived technology intelligence, recommendations, and risks for a project."""
    try:
        validated = ProjectIntelligenceInput(**args)
        intel = projects_service.get_project_intelligence(
            project_id_or_name=validated.project,
            limit=validated.limit,
            db=db,
        )
        if not intel:
            return {"status": "not_found", "message": f"Project '{validated.project}' not found"}
        return intel.model_dump()
    except Exception as e:
        return {"error": "Failed to get project intelligence", "detail": str(e)}


def tool_get_saved_items(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve items saved in personal library."""
    try:
        validated = SavedItemsInput(**args)
        items = saved_service.get_saved_items(
            limit=validated.limit,
            offset=validated.offset,
            tag=validated.tag,
            db=db,
        )
        return {"count": len(items), "saved_items": items}
    except Exception as e:
        return {"error": "Failed to retrieve saved items", "detail": str(e)}


def tool_get_saved_item(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve a specific saved item snapshot with user notes."""
    try:
        validated = SavedItemInput(**args)
        item = saved_service.get_saved_item(saved_id=validated.saved_id, db=db)
        if not item:
            return {"status": "not_found", "message": f"Saved item '{validated.saved_id}' not found"}
        return item
    except Exception as e:
        return {"error": "Failed to retrieve saved item", "detail": str(e)}


def tool_star_item(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Safely star an inbox item and preserve it in personal library."""
    try:
        validated = StarItemInput(**args)
        success, message, saved_item = saved_service.star_inbox_item(
            inbox_item_id=validated.inbox_item_id,
            db=db,
        )
        return {"success": success, "message": message, "saved_item": saved_item}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_add_saved_note(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Add a user note to a saved item (max 2000 chars)."""
    try:
        validated = AddSavedNoteInput(**args)
        success, message = saved_service.add_saved_note(
            saved_id=validated.saved_id,
            note_text=validated.note,
            db=db,
        )
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_add_saved_tag(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Add a tag to a saved item."""
    try:
        validated = AddSavedTagInput(**args)
        success, message = saved_service.add_saved_tag(
            saved_id=validated.saved_id,
            tag=validated.tag,
            db=db,
        )
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_get_recent_changes(args: Dict[str, Any], db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve recent longitudinal changes, claim revisions, and ecosystem movements."""
    try:
        validated = RecentChangesInput(**args)
        changes = intel_service.get_recent_changes(
            hours=validated.hours,
            importance_min=validated.importance_min,
            project=validated.project,
            limit=validated.limit,
            db=db,
        )
        return {"count": len(changes), "changes": changes}
    except Exception as e:
        return {"error": "Failed to get recent changes", "detail": str(e)}


def tool_get_source_health(db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve health and checkpoint telemetry for all source adapters."""
    try:
        sources = runtime_service.get_source_health(db=db)
        return {"count": len(sources), "sources": sources}
    except Exception as e:
        return {"error": "Failed to get source health", "detail": str(e)}


def tool_get_runtime_status(db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieve background daemon status, job schedules, and lifetime metrics."""
    try:
        return runtime_service.get_runtime_status(db=db)
    except Exception as e:
        return {"error": "Failed to get runtime status", "detail": str(e)}
