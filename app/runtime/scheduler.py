import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.runtime.jobs import (
    run_claims_processing,
    run_context_match,
    run_context_scan,
    run_daily_backup,
    run_health_check_job,
    run_inbox_cleanup,
    run_inbox_generation,
    run_longitudinal_recheck,
    run_morning_briefing,
    run_semantic_processing,
    run_source_ingestion,
)
from app.runtime.locks import JobLock
from app.runtime.state import (
    finish_job_run,
    load_runtime_config,
    start_job_run,
    write_heartbeat,
)
from app.storage.db import Database


logger = logging.getLogger("hermes.scheduler")

JOB_DEPENDENCIES_ORDER = [
    "health_check",
    "backup",
    "morning_brief",
    "ingestion",
    "semantic",
    "claims",
    "recheck",
    "context_scan",
    "context_match",
    "inbox_refresh",
    "inbox_cleanup",
]

JOB_RUNNERS = {
    "ingestion": run_source_ingestion,
    "semantic": run_semantic_processing,
    "claims": run_claims_processing,
    "recheck": run_longitudinal_recheck,
    "context_scan": run_context_scan,
    "context_match": run_context_match,
    "inbox_refresh": run_inbox_generation,
    "inbox_cleanup": run_inbox_cleanup,
    "morning_brief": run_morning_briefing,
    "backup": run_daily_backup,
    "health_check": run_health_check_job,
}


def parse_time_string(t_str: str) -> dtime:
    """Parses 'HH:MM' string into a datetime.time object."""
    parts = t_str.strip().split(":")
    return dtime(hour=int(parts[0]), minute=int(parts[1]))


def is_job_due(
    job_name: str,
    db: Database,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Determines if a job is due based on schedule, interval, or missed daily morning run.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    jobs_cfg = config.get("jobs", {})
    j_cfg = jobs_cfg.get(job_name, {})
    if not j_cfg:
        return False, "NOT_CONFIGURED"

    job_state = db.get_runtime_job(job_name)

    # 1. Special Handling: Morning Brief (Daily time + missed run recovery)
    if job_name == "morning_brief":
        target_time_str = j_cfg.get("time", "07:30")
        sched_time = parse_time_string(target_time_str)
        today_date_str = now.strftime("%Y-%m-%d")

        # Check if today's briefing already exists in the database
        briefing = db.get_daily_briefing(today_date_str)
        if not briefing:
            # Check if current time is past morning scheduled time
            now_local_time = now.time()
            if now_local_time >= sched_time:
                return True, f"MISSED_OR_DUE_TODAY (Scheduled: {target_time_str})"
            else:
                return False, f"SCHEDULED_AT_{target_time_str}"
        else:
            return False, "ALREADY_COMPLETED_TODAY"

    # 2. Daily Time-of-day Jobs (e.g. backup)
    if "time" in j_cfg:
        target_time_str = j_cfg["time"]
        sched_time = parse_time_string(target_time_str)
        now_time = now.time()

        if job_state and job_state.last_completed_at:
            if job_state.last_completed_at.date() == now.date():
                return False, "ALREADY_COMPLETED_TODAY"

        if now_time >= sched_time:
            return True, f"DUE_DAILY_TIME ({target_time_str})"
        return False, f"SCHEDULED_AT_{target_time_str}"

    # 3. Interval-based Jobs
    interval_mins = j_cfg.get("interval_minutes", 60)
    if not job_state or not job_state.last_completed_at:
        return True, "INITIAL_RUN"

    elapsed = now - job_state.last_completed_at
    if elapsed >= timedelta(minutes=interval_mins):
        return True, f"INTERVAL_ELAPSED ({int(elapsed.total_seconds() / 60)}m >= {interval_mins}m)"

    remaining = int((timedelta(minutes=interval_mins) - elapsed).total_seconds() / 60)
    return False, f"NEXT_IN_{remaining}m"


def execute_job(
    job_name: str,
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Executes a single runtime job with process lock, error isolation, and metrics tracking.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    if job_name not in JOB_RUNNERS:
        return {"job_name": job_name, "status": "failed", "error": "Unknown job name"}

    runner_fn = JOB_RUNNERS[job_name]

    if dry_run:
        is_due, reason = is_job_due(job_name, db, now, config)
        return {"job_name": job_name, "status": "dry_run", "is_due": is_due, "reason": reason}

    logger.info(f"Starting job: {job_name}...")
    run_rec = start_job_run(job_name, db, now)

    try:
        with JobLock(job_name):
            res = runner_fn(db, dry_run=False, now=now)
            items_count = res.get("events_ingested", res.get("total_items", res.get("active_inbox_items", res.get("clusters_count", 0))))
            finish_job_run(run_rec, status="completed", items_processed=items_count, db=db, now=datetime.now(timezone.utc))
            logger.info(f"Job '{job_name}' completed successfully in {run_rec.duration_seconds}s.")
            return {"job_name": job_name, "status": "completed", "duration_seconds": run_rec.duration_seconds, "result": res}
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Job '{job_name}' failed with error: {err_msg}", exc_info=True)
        finish_job_run(run_rec, status="failed", items_processed=0, error_summary=err_msg, db=db, now=datetime.now(timezone.utc))
        return {"job_name": job_name, "status": "failed", "error": err_msg}


def run_all_due_jobs(
    db: Database,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Evaluates and executes all due jobs in strict dependency order."""
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    results = []
    for j_name in JOB_DEPENDENCIES_ORDER:
        is_due, reason = is_job_due(j_name, db, now, config)
        if is_due:
            res = execute_job(j_name, db, dry_run=dry_run, now=now, config=config)
            res["reason"] = reason
            results.append(res)
        else:
            results.append({"job_name": j_name, "status": "skipped", "reason": reason})

    if not dry_run:
        write_heartbeat(status="running")

    return results
