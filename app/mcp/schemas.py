from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=200, description="Search query or technology keyword")
    project: Optional[str] = Field(None, max_length=100, description="Optional project name/ID for context relevance boost")
    source: Optional[str] = Field(None, max_length=50, description="Optional source filter (e.g. github, arxiv, openalex)")
    days: Optional[int] = Field(None, ge=1, le=365, description="Filter events published within N days")
    limit: int = Field(10, ge=1, le=50, description="Max results (1-50, default 10)")
    verified_only: bool = Field(False, description="Filter for supported/verified items only")
    min_maturity: Optional[str] = Field(None, description="Minimum maturity stage (prototype, experimental, maturing, established, production_ready)")
    max_risk: Optional[str] = Field(None, description="Maximum risk level (low, medium, high, critical)")
    mode: str = Field("hybrid", description="Search mode: hybrid, lexical, or semantic")


class TopDevelopmentsInput(BaseModel):
    limit: int = Field(10, ge=1, le=50, description="Max results (1-50, default 10)")
    project: Optional[str] = Field(None, max_length=100, description="Filter by project relevance")
    section: Optional[str] = Field(None, max_length=50, description="Filter by inbox section")


class TodayInboxInput(BaseModel):
    unseen_only: bool = Field(False, description="Return only unseen inbox items")
    project: Optional[str] = Field(None, max_length=100, description="Filter by project relevance")
    section: Optional[str] = Field(None, max_length=50, description="Filter by section")
    limit: int = Field(20, ge=1, le=50, description="Max items (1-50, default 20)")
    date: Optional[str] = Field(None, max_length=10, description="Snapshot date in YYYY-MM-DD format (defaults to current runtime-local date)")


class MorningBriefInput(BaseModel):
    date: Optional[str] = Field(None, description="Briefing date in YYYY-MM-DD format (defaults to today)")


class StoryInput(BaseModel):
    cluster_id: str = Field(..., min_length=1, max_length=100, description="StoryCluster ID")


class ClaimInput(BaseModel):
    claim_id: str = Field(..., min_length=1, max_length=100, description="Claim ID")


class ProjectIntelligenceInput(BaseModel):
    project: str = Field(..., min_length=1, max_length=100, description="Project name or ID")
    limit: int = Field(10, ge=1, le=50, description="Max matches/recommendations (1-50)")


class SavedItemsInput(BaseModel):
    limit: int = Field(20, ge=1, le=50, description="Max items (1-50, default 20)")
    offset: int = Field(0, ge=0, description="Offset for pagination")
    tag: Optional[str] = Field(None, max_length=50, description="Filter by tag")


class SavedItemInput(BaseModel):
    saved_id: str = Field(..., min_length=1, max_length=100, description="Saved item ID, inbox_item_id, or cluster_id")


class StarItemInput(BaseModel):
    inbox_item_id: str = Field(..., min_length=1, max_length=100, description="Inbox item ID to star")


class AddSavedNoteInput(BaseModel):
    saved_id: str = Field(..., min_length=1, max_length=100, description="Saved item ID")
    note: str = Field(..., min_length=1, max_length=2000, description="Note text (max 2000 chars)")


class AddSavedTagInput(BaseModel):
    saved_id: str = Field(..., min_length=1, max_length=100, description="Saved item ID")
    tag: str = Field(..., min_length=1, max_length=50, description="Tag name (alphanumeric, max 50 chars)")


class RecentChangesInput(BaseModel):
    hours: int = Field(24, ge=1, le=720, description="Hours to look back (default 24)")
    importance_min: Optional[str] = Field(None, description="Minimum importance (low, medium, high, critical)")
    project: Optional[str] = Field(None, max_length=100, description="Filter by project relevance")
    limit: int = Field(20, ge=1, le=50, description="Max changes (1-50, default 20)")
