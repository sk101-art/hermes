import json
import os
import platform
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from app.models.schemas import RuntimeJob, RuntimeJobRun, SourceCheckpoint
from app.runtime.locks import is_pid_alive
from app.runtime.sanitization import sanitize_error
from app.storage.db import Database


DEFAULT_RUNTIME_CONFIG = {
    "timezone": "local",
    "min_free_disk_mb": 1024,
    "max_parallel_sources": 2,
    "semantic_batch_size": 16,
    "log_level": "INFO",
    "log_file": "logs/hermes.log",
    "heartbeat_file": "data/runtime_heartbeat.json",
    "lock_file": "data/hermes.lock",
    "jobs": {
        "ingestion": {"interval_minutes": 60, "timeout_minutes": 15},
        "semantic": {"interval_minutes": 60, "timeout_minutes": 15},
        "claims": {"interval_minutes": 60, "timeout_minutes": 15},
        "recheck": {"interval_minutes": 120, "timeout_minutes": 15},
        "context_scan": {"interval_minutes": 120, "timeout_minutes": 10},
        "context_match": {"interval_minutes": 60, "timeout_minutes": 10},
        "inbox_refresh": {"interval_minutes": 60, "timeout_minutes": 10},
        "inbox_cleanup": {"interval_minutes": 60, "timeout_minutes": 5},
        "morning_brief": {"time": "07:30", "timeout_minutes": 30},
        "health_check": {"interval_minutes": 15, "timeout_minutes": 2},
        "backup": {"time": "03:00", "retention_days": 7},
    },
    "sources": {
        "github": {"interval_minutes": 60, "max_consecutive_failures": 5},
        "github_releases": {"interval_minutes": 60, "max_consecutive_failures": 5},
        "arxiv": {"interval_minutes": 120, "max_consecutive_failures": 5},
        "hackernews": {"interval_minutes": 60, "max_consecutive_failures": 5},
        "huggingface": {"interval_minutes": 60, "max_consecutive_failures": 5},
        "openalex": {"interval_minutes": 180, "max_consecutive_failures": 5},
        "crossref": {"interval_minutes": 360, "max_consecutive_failures": 5},
        "stackexchange": {"interval_minutes": 120, "max_consecutive_failures": 5},
        "rss": {"interval_minutes": 60, "max_consecutive_failures": 5},
    },
}


def load_runtime_config(config_path: str = "config/runtime.yaml") -> Dict[str, Any]:
    cfg = dict(DEFAULT_RUNTIME_CONFIG)
    p = Path(config_path)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "runtime" in data:
                    rdata = data["runtime"]
                    for k, v in rdata.items():
                        if isinstance(v, dict) and k in cfg and isinstance(cfg[k], dict):
                            cfg[k].update(v)
                        else:
                            cfg[k] = v
        except Exception:
            pass
    return cfg


def is_source_due(
    source_name: str,
    db: Optional[Database] = None,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
    checkpoint: Optional[SourceCheckpoint] = None,
) -> Tuple[bool, str]:
    """
    Checks if a source is due for polling based on checkpoint, retry backoff, interval, and enabled status.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    src_cfg = config.get("sources", {}).get(source_name, {})
    if src_cfg.get("enabled", True) is False:
        return False, "CONFIG_DISABLED"

    interval_mins = src_cfg.get("interval_minutes", 60)

    cp = checkpoint if checkpoint is not None else (db.get_source_checkpoint(source_name) if db else None)
    if not cp:
        return True, "INITIAL_RUN"

    if cp.health_status == "disabled":
        return False, "DISABLED"

    # Check backoff retry time
    if cp.next_retry_at and now < cp.next_retry_at:
        remaining = int((cp.next_retry_at - now).total_seconds() / 60)
        return False, f"BACKOFF_DELAY ({remaining}m remaining)"

    # Check interval since last success
    if cp.last_success_at:
        elapsed = now - cp.last_success_at
        if elapsed < timedelta(minutes=interval_mins):
            remaining = int((timedelta(minutes=interval_mins) - elapsed).total_seconds() / 60)
            return False, f"SKIPPED_NOT_DUE ({remaining}m remaining)"

    return True, "DUE"


def record_source_success(
    source_name: str,
    db: Database,
    cursor: Optional[str] = None,
    event_time: Optional[datetime] = None,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> SourceCheckpoint:
    """Updates source checkpoint on successful fetch and persistence, resetting failure counters."""
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    src_cfg = config.get("sources", {}).get(source_name, {})
    max_fails = src_cfg.get("max_consecutive_failures", 5)

    existing = db.get_source_checkpoint(source_name)
    cp = SourceCheckpoint(
        source=source_name,
        last_success_at=now,
        last_attempt_at=now,
        last_cursor=cursor if cursor is not None else (existing.last_cursor if existing else None),
        last_event_time=event_time if event_time is not None else (existing.last_event_time if existing else None),
        last_error=None,
        last_error_category=None,
        consecutive_failures=0,
        failure_threshold_reached=False,
        max_consecutive_failures=max_fails,
        next_retry_at=None,
        health_status="healthy",
        updated_at=now,
    )
    db.save_source_checkpoint(cp)
    return cp


def record_source_failure(
    source_name: str,
    error_input: Any,
    db: Database,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
    error_category: Optional[str] = None,
) -> SourceCheckpoint:
    """Updates source checkpoint with structured sanitization and exponential backoff on failure."""
    if now is None:
        now = datetime.now(timezone.utc)
    if config is None:
        config = load_runtime_config()

    src_cfg = config.get("sources", {}).get(source_name, {})
    max_fails = src_cfg.get("max_consecutive_failures", 5)

    existing = db.get_source_checkpoint(source_name)
    fails = (existing.consecutive_failures if existing and existing.consecutive_failures is not None else 0) + 1

    # Exponential backoff: 15m, 30m, 60m, 120m, max 240m
    delay_minutes = min(240, 15 * (2 ** min(fails - 1, 4)))
    next_retry = now + timedelta(minutes=delay_minutes)

    cat, sanitized_error = sanitize_error(error_input)
    category = error_category or cat

    # Determine health_status
    if category == "rate_limit" or "429" in str(error_input) or "rate limit" in str(error_input).lower():
        health_status = "rate_limited"
    elif fails < 3:
        health_status = "retrying"
    else:
        health_status = "degraded"

    failure_threshold_reached = bool(fails >= max_fails)

    cp = SourceCheckpoint(
        source=source_name,
        last_success_at=existing.last_success_at if existing else None,
        last_attempt_at=now,
        last_cursor=existing.last_cursor if existing else None,
        last_event_time=existing.last_event_time if existing else None,
        last_error=sanitized_error,
        last_error_category=category,
        consecutive_failures=fails,
        failure_threshold_reached=failure_threshold_reached,
        max_consecutive_failures=max_fails,
        next_retry_at=next_retry,
        health_status=health_status,
        updated_at=now,
    )
    db.save_source_checkpoint(cp)
    return cp


def start_job_run(
    job_name: str,
    db: Database,
    now: Optional[datetime] = None,
) -> RuntimeJobRun:
    """Records the start of a job run and updates runtime_jobs state."""
    if now is None:
        now = datetime.now(timezone.utc)

    run_id = f"run:{job_name}:{int(now.timestamp() * 1000)}"
    run = RuntimeJobRun(
        id=run_id,
        job_name=job_name,
        started_at=now,
        status="running",
    )
    db.save_runtime_job_run(run)

    job = db.get_runtime_job(job_name)
    run_count = ((job.run_count if job and job.run_count is not None else 0) + 1)
    fail_count = job.failure_count if job and job.failure_count is not None else 0

    updated_job = RuntimeJob(
        job_name=job_name,
        last_started_at=now,
        last_completed_at=job.last_completed_at if job else None,
        last_status="running",
        evaluation_status="due",
        evaluated_at=now,
        last_error=None,
        last_error_category=None,
        duration_seconds=None,
        run_count=run_count,
        failure_count=fail_count,
        next_run_at=job.next_run_at if job else None,
        blocked_by=None,
        blocked_reason=None,
        updated_at=now,
    )
    db.save_runtime_job(updated_job)
    return run


def finish_job_run(
    run: RuntimeJobRun,
    status: str,
    items_processed: Optional[int],
    db: Database,
    error_summary: Optional[str] = None,
    next_run_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> RuntimeJobRun:
    """Completes a job run record and updates runtime_jobs metrics."""
    if now is None:
        now = datetime.now(timezone.utc)

    duration = max(0.0, (now - run.started_at).total_seconds())
    category = None
    sanitized_err = None
    if error_summary:
        category, sanitized_err = sanitize_error(error_summary)

    run.completed_at = now
    run.status = status
    run.items_processed = items_processed
    run.error_summary = sanitized_err
    run.error_category = category
    run.duration_seconds = round(duration, 2)
    db.save_runtime_job_run(run)

    job = db.get_runtime_job(run.job_name)
    run_count = job.run_count if job and job.run_count is not None else 1
    fail_count = (job.failure_count if job and job.failure_count is not None else 0) + (1 if status == "failed" else 0)

    updated_job = RuntimeJob(
        job_name=run.job_name,
        last_started_at=job.last_started_at if job else run.started_at,
        last_completed_at=now,
        last_status=status,
        evaluation_status=status,
        evaluated_at=now,
        last_error=sanitized_err,
        last_error_category=category,
        duration_seconds=round(duration, 2),
        run_count=run_count,
        failure_count=fail_count,
        next_run_at=next_run_at,
        blocked_by=None,
        blocked_reason=None,
        updated_at=now,
    )
    db.save_runtime_job(updated_job)

    if status == "completed":
        db.increment_runtime_metric("jobs_completed", 1)
    elif status == "failed":
        db.increment_runtime_metric("jobs_failed", 1)
    elif status == "partial":
        db.increment_runtime_metric("jobs_partial", 1)

    return run


def recover_interrupted_jobs(db: Database, now: Optional[datetime] = None) -> List[RuntimeJobRun]:
    """Recovers any abandoned running job runs on daemon startup."""
    if now is None:
        now = datetime.now(timezone.utc)

    running_runs = db.get_running_job_runs()
    recovered = []
    for r in running_runs:
        r.completed_at = now
        r.status = "interrupted"
        r.error_category = "runtime_error"
        r.error_summary = "Job interrupted by daemon restart or crash"
        r.duration_seconds = max(0.0, (now - r.started_at).total_seconds())
        db.save_runtime_job_run(r)

        job = db.get_runtime_job(r.job_name)
        if job and job.last_status == "running":
            job.last_status = "interrupted"
            job.last_error = "Daemon restarted while job was in progress"
            job.last_error_category = "runtime_error"
            job.last_completed_at = now
            job.updated_at = now
            db.save_runtime_job(job)

        db.increment_runtime_metric("jobs_interrupted", 1)
        recovered.append(r)
    return recovered


def write_heartbeat(
    status: str = "running",
    version: str = "0.9.0",
    heartbeat_path: str = "data/runtime_heartbeat.json",
) -> None:
    """Updates the heartbeat file with current PID and timestamp."""
    p = Path(heartbeat_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "hostname": platform.node(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "version": version,
    }
    try:
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def read_heartbeat(heartbeat_path: str = "data/runtime_heartbeat.json") -> Optional[Dict[str, Any]]:
    """Reads the heartbeat file if available."""
    p = Path(heartbeat_path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def is_heartbeat_alive(
    max_stale_seconds: int = 180,
    heartbeat_path: str = "data/runtime_heartbeat.json",
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Checks if the heartbeat is recent and the corresponding PID is alive."""
    data = read_heartbeat(heartbeat_path)
    if not data:
        return False, None

    pid = data.get("pid")
    ts_str = data.get("timestamp")
    if not pid or not ts_str:
        data["status"] = "malformed"
        data["is_stale"] = True
        return False, data

    if not is_pid_alive(pid):
        data["status"] = "stopped"
        data["is_stale"] = True
        return False, data

    try:
        hb_time = datetime.fromisoformat(ts_str)
        now = datetime.now(timezone.utc)
        age = max(0.0, (now - hb_time).total_seconds())
        data["age_seconds"] = int(age)
        if age <= max_stale_seconds:
            data["status"] = "running"
            data["is_stale"] = False
            return True, data
        data["status"] = "stale"
        data["is_stale"] = True
        return False, data
    except Exception:
        data["status"] = "malformed"
        data["is_stale"] = True
        return False, data
