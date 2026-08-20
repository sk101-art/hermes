import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event
from app.semantic.similarity import normalize_doi

DEFAULT_OPENALEX_QUERIES = [
    "LLM inference",
    "compiler optimization",
    "retrieval augmented generation",
    "vector database",
    "machine learning systems",
    "AI agents",
]


class OpenAlexAdapter(SourceAdapter):
    """Adapter for fetching scholarly works metadata from the free OpenAlex API."""

    BASE_URL = "https://api.openalex.org/works"

    def __init__(
        self,
        queries: Optional[List[str]] = None,
        email: str = "hermes-research@local.dev",
        timeout: int = 10,
    ):
        self.queries = queries or DEFAULT_OPENALEX_QUERIES
        self.email = email
        self.timeout = timeout

    @property
    def source_name(self) -> str:
        return "openalex"

    def fetch(self, limit: int = 50) -> List[Dict[str, Any]]:
        raw_items: List[Dict[str, Any]] = []
        seen_ids = set()

        items_per_query = max(3, limit // len(self.queries)) if self.queries else 5

        headers = {
            "User-Agent": f"hermes-intelligence (mailto:{self.email})",
        }

        for q in self.queries:
            if len(raw_items) >= limit:
                break
            try:
                url = (
                    f"{self.BASE_URL}?search={urllib.parse.quote_plus(q)}"
                    f"&per-page={items_per_query}&sort=publication_date:desc"
                )
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    for item in results:
                        wid = item.get("id")
                        if wid and wid not in seen_ids:
                            seen_ids.add(wid)
                            item["__search_query"] = q
                            raw_items.append(item)
                elif resp.status_code == 429:
                    print("[Warning] OpenAlex rate limit reached. Continuing with collected items.", flush=True)
                    break
            except Exception as e:
                print(f"[Warning] OpenAlex query error for '{q}': {e}", flush=True)

        return raw_items[:limit]

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        work_id = raw_item.get("id", "").split("/")[-1].lower() or "unknown"
        event_id = f"openalex:{work_id}"

        title = raw_item.get("display_name") or raw_item.get("title") or "Untitled Scholarly Work"
        doi = normalize_doi(raw_item.get("doi"))

        authors = []
        for authorship in raw_item.get("authorships", []):
            author_obj = authorship.get("author", {})
            name = author_obj.get("display_name")
            if name:
                authors.append(name)

        pub_date_str = raw_item.get("publication_date")
        pub_dt = None
        if pub_date_str:
            try:
                pub_dt = datetime.strptime(pub_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

        concepts = [c.get("display_name") for c in raw_item.get("concepts", []) if c.get("display_name")]
        topics = list(concepts[:8])
        if raw_item.get("__search_query"):
            topics.append(raw_item["__search_query"])

        cited_by = raw_item.get("cited_by_count", 0)
        primary_location = raw_item.get("primary_location") or {}
        source_info = primary_location.get("source") or {}
        venue = source_info.get("display_name")
        landing_url = primary_location.get("landing_page_url") or raw_item.get("doi") or f"https://openalex.org/{work_id.upper()}"

        open_access = raw_item.get("open_access", {})

        abstract_inverted = raw_item.get("abstract_inverted_index")
        abstract_text = ""
        if abstract_inverted and isinstance(abstract_inverted, dict):
            # Reconstruct abstract from inverted index
            word_positions = []
            for word, positions in abstract_inverted.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort(key=lambda x: x[0])
            abstract_text = " ".join([w[1] for w in word_positions[:150]])

        text = f"{title}. Venue: {venue or 'Unknown'}. Citations: {cited_by}. {abstract_text}"

        metadata = {
            "openalex_id": work_id,
            "doi": doi,
            "venue": venue,
            "cited_by_count": cited_by,
            "is_oa": open_access.get("is_oa", False),
            "oa_status": open_access.get("oa_status"),
            "concepts": concepts,
        }

        return Event(
            id=event_id,
            source="openalex",
            source_type="scholarly_index",
            event_type="scholarly_work",
            title=title,
            text=text,
            url=landing_url,
            doi=doi,
            cited_by_count=cited_by,
            authors=authors[:10],
            published_at=pub_dt,
            topics=topics,
            metadata=metadata,
            raw_payload=raw_item,
        )
