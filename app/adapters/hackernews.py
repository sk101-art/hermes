from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event
from app.pipeline.normalize import clean_text, normalize_topics, normalize_url


class HackerNewsAdapter(SourceAdapter):
    """Adapter for fetching and normalizing stories from the official Hacker News Firebase API."""

    TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
    NEW_STORIES_URL = "https://hacker-news.firebaseio.com/v0/newstories.json"
    ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

    def __init__(self, mode: str = "top"):
        self.mode = mode

    @property
    def source_name(self) -> str:
        return "Hacker News"

    def _fetch_single_item(self, session: requests.Session, item_id: int) -> Optional[Dict[str, Any]]:
        try:
            resp = session.get(self.ITEM_URL.format(item_id=item_id), timeout=5)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data or not isinstance(data, dict):
                return None
            if data.get("deleted") or data.get("dead") or data.get("type") != "story":
                return None
            return data
        except Exception:
            return None

    def fetch(self, limit: int = 50) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        target_url = self.TOP_STORIES_URL if self.mode == "top" else self.NEW_STORIES_URL

        session = requests.Session()
        try:
            resp = session.get(target_url, timeout=10)
            if resp.status_code != 200:
                return results
            story_ids: List[int] = resp.json() or []
        except requests.exceptions.Timeout:
            print("[Warning] Hacker News API request timed out fetching story IDs.", flush=True)
            return results
        except requests.exceptions.ConnectionError:
            print("[Warning] Hacker News connection error. Continuing with other sources.", flush=True)
            return results
        except Exception as e:
            print(f"[Warning] Failed to fetch story list from Hacker News: {e}", flush=True)
            return results

        candidate_ids = story_ids[: min(limit * 2, 70)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(self._fetch_single_item, session, item_id) for item_id in candidate_ids]
            for future in as_completed(futures):
                item_data = future.result()
                if item_data:
                    results.append(item_data)
                    if len(results) >= limit:
                        break

        return results

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        hn_id = raw_item.get("id", "")
        event_id = f"hackernews:{hn_id}"

        title = clean_text(raw_item.get("title", ""))
        text = clean_text(raw_item.get("text", ""))

        external_url = raw_item.get("url")
        canonical_hn_url = f"https://news.ycombinator.com/item?id={hn_id}"
        url = normalize_url(external_url) if external_url else canonical_hn_url

        by_author = raw_item.get("by")
        authors = [clean_text(by_author)] if by_author else []

        unix_time = raw_item.get("time")
        published_at = (
            datetime.fromtimestamp(unix_time, tz=timezone.utc)
            if unix_time
            else None
        )

        score = raw_item.get("score", 0)
        descendants = raw_item.get("descendants", 0)

        metadata = {
            "hn_id": hn_id,
            "score": score,
            "descendants": descendants,
            "type": raw_item.get("type", "story"),
            "external_url": external_url,
        }

        return Event(
            id=event_id,
            source="hackernews",
            source_type="discussion",
            event_type="story",
            title=title,
            text=text,
            url=url,
            authors=authors,
            published_at=published_at,
            discovered_at=datetime.now(timezone.utc),
            topics=[],
            metadata=metadata,
            raw_payload=raw_item,
        )
