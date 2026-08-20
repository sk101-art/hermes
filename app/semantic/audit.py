import sys
import yaml
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np

# Ensure UTF-8 console output
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.models.schemas import Event
from app.semantic.clustering import select_candidates
from app.semantic.similarity import cosine_similarity, extract_github_repo, extract_arxiv_id
from app.storage.db import Database


def load_yaml_config(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_audit():
    semantic_cfg = load_yaml_config("config/semantic.yaml").get("semantic", {})
    model_name = semantic_cfg.get("model", {}).get("name", "sentence-transformers/all-MiniLM-L6-v2")

    db = Database(db_path="data/tech_intel.db")
    all_events = db.get_all_events()
    total_events = len(all_events)
    by_source = db.get_event_counts_by_source()
    embeddings_map = db.get_all_embeddings(model_name)
    top_clusters = db.get_top_clusters(limit=1000)
    all_rels = db.get_all_relationships()

    single_clusters = [c for c in top_clusters if len(c.event_ids) == 1]
    multi_clusters = [c for c in top_clusters if len(c.event_ids) > 1]
    multi_source_clusters = [c for c in top_clusters if len(set(c.sources)) > 1]

    print("=" * 60)
    print("HERMES — SEMANTIC AUDIT & DIAGNOSTICS")
    print("=" * 60)

    # 1. Database Semantic Coverage
    print("\nDATABASE SEMANTIC COVERAGE\n")
    print(f"  Total Events:                     {total_events:>5}")
    for src, cnt in sorted(by_source.items()):
        print(f"    - {src:<15} {cnt:>5}")
    print(f"  Events with embeddings:           {len(embeddings_map):>5}")
    print(f"  Events missing embeddings:        {total_events - len(embeddings_map):>5}")
    print(f"  Total StoryClusters:              {len(top_clusters):>5}")
    print(f"    - Single-event clusters:        {len(single_clusters):>5}")
    print(f"    - Multi-event clusters:         {len(multi_clusters):>5}")
    print(f"    - Multi-source clusters:        {len(multi_source_clusters):>5}")
    print(f"  Total Relationships:              {len(all_rels):>5}")

    # 2. Direct Identifier Linking Audit
    print("\n" + "-" * 60)
    print("DIRECT URL LINKING AUDIT")
    print("-" * 60 + "\n")
    hn_events = [e for e in all_events if e.source == "hackernews"]
    hn_gh_urls = 0
    hn_gh_matches = 0
    hn_ax_urls = 0
    hn_ax_matches = 0

    for hn in hn_events:
        gh_id = extract_github_repo(hn.url) or extract_github_repo(hn.metadata.get("external_url"))
        if gh_id:
            hn_gh_urls += 1
            # Check if matching github event exists
            for other in all_events:
                if other.source == "github":
                    if extract_github_repo(other.url) == gh_id or extract_github_repo(other.id) == gh_id:
                        hn_gh_matches += 1
                        break

        ax_id = extract_arxiv_id(hn.url) or extract_arxiv_id(hn.metadata.get("external_url"))
        if ax_id:
            hn_ax_urls += 1
            for other in all_events:
                if other.source == "arxiv":
                    if extract_arxiv_id(other.url) == ax_id or extract_arxiv_id(other.id) == ax_id:
                        hn_ax_matches += 1
                        break

    print(f"  HN -> GitHub URLs found:          {hn_gh_urls:>5}")
    print(f"  HN -> GitHub Event matches:       {hn_gh_matches:>5}")
    print(f"  HN -> arXiv URLs found:           {hn_ax_urls:>5}")
    print(f"  HN -> arXiv Event matches:        {hn_ax_matches:>5}")

    # 3. Exhaustive Pair Similarity & Recall Diagnostic
    print("\n" + "-" * 60)
    print("EXHAUSTIVE PAIR SIMILARITY & RECALL DIAGNOSTIC")
    print("-" * 60 + "\n")

    embedded_events = [e for e in all_events if e.id in embeddings_map]
    n = len(embedded_events)
    pairs: List[Tuple[float, Event, Event, bool, bool]] = []

    # Map event_id -> cluster_id
    event_cluster_map = {}
    for c in top_clusters:
        for eid in c.event_ids:
            event_cluster_map[eid] = c.id

    threshold_buckets = {
        0.90: 0,
        0.85: 0,
        0.82: 0,
        0.80: 0,
        0.78: 0,
        0.75: 0,
        0.70: 0,
    }
    threshold_recall = {t: {"total": 0, "found": 0} for t in threshold_buckets}

    # Pre-cache candidate sets for candidate recall check
    candidate_cache: Dict[str, Set[str]] = {}
    for ev in embedded_events:
        cands = select_candidates(ev, embedded_events, db=db, max_candidates=50)
        candidate_cache[ev.id] = {c.id for c in cands}

    for i in range(n):
        ev1 = embedded_events[i]
        vec1 = embeddings_map[ev1.id]
        for j in range(i + 1, n):
            ev2 = embedded_events[j]
            vec2 = embeddings_map[ev2.id]
            sim = cosine_similarity(vec1, vec2)

            cand_generated = (ev2.id in candidate_cache.get(ev1.id, set())) or (ev1.id in candidate_cache.get(ev2.id, set()))
            same_cluster = (ev1.id in event_cluster_map) and (event_cluster_map.get(ev1.id) == event_cluster_map.get(ev2.id))

            pairs.append((sim, ev1, ev2, cand_generated, same_cluster))

            for t in threshold_buckets:
                if sim >= t:
                    threshold_buckets[t] += 1
                    threshold_recall[t]["total"] += 1
                    if cand_generated:
                        threshold_recall[t]["found"] += 1

    pairs.sort(key=lambda x: x[0], reverse=True)

    print("PAIR SIMILARITY DISTRIBUTION\n")
    for t in sorted(threshold_buckets.keys(), reverse=True):
        count = threshold_buckets[t]
        tot = threshold_recall[t]["total"]
        fnd = threshold_recall[t]["found"]
        recall_pct = (fnd / tot * 100.0) if tot > 0 else 100.0
        print(f"  >= {t:.2f}: {count:>5} pairs | Candidate Recall: {fnd}/{tot} ({recall_pct:.1f}%)")

    # 4. Top 30 Highest-Similarity Pairs
    print("\n" + "-" * 60)
    print("TOP 30 HIGHEST-SIMILARITY EVENT PAIRS (OVERALL)")
    print("-" * 60 + "\n")
    for idx, (sim, e1, e2, cand_gen, same_c) in enumerate(pairs[:30], 1):
        print(f"{idx:02d} [{sim:.4f}] Candidate: {'YES' if cand_gen else 'NO'} | Same Cluster: {'YES' if same_c else 'NO'}")
        print(f"    [{e1.source}] {e1.title[:85]}")
        print(f"    [{e2.source}] {e2.title[:85]}")

    # 5. Top 20 Cross-Source Similarities
    cross_pairs = [p for p in pairs if p[1].source != p[2].source]
    print("\n" + "-" * 60)
    print("TOP 20 CROSS-SOURCE SIMILARITIES")
    print("-" * 60 + "\n")
    for idx, (sim, e1, e2, cand_gen, same_c) in enumerate(cross_pairs[:20], 1):
        print(f"{idx:02d} [{sim:.4f}] {e1.source} <-> {e2.source} | Cand: {'YES' if cand_gen else 'NO'} | Cluster: {'YES' if same_c else 'NO'}")
        print(f"    [{e1.source}] {e1.title[:85]}")
        print(f"    [{e2.source}] {e2.title[:85]}")

    # 6. Multi-Event Clusters
    print("\n" + "-" * 60)
    print("MULTI-EVENT CLUSTERS")
    print("-" * 60 + "\n")
    if not multi_clusters:
        print("  No multi-event clusters currently in database.")
    else:
        for idx, c in enumerate(multi_clusters, 1):
            print(f"{idx:02d} [{c.cluster_score:.2f}] (Sources: {', '.join(c.sources)} | Events: {len(c.event_ids)})")
            print(f"    Canonical: {c.canonical_title}")
            for ev in db.get_cluster_events(c.id):
                print(f"      - [{ev.source}] {ev.title[:75]}")

    print("\n" + "=" * 60)
    db.close()


if __name__ == "__main__":
    run_audit()
