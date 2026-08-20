import sys
import yaml
from pathlib import Path

# Ensure safe UTF-8 console output
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.storage.db import Database


def load_yaml_config(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def check_adapter_available(source_key: str) -> bool:
    try:
        if source_key == "github":
            from app.adapters.github import GitHubAdapter
            return True
        elif source_key == "github_releases":
            from app.adapters.github_releases import GitHubReleasesAdapter
            return True
        elif source_key == "arxiv":
            from app.adapters.arxiv import ArxivAdapter
            return True
        elif source_key == "hackernews":
            from app.adapters.hackernews import HackerNewsAdapter
            return True
        elif source_key == "huggingface":
            from app.adapters.huggingface import HuggingFaceAdapter
            return True
        elif source_key == "openalex":
            from app.adapters.openalex import OpenAlexAdapter
            return True
        elif source_key == "crossref":
            from app.adapters.crossref import CrossrefAdapter
            return True
        elif source_key == "stackexchange":
            from app.adapters.stackexchange import StackExchangeAdapter
            return True
        elif source_key == "rss":
            from app.adapters.rss import RssAdapter
            return True
        return False
    except Exception:
        return False


def run_status():
    sources_cfg = load_yaml_config("config/sources.yaml").get("sources", {})
    db = Database(db_path="data/tech_intel.db")

    counts_by_source = db.get_event_counts_by_source()
    total_events = sum(counts_by_source.values())

    print("=" * 68)
    print("HERMES — SOURCE STATUS & INGESTION MATRIX")
    print("=" * 68)
    print(f"{'Source':<18} {'Enabled':<10} {'Adapter':<12} {'Stored Events':<15} {'Status':<10}")
    print("-" * 68)

    for source_key, cfg in sources_cfg.items():
        enabled = cfg.get("enabled", True)
        adapter_ok = check_adapter_available(source_key)

        stored_count = counts_by_source.get(source_key, 0)
        # Note: github_releases might be stored as github with event_type='release'
        if source_key == "github_releases":
            stored_count = 0
            for ev in db.get_all_events():
                if ev.source == "github" and ev.event_type == "release":
                    stored_count += 1

        status_str = "READY" if (enabled and adapter_ok) else ("DISABLED" if not enabled else "ERROR")
        adapter_str = "AVAILABLE" if adapter_ok else "MISSING"
        enabled_str = "YES" if enabled else "NO"

        print(f"{source_key:<18} {enabled_str:<10} {adapter_str:<12} {stored_count:>13}   {status_str:<10}")

    print("-" * 68)
    print(f"Total Stored Events across all sources: {total_events}")
    print("=" * 68)

    db.close()


if __name__ == "__main__":
    run_status()
