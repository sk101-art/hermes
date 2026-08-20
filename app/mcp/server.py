import sys
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from app.mcp import tools as mcp_tools
from app.storage.db import Database

# Initialize FastMCP Server
mcp = FastMCP("hermes")


@mcp.tool()
def health() -> Dict[str, Any]:
    """Check HERMES local service, database integrity, and runtime daemon health."""
    return mcp_tools.tool_health()


@mcp.tool()
def search_intelligence(
    query: str,
    project: Optional[str] = None,
    source: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = 10,
    verified_only: bool = False,
    min_maturity: Optional[str] = None,
    max_risk: Optional[str] = None,
    mode: str = "hybrid",
) -> Dict[str, Any]:
    """
    Search HERMES verified technology intelligence database using hybrid retrieval.
    Combines SQLite FTS5 lexical matching, semantic vector reranking, verification scores, and project context.
    """
    args = {
        "query": query,
        "project": project,
        "source": source,
        "days": days,
        "limit": limit,
        "verified_only": verified_only,
        "min_maturity": min_maturity,
        "max_risk": max_risk,
        "mode": mode,
    }
    return mcp_tools.tool_search_intelligence(args)


@mcp.tool()
def get_top_developments(
    limit: int = 10,
    project: Optional[str] = None,
    section: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve top-ranked technology developments from current intelligence."""
    args = {"limit": limit, "project": project, "section": section}
    return mcp_tools.tool_get_top_developments(args)


@mcp.tool()
def get_today_inbox(
    unseen_only: bool = False,
    project: Optional[str] = None,
    section: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Retrieve today's active calibrated personal intelligence inbox."""
    args = {
        "unseen_only": unseen_only,
        "project": project,
        "section": section,
        "limit": limit,
    }
    return mcp_tools.tool_get_today_inbox(args)


@mcp.tool()
def get_morning_brief(date: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve structured daily morning briefing for today or a specific date (YYYY-MM-DD)."""
    args = {"date": date}
    return mcp_tools.tool_get_morning_brief(args)


@mcp.tool()
def get_story(cluster_id: str) -> Dict[str, Any]:
    """Retrieve full structured intelligence, supporting events, claims, and project matches for a StoryCluster."""
    args = {"cluster_id": cluster_id}
    return mcp_tools.tool_get_story(args)


@mcp.tool()
def get_claim(claim_id: str) -> Dict[str, Any]:
    """Retrieve claim details with full evidence provenance, stances, and longitudinal revision history."""
    args = {"claim_id": claim_id}
    return mcp_tools.tool_get_claim(args)


@mcp.tool()
def list_projects() -> Dict[str, Any]:
    """List summarized technology profiles for all indexed reference projects (privacy protected; no source code)."""
    return mcp_tools.tool_list_projects()


@mcp.tool()
def get_project_intelligence(project: str, limit: int = 10) -> Dict[str, Any]:
    """Retrieve derived technology intelligence, recommendations, matches, and risks for a specific project."""
    args = {"project": project, "limit": limit}
    return mcp_tools.tool_get_project_intelligence(args)


@mcp.tool()
def get_saved_items(
    limit: int = 20,
    offset: int = 0,
    tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve items saved in personal library with pagination and optional tag filtering."""
    args = {"limit": limit, "offset": offset, "tag": tag}
    return mcp_tools.tool_get_saved_items(args)


@mcp.tool()
def get_saved_item(saved_id: str) -> Dict[str, Any]:
    """Retrieve a specific saved item snapshot with user notes."""
    args = {"saved_id": saved_id}
    return mcp_tools.tool_get_saved_item(args)


@mcp.tool()
def star_item(inbox_item_id: str) -> Dict[str, Any]:
    """Safely star an inbox item and preserve it in the personal saved library."""
    args = {"inbox_item_id": inbox_item_id}
    return mcp_tools.tool_star_item(args)


@mcp.tool()
def add_saved_note(saved_id: str, note: str) -> Dict[str, Any]:
    """Add a user note to a saved item in the personal library (max 2000 characters)."""
    args = {"saved_id": saved_id, "note": note}
    return mcp_tools.tool_add_saved_note(args)


@mcp.tool()
def add_saved_tag(saved_id: str, tag: str) -> Dict[str, Any]:
    """Add a tag to a saved item in the personal library."""
    args = {"saved_id": saved_id, "tag": tag}
    return mcp_tools.tool_add_saved_tag(args)


@mcp.tool()
def get_recent_changes(
    hours: int = 24,
    importance_min: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Retrieve recent longitudinal changes, claim revisions, and ecosystem movements."""
    args = {
        "hours": hours,
        "importance_min": importance_min,
        "project": project,
        "limit": limit,
    }
    return mcp_tools.tool_get_recent_changes(args)


@mcp.tool()
def get_source_health() -> Dict[str, Any]:
    """Retrieve health and checkpoint telemetry for all source adapters."""
    return mcp_tools.tool_get_source_health()


@mcp.tool()
def get_runtime_status() -> Dict[str, Any]:
    """Retrieve background daemon status, job execution schedules, and lifetime metrics."""
    return mcp_tools.tool_get_runtime_status()


def main():
    """Run HERMES MCP Server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
