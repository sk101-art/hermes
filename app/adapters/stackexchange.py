import html
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event

DEFAULT_SE_SITES = ["stackoverflow", "dba"]
DEFAULT_SE_TAGS = [
    "llm",
    "cuda",
    "compiler-optimization",
    "vector-database",
    "rag",
    "machine-learning",
]


def clean_html(text: str) -> str:
    """Unescape entities and strip markup tags."""
    if not text:
        return ""
    clean = html.unescape(text)
    clean = re.sub(r"<[^>]+>", "", clean)
    return re.sub(r"\s+", " ", clean).strip()


class StackExchangeAdapter(SourceAdapter):
    """Adapter for fetching developer community questions from the Stack Exchange API."""

    BASE_URL = "https://api.stackexchange.com/2.3/questions"

    def __init__(
        self,
        sites: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        timeout: int = 10,
    ):
        self.sites = sites or DEFAULT_SE_SITES
        self.tags = tags or DEFAULT_SE_TAGS
        self.timeout = timeout

    @property
    def source_name(self) -> str:
        return "stackexchange"

    def fetch(self, limit: int = 40) -> List[Dict[str, Any]]:
        raw_items: List[Dict[str, Any]] = []
        seen_ids = set()

        per_site_limit = max(5, limit // len(self.sites)) if self.sites else 10
        tagged_filter = ";".join(self.tags[:4]) if self.tags else "llm;cuda"

        headers = {
            "User-Agent": "hermes-intelligence",
            "Accept-Encoding": "gzip",
        }

        for site in self.sites:
            if len(raw_items) >= limit:
                break
            try:
                url = (
                    f"{self.BASE_URL}?order=desc&sort=activity&site={site}"
                    f"&tagged={urllib.parse.quote(tagged_filter)}&pagesize={per_site_limit}&filter=default"
                )
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("items", []):
                        qid = item.get("question_id")
                        full_key = f"{site}:{qid}"
                        if qid and full_key not in seen_ids:
                            seen_ids.add(full_key)
                            item["__site"] = site
                            raw_items.append(item)
                elif resp.status_code == 429 or (resp.status_code == 200 and resp.json().get("backoff")):
                    print(f"[Warning] Stack Exchange rate limit / backoff received on {site}.", flush=True)
                    break
            except Exception as e:
                print(f"[Warning] Stack Exchange query error on site {site}: {e}", flush=True)

        return raw_items[:limit]

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        site = raw_item.get("__site", "stackoverflow")
        qid = raw_item.get("question_id", "0")
        event_id = f"stackexchange:{site}:{qid}"

        raw_title = raw_item.get("title", "Untitled Question")
        title = clean_html(raw_title)

        tags = raw_item.get("tags", [])
        score = raw_item.get("score", 0)
        answer_count = raw_item.get("answer_count", 0)
        is_answered = raw_item.get("is_answered", False)
        view_count = raw_item.get("view_count", 0)

        owner = raw_item.get("owner", {})
        author = owner.get("display_name")
        authors = [author] if author else []

        creation_date = raw_item.get("creation_date")
        pub_dt = datetime.fromtimestamp(creation_date, tz=timezone.utc) if creation_date else datetime.now(timezone.utc)

        url = raw_item.get("link") or f"https://{site}.com/questions/{qid}"
        text = f"{title}. Tags: {', '.join(tags)}. Score: {score}, Answers: {answer_count}."

        metadata = {
            "question_id": qid,
            "site": site,
            "score": score,
            "answer_count": answer_count,
            "is_answered": is_answered,
            "view_count": view_count,
            "tags": tags,
        }

        return Event(
            id=event_id,
            source="stackexchange",
            source_type="developer_community",
            event_type="question",
            title=title,
            text=text,
            url=url,
            authors=authors,
            published_at=pub_dt,
            topics=tags,
            metadata=metadata,
            raw_payload=raw_item,
        )
