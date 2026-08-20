import os
import sys
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Ensure safe UTF-8 terminal printing on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.adapters.arxiv import ArxivAdapter
from app.adapters.github import GitHubAdapter
from app.adapters.hackernews import HackerNewsAdapter
from app.pipeline.dedup import is_duplicate_event
from app.pipeline.filter import filter_event
from app.pipeline.rank import score_event
from app.storage.db import Database


def load_yaml_config(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run():
    load_dotenv()

    # Load configuration
    sources_cfg = load_yaml_config("config/sources.yaml").get("sources", {})
    interests_cfg = load_yaml_config("config/interests.yaml").get("interests", {})

    # Initialize Database
    db = Database(db_path="data/tech_intel.db")

    # Build active adapters
    adapters = []

    gh_cfg = sources_cfg.get("github", {})
    if gh_cfg.get("enabled", True):
        adapters.append((
            "GitHub",
            GitHubAdapter(queries=gh_cfg.get("queries")),
            gh_cfg.get("max_results", 100),
        ))

    arxiv_cfg = sources_cfg.get("arxiv", {})
    if arxiv_cfg.get("enabled", True):
        adapters.append((
            "arXiv",
            ArxivAdapter(queries=arxiv_cfg.get("queries")),
            arxiv_cfg.get("max_results", 50),
        ))

    hn_cfg = sources_cfg.get("hackernews", {})
    if hn_cfg.get("enabled", True):
        adapters.append((
            "Hacker News",
            HackerNewsAdapter(),
            hn_cfg.get("max_results", 50),
        ))

    source_stats = {}
    total_fetched = 0
    total_normalized = 0
    total_duplicates = 0
    total_rejected = 0
    total_accepted = 0

    seen_ids = set()
    seen_urls = set()

    for source_name, adapter, max_results in adapters:
        print(f"Fetching from {source_name}...", flush=True)
        try:
            raw_items = adapter.fetch(limit=max_results)
        except Exception as e:
            print(f"[Warning] {source_name} unavailable ({e}). Continuing with remaining sources.", flush=True)
            raw_items = []

        fetched = len(raw_items)
        normalized = 0
        duplicates = 0
        rejected = 0
        accepted = 0

        for item in raw_items:
            try:
                event = adapter.normalize(item)
                normalized += 1
                total_normalized += 1
            except Exception:
                continue

            if is_duplicate_event(event, seen_ids, seen_urls) or db.event_exists(event.id):
                duplicates += 1
                total_duplicates += 1
                continue

            seen_ids.add(event.id)
            if event.url:
                seen_urls.add(event.url)

            if not filter_event(event, interests_cfg):
                rejected += 1
                total_rejected += 1
                continue

            scored_event = score_event(event, interests_cfg)
            if db.insert_event(scored_event):
                accepted += 1
                total_accepted += 1

        total_fetched += fetched
        source_stats[source_name] = {
            "fetched": fetched,
            "normalized": normalized,
            "duplicates": duplicates,
            "rejected": rejected,
            "accepted": accepted,
        }

    # Print Session 2 summary
    print("\n" + "=" * 60, flush=True)
    print("HERMES — TECHNOLOGY INTELLIGENCE", flush=True)
    print("=" * 60, flush=True)
    print("\nSOURCE SUMMARY\n", flush=True)
    for source_name, stats in source_stats.items():
        print(f"{source_name}", flush=True)
        print(f"  Fetched:       {stats['fetched']:>5}", flush=True)
        print(f"  Normalized:    {stats['normalized']:>5}", flush=True)
        print(f"  Duplicates:    {stats['duplicates']:>5}", flush=True)
        print(f"  Rejected:      {stats['rejected']:>5}", flush=True)
        print(f"  Accepted:      {stats['accepted']:>5}\n", flush=True)

    print("-" * 60 + "\n", flush=True)
    print("TOTAL\n", flush=True)
    print(f"  Fetched:       {total_fetched:>5}", flush=True)
    print(f"  Normalized:    {total_normalized:>5}", flush=True)
    print(f"  Duplicates:    {total_duplicates:>5}", flush=True)
    print(f"  Rejected:      {total_rejected:>5}", flush=True)
    print(f"  Accepted:      {total_accepted:>5}", flush=True)
    print("\n" + "=" * 60, flush=True)
    print("TOP DEVELOPMENTS", flush=True)
    print("=" * 60 + "\n", flush=True)

    # Print top developments
    top_events = db.get_top_events(limit=20)
    if not top_events:
        print("No developments found matching the specified interest criteria.", flush=True)
    else:
        for idx, ev in enumerate(top_events, 1):
            print(f"{idx:02d} [{ev.final_score:.2f}] [{ev.source}]", flush=True)
            print(f"{ev.title}\n", flush=True)
            if ev.text:
                short_text = ev.text[:140] + "..." if len(ev.text) > 140 else ev.text
                print(f"{short_text}\n", flush=True)
            print(f"{ev.url}\n", flush=True)

    db.close()


if __name__ == "__main__":
    run()
