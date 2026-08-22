import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

from app.runtime.jobs import (
    generate_scheduled_morning_briefing,
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
from app.models.schemas import DailyBriefing, RuntimeJob
from app.runtime.locks import JobLock
from app.runtime.state import (
    finish_job_run,
    load_runtime_config,
    start_job_run,
    write_heartbeat,
)
from app.storage.db import Database


logger = logging.getLogger("hermes.scheduler")

# Canonical Topologically Ordered Execution List
JOB_DEPENDENCIES_ORDER = [
    "health_check",
    "ingestion",
    "semantic",
    "claims",
    "recheck",
    "context_scan",
    "context_match",
    "inbox_refresh",
    "morning_brief",
    "inbox_cleanup",
    "backup",
]

# Explicit Prerequisite Graph
JOB_DEPENDENCY_GRAPH = {
    "health_check": [],
    "ingestion": [],
    "semantic": ["ingestion"],
    "claims": ["semantic"],
    "recheck": ["claims"],
    "context_scan": [],
    "context_match": ["semantic", "context_scan"],
    "inbox_refresh": ["claims", "context_match"],
    "morning_brief": ["inbox_refresh"],
    "inbox_cleanup": [],
    "backup": [],
}

JOB_RUNNERS = {
    "ingestion": run_source_ingestion,
    "semantic": run_semantic_processing,
    "claims": run_claims_processing,
    "recheck": run_longitudinal_recheck,
    "context_scan": run_context_scan,
    "context_match": run_context_match,
    "inbox_refresh": run_inbox_generation,
    "inbox_cleanup": run_inbox_cleanup,
    "morning_brief": generate_scheduled_morning_briefing,
    "backup": run_daily_backup,
    "health_check": run_health_check_job,
}


def parse_time_string(t_str: str) -> dtime:
    """Parses 'HH:MM' string into a datetime.time object."""
    parts = t_str.strip().split(":")
    return dtime(hour=int(parts[0]), minute=int(parts[1]))


def get_effective_timezone(config: Optional[Dict[str, Any]] = None) -> Tuple[timezone, str, Optional[str]]:
    """
    Resolves the effective timezone for scheduling and calendar operations.
    Returns: (tzinfo_obj, tz_name, optional_warning)
    """
    if config is None:
        config = load_runtime_config()

    tz_str = config.get("timezone", "local")
    if not tz_str or tz_str.lower() in ("local", "auto"):
        local_tz = datetime.now().astimezone().tzinfo
        tz_name = getattr(local_tz, "key", None) or getattr(local_tz, "zone", None)
        if not tz_name:
            warning = "System local timezone is a fixed offset without IANA identity; consider setting an explicit IANA timezone in config/runtime.yaml."
            return local_tz or timezone.utc, "local", warning
        return local_tz, str(tz_name), None

    try:
        zi = zoneinfo.ZoneInfo(tz_str)
        return zi, tz_str, None
    except Exception:
        warning = f"Invalid timezone '{tz_str}'; fell back to UTC."
        logger.warning(warning)
        return timezone.utc, "UTC", warning


def check_job_dependencies(
    job_name: str,
    db: Database,
    cycle_results: Dict[str, str],
    now: datetime,
    config: Dict[str, Any],
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Evaluates whether all prerequisites for a job are satisfied.
    Satisfaction conditions:
      1. Succeeded or completed partially during current scheduler cycle.
      2. Fresh prior persisted completion within max_dependency_age_minutes policy.
      3. Conditionally not applicable (e.g. context_match when active projects == 0).

    Returns: (is_satisfied, blocked_by_job, blocked_reason)
    """
    prereqs = JOB_DEPENDENCY_GRAPH.get(job_name, [])
    if not prereqs:
        return True, None, None

    active_projects_count = db.get_active_project_count()

    for prereq in prereqs:
        # Special case: context_match when no active projects exist is not_applicable
        if prereq == "context_match" and active_projects_count == 0:
            continue

        # 1. Check current scheduler cycle outcome
        if prereq in cycle_results:
            c_status = cycle_results[prereq]
            if c_status in ("completed", "partial"):
                continue  # Satisfied by current cycle
            if c_status == "failed":
                return False, prereq, f"Prerequisite '{prereq}' failed during current cycle"
            if c_status in ("blocked", "interrupted"):
                return False, prereq, f"Prerequisite '{prereq}' did not complete ({c_status}) during current cycle"

        # 2. Check persisted prior run in database
        pj = db.get_runtime_job(prereq)
        if not pj or not pj.last_completed_at:
            return False, prereq, f"Prerequisite '{prereq}' has never completed successfully"

        if pj.last_status not in ("completed", "partial"):
            return False, prereq, f"Prerequisite '{prereq}' latest recorded status is '{pj.last_status}'"

        p_cfg = config.get("jobs", {}).get(prereq, {})
        interval_mins = p_cfg.get("interval_minutes", 60)
        max_age_mins = p_cfg.get("max_dependency_age_minutes", max(120, interval_mins * 2))

        age_mins = (now - pj.last_completed_at).total_seconds() / 60
        if age_mins > max_age_mins:
            return False, prereq, f"Prerequisite '{prereq}' is stale ({int(age_mins)}m elapsed > max {max_age_mins}m)"

    return True, None, None


def is_job_due(
    job_name: str,
    db: Optional[Database] = None,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
    cached_job: Optional[RuntimeJob] = None,
    active_projects_count: Optional[int] = None,
    cached_briefing: Optional[DailyBriefing] = None,
) -> Tuple[bool, str]:
    """
    Determines if a job is due based on schedule, interval, timezone, and calendar date.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    jobs_cfg = config.get("jobs", {})
    j_cfg = jobs_cfg.get(job_name, {})
    if not j_cfg:
        return False, "NOT_CONFIGURED"

    eff_tz, tz_name, _ = get_effective_timezone(config)
    now_local = now.astimezone(eff_tz)

    job_state = cached_job if cached_job is not None else (db.get_runtime_job(job_name) if db else None)

    # 1. Special Handling: Morning Briefing
    if job_name == "morning_brief":
        target_time_str = j_cfg.get("time", "07:30")
        sched_time = parse_time_string(target_time_str)
        today_date_str = now_local.strftime("%Y-%m-%d")

        briefing = cached_briefing if (cached_briefing and cached_briefing.briefing_date == today_date_str) else (db.get_daily_briefing(today_date_str) if db else None)
        if not briefing:
            if now_local.time() >= sched_time:
                return True, f"MISSED_OR_DUE_TODAY (Scheduled: {target_time_str} {tz_name})"
            else:
                return False, f"SCHEDULED_AT_{target_time_str}"
        else:
            return False, "ALREADY_COMPLETED_TODAY"

    # 2. Daily Time-of-day Jobs (e.g. backup)
    if "time" in j_cfg:
        target_time_str = j_cfg["time"]
        sched_time = parse_time_string(target_time_str)

        if job_state and job_state.last_completed_at:
            last_local_date = job_state.last_completed_at.astimezone(eff_tz).date()
            if last_local_date == now_local.date():
                return False, "ALREADY_COMPLETED_TODAY"

        if now_local.time() >= sched_time:
            return True, f"DUE_DAILY_TIME ({target_time_str} {tz_name})"
        return False, f"SCHEDULED_AT_{target_time_str}"

    # 3. Context Match with zero active projects
    proj_cnt = active_projects_count if active_projects_count is not None else (db.get_active_project_count() if db else 0)
    if job_name == "context_match" and proj_cnt == 0:
        return False, "NOT_APPLICABLE (No active projects configured)"

    # 4. Interval-based Jobs
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

    # If context_match has no projects, handle cleanly as not_applicable
    if job_name == "context_match" and db.get_active_project_count() == 0:
        return {"job_name": job_name, "status": "not_applicable", "reason": "No active projects configured"}

    logger.info(f"Starting job: {job_name}...")
    run_rec = start_job_run(job_name, db, now)

    try:
        with JobLock(job_name):
            res = runner_fn(db, dry_run=False, now=now)
            runner_status = res.get("status", "completed")
            items_count = res.get("events_ingested", res.get("total_items", res.get("active_inbox_items", res.get("clusters_count", 0))))

            if runner_status in ("export_failed", "failed"):
                err = res.get("error", "Runner reported failure status")
                finish_job_run(run_rec, status="failed", items_processed=items_count, error_summary=err, db=db, now=datetime.now(timezone.utc))
                return {"job_name": job_name, "status": "failed", "duration_seconds": run_rec.duration_seconds, "error": err, "result": res}
            elif runner_status == "partial":
                finish_job_run(run_rec, status="partial", items_processed=items_count, db=db, now=datetime.now(timezone.utc))
                return {"job_name": job_name, "status": "partial", "duration_seconds": run_rec.duration_seconds, "result": res}
            elif runner_status == "not_applicable":
                finish_job_run(run_rec, status="not_applicable", items_processed=0, db=db, now=datetime.now(timezone.utc))
                return {"job_name": job_name, "status": "not_applicable", "duration_seconds": run_rec.duration_seconds, "result": res}
            else:
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
    """Evaluates and executes all due jobs in strict dependency order with prerequisite satisfaction checks."""
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    results = []
    cycle_results: Dict[str, str] = {}

    for j_name in JOB_DEPENDENCIES_ORDER:
        is_due, reason = is_job_due(j_name, db, now, config)
        if not is_due:
            cycle_results[j_name] = "not_due"
            results.append({"job_name": j_name, "status": "skipped", "reason": reason})
            continue

        # Check dependencies before starting execution
        deps_ok, blocked_by, blocked_reason = check_job_dependencies(j_name, db, cycle_results, now, config)
        if not deps_ok:
            logger.warning(f"Job '{j_name}' blocked by prerequisite '{blocked_by}': {blocked_reason}")
            cycle_results[j_name] = "blocked"

            # Update runtime_jobs state without creating a fake execution run record
            job_rec = db.get_runtime_job(j_name)
            if not job_rec:
                job_rec = RuntimeJob(
                    job_name=j_name,
                    last_status="blocked",
                    blocked_by=blocked_by,
                    blocked_reason=blocked_reason,
                    updated_at=now,
                )
            else:
                job_rec.last_status = "blocked"
                job_rec.blocked_by = blocked_by
                job_rec.blocked_reason = blocked_reason
                job_rec.updated_at = now
            db.save_runtime_job(job_rec)

            results.append({
                "job_name": j_name,
                "status": "blocked",
                "blocked_by": blocked_by,
                "reason": blocked_reason,
            })
            continue

        # Execute due job
        res = execute_job(j_name, db, dry_run=dry_run, now=now, config=config)
        res.setdefault("job_name", j_name)
        res["reason"] = reason
        cycle_results[j_name] = res.get("status", "completed")
        results.append(res)

    if not dry_run:
        write_heartbeat(status="running")

    return results
