from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.models.schemas import (
    MaturityStage,
    ClaimStatus,
    EvidenceStance,
    EvidenceClass,
    AssertionLevel,
    RiskLevel,
    RiskStatus,
    normalize_maturity_stage,
    normalize_claim_status,
    normalize_evidence_stance,
    normalize_evidence_class,
    normalize_assertion_level,
)


class SearchResult(BaseModel):
    entity_type: str = "story_cluster"
    entity_id: str
    title: str
    summary: Optional[str] = None
    score: float
    sources: List[str] = Field(default_factory=list)
    published_at: Optional[str] = None
    verification_score: Optional[float] = None
    maturity: Optional[str] = None
    risk: Optional[str] = None
    risk_status: Optional[str] = None
    project_relevance: float = 0.0
    reason_codes: List[str] = Field(default_factory=list)
    urls: List[str] = Field(default_factory=list)
    explain: Optional[Dict[str, float]] = None


class StoryDetail(BaseModel):
    cluster_id: str
    canonical_title: str
    cluster_score: float
    sources: List[str] = Field(default_factory=list)
    events_count: int = 0
    events: List[Dict[str, Any]] = Field(default_factory=list)
    claims: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_summary: Dict[str, int] = Field(default_factory=dict)
    verification: Dict[str, Any] = Field(default_factory=dict)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    project_matches: List[Dict[str, Any]] = Field(default_factory=list)
    is_saved: bool = False


class ClaimDetail(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str
    assertion_level: str
    status: str
    verification_score: float
    staleness_score: float = 0.0
    is_self_reported: bool = False
    cluster_id: str
    evidence_count: int = 0
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    revisions: List[Dict[str, Any]] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    project_id: str
    name: str
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    libraries: List[str] = Field(default_factory=list)
    databases: List[str] = Field(default_factory=list)
    infrastructure: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    last_indexed_at: Optional[str] = None


class ProjectIntelligence(BaseModel):
    project_id: str
    name: str
    technology_profile: Dict[str, Any] = Field(default_factory=dict)
    top_matches: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    recent_changes: List[Dict[str, Any]] = Field(default_factory=list)
