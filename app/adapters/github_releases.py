import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event

DEFAULT_WATCH_REPOSITORIES = [
    "vllm-project/vllm",
    "ggerganov/llama.cpp",
    "sgl-project/sglang",
    "llvm/llvm-project",
    "triton-lang/triton",
    "pytorch/pytorch",
    "facebook/rocksdb",
]


class GitHubReleasesAdapter(SourceAdapter):
    """Adapter for fetching official releases from high-value watched GitHub repositories."""

    BASE_URL = "https://api.github.com/repos"

    def __init__(
        self,
        watch_repositories: Optional[List[str]] = None,
        timeout: int = 10,
    ):
        self.watch_repositories = watch_repositories or DEFAULT_WATCH_REPOSITORIES
        self.timeout = timeout

    @property
    def source_name(self) -> str:
        return "github_releases"

    def fetch(self, limit: int = 30) -> List[Dict[str, Any]]:
        raw_items: List[Dict[str, Any]] = []
        token = os.environ.get("GITHUB_TOKEN")

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "hermes-intelligence",
        }
        if token:
            headers["Authorization"] = f"Bearer {token.strip()}"

        per_repo_limit = max(2, limit // len(self.watch_repositories)) if self.watch_repositories else 3

        for repo in self.watch_repositories:
            if len(raw_items) >= limit:
                break
            try:
                url = f"{self.BASE_URL}/{repo}/releases?per_page={per_repo_limit}"
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    releases = resp.json()
                    for rel in releases:
                        if not rel.get("draft", False):
                            rel["__repository"] = repo
                            raw_items.append(rel)
                elif resp.status_code == 403 or resp.status_code == 429:
                    print(f"[Warning] GitHub API rate limit reached on releases for {repo}.", flush=True)
                    break
            except Exception as e:
                print(f"[Warning] GitHub releases fetch error for {repo}: {e}", flush=True)

        return raw_items[:limit]

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        repo = raw_item.get("__repository") or raw_item.get("repository", {}).get("full_name") or "unknown/repo"
        tag_name = raw_item.get("tag_name") or "v0.0"
        rel_id = raw_item.get("id") or f"{repo}:{tag_name}"

        event_id = f"github:release:{rel_id}"

        name = raw_item.get("name") or tag_name
        title = f"Release {tag_name} for {repo}: {name}" if name != tag_name else f"Release {tag_name} for {repo}"

        body = raw_item.get("body") or ""
        short_body = body[:500] if len(body) > 500 else body
        text = f"{title}. {short_body}"

        url = raw_item.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag_name}"

        author_login = raw_item.get("author", {}).get("login")
        authors = [author_login] if author_login else [repo.split("/")[0]]

        pub_str = raw_item.get("published_at")
        pub_dt = None
        if pub_str:
            try:
                clean_iso = pub_str.replace("Z", "+00:00")
                pub_dt = datetime.fromisoformat(clean_iso)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

        prerelease = raw_item.get("prerelease", False)

        topics = ["release", "github", repo.split("/")[-1]]

        metadata = {
            "repository": repo,
            "tag_name": tag_name,
            "prerelease": prerelease,
            "release_id": raw_item.get("id"),
        }

        return Event(
            id=event_id,
            source="github",
            source_type="code_repository",
            event_type="release",
            title=title,
            text=text,
            url=url,
            authors=authors,
            published_at=pub_dt,
            topics=topics,
            metadata=metadata,
            raw_payload=raw_item,
        )
