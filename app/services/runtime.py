from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime.health import check_system_health
from app.runtime.locks import SingleInstanceLock
from app.runtime.sanitization import sanitize_error, sanitize_error_category, sanitize_error_summary
from app.runtime.scheduler import (
    JOB_DEPENDENCIES_ORDER,
    is_job_due,
)
from app.runtime.timezone import (
    get_effective_timezone,
    runtime_date_string,
    to_runtime_local,
)
from app.runtime.state import (
    is_heartbeat_alive,
    is_source_due,
    load_runtime_config,
    read_heartbeat,
)
from app.services.schemas import (
    BriefingFreshnessInfo,
    CurrentSourceIssueRecord,
    IntelligenceFreshnessRecord,
    JobOperationalRecord,
    JobSummaryCounts,
    RecentJobFailureRecord,
    RuntimeDaemonInfo,
    RuntimeOverviewResponse,
    RuntimeSystemDiagnostics,
    SourceOperationalRecord,
    SourceSummaryCounts,
)
from app.storage.db import Database


def get_runtime_overview(
    db: Optional[Database] = None,
    now: Optional[datetime] = None,
) -> RuntimeOverviewResponse:
    """
    Constructs the complete aggregated runtime operational overview in a single call.
    Uses batch database retrievals (<= 6 queries total) and applies read-boundary sanitization.
    """
    if db is None:
        db = Database()

    config = load_runtime_config()
    if now is None:
        now = datetime.now(timezone.utc)

    # 1. Resolve Timezone
    eff_tz, tz_name, tz_warning = get_effective_timezone(config)
    now_local = to_runtime_local(now, config)
    scheduler_time_str = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")

    # 2. Daemon & Heartbeat Info
    hb_alive, hb_data = is_heartbeat_alive()
    lock_info = SingleInstanceLock().get_lock_info()
    lock_present = lock_info is not None

    pid: Optional[int] = None
    hb_ts_str: Optional[str] = None
    hb_age_sec: Optional[int] = None
    is_stale = False
    disagreement_notice: Optional[str] = None

    if hb_data:
        pid = hb_data.get("pid")
        hb_ts_str = hb_data.get("timestamp")
        hb_age_sec = hb_data.get("age_seconds")
        if hb_age_sec is None and hb_ts_str:
            try:
                hb_dt = datetime.fromisoformat(hb_ts_str)
                hb_age_sec = max(0, int((now - hb_dt).total_seconds()))
            except Exception:
                pass

    if hb_alive:
        daemon_status = "running"
        is_stale = False
    elif lock_present and not hb_alive:
        daemon_status = "stale"
        is_stale = True
        pid = lock_info.get("pid") if lock_info else pid
        disagreement_notice = "Lock file present but heartbeat timestamp is expired or dead."
    elif lock_present and not hb_data:
        daemon_status = "disagreement"
        pid = lock_info.get("pid") if lock_info else None
        disagreement_notice = "Lock file exists but no heartbeat file found."
    elif hb_data:
        # Heartbeat exists on disk but process is not alive or expired
        hb_stat = hb_data.get("status")
        if hb_stat == "malformed":
            daemon_status = "unknown"
            is_stale = True
            disagreement_notice = "Heartbeat timestamp is malformed or invalid."
        elif hb_stat == "stale" or (hb_age_sec is not None and hb_age_sec > 180):
            daemon_status = "stale"
            is_stale = True
        else:
            daemon_status = "stopped"
            is_stale = True
    else:
        daemon_status = "stopped"
        is_stale = False

    daemon_info = RuntimeDaemonInfo(
        status=daemon_status,
        pid=pid,
        heartbeat_timestamp=hb_ts_str,
        heartbeat_age_seconds=hb_age_sec,
        is_stale=is_stale,
        lock_present=lock_present,
        disagreement_notice=disagreement_notice,
    )

    # 3. Batch Database Queries with partial failure isolation
    checkpoints_map: Dict[str, Any] = {}
    jobs_map: Dict[str, Any] = {}
    recent_runs: List[Any] = []
    lifetime_metrics: Dict[str, Any] = {}
    active_projects_count = 0
    latest_briefing = None
    query_failures: List[str] = []

    try:
        checkpoints_map = db.get_all_source_checkpoints_map()
    except Exception as e:
        query_failures.append(f"Source checkpoints query failed: {e}")

    try:
        jobs_map = db.get_all_runtime_jobs_map()
    except Exception as e:
        query_failures.append(f"Runtime jobs query failed: {e}")

    try:
        recent_runs = db.get_recent_runtime_job_runs(limit=100)
    except Exception as e:
        query_failures.append(f"Job runs query failed: {e}")

    try:
        lifetime_metrics = db.get_runtime_metrics()
    except Exception as e:
        query_failures.append(f"Lifetime metrics query failed: {e}")

    try:
        active_projects_count = db.get_active_project_count()
    except Exception as e:
        query_failures.append(f"Projects query failed: {e}")

    try:
        latest_briefing = db.get_latest_daily_briefing()
    except Exception as e:
        query_failures.append(f"Daily briefing query failed: {e}")

    # 4. System Diagnostics (via cached probe, passing batch checkpoints)
    try:
        sys_health = check_system_health(db, config=config, now=now, use_cache=True, checkpoints_map=checkpoints_map)
    except Exception as e:
        query_failures.append(f"System health probe failed: {e}")
        sys_health = {
            "status": "DEGRADED",
            "database": "error",
            "network": "offline",
            "disk_status": "error",
            "issues": [f"Health probe error: {e}"],
            "warnings": [],
        }

    system_diag = RuntimeSystemDiagnostics(
        database=sys_health.get("database", "ok"),
        network=sys_health.get("network", "offline"),
        disk_free_mb=sys_health.get("disk_free_mb"),
        disk_status=sys_health.get("disk_status", "ok"),
        embedding_model=sys_health.get("embedding_model", "cached"),
        reference_folder=sys_health.get("reference_folder", "accessible"),
        observed_at=sys_health.get("observed_at", now.isoformat()),
        cache_age_seconds=sys_health.get("cache_age_seconds", 0.0),
        is_cached=sys_health.get("is_cached", False),
    )

    # 5. Sources Operational Records & Counts
    sources_cfg = config.get("sources", {})
    all_source_names = list(sources_cfg.keys())
    # Also include any checkpointed sources that might not be in config
    for src in checkpoints_map.keys():
        if src not in all_source_names:
            all_source_names.append(src)

    source_records: List[SourceOperationalRecord] = []
    src_counts = SourceSummaryCounts()
    current_source_issues: List[CurrentSourceIssueRecord] = []

    for src in sorted(all_source_names):
        s_cfg = sources_cfg.get(src, {})
        enabled = s_cfg.get("enabled", True)
        interval_mins = s_cfg.get("interval_minutes", 60)
        max_fails = s_cfg.get("max_consecutive_failures", 5)

        cp = checkpoints_map.get(src)
        due, due_reason = is_source_due(src, db=None, now=now, config=config, checkpoint=cp)

        if not enabled:
            health_status = "disabled"
        elif not cp:
            health_status = "unknown"
        else:
            health_status = cp.health_status or "unknown"

        # Apply sanitization to error fields at read boundary
        sanitized_err = None
        err_cat = None
        consecutive_failures = None
        failure_threshold_reached = False
        next_retry_str = None
        backoff_sec = None

        if cp:
            consecutive_failures = cp.consecutive_failures
            if cp.last_error:
                err_cat, sanitized_err = sanitize_error(cp.last_error)
            elif cp.last_error_category:
                err_cat = cp.last_error_category

            if cp.next_retry_at:
                next_retry_str = cp.next_retry_at.isoformat()
                if cp.next_retry_at > now:
                    backoff_sec = int((cp.next_retry_at - now).total_seconds())

            failure_threshold_reached = bool(
                consecutive_failures is not None and consecutive_failures >= max_fails
            )

        rec = SourceOperationalRecord(
            source=src,
            enabled=enabled,
            health_status=health_status,
            last_attempt_at=cp.last_attempt_at.isoformat() if cp and cp.last_attempt_at else None,
            last_success_at=cp.last_success_at.isoformat() if cp and cp.last_success_at else None,
            last_event_time=cp.last_event_time.isoformat() if cp and cp.last_event_time else None,
            consecutive_failures=consecutive_failures,
            failure_threshold_reached=failure_threshold_reached,
            max_consecutive_failures=max_fails,
            next_retry_at=next_retry_str,
            backoff_seconds=backoff_sec,
            is_due=due,
            due_reason=due_reason,
            interval_minutes=interval_mins,
            error_category=err_cat,
            sanitized_error=sanitized_err,
        )
        source_records.append(rec)

        # Summary counts
        src_counts.total += 1
        if health_status == "healthy":
            src_counts.healthy += 1
        elif health_status == "retrying":
            src_counts.retrying += 1
        elif health_status == "rate_limited":
            src_counts.rate_limited += 1
        elif health_status == "degraded":
            src_counts.degraded += 1
        elif health_status == "disabled":
            src_counts.disabled += 1
        elif health_status == "unavailable":
            src_counts.unavailable += 1
        else:
            src_counts.unknown += 1

        # Current issues
        if health_status in ("degraded", "retrying", "rate_limited", "unavailable") and cp:
            current_source_issues.append(
                CurrentSourceIssueRecord(
                    source=src,
                    health_status=health_status,
                    consecutive_failures=cp.consecutive_failures or 0,
                    last_attempt_at=cp.last_attempt_at.isoformat() if cp.last_attempt_at else None,
                    next_retry_at=next_retry_str,
                    error_category=err_cat,
                    sanitized_error=sanitized_err,
                )
            )

    # 6. Jobs Operational Records & Counts
    job_records: List[JobOperationalRecord] = []
    job_counts = JobSummaryCounts()

    for j_name in JOB_DEPENDENCIES_ORDER:
        j_cfg = config.get("jobs", {}).get(j_name, {})
        timeout_mins = j_cfg.get("timeout_minutes")
        j_state = jobs_map.get(j_name)
        due, due_reason = is_job_due(
            j_name,
            db=None,
            now=now,
            config=config,
            cached_job=j_state,
            active_projects_count=active_projects_count,
            cached_briefing=latest_briefing,
        )

        last_st = j_state.last_status if j_state else "pending"
        eval_st = j_state.evaluation_status if j_state and j_state.evaluation_status else (
            "not_applicable" if "NOT_APPLICABLE" in due_reason else (
                "due" if due else (
                    "blocked" if j_state and j_state.blocked_by else "not_due"
                )
            )
        )

        # Operational status for badging: running > blocked > not_applicable > last execution status
        if last_st == "running":
            op_status = "running"
        elif eval_st == "blocked":
            op_status = "blocked"
        elif eval_st == "not_applicable":
            op_status = "not_applicable"
        else:
            op_status = last_st

        j_err_cat = None
        j_sanitized_err = None
        if j_state and j_state.last_error:
            j_err_cat, j_sanitized_err = sanitize_error(j_state.last_error)
        elif j_state and j_state.last_error_category:
            j_err_cat = j_state.last_error_category

        j_rec = JobOperationalRecord(
            job_name=j_name,
            status=op_status,
            last_status=last_st,
            evaluation_status=eval_st,
            evaluated_at=j_state.evaluated_at.isoformat() if j_state and j_state.evaluated_at else None,
            last_started_at=j_state.last_started_at.isoformat() if j_state and j_state.last_started_at else None,
            last_completed_at=j_state.last_completed_at.isoformat() if j_state and j_state.last_completed_at else None,
            duration_seconds=j_state.duration_seconds if j_state else None,
            run_count=j_state.run_count if j_state else None,
            failure_count=j_state.failure_count if j_state else None,
            is_due=due,
            next_schedule=due_reason,
            configured_timeout_minutes=timeout_mins,
            timeout_enforced=False,
            blocked_by=j_state.blocked_by if j_state else None,
            blocked_reason=j_state.blocked_reason if j_state else None,
            error_category=j_err_cat,
            sanitized_error=j_sanitized_err,
        )
        job_records.append(j_rec)

        job_counts.total += 1
        if op_status == "completed":
            job_counts.completed += 1
        elif op_status == "running":
            job_counts.running += 1
        elif op_status == "failed":
            job_counts.failed += 1
        elif op_status == "partial":
            job_counts.partial += 1
        elif op_status == "interrupted":
            job_counts.interrupted += 1
        elif op_status == "blocked":
            job_counts.blocked += 1
        elif op_status in ("not_due", "skipped"):
            job_counts.not_due += 1
        elif op_status == "not_applicable":
            job_counts.not_applicable += 1
        else:
            job_counts.pending += 1

    # 7. Recent Failures / Issues (sanitized)
    recent_failures: List[RecentJobFailureRecord] = []
    for r in recent_runs:
        if r.status in ("failed", "partial", "interrupted"):
            rf_cat, rf_err = sanitize_error(r.error_summary) if r.error_summary else (r.error_category, None)
            recent_failures.append(
                RecentJobFailureRecord(
                    run_id=r.id,
                    job_name=r.job_name,
                    started_at=r.started_at.isoformat(),
                    completed_at=r.completed_at.isoformat() if r.completed_at else None,
                    status=r.status,
                    items_processed=r.items_processed,
                    duration_seconds=r.duration_seconds,
                    error_category=rf_cat or r.error_category,
                    sanitized_error=rf_err,
                )
            )
        if len(recent_failures) >= 20:
            break

    # 8. Intelligence Freshness
    last_ingest_cp = max(
        [cp.last_success_at for cp in checkpoints_map.values() if cp.last_success_at],
        default=None,
    )
    last_ingestion_str = last_ingest_cp.isoformat() if last_ingest_cp else None

    today_str = runtime_date_string(now, config)
    today_briefing = latest_briefing if (latest_briefing and latest_briefing.briefing_date == today_str) else None

    briefing_info = BriefingFreshnessInfo(
        date=today_str,
        generated=today_briefing is not None,
        total_items=today_briefing.total_items if today_briefing else None,
        high_priority_count=today_briefing.high_priority_count if today_briefing else None,
        project_relevant_count=today_briefing.project_relevant_count if today_briefing else None,
        generated_at=today_briefing.generated_at.isoformat() if today_briefing else None,
        markdown_path=getattr(today_briefing, "markdown_path", None) if today_briefing else None,
    )

    intelligence_freshness = IntelligenceFreshnessRecord(
        last_successful_ingestion=last_ingestion_str,
        today_briefing=briefing_info,
    )

    # 9. Aggregate Issues, Warnings & Partial Availability
    warnings = list(sys_health.get("warnings", []))
    issues = list(sys_health.get("issues", []))

    for qf in query_failures:
        issues.append(qf)

    if tz_warning:
        warnings.append(tz_warning)

    is_partial_availability = False
    if query_failures:
        is_partial_availability = True

    if src_counts.total == 0:
        warnings.append("No source adapters configured or active.")
    if job_counts.total == 0:
        warnings.append("No runtime jobs scheduled.")

    if src_counts.degraded > 0 or src_counts.rate_limited > 0 or src_counts.retrying > 0:
        is_partial_availability = True
        warnings.append(f"{src_counts.degraded + src_counts.rate_limited + src_counts.retrying} source(s) experiencing retries or degradation")

    if job_counts.failed > 0 or job_counts.interrupted > 0 or job_counts.partial > 0:
        is_partial_availability = True

    overall_status = sys_health.get("status", "HEALTHY")
    if sys_health.get("database") != "ok" or any("integrity" in iss.lower() for iss in issues):
        overall_status = "UNHEALTHY"
    elif overall_status == "HEALTHY":
        if src_counts.total == 0 or job_counts.total == 0:
            overall_status = "UNKNOWN"
        elif is_partial_availability or daemon_status in ("stale", "stopped", "disagreement", "unknown"):
            overall_status = "DEGRADED"

    return RuntimeOverviewResponse(
        schema_version="v1",
        status=overall_status,
        observed_at=now.isoformat(),
        effective_timezone=tz_name,
        scheduler_time=scheduler_time_str,
        timezone_warning=tz_warning,
        daemon=daemon_info,
        system=system_diag,
        sources=source_records,
        source_summary=src_counts,
        jobs=job_records,
        job_summary=job_counts,
        recent_failures=recent_failures,
        current_source_issues=current_source_issues,
        intelligence_freshness=intelligence_freshness,
        lifetime_metrics=lifetime_metrics,
        warnings=warnings,
        issues=issues,
        is_partial_availability=is_partial_availability,
    )


def get_runtime_status(db: Optional[Database] = None) -> Dict[str, Any]:
    """Compatibility wrapper returning dict from the canonical get_runtime_overview."""
    overview = get_runtime_overview(db)
    return overview.model_dump()


def get_source_health(db: Optional[Database] = None) -> List[Dict[str, Any]]:
    """Retrieves sanitized source checkpoints and health statuses."""
    overview = get_runtime_overview(db)
    return [s.model_dump() for s in overview.sources]


def get_recent_job_failures(
    limit: int = 10,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recent failed runtime job executions."""
    overview = get_runtime_overview(db)
    return [f.model_dump() for f in overview.recent_failures[:limit]]


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
        "database_path": str(db.db_path),  # Expose for test isolation verification
        "network": h["network"],
        "disk_free_mb": h["disk_free_mb"],
        "daemon_running": h["daemon_running"],
        "timestamp": h["timestamp"],
    }
