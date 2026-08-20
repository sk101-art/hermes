import re
from datetime import datetime, timezone
from typing import List, Optional


def normalize_whitespace(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = normalize_whitespace(text)
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", cleaned)


def normalize_url(url: Optional[str]) -> str:
    if not url:
        return ""
    return url.strip().rstrip("/")


def normalize_topics(topics: Optional[List[str]]) -> List[str]:
    if not topics:
        return []
    cleaned = []
    for topic in topics:
        if isinstance(topic, str):
            t = topic.strip().lower()
            if t and t not in cleaned:
                cleaned.append(t)
    return cleaned


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None
