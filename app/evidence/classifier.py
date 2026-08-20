from typing import Tuple
from app.models.schemas import Event

EVIDENCE_PRIORS = {
    "independent_reproduction": 0.95,
    "peer_reviewed_research": 0.90,
    "official_release": 0.88,
    "benchmark": 0.85,
    "source_code": 0.82,
    "official_documentation": 0.82,
    "preprint": 0.78,
    "issue_report": 0.68,
    "developer_experience": 0.62,
    "technical_blog": 0.58,
    "community_discussion": 0.45,
    "announcement": 0.40,
    "registry_metadata": 0.35,
    "unknown": 0.25,
}


def classify_evidence(event: Event) -> Tuple[str, str, float]:
    """
    Classifies an event into an evidence type, evidence class, and baseline quality score.
    Returns: (evidence_type, evidence_class, quality_score)
    """
    src = event.source.lower().strip()
    ev_type = event.event_type.lower().strip()
    src_type = event.source_type.lower().strip()

    if src == "github":
        if ev_type == "release":
            e_type = "official_release"
            e_class = "primary"
        elif ev_type in ("issue", "pull_request"):
            e_type = "issue_report"
            e_class = "secondary"
        else:
            e_type = "source_code"
            e_class = "primary"

    elif src == "arxiv":
        # Check if metadata indicates peer-reviewed publication venue
        venue = event.metadata.get("journal_ref") or event.metadata.get("venue")
        if venue and not ("arxiv" in str(venue).lower()):
            e_type = "peer_reviewed_research"
            e_class = "primary"
        else:
            e_type = "preprint"
            e_class = "primary"

    elif src in ("crossref", "openalex"):
        e_type = "registry_metadata"
        e_class = "metadata"

    elif src == "huggingface":
        e_type = "registry_metadata"
        e_class = "primary"

    elif src == "hackernews":
        e_type = "community_discussion"
        e_class = "community"

    elif src == "stackexchange":
        e_type = "developer_experience"
        e_class = "community"

    elif src == "rss":
        e_type = "technical_blog"
        e_class = "secondary"

    else:
        e_type = "unknown"
        e_class = "secondary"

    base_quality = EVIDENCE_PRIORS.get(e_type, 0.25)
    return e_type, e_class, base_quality
