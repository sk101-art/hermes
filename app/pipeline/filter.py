import re
from typing import Dict, List, Tuple
from app.models.schemas import Event

# Explicit domain synonyms/aliases for robust matching
SYNONYM_MAP = {
    "ml": ["machine learning"],
    "machine learning": ["ml"],
    "llm": ["large language model", "large language models"],
    "large language model": ["llm"],
    "large language models": ["llm"],
    "llm inference": ["large language model inference"],
    "large language model inference": ["llm inference"],
    "ml systems": ["machine learning systems"],
    "machine learning systems": ["ml systems"],
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "retrieval augmented generation": ["rag"],
    "db": ["database", "databases"],
    "database": ["db"],
    "databases": ["db"],
    "gpu": ["graphics processing unit"],
}


def _expand_keywords(keywords: List[str]) -> List[str]:
    expanded = set()
    for kw in keywords:
        kw_clean = kw.lower().strip()
        expanded.add(kw_clean)
        if kw_clean in SYNONYM_MAP:
            for syn in SYNONYM_MAP[kw_clean]:
                expanded.add(syn.lower().strip())
    return list(expanded)


def _contains_keyword(text: str, keyword: str) -> bool:
    kw_clean = keyword.lower().strip()
    if not kw_clean:
        return False
    pattern = r"(?:\b|\b_)" + re.escape(kw_clean).replace(r"\ ", r"[\s\-_]+") + r"(?:\b|_)"
    return bool(re.search(pattern, text))


def evaluate_interests(
    event: Event, interests: Dict[str, list]
) -> Tuple[int, int, int]:
    searchable_text = f"{event.title} {event.text} {' '.join(event.topics)}".lower()

    high_kws = _expand_keywords(interests.get("high", []))
    med_kws = _expand_keywords(interests.get("medium", []))
    low_kws = _expand_keywords(interests.get("low", []))

    high_matches = sum(1 for kw in high_kws if _contains_keyword(searchable_text, kw))
    medium_matches = sum(1 for kw in med_kws if _contains_keyword(searchable_text, kw))
    low_matches = sum(1 for kw in low_kws if _contains_keyword(searchable_text, kw))

    return high_matches, medium_matches, low_matches


def filter_event(event: Event, interests: Dict[str, list]) -> bool:
    """Accept if matches high or medium interest."""
    high, medium, _ = evaluate_interests(event, interests)
    return (high > 0) or (medium > 0)
