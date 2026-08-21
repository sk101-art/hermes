from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class MaturityStage(str, Enum):
    CONCEPT = "concept"
    RESEARCH = "research"
    PROTOTYPE = "prototype"
    EXPERIMENTAL = "experimental"
    EARLY_ADOPTION = "early_adoption"
    PRODUCTION_CANDIDATE = "production_candidate"
    ESTABLISHED = "established"


class ClaimStatus(str, Enum):
    STRONGLY_SUPPORTED = "strongly_supported"
    SUPPORTED = "supported"
    WEAKLY_SUPPORTED = "weakly_supported"
    MIXED = "mixed"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class EvidenceStance(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class EvidenceClass(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    COMMUNITY = "community"
    METADATA = "metadata"


class AssertionLevel(str, Enum):
    ARTIFACT_FACT = "artifact_fact"
    PERFORMANCE_CLAIM = "performance_claim"
    RESEARCH_CLAIM = "research_claim"
    COMMUNITY_OBSERVATION = "community_observation"
    SELF_REPORTED_CLAIM = "self_reported_claim"


class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskStatus(str, Enum):
    NOT_ASSESSED = "not_assessed"
    INSUFFICIENT_DATA = "insufficient_data"
    ASSESSED = "assessed"


def normalize_maturity_stage(val: Any) -> Optional[str]:
    """Normalizes raw or legacy maturity stage strings or enum members to canonical MaturityStage values."""
    if not val:
        return None
    v = val.value if hasattr(val, "value") else str(val)
    v = v.strip().lower()
    mapping = {
        "maturing": MaturityStage.EARLY_ADOPTION.value,
        "production_ready": MaturityStage.ESTABLISHED.value,
        "stable": MaturityStage.ESTABLISHED.value,
    }
    if v in mapping:
        return mapping[v]
    valid_stages = {s.value for s in MaturityStage}
    if v in valid_stages:
        return v
    return None


def normalize_claim_status(val: Any) -> Optional[str]:
    """Normalizes raw claim status strings or enum members to canonical ClaimStatus values."""
    if not val:
        return None
    v = val.value if hasattr(val, "value") else str(val)
    v = v.strip().lower()
    valid_statuses = {s.value for s in ClaimStatus}
    if v in valid_statuses:
        return v
    return None


def normalize_evidence_stance(val: Any) -> Optional[str]:
    """Normalizes raw evidence stance strings or enum members to canonical EvidenceStance values."""
    if not val:
        return None
    v = val.value if hasattr(val, "value") else str(val)
    v = v.strip().lower()
    mapping = {
        "refutes": EvidenceStance.CONTRADICTS.value,
        "opposes": EvidenceStance.CONTRADICTS.value,
        "neutral": EvidenceStance.CONTEXT.value,
        "background": EvidenceStance.CONTEXT.value,
    }
    if v in mapping:
        return mapping[v]
    valid_stances = {s.value for s in EvidenceStance}
    if v in valid_stances:
        return v
    return None


def normalize_evidence_class(val: Any) -> Optional[str]:
    """Normalizes raw evidence class strings or enum members to canonical EvidenceClass values."""
    if not val:
        return None
    v = val.value if hasattr(val, "value") else str(val)
    v = v.strip().lower()
    mapping = {
        "author": EvidenceClass.PRIMARY.value,
        "discussion": EvidenceClass.COMMUNITY.value,
        "registry": EvidenceClass.METADATA.value,
        "benchmark": EvidenceClass.SECONDARY.value,
        "independent": EvidenceClass.PRIMARY.value,
    }
    if v in mapping:
        return mapping[v]
    valid_classes = {c.value for c in EvidenceClass}
    if v in valid_classes:
        return v
    return None


def normalize_assertion_level(val: Any) -> Optional[str]:
    """Normalizes raw assertion level strings or enum members to canonical AssertionLevel values."""
    if not val:
        return None
    v = val.value if hasattr(val, "value") else str(val)
    v = v.strip().lower()
    mapping = {
        "artifact": AssertionLevel.ARTIFACT_FACT.value,
        "performance": AssertionLevel.PERFORMANCE_CLAIM.value,
        "research": AssertionLevel.RESEARCH_CLAIM.value,
        "community": AssertionLevel.COMMUNITY_OBSERVATION.value,
        "self_reported": AssertionLevel.SELF_REPORTED_CLAIM.value,
    }
    if v in mapping:
        return mapping[v]
    valid_levels = {a.value for a in AssertionLevel}
    if v in valid_levels:
        return v
    return None


class SourceProfile(BaseModel):
    name: str
    source_type: str
    enabled: bool = True
    priority: float = 1.0
    trust_prior: float = 0.70
    supports_citations: bool = False
    supports_downloads: bool = False
    supports_authors: bool = True
    dedup_strategy: str = "canonical_id"
    rate_limit_rpm: Optional[int] = None
    auth_env_var: Optional[str] = None


class Event(BaseModel):
    id: str
    source: str = "generic"
    source_type: str = "generic"
    event_type: str = "update"
    title: str
    text: str = ""
    url: Optional[str] = None
    doi: Optional[str] = None
    cited_by_count: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    topics: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)

    relevance_score: float = 0.0
    trust_score: float = 0.5
    novelty_score: float = 0.5
    final_score: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def infer_defaults_from_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Infer source
            if ("source" not in data or not data.get("source") or data.get("source") == "generic") and "id" in data and ":" in data["id"]:
                data["source"] = data["id"].split(":")[0]

            src = data.get("source", "generic")
            if src == "github":
                if "source_type" not in data or data.get("source_type") == "generic":
                    data["source_type"] = "code_repository"
                if "event_type" not in data or data.get("event_type") == "update":
                    data["event_type"] = "repository"
            elif src == "arxiv":
                if "source_type" not in data or data.get("source_type") == "generic":
                    data["source_type"] = "research_paper"
                if "event_type" not in data or data.get("event_type") == "update":
                    data["event_type"] = "paper"
            elif src == "hackernews":
                if "source_type" not in data or data.get("source_type") == "generic":
                    data["source_type"] = "discussion"
                if "event_type" not in data or data.get("event_type") == "update":
                    data["event_type"] = "story"
        return data


class StoryCluster(BaseModel):
    id: str
    canonical_title: str
    event_ids: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    cluster_score: float = 0.0
    source_diversity_score: float = 0.0
    max_event_score: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Relationship(BaseModel):
    id: str
    source_event_id: str
    target_event_id: str
    relationship_type: str
    confidence: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Backward compatibility alias
EventRelationship = Relationship


class Claim(BaseModel):
    id: str
    cluster_id: str
    claim_type: str = "general"
    assertion_level: str = "artifact_fact"
    subject: str
    predicate: str
    object: str
    claim_text: str
    status: str = "unverified"
    confidence: float = 1.0
    verification_score: float = 0.0
    self_reported: bool = True
    is_current: bool = True
    superseded_by: Optional[str] = None
    last_verified_at: Optional[datetime] = None
    staleness_score: float = 0.0
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Evidence(BaseModel):
    id: str
    claim_id: str
    event_id: str
    source: str
    evidence_type: str = "unknown"
    evidence_class: str = "primary"
    stance: str = "supports"
    excerpt: str = ""
    url: Optional[str] = None
    quality_score: float = 0.50
    independence_score: float = 0.50
    reproducibility_score: float = 0.50
    is_current: bool = True
    superseded_by: Optional[str] = None
    observed_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TechnologyAssessment(BaseModel):
    cluster_id: str
    maturity_stage: str = "concept"
    research_score: float = 0.0
    implementation_score: float = 0.0
    adoption_score: float = 0.0
    reproducibility_score: float = 0.0
    community_score: float = 0.0
    assessment_score: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClaimRevision(BaseModel):
    id: str
    claim_id: str
    previous_status: Optional[str] = None
    new_status: str
    previous_verification_score: Optional[float] = None
    new_verification_score: Optional[float] = None
    reason: str
    trigger_event_id: Optional[str] = None
    trigger_evidence_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TechnologyAssessmentRevision(BaseModel):
    id: str
    cluster_id: str
    previous_stage: Optional[str] = None
    new_stage: str
    previous_score: Optional[float] = None
    new_score: float
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TechnologyState(BaseModel):
    cluster_id: str
    current_status: str = "active"
    latest_event_at: Optional[datetime] = None
    latest_release: Optional[str] = None
    latest_claim_revision_at: Optional[datetime] = None
    active_claim_count: int = 0
    supported_claim_count: int = 0
    contradicted_claim_count: int = 0
    superseded_claim_count: int = 0
    risk_score: float = 0.0
    trend: str = "stable"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecheckQueueItem(BaseModel):
    id: str
    entity_type: str = "claim"
    entity_id: str
    reason: str
    priority: float = 0.50
    not_before: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntelligenceChange(BaseModel):
    id: str
    entity_type: str = "claim"
    entity_id: str
    change_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    importance: float = 0.50
    reason: str
    origin: str = "live_update"  # live_update, source_refresh, backfill_initialization, migration, recompute, manual_rebuild, new_evidence, new_release, actual_revision
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Session 7: Reference / Context Folder Personalization Models ---


class Project(BaseModel):
    id: str
    name: str
    path: str
    description: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    libraries: List[str] = Field(default_factory=list)
    databases: List[str] = Field(default_factory=list)
    infrastructure: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    is_active: bool = True
    context_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_indexed_at: Optional[datetime] = None


class ProjectFile(BaseModel):
    id: str
    project_id: str
    relative_path: str
    file_type: str
    size_bytes: int
    content_hash: str
    extracted_text: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectTechnologyProfile(BaseModel):
    project_id: str
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    libraries: List[str] = Field(default_factory=list)
    dependencies: Dict[str, str] = Field(default_factory=dict)
    databases: List[str] = Field(default_factory=list)
    storage: List[str] = Field(default_factory=list)
    infrastructure: List[str] = Field(default_factory=list)
    ml_stack: List[str] = Field(default_factory=list)
    deployment: List[str] = Field(default_factory=list)
    observability: List[str] = Field(default_factory=list)
    testing: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    profile_text: str = ""
    profile_hash: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectMatch(BaseModel):
    id: str
    project_id: str
    entity_type: str = "cluster"  # cluster, claim, event
    entity_id: str
    match_type: str = "general_related"
    relevance_score: float = 0.0
    impact_score: float = 0.0
    recommendation: str = "watch"
    reason_codes: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Session 8: Daily Inbox, Stars, Saved Library, Retention, and Morning Briefing Models ---


class InboxItem(BaseModel):
    id: str
    entity_type: str = "cluster"  # cluster, claim, change
    entity_id: str
    story_cluster_id: str
    title: str
    section: str = "ai_ml"  # must_know, project_relevant, ai_ml, systems_compilers, storage_databases, developer_tooling, research, corrections_updates, watchlist
    inbox_score: float = 0.50
    rank_score: float = 0.50
    project_impact_score: float = 0.0
    state: str = "unseen"  # unseen, seen, opened, starred, expired, archived
    item_type: str = "new_story"  # new_story, story_update, claim_strengthened, claim_weakened, new_release, new_risk, maturity_change, correction
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    seen_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    is_starred: bool = False
    saved_item_id: Optional[str] = None
    matched_project_ids: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)


class SavedItem(BaseModel):
    id: str
    entity_type: str = "cluster"
    entity_id: str
    story_cluster_id: str
    inbox_item_id: Optional[str] = None
    title_snapshot: str
    saved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_snapshot: Optional[float] = None
    maturity_snapshot: Optional[str] = None
    risk_snapshot: Optional[float] = None
    user_note: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    project_ids: List[str] = Field(default_factory=list)
    is_active: bool = True
    link_status: str = "resolved"  # resolved, unresolved
    event_ids_snapshot: List[str] = Field(default_factory=list)


class UserFeedback(BaseModel):
    id: str
    entity_type: str = "inbox_item"  # inbox_item, cluster, claim
    entity_id: str
    action: str  # star, unstar, open, dismiss, useful, not_useful, note, tag
    value: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DailyBriefing(BaseModel):
    id: str
    briefing_date: str  # YYYY-MM-DD
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_items: int = 0
    high_priority_count: int = 0
    project_relevant_count: int = 0
    content_hash: str = ""
    summary_text: Optional[str] = None
    sections: Dict[str, List[str]] = Field(default_factory=dict)  # section_name -> list of inbox_item_ids
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DailyBriefingItem(BaseModel):
    briefing_id: str
    inbox_item_id: str
    position: int
    section: str


class SourceCheckpoint(BaseModel):
    source: str
    last_success_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    last_cursor: Optional[str] = None
    last_event_time: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    next_retry_at: Optional[datetime] = None
    health_status: str = "unknown"  # healthy, degraded, rate_limited, offline, disabled, unknown
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RuntimeJob(BaseModel):
    job_name: str
    last_started_at: Optional[datetime] = None
    last_completed_at: Optional[datetime] = None
    last_status: str = "pending"  # pending, running, completed, failed, interrupted, skipped
    last_error: Optional[str] = None
    duration_seconds: float = 0.0
    run_count: int = 0
    failure_count: int = 0
    next_run_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RuntimeJobRun(BaseModel):
    id: str
    job_name: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    status: str = "running"  # running, completed, failed, interrupted, skipped
    items_processed: int = 0
    error_summary: Optional[str] = None
    duration_seconds: float = 0.0


