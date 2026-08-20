import email.utils
import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event

DEFAULT_RSS_FEEDS = [
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "AI/ML"},
    {"name": "PyTorch Blog", "url": "https://pytorch.org/blog/feed.xml", "category": "ML Systems"},
    {"name": "Simon Willison Weblog", "url": "https://simonwillison.net/atom/entries/", "category": "AI Engineering"},
    {"name": "Berkeley AI Research", "url": "https://bair.berkeley.edu/blog/feed.xml", "category": "AI Research"},
]


def strip_html_tags(text: str) -> str:
    """Strip HTML markup from feed descriptions."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = html.unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()


def parse_feed_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse RFC 822 or ISO 8601 dates from RSS/Atom."""
    if not date_str:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        clean_iso = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_iso).astimezone(timezone.utc)
    except Exception:
        return None


class RssAdapter(SourceAdapter):
    """Adapter for fetching technical publications and blog posts from RSS/Atom feeds."""

    def __init__(
        self,
        feeds: Optional[List[Dict[str, str]]] = None,
        timeout: int = 10,
    ):
        self.feeds = feeds or DEFAULT_RSS_FEEDS
        self.timeout = timeout

    @property
    def source_name(self) -> str:
        return "rss"

    def fetch(self, limit: int = 30) -> List[Dict[str, Any]]:
        raw_items: List[Dict[str, Any]] = []
        headers = {"User-Agent": "hermes-intelligence"}

        per_feed_limit = max(3, limit // len(self.feeds)) if self.feeds else 5

        for feed in self.feeds:
            feed_name = feed.get("name", "Unknown Feed")
            feed_url = feed.get("url", "")
            if not feed_url:
                continue

            try:
                resp = requests.get(feed_url, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    items = self._parse_feed_xml(resp.content, feed_name, feed_url)
                    raw_items.extend(items[:per_feed_limit])
            except Exception as e:
                print(f"[Warning] RSS feed fetch error for {feed_name}: {e}", flush=True)

            if len(raw_items) >= limit:
                break

        return raw_items[:limit]

    def _parse_feed_xml(self, content: bytes, feed_name: str, feed_url: str) -> List[Dict[str, Any]]:
        items = []
        try:
            root = ET.fromstring(content)
        except Exception:
            return items

        # Handle RSS 2.0 (<channel><item>)
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                desc_elem = item.find("description")
                guid_elem = item.find("guid")
                pub_date_elem = item.find("pubDate")
                creator_elem = item.find("{http://purl.org/dc/elements/1.1/}creator")

                title = title_elem.text if title_elem is not None else "Untitled"
                link = link_elem.text if link_elem is not None else ""
                desc = desc_elem.text if desc_elem is not None else ""
                guid = guid_elem.text if guid_elem is not None else link
                pub_date = pub_date_elem.text if pub_date_elem is not None else None
                author = creator_elem.text if creator_elem is not None else None

                items.append({
                    "feed_name": feed_name,
                    "feed_url": feed_url,
                    "title": title,
                    "link": link,
                    "description": desc,
                    "guid": guid,
                    "pub_date": pub_date,
                    "author": author,
                    "format": "rss",
                })
            return items

        # Handle Atom 1.0 (<feed><entry>)
        # Handle namespaces
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns) or root.findall("entry")
        for entry in entries:
            title_elem = entry.find("atom:title", ns) or entry.find("title")
            link_elem = entry.find("atom:link", ns) or entry.find("link")
            summary_elem = entry.find("atom:summary", ns) or entry.find("atom:content", ns) or entry.find("summary") or entry.find("content")
            id_elem = entry.find("atom:id", ns) or entry.find("id")
            updated_elem = entry.find("atom:updated", ns) or entry.find("atom:published", ns) or entry.find("updated") or entry.find("published")
            author_elem = entry.find("atom:author/atom:name", ns) or entry.find("author/name")

            title = title_elem.text if title_elem is not None else "Untitled"
            link = link_elem.get("href") if link_elem is not None else ""
            summary = summary_elem.text if summary_elem is not None else ""
            guid = id_elem.text if id_elem is not None else link
            updated = updated_elem.text if updated_elem is not None else None
            author = author_elem.text if author_elem is not None else None

            items.append({
                "feed_name": feed_name,
                "feed_url": feed_url,
                "title": title,
                "link": link,
                "description": summary,
                "guid": guid,
                "pub_date": updated,
                "author": author,
                "format": "atom",
            })

        return items

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        feed_name = raw_item.get("feed_name", "RSS")
        feed_slug = re.sub(r"[^a-zA-Z0-9]+", "_", feed_name.lower()).strip("_")

        guid = raw_item.get("guid") or raw_item.get("link") or raw_item.get("title") or "item"
        guid_hash = hashlib.md5(guid.encode("utf-8")).hexdigest()[:12]
        event_id = f"rss:{feed_slug}:{guid_hash}"

        title = raw_item.get("title", "Untitled Article")
        clean_desc = strip_html_tags(raw_item.get("description", ""))
        short_desc = clean_desc[:400] if len(clean_desc) > 400 else clean_desc
        text = f"{title}. {short_desc}"

        url = raw_item.get("link") or raw_item.get("guid") or ""
        author = raw_item.get("author")
        authors = [author] if author else [feed_name]

        pub_dt = parse_feed_date(raw_item.get("pub_date")) or datetime.now(timezone.utc)

        topics = ["technical_article", feed_slug]

        metadata = {
            "feed_name": feed_name,
            "feed_url": raw_item.get("feed_url"),
            "guid": guid,
            "format": raw_item.get("format"),
        }

        return Event(
            id=event_id,
            source="rss",
            source_type="technical_publication",
            event_type="article",
            title=title,
            text=text,
            url=url,
            authors=authors,
            published_at=pub_dt,
            topics=topics,
            metadata=metadata,
            raw_payload=raw_item,
        )
