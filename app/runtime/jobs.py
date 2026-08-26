import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from app.inbox.briefing import export_briefing_markdown, generate_morning_briefing
from app.inbox.generator import generate_daily_inbox
from app.models.schemas import DailyBriefing, Event, Project
from app.pipeline.dedup import is_duplicate_event
from app.pipeline.filter import filter_event
from app.pipeline.rank import score_event
from app.runtime.health import check_system_health
from app.runtime.locks import JobLock
from app.runtime.sanitization import sanitize_error
from app.runtime.timezone import runtime_date_string
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


def _get_adapter_factories(sources_cfg: Dict[str, Any]) -> Dict[str, Tuple[Callable[[], Any], int]]:
    """Returns factory functions for creating adapters on demand only when due."""
    return {
        "github": (
            lambda: GitHubAdapter(queries=sources_cfg.get("github", {}).get("queries")),
            50,
        ),
        "github_releases": (
            lambda: GitHubReleasesAdapter(watch_repositories=sources_cfg.get("github_releases", {}).get("watch_repositories")),
            30,
        ),
        "arxiv": (
            lambda: ArxivAdapter(queries=sources_cfg.get("arxiv", {}).get("queries")),
            30,
        ),
        "hackernews": (
            lambda: HackerNewsAdapter(),
            30,
        ),
        "huggingface": (
            lambda: HuggingFaceAdapter(
                queries=sources_cfg.get("huggingface", {}).get("queries"),
                fetch_models=sources_cfg.get("huggingface", {}).get("models", True),
                fetch_datasets=sources_cfg.get("huggingface", {}).get("datasets", True),
            ),
            30,
        ),
        "openalex": (
            lambda: OpenAlexAdapter(queries=sources_cfg.get("openalex", {}).get("queries")),
            30,
        ),
        "crossref": (
            lambda: CrossrefAdapter(queries=sources_cfg.get("crossref", {}).get("queries")),
            20,
        ),
        "stackexchange": (
            lambda: StackExchangeAdapter(
                sites=sources_cfg.get("stackexchange", {}).get("sites"),
                tags=sources_cfg.get("stackexchange", {}).get("tags"),
            ),
            20,
        ),
        "rss": (
            lambda: RssAdapter(feeds=sources_cfg.get("rss", {}).get("feeds")),
            30,
        ),
    }


def run_source_ingestion(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Polls due enabled sources incrementally using lazy adapter instantiation.
    Isolates failures per provider, updates checkpoints, and persists new events.
    """
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

    factories = _get_adapter_factories(sources_cfg)

    results = {
        "status": "completed",
        "sources_polled": [],
        "sources_skipped": [],
        "sources_failed": [],
        "events_ingested": 0,
    }

    seen_ids = set()
    seen_urls = set()

    for src_name, (factory_fn, max_res) in factories.items():
        src_runtime_cfg = config.get("sources", {}).get(src_name, {})
        if src_runtime_cfg.get("enabled", True) is False:
            results["sources_skipped"].append({"source": src_name, "reason": "CONFIG_DISABLED"})
            continue

        is_due, reason = is_source_due(src_name, db, now, config)
        if not is_due:
            results["sources_skipped"].append({"source": src_name, "reason": reason})
            logger.debug(f"Source '{src_name}' skipped: {reason}")
            continue

        if dry_run:
            results["sources_polled"].append({"source": src_name, "status": "dry_run_due"})
            continue

        logger.info(f"Polling source: {src_name}...")
        current_stage = "construct"
        try:
            # 1. Construct adapter
            current_stage = "construct"
            adapter = factory_fn()

            # 2. Fetch raw items
            current_stage = "fetch"
            raw_items = adapter.fetch(limit=max_res)

            # 3. Validate fetch shape
            current_stage = "validate_fetch_shape"
            if not isinstance(raw_items, list):
                raise TypeError(f"Adapter '{src_name}' fetch() must return a list, got {type(raw_items).__name__}")

            items_fetched = len(raw_items)
            items_normalized = 0
            items_failed = 0
            items_rejected = 0
            new_events_count = 0

            # 4. Normalize & Validate Event Schema
            current_stage = "normalize"
            for item in raw_items:
                if not isinstance(item, dict):
                    items_failed += 1
                    continue

                try:
                    event = adapter.normalize(item)
                except Exception:
                    items_failed += 1
                    continue

                if not isinstance(event, Event):
                    items_failed += 1
                    continue

                if not event.id or not isinstance(event.id, str):
                    items_failed += 1
                    continue

                if event.published_at is not None and not isinstance(event.published_at, datetime):
                    items_failed += 1
                    continue

                if not isinstance(event.discovered_at, datetime) or event.discovered_at.tzinfo is None:
                    items_failed += 1
                    continue

                if not isinstance(event.metadata, dict) or not isinstance(event.raw_payload, dict):
                    items_failed += 1
                    continue

                if not isinstance(event.authors, list) or not isinstance(event.topics, list):
                    items_failed += 1
                    continue

                items_normalized += 1

                # 5. Deduplicate
                if is_duplicate_event(event, seen_ids, seen_urls) or db.event_exists(event.id):
                    continue

                seen_ids.add(event.id)
                if event.url:
                    seen_urls.add(event.url)

                # 6. Filter
                if not filter_event(event, interests_cfg):
                    items_rejected += 1
                    continue

                # 7. Score & Persist (insert_event also indexes into events_fts
                # when FTS5 is available)
                scored_event = score_event(event, interests_cfg)
                if db.insert_event(scored_event):
                    new_events_count += 1

            # Determine per-source outcome
            if items_failed > 0 and items_normalized == 0 and items_fetched > 0:
                raise ValueError(f"All {items_fetched} items returned by '{src_name}' failed normalization/schema validation")

            # 8. Checkpoint
            current_stage = "checkpoint"
            record_source_success(src_name, db, now=now)
            results["sources_polled"].append({
                "source": src_name,
                "events_found": items_fetched,
                "items_normalized": items_normalized,
                "items_failed": items_failed,
                "new_events": new_events_count,
            })
            results["events_ingested"] += new_events_count
            db.increment_runtime_metric("sources_polled", 1)
            db.increment_runtime_metric("events_ingested", new_events_count)
            logger.info(f"Source '{src_name}' complete: {new_events_count} new events persisted.")
        except Exception as e:
            category, sanitized_err = sanitize_error(e)
            logger.warning(f"Source '{src_name}' failed at stage '{current_stage}': {sanitized_err}")
            record_source_failure(src_name, e, db, now=now, config=config, error_category=category)
            results["sources_failed"].append({
                "source": src_name,
                "stage": current_stage,
                "error": sanitized_err,
                "error_category": category,
            })

    # Determine aggregated ingestion status
    if results["sources_failed"]:
        if results["sources_polled"]:
            results["status"] = "partial"
        else:
            results["status"] = "failed"
    else:
        results["status"] = "completed"

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
        return {"clusters_count": len(all_clusters), "events_processed": stats.get("accepted_events", 0), "status": "completed"}
    finally:
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

    return {"claims_created": claims_created, "evidence_created": evidence_created, "status": "completed"}


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

    queue_items = populate_recheck_queue(db, dry_run=False)
    processed_results = process_recheck_queue(db, dry_run=False, limit=50)

    return {"queue_populated": len(queue_items), "items_evaluated": len(processed_results), "status": "completed"}


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
    return {"projects_scanned": len(projects), "files_scanned": scanned_files, "profiles_updated": profiles_updated, "status": "completed"}


def run_context_match(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Matches active projects with recent clusters."""
    if now is None:
        now = datetime.now(timezone.utc)

    projects = db.get_all_projects(active_only=True)
    if not projects:
        return {"status": "not_applicable", "matches_created": 0, "reason": "No active projects configured"}

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

    return {"matches_created": matches_count, "status": "completed"}


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
    return {"active_inbox_items": len(active_items), "status": "completed"}


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
    return {"expired_count": expired_count, "status": "completed"}


def generate_scheduled_morning_briefing(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    refresh: bool = False,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Scheduled entry point: Generates morning briefing snapshot directly from existing DB state
    without re-executing upstream ingestion/semantic pipeline.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    config = load_runtime_config()
    if target_date is not None:
        target_date_clean = target_date.strip()
        try:
            parsed = datetime.strptime(target_date_clean, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != target_date_clean:
                raise ValueError()
        except ValueError:
            raise ValueError(f"Invalid target_date format '{target_date}'. Expected valid calendar date in YYYY-MM-DD format.")
        target_date = target_date_clean
    else:
        target_date = runtime_date_string(now, config)

    existing_briefing = db.get_daily_briefing(target_date)

    if existing_briefing and not refresh and not dry_run:
        export_file = Path("data/briefings") / f"{target_date}.md"
        if export_file.exists():
            logger.info(f"Morning briefing for {target_date} already exists.")
            return {
                "status": "already_exists",
                "briefing_id": existing_briefing.id,
                "briefing_date": target_date,
                "total_items": existing_briefing.total_items,
                "markdown_file": str(export_file),
            }
        else:
            logger.info(f"Morning briefing row exists for {target_date}, but markdown file is missing. Re-exporting stored summary...")
            try:
                markdown_file_path = export_briefing_markdown(
                    briefing_date=target_date,
                    text=existing_briefing.summary_text or "",
                    export_dir="data/briefings",
                )
                logger.info(f"Morning briefing recovered export to {markdown_file_path} ({existing_briefing.total_items} items).")
                return {
                    "status": "completed",
                    "briefing_id": existing_briefing.id,
                    "briefing_date": target_date,
                    "total_items": existing_briefing.total_items,
                    "high_priority_count": existing_briefing.high_priority_count,
                    "project_relevant_count": existing_briefing.project_relevant_count,
                    "markdown_file": markdown_file_path,
                    "recovered_export": True,
                }
            except Exception as e:
                logger.error(f"Failed to recover morning briefing markdown export: {e}")
                return {
                    "status": "export_failed",
                    "briefing_id": existing_briefing.id,
                    "briefing_date": target_date,
                    "total_items": existing_briefing.total_items,
                    "error": str(e),
                }

    if dry_run:
        return {"status": "dry_run", "target_date": target_date}

    logger.info(f"Generating scheduled morning briefing for {target_date} from DB...")
    briefing = generate_morning_briefing(db=db, target_date=target_date, refresh=True, now=now)
    db.increment_runtime_metric("briefings_generated", 1)

    try:
        markdown_file_path = export_briefing_markdown(
            briefing_date=target_date,
            text=briefing.summary_text or "",
            export_dir="data/briefings",
        )
        logger.info(f"Morning briefing exported to {markdown_file_path} ({briefing.total_items} items).")
        export_success = True
        export_error = None
    except Exception as e:
        logger.error(f"Failed to export morning briefing markdown: {e}")
        export_success = False
        export_error = str(e)
        markdown_file_path = None

    if not export_success:
        return {
            "status": "export_failed",
            "briefing_id": briefing.id,
            "briefing_date": target_date,
            "total_items": briefing.total_items,
            "error": export_error,
        }

    return {
        "status": "success",
        "briefing_id": briefing.id,
        "briefing_date": target_date,
        "total_items": briefing.total_items,
        "high_priority_count": briefing.high_priority_count,
        "project_relevant_count": briefing.project_relevant_count,
        "markdown_file": markdown_file_path,
    }


def run_morning_pipeline_orchestration(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    refresh: bool = False,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Standalone / manual entry point: Sequentially executes all upstream pipeline stages
    and then generates and exports the morning briefing.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    config = load_runtime_config()
    if target_date is not None:
        target_date_clean = target_date.strip()
        try:
            parsed = datetime.strptime(target_date_clean, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != target_date_clean:
                raise ValueError()
        except ValueError:
            raise ValueError(f"Invalid target_date format '{target_date}'. Expected valid calendar date in YYYY-MM-DD format.")
        target_date = target_date_clean
    else:
        target_date = runtime_date_string(now, config)

    existing_briefing = db.get_daily_briefing(target_date)

    if existing_briefing and not refresh and not dry_run:
        export_file = Path("data/briefings") / f"{target_date}.md"
        if export_file.exists():
            logger.info(f"Morning briefing for {target_date} already exists.")
            return {"status": "already_exists", "briefing_id": existing_briefing.id, "total_items": existing_briefing.total_items}

    if dry_run:
        return {"status": "dry_run", "target_date": target_date}

    logger.info(f"Executing full morning orchestration pipeline for {target_date}...")

    # Upstream pipeline sequence
    run_source_ingestion(db, now=now)
    run_semantic_processing(db, now=now)
    run_claims_processing(db, now=now)
    run_longitudinal_recheck(db, now=now)
    run_context_match(db, now=now)
    run_inbox_generation(db, now=now)

    return generate_scheduled_morning_briefing(db, dry_run=False, now=now, refresh=True, target_date=target_date)


# Backwards compatibility alias
run_morning_briefing = generate_scheduled_morning_briefing


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
        return {"success": True, "backup_path": path, "message": msg, "status": "completed"}
    else:
        logger.error(f"Daily backup failed: {msg}")
        return {"success": False, "backup_path": path, "message": msg, "status": "failed"}


def run_health_check_job(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Executes periodic health check and logs any anomalies."""
    if now is None:
        now = datetime.now(timezone.utc)

    health = check_system_health(db, now=now, use_cache=False)
    if health["status"] != "HEALTHY":
        logger.warning(f"Health check status: {health['status']} | Issues: {health['issues']} | Warnings: {health['warnings']}")
    return {"status": "completed", "health": health}


def run_saved_hydration(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Re-hydrates active SavedItem snapshot fields from current intelligence.

    Refreshes verification/maturity/risk/claim-status snapshots and link status
    for every active saved item without mutating user notes, tags, or the
    saved_at timestamp. Items whose backing cluster no longer exists are marked
    'unresolved' instead of being deleted.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if dry_run:
        return {"status": "dry_run"}

    saved_items = db.get_all_saved_items(active_only=True)
    hydrated = 0
    unresolved = 0

    for item in saved_items:
        cluster = db.get_cluster(item.story_cluster_id) if item.story_cluster_id else None
        if not cluster:
            if item.link_status != "unresolved":
                item.link_status = "unresolved"
                db.save_saved_item(item)
                unresolved += 1
            continue

        claims = db.get_claims_by_cluster(cluster.id)
        current_claims = [c for c in claims if getattr(c, "is_current", True)]
        assessment = db.get_technology_assessment(cluster.id)
        tech_state = db.get_technology_state(cluster.id)

        if current_claims:
            scores = [c.verification_score for c in current_claims if c.verification_score is not None]
            item.verification_snapshot = round(sum(scores) / len(scores), 4) if scores else item.verification_snapshot
        if assessment:
            item.maturity_snapshot = assessment.maturity_stage
        if tech_state:
            item.risk_snapshot = tech_state.risk_score

        # Claim status snapshot from current claims
        if current_claims:
            statuses = [getattr(c, "status", None) for c in current_claims]
            if any(s == "contradicted" for s in statuses):
                item.claim_status_snapshot = "contradicted"
            elif any(s == "superseded" for s in statuses):
                item.claim_status_snapshot = "superseded"
            elif any(s == "supported" for s in statuses):
                item.claim_status_snapshot = "supported"
            else:
                item.claim_status_snapshot = "unverified"

        if item.link_status != "resolved":
            item.link_status = "resolved"
        db.save_saved_item(item)
        hydrated += 1

    db.increment_runtime_metric("saved_hydration_runs", 1)
    logger.info(f"Saved hydration complete: {hydrated} hydrated, {unresolved} marked unresolved")
    return {
        "status": "completed",
        "hydrated": hydrated,
        "unresolved": unresolved,
        "total_active": len(saved_items),
    }


def run_daily_refresh(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    surface_date: Optional[str] = None,
    daily_run_id: Optional[str] = None,
    data_cutoff_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Executes the comprehensive Daily Refresh job pipeline sequentially:
    Ingestion -> Semantic Processing -> Claims Processing -> Longitudinal Recheck ->
    Context Scan -> Context Match -> Inbox Generation -> Morning Briefing.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if surface_date is None:
        runtime_config = load_runtime_config()
        surface_date = runtime_date_string(now, runtime_config)

    if daily_run_id is None:
        daily_run_id = f"daily-run:{surface_date}"

    if data_cutoff_at is None:
        data_cutoff_at = now

    if dry_run:
        return {"status": "dry_run", "surface_date": surface_date}

    # Idempotence + catch-up: skip only when a successful run already exists
    # for this date. A previously FAILED run is retried with an incremented
    # retry_count so transient failures do not permanently block the day.
    existing_run = db.get_daily_signal_run_by_date(surface_date)
    retry_count = 0
    if existing_run is not None:
        if existing_run.status in ("completed", "completed_empty", "partial_sources"):
            logger.info(f"Daily Refresh for {surface_date} already completed (run: {existing_run.id}). Skipping.")
            return {
                "status": "already_completed",
                "surface_date": surface_date,
                "daily_run_id": existing_run.id,
                "briefing_id": existing_run.briefing_id,
            }
        # Failed run: retry with incremented retry_count, keep the same run id.
        daily_run_id = existing_run.id
        retry_count = (existing_run.retry_count or 0) + 1
        logger.warning(f"Retrying failed Daily Refresh for {surface_date} (attempt {retry_count}, run: {daily_run_id})")

    logger.info(f"Starting Daily Refresh pipeline for {surface_date} (run: {daily_run_id})")

    try:
        # 1. Ingestion
        ingest_res = run_source_ingestion(db, dry_run=False, now=now)
        # 2. Semantic
        semantic_res = run_semantic_processing(db, dry_run=False, now=now)
        # 3. Claims
        claims_res = run_claims_processing(db, dry_run=False, now=now)
        # 4. Recheck
        recheck_res = run_longitudinal_recheck(db, dry_run=False, now=now)
        # 5. Context Scan
        scan_res = run_context_scan(db, dry_run=False, now=now)
        # 6. Context Match
        match_res = run_context_match(db, dry_run=False, now=now)
        # 7. Inbox (Today)
        inbox_res = generate_daily_inbox(
            db=db,
            now=now,
            surface_date=surface_date,
            daily_run_id=daily_run_id,
            data_cutoff_at=data_cutoff_at,
        )
        # 8. Briefing
        briefing = generate_morning_briefing(
            db=db,
            target_date=surface_date,
            refresh=True,
            now=now,
            daily_run_id=daily_run_id,
            data_cutoff_at=data_cutoff_at,
        )

        logger.info(f"Completed Daily Refresh pipeline for {surface_date} (run: {daily_run_id})")
        
        # Save the daily signal run to DB to prevent duplicate runs
        from app.models.schemas import DailySignalRun
        from app.runtime.timezone import get_effective_timezone
        _, tz_name, _ = get_effective_timezone()
        completed_at = datetime.now(timezone.utc)
        source_status = {
            "sources_polled": ingest_res.get("sources_polled", []),
            "sources_skipped": ingest_res.get("sources_skipped", []),
            "sources_failed": ingest_res.get("sources_failed", []),
        }
        new_signals = ingest_res.get("events_ingested", 0) or 0
        updated_signals = semantic_res.get("events_processed", 0)
        carried_signals = len(inbox_res)
        run_record = DailySignalRun(
            id=daily_run_id,
            runtime_date=surface_date,
            runtime_timezone=tz_name,
            run_kind="daily_refresh",
            started_at=now,
            completed_at=completed_at,
            data_cutoff_at=data_cutoff_at,
            status="completed" if not ingest_res.get("sources_failed") else "partial_sources",
            new_signal_count=new_signals,
            updated_signal_count=updated_signals,
            carried_signal_count=carried_signals,
            retry_count=retry_count,
            briefing_id=briefing.id,
            source_status_json=json.dumps(source_status),
            error_summary=None,
            content_hash=f"{daily_run_id}:{briefing.content_hash}" if getattr(briefing, "content_hash", None) else f"{daily_run_id}:{completed_at.isoformat()}",
        )
        db.save_daily_signal_run(run_record)

        return {
            "status": "completed",
            "surface_date": surface_date,
            "daily_run_id": daily_run_id,
            "briefing_id": briefing.id,
            "inbox_items_count": len(inbox_res),
            "signals_run": run_record.model_dump(),
        }
    except Exception as e:
        logger.exception(f"Daily Refresh pipeline failed for {surface_date} (run: {daily_run_id}): {e}")
        from app.models.schemas import DailySignalRun
        from app.runtime.timezone import get_effective_timezone
        _, tz_name, _ = get_effective_timezone()
        failed_at = datetime.now(timezone.utc)
        run_record = DailySignalRun(
            id=daily_run_id,
            runtime_date=surface_date,
            runtime_timezone=tz_name,
            run_kind="daily_refresh",
            started_at=now,
            completed_at=failed_at,
            data_cutoff_at=data_cutoff_at,
            status="failed",
            new_signal_count=0,
            updated_signal_count=0,
            carried_signal_count=0,
            retry_count=retry_count,
            briefing_id=None,
            source_status_json=None,
            error_summary=str(e),
            content_hash=f"{daily_run_id}:failed:{failed_at.isoformat()}",
        )
        db.save_daily_signal_run(run_record)
        raise e

