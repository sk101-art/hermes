import os
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.adapters.base import SourceAdapter
from app.models.schemas import Event
from app.pipeline.normalize import (
    clean_text,
    normalize_topics,
    normalize_url,
    parse_iso_datetime,
)


class GitHubAdapter(SourceAdapter):
    """Adapter for fetching and normalizing public GitHub repositories."""

    BASE_URL = "https://api.github.com/search/repositories"

    def __init__(
        self,
        token: Optional[str] = None,
        queries: Optional[List[str]] = None,
    ):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.queries = queries or [
            "LLM inference",
            "CUDA inference",
            "LLVM optimization",
            "compiler optimization",
            "machine learning systems",
            "vector database",
            "distributed systems",
            "RAG",
            "AI agent",
        ]

    @property
    def source_name(self) -> str:
        return "GitHub"

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "hermes-tech-intel/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def fetch(self, limit: int = 100) -> List[Dict[str, Any]]:
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
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": min(per_query_limit, 20),
            }

            try:
                response = session.get(
                    self.BASE_URL,
                    headers=self._get_headers(),
                    params=params,
                    timeout=10,
                )

                if response.status_code == 403:
                    print(
                        f"[Warning] GitHub API rate limit reached for query '{query}'.",
                        flush=True,
                    )
                    break
                elif response.status_code != 200:
                    continue

                data = response.json()
                items = data.get("items", [])
                for item in items:
                    repo_id = item.get("id")
                    if repo_id and repo_id not in seen_ids:
                        seen_ids.add(repo_id)
                        results.append(item)
                        if len(results) >= limit:
                            break

            except requests.exceptions.Timeout:
                print(f"[Warning] GitHub API request timed out for query '{query}'.", flush=True)
            except requests.exceptions.ConnectionError:
                print("[Warning] Failed to connect to GitHub API. Continuing with other sources.", flush=True)
                break
            except Exception as e:
                print(f"[Warning] Unexpected error querying GitHub: {e}", flush=True)

        return results

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        repo_id = raw_item.get("id", "")
        event_id = f"github:{repo_id}"

        full_name = clean_text(raw_item.get("full_name", ""))
        description = clean_text(raw_item.get("description", ""))
        language = clean_text(raw_item.get("language", ""))
        topics = normalize_topics(raw_item.get("topics", []))
        html_url = normalize_url(raw_item.get("html_url", ""))

        owner = raw_item.get("owner", {})
        owner_login = owner.get("login") if isinstance(owner, dict) else None
        authors = [owner_login] if owner_login else []

        title = f"{full_name} - {description}" if description else full_name

        text_parts = [description]
        if language:
            text_parts.append(f"Language: {language}")
        if topics:
            text_parts.append(f"Topics: {', '.join(topics)}")
        combined_text = " | ".join(filter(None, text_parts))

        published_at = parse_iso_datetime(
            raw_item.get("pushed_at") or raw_item.get("updated_at") or raw_item.get("created_at")
        )

        metadata = {
            "stars": raw_item.get("stargazers_count", 0),
            "forks": raw_item.get("forks_count", 0),
            "open_issues": raw_item.get("open_issues_count", 0),
            "language": language,
            "updated_at": raw_item.get("updated_at"),
            "created_at": raw_item.get("created_at"),
            "topics": topics,
        }

        return Event(
            id=event_id,
            source="github",
            source_type="code_repository",
            event_type="repository",
            title=title,
            text=combined_text,
            url=html_url,
            authors=authors,
            published_at=published_at,
            discovered_at=datetime.now(timezone.utc),
            topics=topics,
            metadata=metadata,
            raw_payload=raw_item,
        )
