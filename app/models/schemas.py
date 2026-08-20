from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Event(BaseModel):
    id: str
    source: str = "github"
    source_type: str = "code_repository"
    event_type: str = "repository"

    title: str
    text: str = ""
    url: str

    authors: List[str] = Field(default_factory=list)

    published_at: Optional[datetime] = None
    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    topics: List[str] = Field(default_factory=list)

    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)

    trust_score: float = 0.0
    relevance_score: float = 0.0
    novelty_score: float = 0.0
    final_score: float = 0.0
