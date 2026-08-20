import argparse
import sys
import time
import yaml
from pathlib import Path

# Ensure UTF-8 console output
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.semantic.clustering import ClusterManager
from app.semantic.embeddings import EmbeddingService
from app.storage.db import Database


def load_yaml_config(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_backfill(rebuild_clusters: bool = False):
    start_time = time.time()
    semantic_cfg = load_yaml_config("config/semantic.yaml").get("semantic", {})

    model_cfg = semantic_cfg.get("model", {})
    cluster_cfg = semantic_cfg.get("clustering", {})
    text_cfg = semantic_cfg.get("text", {})

    model_name = model_cfg.get("name", "sentence-transformers/all-MiniLM-L6-v2")
    device = model_cfg.get("device", "cpu")
    batch_size = model_cfg.get("batch_size", 16)
    threshold = cluster_cfg.get("similarity_threshold", 0.78)
    candidate_days = cluster_cfg.get("candidate_days", 30)
    max_candidates = cluster_cfg.get("max_candidates", 50)
    max_chars = text_cfg.get("max_characters", 2500)

    db = Database(db_path="data/tech_intel.db")
    embedding_service = EmbeddingService(model_name=model_name, device=device, batch_size=batch_size)
    cluster_mgr = ClusterManager(
        similarity_threshold=threshold,
        candidate_days=candidate_days,
        max_candidates=max_candidates,
        max_chars=max_chars,
    )

    all_events = db.get_all_events()
    total_events = len(all_events)
    by_source = db.get_event_counts_by_source()

    print("=" * 60)
    print("HERMES — SEMANTIC BACKFILL & REBUILD")
    print("=" * 60)
    print("\nDATABASE STATUS BEFORE RUN\n")
    print(f"  Total Events:                     {total_events:>5}")
    for src, count in sorted(by_source.items()):
        print(f"    - {src:<15} {count:>5}")

    unembedded_before = db.get_unembedded_events(model_name)
    print(f"  Events with embeddings:           {total_events - len(unembedded_before):>5}")
    print(f"  Events missing embeddings:        {len(unembedded_before):>5}")

    if rebuild_clusters:
        print("\n[Action] --rebuild-clusters flag detected.")
        print("Clearing story_clusters, cluster_events, and event_relationships (preserving events & embeddings)...")
        db.clear_clusters_and_relationships()
        events_to_cluster = all_events
    else:
        events_to_cluster = db.get_unclustered_events()

    print(f"\nProcessing {len(events_to_cluster)} events through semantic clustering pipeline...\n")
    stats = cluster_mgr.process(events_to_cluster, db, embedding_service)

    top_clusters = db.get_top_clusters(limit=1000)
    single_event = sum(1 for c in top_clusters if len(c.event_ids) == 1)
    multi_event = sum(1 for c in top_clusters if len(c.event_ids) > 1)
    multi_source = sum(1 for c in top_clusters if len(set(c.sources)) > 1)

    total_duration = round(time.time() - start_time, 2)

    print("=" * 60)
    print("BACKFILL & CLUSTERING SUMMARY")
    print("=" * 60)
    print(f"  Events Processed:                 {stats['accepted_events']:>5}")
    print(f"  Embeddings Generated:             {stats['embeddings_generated']:>5}")
    print(f"  Embeddings Reused:                {stats['embeddings_reused']:>5}")
    print(f"  Total StoryClusters:              {len(top_clusters):>5}")
    print(f"    - Single-event clusters:        {single_event:>5}")
    print(f"    - Multi-event clusters:         {multi_event:>5}")
    print(f"    - Multi-source clusters:        {multi_source:>5}")
    print(f"  Events Attached to Existing:      {stats['events_attached']:>5}")
    print(f"  Relationships Created:            {stats['relationships_created']:>5}")
    print(f"  Semantic Failures:                {stats['semantic_failures']:>5}")
    print(f"  Candidate Comparisons:            {stats['candidate_comparisons']:>5}")
    print(f"  Semantic Comparisons:             {stats['semantic_comparisons']:>5}")
    print(f"  Avg Candidates / Event:           {stats['avg_candidates_per_event']:>5.1f}")
    print(f"  Max Candidates for Event:         {stats['max_candidates_for_event']:>5}")
    print(f"  Total Duration:                   {total_duration:>5.2f}s")
    print("=" * 60)

    db.close()


def main():
    parser = argparse.ArgumentParser(description="HERMES Semantic Backfill and Cluster Rebuilder")
    parser.add_argument(
        "--rebuild-clusters",
        action="store_true",
        help="Clear and rebuild story_clusters and relationships while preserving events and cached embeddings",
    )
    args = parser.parse_args()
    run_backfill(rebuild_clusters=args.rebuild_clusters)


if __name__ == "__main__":
    main()
