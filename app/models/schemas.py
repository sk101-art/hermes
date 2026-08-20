from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


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
    subject: str
    predicate: str
    object: str
    claim_text: str
    status: str = "unverified"
    confidence: float = 1.0
    verification_score: float = 0.0
    self_reported: bool = True
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
