from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

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


class GroundingRef(BaseModel):
    entity_type: str  # 'event', 'claim', 'evidence', 'assessment', 'project_match', 'change'
    entity_id: str
    label: Optional[str] = None


class StatementWithProvenance(BaseModel):
    statement: str
    grounding_references: List[GroundingRef] = Field(default_factory=list)


class KeyClaimRef(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str
    status: Optional[str] = None
    verification_score: Optional[float] = None
    is_self_reported: bool = False


class StorySynthesis(BaseModel):
    what_happened: Optional[StatementWithProvenance] = None
    why_it_matters: Optional[StatementWithProvenance] = None
    evidence_position: Optional[StatementWithProvenance] = None
    key_claims: List[KeyClaimRef] = Field(default_factory=list)
    project_implications: Optional[StatementWithProvenance] = None
    change_summary: Optional[StatementWithProvenance] = None
    is_synthesized: bool = False
    fallback_excerpt: Optional[str] = None


class EventSummary(BaseModel):
    event_id: str
    source: str
    title: str
    url: Optional[str] = None
    published_at: Optional[str] = None
    discovered_at: Optional[str] = None
    final_score: float = 0.0
    # Backward compatibility alias
    id: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @model_validator(mode="before")
    @classmethod
    def populate_compat(cls, data: Any) -> Any:
        if isinstance(data, dict):
            eid = data.get("event_id") or data.get("id")
            data["event_id"] = eid
            if "id" not in data or data["id"] is None:
                data["id"] = eid
        return data


class ClaimSummary(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str
    assertion_level: str
    status: str
    verification_score: Optional[float] = None
    is_self_reported: bool = False
    evidence_count: int = 0
    # Backward compatibility aliases
    id: Optional[str] = None
    text: Optional[str] = None
    type: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @model_validator(mode="before")
    @classmethod
    def populate_compat(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cid = data.get("claim_id") or data.get("id")
            ctext = data.get("claim_text") or data.get("text")
            ctype = data.get("claim_type") or data.get("type")
            data["claim_id"] = cid
            data["claim_text"] = ctext
            data["claim_type"] = ctype
            if "id" not in data or data["id"] is None:
                data["id"] = cid
            if "text" not in data or data["text"] is None:
                data["text"] = ctext
            if "type" not in data or data["type"] is None:
                data["type"] = ctype
        return data


class RiskDetail(BaseModel):
    level: Optional[str] = None
    score: Optional[float] = None
    status: RiskStatus = RiskStatus.NOT_ASSESSED
    reason_codes: List[str] = Field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> RiskStatus:
        if isinstance(v, RiskStatus):
            return v
        if isinstance(v, str):
            v_clean = v.strip().lower()
            for s in RiskStatus:
                if s.value == v_clean or s.name.lower() == v_clean:
                    return s
        return RiskStatus.NOT_ASSESSED


class ProjectMatchSummary(BaseModel):
    project_id: str
    project_name: str
    relevance_score: float
    match_type: str
    recommendation: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class RelationshipSummary(BaseModel):
    source_event_id: str
    target_event_id: str
    type: str
    confidence: float = 1.0

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class VerificationDetail(BaseModel):
    verification_score: Optional[float] = None
    claim_status: Optional[str] = None
    claims_count: int = 0
    evidence_count: int = 0
    contradiction_detected: bool = False
    contradictions_count: int = 0
    # Additional context fields for backward compatibility
    maturity_stage: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[float] = None
    risk_status: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class StoryDetail(BaseModel):
    cluster_id: str
    canonical_title: str
    cluster_score: float
    sources: List[str] = Field(default_factory=list)
    events_count: int = 0
    events: List[EventSummary] = Field(default_factory=list)
    claims: List[ClaimSummary] = Field(default_factory=list)
    technology_maturity: Optional[str] = None
    risk: Optional[RiskDetail] = None
    evidence_summary: Dict[str, int] = Field(default_factory=dict)
    verification: VerificationDetail = Field(default_factory=VerificationDetail)
    relationships: List[RelationshipSummary] = Field(default_factory=list)
    project_matches: List[ProjectMatchSummary] = Field(default_factory=list)
    is_saved: bool = False
    synthesis: Optional[StorySynthesis] = None


class EvidenceDetail(BaseModel):
    evidence_id: str
    claim_id: str
    event_id: Optional[str] = None
    source: str
    evidence_type: str
    evidence_class: str
    stance: str
    quality_score: float
    independence_score: float
    reproducibility_score: float
    is_independent: bool
    url: Optional[str] = None
    excerpt: Optional[str] = None
    observed_at: Optional[str] = None
    created_at: Optional[str] = None
    # Backward compat aliases
    id: Optional[str] = None
    type: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @model_validator(mode="before")
    @classmethod
    def populate_compat(cls, data: Any) -> Any:
        if isinstance(data, dict):
            eid = data.get("evidence_id") or data.get("id")
            etype = data.get("evidence_type") or data.get("type")
            data["evidence_id"] = eid
            data["evidence_type"] = etype
            if "id" not in data or data["id"] is None:
                data["id"] = eid
            if "type" not in data or data["type"] is None:
                data["type"] = etype
        return data


class ClaimRevisionDetail(BaseModel):
    revision_id: str
    claim_id: str
    previous_status: Optional[str] = None
    new_status: str
    previous_verification_score: Optional[float] = None
    new_verification_score: float
    reason: str
    trigger_event_id: Optional[str] = None
    trigger_evidence_id: Optional[str] = None
    revised_at: str
    # Backward compatibility aliases
    id: Optional[str] = None
    old_status: Optional[str] = None
    old_verification_score: Optional[float] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @model_validator(mode="before")
    @classmethod
    def populate_compat(cls, data: Any) -> Any:
        if isinstance(data, dict):
            rid = data.get("revision_id") or data.get("id")
            data["revision_id"] = rid
            if "id" not in data or data["id"] is None:
                data["id"] = rid
            if "old_status" in data and "previous_status" not in data:
                data["previous_status"] = data["old_status"]
            if "previous_status" in data and ("old_status" not in data or data["old_status"] is None):
                data["old_status"] = data["previous_status"]
            if "old_verification_score" in data and "previous_verification_score" not in data:
                data["previous_verification_score"] = data["old_verification_score"]
            if "previous_verification_score" in data and ("old_verification_score" not in data or data["old_verification_score"] is None):
                data["old_verification_score"] = data["previous_verification_score"]
        return data

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class ClaimDetail(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str
    assertion_level: str
    status: str
    verification_score: Optional[float] = None
    staleness_score: float = 0.0
    is_self_reported: bool = False
    cluster_id: str
    evidence_count: int = 0
    evidence: List[EvidenceDetail] = Field(default_factory=list)
    revisions: List[ClaimRevisionDetail] = Field(default_factory=list)
    # Backward compat aliases
    id: Optional[str] = None
    text: Optional[str] = None
    type: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @model_validator(mode="before")
    @classmethod
    def populate_compat(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cid = data.get("claim_id") or data.get("id")
            ctext = data.get("claim_text") or data.get("text")
            ctype = data.get("claim_type") or data.get("type")
            data["claim_id"] = cid
            data["claim_text"] = ctext
            data["claim_type"] = ctype
            if "id" not in data or data["id"] is None:
                data["id"] = cid
            if "text" not in data or data["text"] is None:
                data["text"] = ctext
            if "type" not in data or data["type"] is None:
                data["type"] = ctype
        return data


class CurrentIntelligenceState(BaseModel):
    title: str
    cluster_score: float
    verification_score: Optional[float] = None
    maturity_stage: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[float] = None
    risk_status: str = "not_assessed"
    claim_status: Optional[str] = None
    claims_count: int = 0
    events_count: int = 0
    is_active: bool = True

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class SavedItemDetail(BaseModel):
    id: str
    inbox_item_id: Optional[str] = None
    story_cluster_id: Optional[str] = None
    title: str
    verification_score: Optional[float] = None
    maturity_stage: Optional[str] = None
    risk_score: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    user_note: Optional[str] = None
    project_ids: List[str] = Field(default_factory=list)
    saved_at: str
    current_state: Optional[CurrentIntelligenceState] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


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
