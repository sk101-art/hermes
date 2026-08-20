import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event
from app.pipeline.normalize import (
    clean_text,
    normalize_topics,
    normalize_url,
    parse_iso_datetime,
)


class ArxivAdapter(SourceAdapter):
    """Adapter for fetching and normalizing research papers from the public arXiv API."""

    BASE_URL = "http://export.arxiv.org/api/query"
    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    def __init__(self, queries: Optional[List[str]] = None):
        self.queries = queries or [
            "large language models",
            "inference optimization",
            "CUDA",
            "compiler optimization",
            "LLVM",
            "machine learning systems",
            "distributed systems",
            "retrieval augmented generation",
            "AI agents",
            "vector databases",
        ]

    @property
    def source_name(self) -> str:
        return "arXiv"

    def fetch(self, limit: int = 50) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_ids = set()

        if not self.queries:
            return results

        session = requests.Session()
        per_query_limit = max(5, limit // len(self.queries))

        for query in self.queries:
            if len(results) >= limit:
                break

            params = {
                "search_query": f'all:"{query}"',
                "start": 0,
                "max_results": min(per_query_limit, 15),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            try:
                response = session.get(self.BASE_URL, params=params, timeout=10)
                if response.status_code != 200:
                    continue

                root = ET.fromstring(response.content)
                entries = root.findall("atom:entry", self.ATOM_NS)

                for entry in entries:
                    raw_id = entry.findtext("atom:id", default="", namespaces=self.ATOM_NS).strip()
                    arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id

                    if not arxiv_id or arxiv_id in seen_ids:
                        continue

                    seen_ids.add(arxiv_id)

                    title = entry.findtext("atom:title", default="", namespaces=self.ATOM_NS)
                    summary = entry.findtext("atom:summary", default="", namespaces=self.ATOM_NS)
                    published = entry.findtext("atom:published", default="", namespaces=self.ATOM_NS)
                    updated = entry.findtext("atom:updated", default="", namespaces=self.ATOM_NS)

                    authors = [
                        author.findtext("atom:name", default="", namespaces=self.ATOM_NS).strip()
                        for author in entry.findall("atom:author", self.ATOM_NS)
                    ]

                    categories = [
                        cat.attrib.get("term", "").strip()
                        for cat in entry.findall("atom:category", self.ATOM_NS)
                        if cat.attrib.get("term")
                    ]

                    primary_cat = entry.find("arxiv:primary_category", self.ATOM_NS)
                    primary_category = primary_cat.attrib.get("term", "") if primary_cat is not None else ""

                    link_elem = entry.find("atom:link[@rel='alternate']", self.ATOM_NS)
                    url = link_elem.attrib.get("href", f"https://arxiv.org/abs/{arxiv_id}") if link_elem is not None else f"https://arxiv.org/abs/{arxiv_id}"

                    raw_item = {
                        "arxiv_id": arxiv_id,
                        "title": title,
                        "summary": summary,
                        "url": url,
                        "authors": authors,
                        "published": published,
                        "updated": updated,
                        "primary_category": primary_category,
                        "categories": categories,
                    }
                    results.append(raw_item)
                    if len(results) >= limit:
                        break

            except requests.exceptions.Timeout:
                print(f"[Warning] arXiv API request timed out for query '{query}'.", flush=True)
            except requests.exceptions.ConnectionError:
                print("[Warning] arXiv connection error. Continuing with other sources.", flush=True)
                break
            except ET.ParseError:
                print(f"[Warning] Failed to parse arXiv XML response for query '{query}'.", flush=True)
            except Exception as e:
                print(f"[Warning] Unexpected error querying arXiv: {e}", flush=True)

        return results

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        arxiv_id = raw_item.get("arxiv_id", "")
        event_id = f"arxiv:{arxiv_id}"

        title = clean_text(raw_item.get("title", ""))
        abstract = clean_text(raw_item.get("summary", ""))
        url = normalize_url(raw_item.get("url", f"https://arxiv.org/abs/{arxiv_id}"))

        authors = [clean_text(a) for a in raw_item.get("authors", []) if clean_text(a)]
        categories = raw_item.get("categories", [])
        topics = normalize_topics(categories)

        published_at = parse_iso_datetime(raw_item.get("published"))

        metadata = {
            "arxiv_id": arxiv_id,
            "primary_category": raw_item.get("primary_category", ""),
            "categories": categories,
            "published_at": raw_item.get("published"),
            "updated_at": raw_item.get("updated"),
        }

        return Event(
            id=event_id,
            source="arxiv",
            source_type="research_paper",
            event_type="paper",
            title=title,
            text=abstract,
            url=url,
            authors=authors,
            published_at=published_at,
            discovered_at=datetime.now(timezone.utc),
            topics=topics,
            metadata=metadata,
            raw_payload=raw_item,
        )
