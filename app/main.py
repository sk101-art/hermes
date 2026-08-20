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
from app.adapters.crossref import CrossrefAdapter
from app.adapters.github import GitHubAdapter
from app.adapters.github_releases import GitHubReleasesAdapter
from app.adapters.hackernews import HackerNewsAdapter
from app.adapters.huggingface import HuggingFaceAdapter
from app.adapters.openalex import OpenAlexAdapter
from app.adapters.rss import RssAdapter
from app.adapters.stackexchange import StackExchangeAdapter
from app.evidence.claims import extract_claims_for_cluster
from app.evidence.maturity import assess_technology_maturity
from app.evidence.verification import compute_verification
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
    semantic_cfg = load_yaml_config("config/semantic.yaml").get("semantic", {})

    # Initialize Database
    db = Database(db_path="data/tech_intel.db")

    # Build active adapters dynamically based on configuration
    adapters = []

    gh_cfg = sources_cfg.get("github", {})
    if gh_cfg.get("enabled", True):
        adapters.append((
            "GitHub Repositories",
            GitHubAdapter(queries=gh_cfg.get("queries")),
            gh_cfg.get("max_results", 100),
        ))

    gh_rel_cfg = sources_cfg.get("github_releases", {})
    if gh_rel_cfg.get("enabled", True):
        adapters.append((
            "GitHub Releases",
            GitHubReleasesAdapter(watch_repositories=gh_rel_cfg.get("watch_repositories")),
            gh_rel_cfg.get("max_results", 30),
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

    hf_cfg = sources_cfg.get("huggingface", {})
    if hf_cfg.get("enabled", True):
        adapters.append((
            "Hugging Face",
            HuggingFaceAdapter(
                queries=hf_cfg.get("queries"),
                fetch_models=hf_cfg.get("models", True),
                fetch_datasets=hf_cfg.get("datasets", True),
            ),
            hf_cfg.get("max_results", 50),
        ))

    alex_cfg = sources_cfg.get("openalex", {})
    if alex_cfg.get("enabled", True):
        adapters.append((
            "OpenAlex",
            OpenAlexAdapter(queries=alex_cfg.get("queries")),
            alex_cfg.get("max_results", 40),
        ))

    cr_cfg = sources_cfg.get("crossref", {})
    if cr_cfg.get("enabled", True):
        adapters.append((
            "Crossref",
            CrossrefAdapter(queries=cr_cfg.get("queries")),
            cr_cfg.get("max_results", 25),
        ))

    se_cfg = sources_cfg.get("stackexchange", {})
    if se_cfg.get("enabled", True):
        adapters.append((
            "Stack Exchange",
            StackExchangeAdapter(sites=se_cfg.get("sites"), tags=se_cfg.get("tags")),
            se_cfg.get("max_results", 30),
        ))

    rss_cfg = sources_cfg.get("rss", {})
    if rss_cfg.get("enabled", True):
        adapters.append((
            "RSS Feeds",
            RssAdapter(feeds=rss_cfg.get("feeds")),
            rss_cfg.get("max_results", 25),
        ))

    source_stats = {}
    total_fetched = 0
    total_normalized = 0
    total_duplicates = 0
    total_rejected = 0
    total_accepted = 0

    seen_ids = set()
    seen_urls = set()
    accepted_events_list = []

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
                accepted_events_list.append(scored_event)

        total_fetched += fetched
        source_stats[source_name] = {
            "fetched": fetched,
            "normalized": normalized,
            "duplicates": duplicates,
            "rejected": rejected,
            "accepted": accepted,
        }

    # Print Session Ingestion summary
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
    print("=" * 60, flush=True)

    # --- Semantic Story Clustering ---
    semantic_enabled = semantic_cfg.get("enabled", True)
    clustering_successful = False

    if semantic_enabled:
        try:
            from app.semantic.clustering import ClusterManager
            from app.semantic.embeddings import EmbeddingService

            model_cfg = semantic_cfg.get("model", {})
            cluster_cfg = semantic_cfg.get("clustering", {})
            text_cfg = semantic_cfg.get("text", {})

            embedding_service = EmbeddingService(
                model_name=model_cfg.get("name", "sentence-transformers/all-MiniLM-L6-v2"),
                device=model_cfg.get("device", "cpu"),
                batch_size=model_cfg.get("batch_size", 16),
            )

            cluster_mgr = ClusterManager(
                similarity_threshold=cluster_cfg.get("similarity_threshold", 0.78),
                candidate_days=cluster_cfg.get("candidate_days", 30),
                max_candidates=cluster_cfg.get("max_candidates", 50),
                max_chars=text_cfg.get("max_characters", 2500),
            )

            sem_stats = cluster_mgr.process(accepted_events_list, db, embedding_service)
            clustering_successful = True

            print("\nSEMANTIC SUMMARY\n", flush=True)
            print(f"  Accepted Events:                  {sem_stats['accepted_events']:>5}", flush=True)
            print(f"  Embeddings Generated:             {sem_stats['embeddings_generated']:>5}", flush=True)
            print(f"  Embeddings Reused:                {sem_stats['embeddings_reused']:>5}", flush=True)
            print(f"  Clusters Created:                 {sem_stats['clusters_created']:>5}", flush=True)
            print(f"  Attached To Existing Clusters:    {sem_stats['events_attached']:>5}", flush=True)
            print(f"  Relationships Created:            {sem_stats['relationships_created']:>5}", flush=True)
            print(f"  Semantic Failures:                {sem_stats['semantic_failures']:>5}", flush=True)
            print("=" * 60, flush=True)

            # --- Claims, Evidence & Technology Assessment Processing ---
            all_clusters = db.get_all_clusters()
            for cl in all_clusters:
                cl_events = db.get_cluster_events(cl.id)
                if not cl_events:
                    continue

                assessment = assess_technology_maturity(cl, cl_events)
                db.save_technology_assessment(assessment)

                claims_with_ev = extract_claims_for_cluster(cl, cl_events)
                for claim, ev_list in claims_with_ev:
                    v_score, status = compute_verification(claim, ev_list)
                    claim.verification_score = v_score
                    claim.status = status
                    db.save_claim(claim)
                    for ev in ev_list:
                        db.save_evidence(ev)

        except Exception as e:
            print(f"\n[Warning] Semantic clustering unavailable ({e}). Continuing with Event-level intelligence.", flush=True)

    # Print Top Intelligence Stories if available
    top_clusters = db.get_top_clusters(limit=20)
    if clustering_successful and top_clusters:
        print("\nTOP INTELLIGENCE STORIES\n", flush=True)
        for idx, cluster in enumerate(top_clusters, 1):
            sources_str = ", ".join(cluster.sources)
            assessment = db.get_technology_assessment(cluster.id)
            maturity_str = assessment.maturity_stage.upper() if assessment else "UNKNOWN"
            claims = db.get_claims_by_cluster(cluster.id)

            print(f"{idx:02d} [{cluster.cluster_score:.2f}] [Maturity: {maturity_str}]", flush=True)
            print(f"{cluster.canonical_title}\n", flush=True)
            print(f"  Sources: {sources_str} | Supporting Events: {len(cluster.event_ids)} | Claims: {len(claims)}", flush=True)

            if claims:
                strongest = claims[0]
                print(f"  Strongest Claim: \"{strongest.claim_text}\"", flush=True)
                print(f"  Verification:    {strongest.verification_score:.2f} — {strongest.status.upper()}", flush=True)

            cluster_events = db.get_cluster_events(cluster.id)[:2]
            for ev in cluster_events:
                print(f"    [{ev.source}] {ev.title}", flush=True)
                print(f"    {ev.url}", flush=True)
            print("-" * 60, flush=True)

    else:
        print("\nTOP DEVELOPMENTS\n", flush=True)
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
