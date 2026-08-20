from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.runtime.health import check_system_health
from app.runtime.locks import SingleInstanceLock
from app.runtime.scheduler import JOB_DEPENDENCIES_ORDER, is_job_due
from app.runtime.state import is_heartbeat_alive, is_source_due, load_runtime_config
from app.storage.db import Database


def get_runtime_status(db: Optional[Database] = None) -> Dict[str, Any]:
    """Retrieves safe runtime daemon status and job execution metrics."""
    if db is None:
        db = Database()

    config = load_runtime_config()
    now = datetime.now(timezone.utc)

    hb_alive, hb_data = is_heartbeat_alive()
    lock_info = SingleInstanceLock().get_lock_info()

    if hb_alive and hb_data:
        daemon_status = "running"
        pid = hb_data.get("pid")
    elif lock_info and not hb_alive:
        daemon_status = "stale"
        pid = lock_info.get("pid")
    else:
        daemon_status = "stopped"
        pid = None

    # Ingestion & Briefing status
    ingest_job = db.get_runtime_job("ingestion")
    last_ingestion = ingest_job.last_completed_at.isoformat() if ingest_job and ingest_job.last_completed_at else None

    today_str = now.strftime("%Y-%m-%d")
    briefing = db.get_daily_briefing(today_str)
    briefing_info = {
        "date": today_str,
        "generated": bool(briefing),
        "total_items": briefing.total_items if briefing else 0,
        "generated_at": briefing.generated_at.isoformat() if briefing else None,
    }

    # Scheduled jobs overview
    jobs_summary = []
    for j in JOB_DEPENDENCIES_ORDER:
        j_state = db.get_runtime_job(j)
        due, reason = is_job_due(j, db, now, config)
        jobs_summary.append({
            "job_name": j,
            "status": j_state.last_status if j_state else "pending",
            "run_count": j_state.run_count if j_state else 0,
            "failure_count": j_state.failure_count if j_state else 0,
            "last_completed_at": j_state.last_completed_at.isoformat() if j_state and j_state.last_completed_at else None,
            "is_due": due,
            "next_schedule": reason,
        })

    # Metrics
    metrics = db.get_runtime_metrics()

    return {
        "status": daemon_status,
        "daemon_status": daemon_status,
        "pid": pid,
        "last_ingestion_at": last_ingestion,
        "today_briefing": briefing_info,
        "jobs": jobs_summary,
        "lifetime_metrics": metrics,
        "timestamp": now.isoformat(),
    }


def get_source_health(db: Optional[Database] = None) -> List[Dict[str, Any]]:
    """Retrieves source checkpoints, health statuses, and failure logs."""
    if db is None:
        db = Database()

    config = load_runtime_config()
    now = datetime.now(timezone.utc)
    all_sources = list(config.get("sources", {}).keys())

    out = []
    for src in all_sources:
        cp = db.get_source_checkpoint(src)
        due, reason = is_source_due(src, db, now, config)
        if cp:
            out.append({
                "source": src,
                "health": cp.health_status,
                "consecutive_failures": cp.consecutive_failures,
                "last_success_at": cp.last_success_at.isoformat() if cp.last_success_at else None,
                "last_attempt_at": cp.last_attempt_at.isoformat() if cp.last_attempt_at else None,
                "next_retry_at": cp.next_retry_at.isoformat() if cp.next_retry_at else None,
                "last_error": cp.last_error,
                "is_due": due,
            })
        else:
            out.append({
                "source": src,
                "health": "unknown",
                "consecutive_failures": 0,
                "last_success_at": None,
                "last_attempt_at": None,
                "next_retry_at": None,
                "last_error": None,
                "is_due": due,
            })
    return out


def get_recent_job_failures(
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recent failed runtime job executions."""
    if db is None:
        db = Database()

    limit = max(1, min(limit, 50))
    runs = db.get_recent_runtime_job_runs(limit=100)
    failed = [r for r in runs if r.status == "failed"]

    out = []
    for f in failed[:limit]:
        out.append({
            "run_id": f.id,
            "job_name": f.job_name,
            "started_at": f.started_at.isoformat(),
            "completed_at": f.completed_at.isoformat() if f.completed_at else None,
            "duration_seconds": f.duration_seconds,
            "error_summary": f.error_summary,
        })
    return out


def get_last_briefing(db: Optional[Database] = None) -> Optional[Dict[str, Any]]:
    """Retrieves the most recent daily briefing."""
    if db is None:
        db = Database()

    cursor = db.conn.cursor()
    cursor.execute("SELECT briefing_date FROM daily_briefings ORDER BY briefing_date DESC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        return None

    from app.services.intelligence import get_morning_brief
    return get_morning_brief(row["briefing_date"], db=db)


def get_health(db: Optional[Database] = None) -> Dict[str, Any]:
    """Evaluates local system health and returns structured diagnostics."""
    if db is None:
        db = Database()

    h = check_system_health(db)
    return {
        "status": h["status"].lower(),
        "database": h["database"],
        "network": h["network"],
        "disk_free_mb": h["disk_free_mb"],
        "daemon_running": h["daemon_running"],
        "timestamp": h["timestamp"],
    }
