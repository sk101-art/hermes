import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from app.adapters.base import SourceAdapter
from app.models.schemas import Event

DEFAULT_HF_QUERIES = [
    "inference",
    "quantization",
    "rag",
    "agent",
    "embeddings",
    "compiler optimization",
    "vllm",
    "gguf",
]


class HuggingFaceAdapter(SourceAdapter):
    """Adapter for fetching public model and dataset metadata from Hugging Face Hub."""

    BASE_URL = "https://huggingface.co/api"

    def __init__(
        self,
        queries: Optional[List[str]] = None,
        fetch_models: bool = True,
        fetch_datasets: bool = True,
        timeout: int = 10,
    ):
        self.queries = queries or DEFAULT_HF_QUERIES
        self.fetch_models = fetch_models
        self.fetch_datasets = fetch_datasets
        self.timeout = timeout

    @property
    def source_name(self) -> str:
        return "huggingface"

    def fetch(self, limit: int = 50) -> List[Dict[str, Any]]:
        raw_items: List[Dict[str, Any]] = []
        seen_ids = set()

        items_per_query = max(3, limit // (len(self.queries) * 2)) if self.queries else 5

        # 1. Fetch Models
        if self.fetch_models:
            for q in self.queries:
                if len(raw_items) >= limit:
                    break
                try:
                    url = f"{self.BASE_URL}/models?search={urllib.parse.quote_plus(q)}&limit={items_per_query}&sort=lastModified&direction=-1"
                    resp = requests.get(url, timeout=self.timeout, headers={"User-Agent": "hermes-intelligence"})
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data:
                            mid = item.get("id") or item.get("_id")
                            if mid and mid not in seen_ids:
                                seen_ids.add(mid)
                                item["__hf_type"] = "model"
                                item["__search_query"] = q
                                raw_items.append(item)
                    elif resp.status_code == 429:
                        print("[Warning] Hugging Face rate limit reached. Continuing with collected items.", flush=True)
                        break
                except Exception as e:
                    print(f"[Warning] Hugging Face model query error for '{q}': {e}", flush=True)

        # 2. Fetch Datasets
        if self.fetch_datasets and len(raw_items) < limit:
            remaining = limit - len(raw_items)
            ds_per_query = max(2, remaining // len(self.queries)) if self.queries else 3
            for q in self.queries:
                if len(raw_items) >= limit:
                    break
                try:
                    url = f"{self.BASE_URL}/datasets?search={urllib.parse.quote_plus(q)}&limit={ds_per_query}&sort=lastModified&direction=-1"
                    resp = requests.get(url, timeout=self.timeout, headers={"User-Agent": "hermes-intelligence"})
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data:
                            did = item.get("id") or item.get("_id")
                            if did and did not in seen_ids:
                                seen_ids.add(did)
                                item["__hf_type"] = "dataset"
                                item["__search_query"] = q
                                raw_items.append(item)
                    elif resp.status_code == 429:
                        break
                except Exception as e:
                    print(f"[Warning] Hugging Face dataset query error for '{q}': {e}", flush=True)

        return raw_items[:limit]

    def normalize(self, raw_item: Dict[str, Any]) -> Event:
        hf_type = raw_item.get("__hf_type", "model")
        repo_id = raw_item.get("id") or raw_item.get("_id") or "unknown"

        author = raw_item.get("author")
        if not author and "/" in repo_id:
            author = repo_id.split("/")[0]

        authors = [author] if author else []
        tags = raw_item.get("tags") or []
        pipeline_tag = raw_item.get("pipeline_tag")
        downloads = raw_item.get("downloads", 0)
        likes = raw_item.get("likes", 0)
        last_modified = raw_item.get("lastModified")

        pub_dt = None
        if last_modified:
            try:
                # Handle ISO format like 2026-08-20T10:00:00.000Z
                clean_iso = last_modified.replace("Z", "+00:00")
                pub_dt = datetime.fromisoformat(clean_iso)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

        topics = list(tags)
        if pipeline_tag and pipeline_tag not in topics:
            topics.append(pipeline_tag)
        if raw_item.get("__search_query"):
            topics.append(raw_item["__search_query"])

        if hf_type == "dataset":
            event_id = f"huggingface:dataset:{repo_id.lower()}"
            url = f"https://huggingface.co/datasets/{repo_id}"
            title = f"Hugging Face Dataset: {repo_id}"
            text = f"Dataset {repo_id} by {author or 'community'}. Tags: {', '.join(tags[:6])}."
            source_type = "dataset_registry"
            event_type = "dataset"
        else:
            event_id = f"huggingface:model:{repo_id.lower()}"
            url = f"https://huggingface.co/{repo_id}"
            pipeline_str = f" for {pipeline_tag}" if pipeline_tag else ""
            title = f"Hugging Face Model: {repo_id}{pipeline_str}"
            text = f"Model {repo_id} by {author or 'community'}. Pipeline: {pipeline_tag or 'N/A'}. Tags: {', '.join(tags[:6])}."
            source_type = "model_registry"
            event_type = "model"

        metadata = {
            "repo_id": repo_id,
            "author": author,
            "downloads": downloads,
            "likes": likes,
            "tags": tags,
            "pipeline_tag": pipeline_tag,
            "hf_type": hf_type,
        }

        return Event(
            id=event_id,
            source="huggingface",
            source_type=source_type,
            event_type=event_type,
            title=title,
            text=text,
            url=url,
            authors=authors,
            published_at=pub_dt,
            topics=topics,
            metadata=metadata,
            raw_payload=raw_item,
        )
