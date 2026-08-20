import math
from datetime import datetime, timezone
from typing import List
from app.models.schemas import Event, StoryCluster, TechnologyAssessment


def assess_technology_maturity(
    cluster: StoryCluster,
    events: List[Event],
) -> TechnologyAssessment:
    """
    Evaluates technology maturity stage and multidimensional assessment scores
    based on deterministic signals across research, implementation, adoption,
    reproducibility, and community interest.
    """
    sources = {e.source for e in events}
    event_types = {e.event_type for e in events}

    # 1. Research Signal (papers, DOIs, citations)
    has_arxiv = "arxiv" in sources
    has_scholarly = any(e.source in ("openalex", "crossref") for e in events)
    max_citations = max([e.cited_by_count or e.metadata.get("cited_by_count", 0) for e in events] + [0])

    research_score = 0.0
    if has_arxiv:
        research_score += 0.50
    if has_scholarly:
        research_score += 0.30
    if max_citations > 0:
        research_score += min(0.20, math.log10(max_citations + 1) / 3.0 * 0.20)
    research_score = min(1.0, research_score)

    # 2. Implementation Signal (code repository, official releases)
    has_repo = "github" in sources or any(e.event_type == "repository" for e in events)
    releases = [e for e in events if e.source == "github" and e.event_type == "release"]
    release_count = len(releases)

    implementation_score = 0.0
    if has_repo:
        implementation_score += 0.45
    if release_count >= 1:
        implementation_score += 0.30
    if release_count >= 3:
        implementation_score += 0.25
    implementation_score = min(1.0, implementation_score)

    # 3. Adoption Signal (stars, downloads, citations)
    max_stars = max([e.metadata.get("stars", 0) for e in events] + [0])
    max_downloads = max([e.metadata.get("downloads", 0) for e in events] + [0])

    adoption_score = 0.0
    if max_stars > 0:
        adoption_score += min(0.60, math.log10(max_stars + 1) / 4.0 * 0.60)
    if max_downloads > 0:
        adoption_score += min(0.40, math.log10(max_downloads + 1) / 5.0 * 0.40)
    adoption_score = min(1.0, adoption_score)

    # 4. Reproducibility Signal (open source code, open datasets, explicit benchmark)
    reproducibility_score = 0.0
    if has_repo:
        reproducibility_score += 0.50
    if "huggingface" in sources:
        reproducibility_score += 0.25
    if has_arxiv or has_scholarly:
        reproducibility_score += 0.25
    reproducibility_score = min(1.0, reproducibility_score)

    # 5. Community Signal (HN discussion, Stack Exchange questions)
    has_hn = "hackernews" in sources
    has_se = "stackexchange" in sources

    community_score = 0.0
    if has_hn:
        community_score += 0.50
    if has_se:
        community_score += 0.50
    community_score = min(1.0, community_score)

    # Combined Assessment Score
    assessment_score = round(
        (
            implementation_score * 0.25
            + adoption_score * 0.25
            + research_score * 0.20
            + reproducibility_score * 0.15
            + community_score * 0.15
        ),
        4,
    )

    # Determine Maturity Stage conservatively
    if implementation_score >= 0.70 and adoption_score >= 0.60 and (release_count >= 2 or max_stars >= 5000):
        maturity_stage = "established"
    elif implementation_score >= 0.60 and release_count >= 1 and adoption_score >= 0.35:
        maturity_stage = "production_candidate"
    elif implementation_score >= 0.50 and release_count >= 1:
        maturity_stage = "early_adoption"
    elif has_repo and (release_count >= 1 or max_stars >= 100):
        maturity_stage = "experimental"
    elif has_repo and (has_arxiv or has_scholarly):
        maturity_stage = "prototype"
    elif has_repo:
        maturity_stage = "prototype"
    elif has_arxiv or has_scholarly:
        maturity_stage = "research"
    else:
        maturity_stage = "concept"

    return TechnologyAssessment(
        cluster_id=cluster.id,
        maturity_stage=maturity_stage,
        research_score=round(research_score, 4),
        implementation_score=round(implementation_score, 4),
        adoption_score=round(adoption_score, 4),
        reproducibility_score=round(reproducibility_score, 4),
        community_score=round(community_score, 4),
        assessment_score=assessment_score,
        updated_at=datetime.now(timezone.utc),
    )
