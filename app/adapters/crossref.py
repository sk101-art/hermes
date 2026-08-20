import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event
from app.semantic.similarity import normalize_doi

DEFAULT_CROSSREF_QUERIES = [
    "LLM inference optimization",
    "compiler optimization LLVM",
    "vector database ANN search",
    "retrieval augmented generation",
]


class CrossrefAdapter(SourceAdapter):
    """Adapter for fetching official scholarly DOI records from the Crossref REST API."""

    BASE_URL = "https://api.crossref.org/works"

    def __init__(
        self,
        queries: Optional[List[str]] = None,
        email: str = "hermes-research@local.dev",
        timeout: int = 10,
    ):
        self.queries = queries or DEFAULT_CROSSREF_QUERIES
        self.email = email
        self.timeout = timeout

    @property
    def source_name(self) -> str:
        return "crossref"

    def fetch(self, limit: int = 30) -> List[Dict[str, Any]]:
        raw_items: List[Dict[str, Any]] = []
        seen_dois = set()

        items_per_query = max(3, limit // len(self.queries)) if self.queries else 5

        headers = {
            "User-Agent": f"hermes-intelligence (mailto:{self.email})",
        }

        for q in self.queries:
            if len(raw_items) >= limit:
                break
            try:
                url = (
                    f"{self.BASE_URL}?query={urllib.parse.quote_plus(q)}"
                    f"&rows={items_per_query}&sort=published&order=desc"
                )
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("message", {}).get("items", [])
                    for item in items:
                        raw_doi = item.get("DOI")
                        norm_doi = normalize_doi(raw_doi)
                        if norm_doi and norm_doi not in seen_dois:
                            seen_dois.add(norm_doi)
                            item["__search_query"] = q
                            raw_items.append(item)
                elif resp.status_code == 429:
                    print("[Warning] Crossref rate limit reached. Continuing with collected items.", flush=True)
                    break
            except Exception as e:
                print(f"[Warning] Crossref query error for '{q}': {e}", flush=True)

        return raw_items[:limit]

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        raw_doi = raw_item.get("DOI", "")
        norm_doi = normalize_doi(raw_doi) or raw_doi.lower().strip()
        event_id = f"crossref:{norm_doi}"

        titles = raw_item.get("title", [])
        title = titles[0] if titles else "Untitled Crossref Record"

        authors = []
        for author in raw_item.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        # Parse publication date
        published = raw_item.get("published-print") or raw_item.get("published-online") or raw_item.get("issued") or {}
        date_parts = published.get("date-parts", [[]])[0]
        pub_dt = None
        if date_parts:
            try:
                year = date_parts[0]
                month = date_parts[1] if len(date_parts) > 1 else 1
                day = date_parts[2] if len(date_parts) > 2 else 1
                pub_dt = datetime(year, month, day, tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

        container_titles = raw_item.get("container-title", [])
        venue = container_titles[0] if container_titles else None
        publisher = raw_item.get("publisher")
        ref_count = raw_item.get("references-count", 0)

        topics = []
        for sub in raw_item.get("subject", []):
            topics.append(sub)
        if raw_item.get("__search_query"):
            topics.append(raw_item["__search_query"])

        url = f"https://doi.org/{norm_doi}"
        text = f"{title}. Publisher: {publisher or 'Unknown'}. Venue: {venue or 'Unknown'}. References: {ref_count}."

        metadata = {
            "doi": norm_doi,
            "publisher": publisher,
            "venue": venue,
            "references_count": ref_count,
            "type": raw_item.get("type"),
        }

        return Event(
            id=event_id,
            source="crossref",
            source_type="doi_registry",
            event_type="scholarly_work",
            title=title,
            text=text,
            url=url,
            doi=norm_doi,
            authors=authors[:10],
            published_at=pub_dt,
            topics=topics,
            metadata=metadata,
            raw_payload=raw_item,
        )
