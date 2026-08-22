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
    is_synthesized: bool = False
    claim_status: Optional[str] = None
    score: Optional[float] = None
    sources: List[str] = Field(default_factory=list)
    published_at: Optional[str] = None
    verification_score: Optional[float] = None
    maturity: Optional[str] = None
    risk: Optional[str] = None
    risk_status: Optional[str] = None
    project_relevance: Optional[float] = None
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
    new_verification_score: Optional[float] = None
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
    risk_status: Optional[str] = None
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
    claim_status: Optional[str] = None
    maturity_stage: Optional[str] = None
    risk_level: Optional[str] = None
    risk_status: Optional[str] = None
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


class SaveItemRequest(BaseModel):
    story_cluster_id: str
    inbox_item_id: Optional[str] = None
    user_note: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self) -> "SaveItemRequest":
        if not self.story_cluster_id or not self.story_cluster_id.strip():
            raise ValueError("story_cluster_id must be provided and non-empty")
        if self.user_note and len(self.user_note) > 2000:
            raise ValueError("user_note cannot exceed 2000 characters")
        if self.tags:
            for t in self.tags:
                if len(t) > 50:
                    raise ValueError("Each tag cannot exceed 50 characters")
        return self


class ProjectSummary(BaseModel):
    project_id: str
    name: str
    description: Optional[str] = None
    is_active: bool = True
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    libraries: List[str] = Field(default_factory=list)
    databases: List[str] = Field(default_factory=list)
    infrastructure: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    last_indexed_at: Optional[str] = None
    matches_count: int = 0


class ProjectIntelligence(BaseModel):
    project_id: str
    name: str
    description: Optional[str] = None
    is_active: bool = True
    last_indexed_at: Optional[str] = None
    technology_profile: Dict[str, Any] = Field(default_factory=dict)
    top_matches: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    recent_changes: List[Dict[str, Any]] = Field(default_factory=list)
    intelligence_available: bool


class BriefingItemDetail(BaseModel):
    briefing_id: str
    inbox_item_id: str
    story_cluster_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    section: str
    position: int
    item_type: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)
    inbox_score: Optional[float] = None
    rank_score: Optional[float] = None
    project_impact_score: Optional[float] = None
    matched_project_ids: List[str] = Field(default_factory=list)
    snapshot_status: str = "complete"  # "complete" vs "legacy_incomplete"
    snapshot_version: Optional[str] = None
    story_available: bool = False

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class DailyBriefingResponse(BaseModel):
    id: str
    briefing_date: str
    generated_at: str
    total_items: int = 0
    high_priority_count: int = 0
    project_relevant_count: int = 0
    content_hash: str = ""
    summary_text: Optional[str] = None
    sections: Dict[str, List[BriefingItemDetail]] = Field(default_factory=dict)
    ordered_sections: List[str] = Field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


# --- Phase 13: Runtime Reliability, Source Health & Operational Schemas ---

class RuntimeDaemonInfo(BaseModel):
    status: str  # running, stopped, stale, disagreement
    pid: Optional[int] = None
    heartbeat_timestamp: Optional[str] = None
    heartbeat_age_seconds: Optional[int] = None
    is_stale: bool = False
    lock_present: bool = False
    disagreement_notice: Optional[str] = None


class RuntimeSystemDiagnostics(BaseModel):
    database: str
    network: str
    disk_free_mb: Optional[int] = None
    disk_status: str
    embedding_model: str
    reference_folder: str
    observed_at: str
    cache_age_seconds: Optional[float] = None
    is_cached: bool = False


class SourceOperationalRecord(BaseModel):
    source: str
    enabled: bool = True
    health_status: str  # unknown, healthy, retrying, rate_limited, degraded, disabled, unavailable
    last_attempt_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_event_time: Optional[str] = None
    consecutive_failures: Optional[int] = None
    failure_threshold_reached: bool = False
    max_consecutive_failures: int = 5
    next_retry_at: Optional[str] = None
    backoff_seconds: Optional[int] = None
    is_due: bool = False
    due_reason: str
    interval_minutes: int
    error_category: Optional[str] = None
    sanitized_error: Optional[str] = None


class JobOperationalRecord(BaseModel):
    job_name: str
    status: str  # pending, running, completed, failed, partial, interrupted, blocked, skipped, not_due, not_applicable
    last_status: str = "pending"  # latest execution outcome: pending, running, completed, failed, partial, interrupted
    evaluation_status: str = "pending"  # latest scheduler evaluation: pending, due, not_due, blocked, not_applicable
    evaluated_at: Optional[str] = None
    last_started_at: Optional[str] = None
    last_completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    run_count: Optional[int] = None
    failure_count: Optional[int] = None
    is_due: bool = False
    next_schedule: str
    configured_timeout_minutes: Optional[int] = None
    timeout_enforced: bool = False
    blocked_by: Optional[str] = None
    blocked_reason: Optional[str] = None
    error_category: Optional[str] = None
    sanitized_error: Optional[str] = None


class RecentJobFailureRecord(BaseModel):
    run_id: str
    job_name: str
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str  # failed, partial, interrupted
    error_category: Optional[str] = None
    sanitized_error: Optional[str] = None


class CurrentSourceIssueRecord(BaseModel):
    source: str
    health_status: str
    consecutive_failures: int
    last_attempt_at: Optional[str] = None
    next_retry_at: Optional[str] = None
    error_category: Optional[str] = None
    sanitized_error: Optional[str] = None


class BriefingFreshnessInfo(BaseModel):
    date: str
    generated: bool
    total_items: Optional[int] = None
    generated_at: Optional[str] = None


class IntelligenceFreshnessRecord(BaseModel):
    last_successful_ingestion: Optional[str] = None
    today_briefing: BriefingFreshnessInfo


class SourceSummaryCounts(BaseModel):
    total: int = 0
    healthy: int = 0
    retrying: int = 0
    rate_limited: int = 0
    degraded: int = 0
    disabled: int = 0
    unknown: int = 0
    unavailable: int = 0


class JobSummaryCounts(BaseModel):
    total: int = 0
    completed: int = 0
    running: int = 0
    failed: int = 0
    partial: int = 0
    interrupted: int = 0
    blocked: int = 0
    not_due: int = 0
    not_applicable: int = 0
    pending: int = 0


class RuntimeOverviewResponse(BaseModel):
    schema_version: str = "v1"
    status: str  # HEALTHY, DEGRADED, UNHEALTHY
    observed_at: str
    effective_timezone: str
    scheduler_time: str
    timezone_warning: Optional[str] = None
    daemon: RuntimeDaemonInfo
    system: RuntimeSystemDiagnostics
    sources: List[SourceOperationalRecord] = Field(default_factory=list)
    source_summary: SourceSummaryCounts
    jobs: List[JobOperationalRecord] = Field(default_factory=list)
    job_summary: JobSummaryCounts
    recent_failures: List[RecentJobFailureRecord] = Field(default_factory=list)
    current_source_issues: List[CurrentSourceIssueRecord] = Field(default_factory=list)
    intelligence_freshness: IntelligenceFreshnessRecord
    lifetime_metrics: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    is_partial_availability: bool = False
