import math
from datetime import datetime, timezone
from typing import Dict
from app.models.schemas import Event
from app.pipeline.filter import evaluate_interests

WEIGHTS = {
    "relevance": 0.45,
    "novelty": 0.25,
    "trust": 0.20,
    "popularity": 0.10,
}


def calculate_relevance(event: Event, interests: Dict[str, list]) -> float:
    high, medium, low = evaluate_interests(event, interests)
    raw_score = (high * 0.40) + (medium * 0.20) - (low * 0.10)
    return max(0.0, min(1.0, raw_score))


def calculate_trust(event: Event) -> float:
    src = event.source.lower()
    if src == "crossref":
        return 0.95
    elif src in ("arxiv", "openalex"):
        return 0.90
    elif src == "github":
        if event.event_type == "release":
            return 0.85
        base_trust = 0.75
        stars = event.metadata.get("stars", 0)
        if stars > 5000:
            base_trust += 0.15
        elif stars > 500:
            base_trust += 0.10
        return min(1.0, base_trust)
    elif src == "huggingface":
        return 0.70
    elif src == "rss":
        return 0.70
    elif src in ("hackernews", "stackexchange"):
        return 0.65
    return 0.50


def calculate_novelty(event: Event) -> float:
    now = datetime.now(timezone.utc)
    pub_at = event.published_at

    if not pub_at:
        return 0.50

    if pub_at.tzinfo is None:
        pub_at = pub_at.replace(tzinfo=timezone.utc)

    days_old = max(0, (now - pub_at).total_seconds() / 86400.0)

    if days_old <= 7:
        return 1.0
    elif days_old <= 30:
        return 0.80
    elif days_old <= 90:
        return 0.50
    else:
        return max(0.10, 1.0 - (days_old / 365.0))


def calculate_popularity(event: Event) -> float:
    src = event.source.lower()
    if src == "github":
        stars = event.metadata.get("stars", 0)
        if stars <= 0:
            return 0.0
        return min(1.0, math.log10(stars + 1) / 4.0)
    elif src == "hackernews":
        score = event.metadata.get("score", 0)
        if score <= 0:
            return 0.0
        return min(1.0, math.log10(score + 1) / 3.0)
    elif src == "huggingface":
        downloads = event.metadata.get("downloads", 0)
        likes = event.metadata.get("likes", 0)
        dl_score = math.log10(downloads + 1) / 5.0 if downloads > 0 else 0.0
        like_score = math.log10(likes + 1) / 3.0 if likes > 0 else 0.0
        return min(1.0, (dl_score * 0.7) + (like_score * 0.3))
    elif src == "openalex":
        citations = event.cited_by_count or event.metadata.get("cited_by_count", 0)
        if citations <= 0:
            return 0.0
        return min(1.0, math.log10(citations + 1) / 3.0)
    elif src == "crossref":
        refs = event.metadata.get("references_count", 0)
        if refs <= 0:
            return 0.0
        return min(1.0, math.log10(refs + 1) / 3.0)
    elif src == "stackexchange":
        score = event.metadata.get("score", 0)
        answers = event.metadata.get("answer_count", 0)
        sc_score = math.log10(max(0, score) + 1) / 3.0
        ans_score = math.log10(max(0, answers) + 1) / 2.0
        return min(1.0, (sc_score * 0.6) + (ans_score * 0.4))
    return 0.0


def score_event(event: Event, interests: Dict[str, list]) -> Event:
    """Calculate all scores and assign them to the event."""
    event.relevance_score = calculate_relevance(event, interests)
    event.trust_score = calculate_trust(event)
    event.novelty_score = calculate_novelty(event)
    pop_score = calculate_popularity(event)

    final = (
        event.relevance_score * WEIGHTS["relevance"]
        + event.novelty_score * WEIGHTS["novelty"]
        + event.trust_score * WEIGHTS["trust"]
        + pop_score * WEIGHTS["popularity"]
    )
    event.final_score = round(max(0.0, min(1.0, final)), 4)
    return event
