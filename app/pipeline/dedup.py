from typing import Optional, Set
from app.models.schemas import Event


def is_duplicate_event(
    event: Event,
    seen_ids: Set[str],
    seen_urls: Optional[Set[str]] = None,
) -> bool:
    """Deterministic duplicate check by Event.id and normalized URL."""
    if event.id in seen_ids:
        return True

    if seen_urls is not None and event.url and event.url in seen_urls:
        return True

    return False
