import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.arxiv import ArxivAdapter
from app.adapters.crossref import CrossrefAdapter
from app.adapters.github import GitHubAdapter
from app.adapters.github_releases import GitHubReleasesAdapter
from app.adapters.hackernews import HackerNewsAdapter
from app.adapters.huggingface import HuggingFaceAdapter
from app.adapters.openalex import OpenAlexAdapter
from app.adapters.rss import RssAdapter
from app.adapters.stackexchange import StackExchangeAdapter

from app.backup import create_database_backup
from app.context.embeddings import get_or_create_project_embedding, unload_embedder
from app.context.matcher import match_project_with_cluster
from app.context.profiler import build_project_technology_profile
from app.context.scanner import compute_project_context_hash, discover_projects, scan_project_files
from app.evidence.claims import extract_claims_for_cluster
from app.evidence.recheck import populate_recheck_queue, process_recheck_queue
from app.evidence.reevaluate import reevaluate_claim, reevaluate_cluster_maturity, sequence_cluster_releases, update_technology_state
from app.inbox.briefing import generate_morning_briefing
from app.inbox.generator import generate_daily_inbox
from app.models.schemas import Project
from app.pipeline.dedup import is_duplicate_event
from app.pipeline.filter import filter_event
from app.pipeline.rank import score_event
from app.runtime.health import check_system_health
from app.runtime.locks import JobLock
from app.runtime.state import (
    finish_job_run,
    is_source_due,
    load_runtime_config,
    record_source_failure,
    record_source_success,
    start_job_run,
)
from app.semantic.clustering import ClusterManager
from app.semantic.embeddings import EmbeddingService
from app.storage.db import Database


logger = logging.getLogger("hermes.jobs")


def run_source_ingestion(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Polls due sources incrementally, isolates failures, and persists new events."""
    if now is None:
        now = datetime.now(timezone.utc)

    config = load_runtime_config()
    interests_cfg = {}
    interests_file = Path("config/interests.yaml")
    if interests_file.exists():
        try:
            import yaml
            with open(interests_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    interests_cfg = data.get("interests", {})
        except Exception:
            pass

    sources_file = Path("config/sources.yaml")
    sources_cfg = {}
    if sources_file.exists():
        try:
            import yaml
            with open(sources_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    sources_cfg = data.get("sources", {})
        except Exception:
            pass

    sources_map = {
        "github": (GitHubAdapter(queries=sources_cfg.get("github", {}).get("queries")), 50),
        "github_releases": (GitHubReleasesAdapter(watch_repositories=sources_cfg.get("github_releases", {}).get("watch_repositories")), 30),
        "arxiv": (ArxivAdapter(queries=sources_cfg.get("arxiv", {}).get("queries")), 30),
        "hackernews": (HackerNewsAdapter(), 30),
        "huggingface": (HuggingFaceAdapter(
            queries=sources_cfg.get("huggingface", {}).get("queries"),
            fetch_models=sources_cfg.get("huggingface", {}).get("models", True),
            fetch_datasets=sources_cfg.get("huggingface", {}).get("datasets", True),
        ), 30),
        "openalex": (OpenAlexAdapter(queries=sources_cfg.get("openalex", {}).get("queries")), 30),
        "crossref": (CrossrefAdapter(queries=sources_cfg.get("crossref", {}).get("queries")), 20),
        "stackexchange": (StackExchangeAdapter(sites=sources_cfg.get("stackexchange", {}).get("sites"), tags=sources_cfg.get("stackexchange", {}).get("tags")), 20),
        "rss": (RssAdapter(feeds=sources_cfg.get("rss", {}).get("feeds")), 30),
    }

    results = {
        "sources_polled": [],
        "sources_skipped": [],
        "sources_failed": [],
        "events_ingested": 0,
    }

    seen_ids = set()
    seen_urls = set()

    for src_name, (adapter, max_res) in sources_map.items():
        is_due, reason = is_source_due(src_name, db, now, config)
        if not is_due:
            results["sources_skipped"].append({"source": src_name, "reason": reason})
            logger.debug(f"Source '{src_name}' skipped: {reason}")
            continue

        if dry_run:
            results["sources_polled"].append({"source": src_name, "status": "dry_run_due"})
            continue

        logger.info(f"Polling source: {src_name}...")
        try:
            raw_items = adapter.fetch(limit=max_res)
            new_events_count = 0
            for item in raw_items:
                try:
                    event = adapter.normalize(item)
                except Exception:
                    continue

                if is_duplicate_event(event, seen_ids, seen_urls) or db.event_exists(event.id):
                    continue

                seen_ids.add(event.id)
                if event.url:
                    seen_urls.add(event.url)

                if not filter_event(event, interests_cfg):
                    continue

                scored_event = score_event(event, interests_cfg)
                if db.insert_event(scored_event):
                    db.add_event_to_fts(scored_event)
                    new_events_count += 1

            record_source_success(src_name, db, now=now)
            results["sources_polled"].append({"source": src_name, "events_found": len(raw_items), "new_events": new_events_count})
            results["events_ingested"] += new_events_count
            db.increment_runtime_metric("sources_polled", 1)
            db.increment_runtime_metric("events_ingested", new_events_count)
            logger.info(f"Source '{src_name}' complete: {new_events_count} new events persisted.")
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"Source '{src_name}' failed: {err_msg}")
            record_source_failure(src_name, err_msg, db, now=now)
            results["sources_failed"].append({"source": src_name, "error": err_msg})

    return results


def run_semantic_processing(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Generates embeddings and clusters for new events, releasing model memory afterward."""
    if now is None:
        now = datetime.now(timezone.utc)

    unclustered = db.get_unclustered_events()
    if dry_run:
        return {"status": "dry_run", "unclustered_events": len(unclustered)}

    cluster_mgr = ClusterManager(similarity_threshold=0.78, candidate_days=30, max_candidates=50)
    embedding_service = EmbeddingService(model_name="sentence-transformers/all-MiniLM-L6-v2", device="cpu", batch_size=16)

    try:
        stats = cluster_mgr.process(unclustered, db, embedding_service)
        all_clusters = db.get_all_clusters()
        logger.info(f"Semantic clustering complete: {stats.get('accepted_events', 0)} events processed, {len(all_clusters)} StoryClusters total.")
        return {"clusters_count": len(all_clusters), "events_processed": stats.get("accepted_events", 0)}
    finally:
        # Release memory
        embedding_service.unload()
        unload_embedder()


def run_claims_processing(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Extracts and verifies claims for story clusters."""
    if now is None:
        now = datetime.now(timezone.utc)

    clusters = db.get_all_clusters()
    if dry_run:
        return {"status": "dry_run", "clusters": len(clusters)}

    claims_created = 0
    evidence_created = 0

    for cl in clusters:
        existing_claims = db.get_claims_by_cluster(cl.id)
        if not existing_claims:
            events = db.get_cluster_events(cl.id)
            claim_tuples = extract_claims_for_cluster(cl, events)
            for c, ev_rec_list in claim_tuples:
                db.save_claim(c)
                claims_created += 1
                for ev_rec in ev_rec_list:
                    db.save_evidence(ev_rec)
                    evidence_created += 1

    return {"claims_created": claims_created, "evidence_created": evidence_created}


def run_longitudinal_recheck(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Evaluates recheck queue and updates technology state."""
    if now is None:
        now = datetime.now(timezone.utc)

    if dry_run:
        return {"status": "dry_run"}

    # 1. Populate queue
    queue_items = populate_recheck_queue(db, dry_run=False)

    # 2. Process top due queue items
    processed_results = process_recheck_queue(db, dry_run=False, limit=50)

    return {"queue_populated": len(queue_items), "items_evaluated": len(processed_results)}


def run_context_scan(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Scans reference projects, builds technology profiles, and updates embeddings."""
    if now is None:
        now = datetime.now(timezone.utc)

    projects = db.get_all_projects(active_only=True)
    if dry_run:
        return {"status": "dry_run", "projects": len(projects)}

    scanned_files = 0
    profiles_updated = 0

    for p in projects:
        p_dir = Path(p.path)
        if not p_dir.exists():
            continue

        files, stats = scan_project_files(p.id, p_dir)
        scanned_files += len(files)
        context_hash = compute_project_context_hash(files)

        if p.context_hash != context_hash:
            profile, meta = build_project_technology_profile(p.id, p.name, files)
            for pf in files:
                db.save_project_file(pf)
            p.context_hash = context_hash
            p.updated_at = now
            p.last_indexed_at = now
            db.save_project(p)
            db.save_project_profile(profile)
            get_or_create_project_embedding(p.id, profile.profile_text, profile.profile_hash, db)
            profiles_updated += 1

    unload_embedder()
    return {"projects_scanned": len(projects), "files_scanned": scanned_files, "profiles_updated": profiles_updated}


def run_context_match(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Matches active projects with recent clusters."""
    if now is None:
        now = datetime.now(timezone.utc)

    projects = db.get_all_projects(active_only=True)
    clusters = db.get_all_clusters()
    if dry_run:
        return {"status": "dry_run", "projects": len(projects), "clusters": len(clusters)}

    matches_count = 0
    for p in projects:
        profile = db.get_project_profile(p.id)
        if not profile:
            continue
        p_emb = db.get_project_embedding(p.id, "sentence-transformers/all-MiniLM-L6-v2")

        for cl in clusters[:100]:
            events = db.get_cluster_events(cl.id)
            claims = db.get_claims_by_cluster(cl.id)
            assessment = db.get_technology_assessment(cl.id)
            tech_state = db.get_technology_state(cl.id)

            match = match_project_with_cluster(
                project=p,
                profile=profile,
                project_embedding=p_emb,
                cluster=cl,
                cluster_events=events,
                cluster_claims=claims,
                assessment=assessment,
                tech_state=tech_state,
                db=db,
            )
            if match:
                db.save_project_match(match)
                matches_count += 1

    return {"matches_created": matches_count}


def run_inbox_generation(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Generates today's active calibrated inbox items."""
    if now is None:
        now = datetime.now(timezone.utc)

    if dry_run:
        return {"status": "dry_run"}

    active_items = generate_daily_inbox(db=db, now=now, rebuild_today=False)
    db.increment_runtime_metric("inbox_items_generated", len(active_items))
    return {"active_inbox_items": len(active_items)}


def run_inbox_cleanup(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Expires old unstarred inbox items beyond 24-hour TTL."""
    if now is None:
        now = datetime.now(timezone.utc)

    if dry_run:
        return {"status": "dry_run"}

    cursor = db.conn.cursor()
    cursor.execute(
        "UPDATE inbox_items SET state = 'expired' WHERE expires_at < ? AND is_starred = 0 AND state NOT IN ('expired', 'archived')",
        (now.isoformat(),),
    )
    db.conn.commit()
    expired_count = cursor.rowcount
    return {"expired_count": expired_count}


def run_morning_briefing(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """
    Executes the full morning intelligence pipeline and writes the daily briefing markdown file.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    target_date = now.strftime("%Y-%m-%d")
    existing_briefing = db.get_daily_briefing(target_date)

    if existing_briefing and not refresh and not dry_run:
        logger.info(f"Morning briefing for {target_date} already exists.")
        return {"status": "already_exists", "briefing_id": existing_briefing.id, "total_items": existing_briefing.total_items}

    if dry_run:
        return {"status": "dry_run", "target_date": target_date}

    logger.info(f"Executing morning pipeline for {target_date}...")

    # Upstream pipeline sequence
    ingest_res = run_source_ingestion(db, now=now)
    semantic_res = run_semantic_processing(db, now=now)
    claims_res = run_claims_processing(db, now=now)
    recheck_res = run_longitudinal_recheck(db, now=now)
    ctx_res = run_context_match(db, now=now)
    inbox_res = run_inbox_generation(db, now=now)

    # Generate / refresh morning briefing
    briefing = generate_morning_briefing(db=db, target_date=target_date, refresh=True, now=now)
    db.increment_runtime_metric("briefings_generated", 1)

    # Export to markdown file
    briefings_dir = Path("data/briefings")
    briefings_dir.mkdir(parents=True, exist_ok=True)
    briefing_file = briefings_dir / f"{target_date}.md"
    briefing_file.write_text(briefing.summary_text or "", encoding="utf-8")

    logger.info(f"Morning briefing saved to {briefing_file} ({briefing.total_items} items).")

    return {
        "briefing_id": briefing.id,
        "briefing_date": target_date,
        "total_items": briefing.total_items,
        "high_priority_count": briefing.high_priority_count,
        "project_relevant_count": briefing.project_relevant_count,
        "markdown_file": str(briefing_file),
    }


def run_daily_backup(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Creates a consistent daily online backup of the SQLite database."""
    if now is None:
        now = datetime.now(timezone.utc)

    if dry_run:
        return {"status": "dry_run"}

    success, path, msg = create_database_backup(
        db_path=db.db_path,
        backup_dir="data/backups",
        retention_days=7,
        now=now,
    )
    if success:
        db.increment_runtime_metric("backups_created", 1)
        logger.info(f"Daily backup created: {path}")
    else:
        logger.error(f"Daily backup failed: {msg}")

    return {"success": success, "backup_path": path, "message": msg}


def run_health_check_job(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Executes periodic health check and logs any anomalies."""
    if now is None:
        now = datetime.now(timezone.utc)

    health = check_system_health(db, now=now)
    if health["status"] != "HEALTHY":
        logger.warning(f"Health check status: {health['status']} | Issues: {health['issues']} | Warnings: {health['warnings']}")
    return health
