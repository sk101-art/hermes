import json
import os
import sqlite3
import tempfile
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import (
    DailyBriefing,
    Project,
    RuntimeJob,
    RuntimeJobRun,
    SourceCheckpoint,
)
from app.runtime.health import (
    check_network_connectivity,
    check_system_health,
    invalidate_health_cache,
)
from app.runtime.jobs import (
    generate_scheduled_morning_briefing,
    run_context_match,
    run_morning_pipeline_orchestration,
    run_source_ingestion,
)
from app.runtime.sanitization import (
    classify_error_category,
    sanitize_error,
    sanitize_error_category,
    sanitize_error_summary,
)
from app.runtime.scheduler import (
    check_job_dependencies,
    execute_job,
    get_effective_timezone,
    is_job_due,
    run_all_due_jobs,
)
from app.runtime.state import (
    finish_job_run,
    is_source_due,
    record_source_failure,
    record_source_success,
    recover_interrupted_jobs,
    start_job_run,
)
from app.services.runtime import get_runtime_overview
from app.storage.db import Database


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    invalidate_health_cache(path)
    yield db
    db.close()
    invalidate_health_cache(path)
    if os.path.exists(path):
        os.remove(path)


# =========================================================================
# 1. Error Sanitization & Redaction Adversarial Tests
# =========================================================================

def test_sanitization_redacts_bearer_and_secrets():
    err = "HTTP 401 Unauthorized for Authorization: Bearer secret_token_123456789abcdef"
    cat, clean = sanitize_error(err)
    assert cat == "auth_error"
    assert "secret_token_123456789abcdef" not in clean
    assert "[REDACTED]" in clean

    err_param = "Failed calling https://api.example.com/v1?api_key=sk-proj-999888777&mode=fast"
    cat, clean_param = sanitize_error(err_param)
    assert "sk-proj-999888777" not in clean_param
    assert "api_key=[REDACTED]" in clean_param


def test_sanitization_redacts_url_credentials_and_local_paths():
    err_url = "Failed connecting to https://user:super_secret_pw@internal.service.com/data"
    cat, clean_url = sanitize_error(err_url)
    assert "super_secret_pw" not in clean_url
    assert "https://[REDACTED]@" in clean_url

    win_path_err = r"FileNotFoundError: Cannot open C:\Users\john_doe\Documents\secret_intel\data.json"
    cat, clean_win = sanitize_error(win_path_err)
    assert "john_doe" not in clean_win
    assert "[LOCAL_PATH]" in clean_win

    unix_path_err = "IOError: /home/admin_user/.secrets/api.pem not found"
    cat, clean_unix = sanitize_error(unix_path_err)
    assert "admin_user" not in clean_unix
    assert "[LOCAL_PATH]" in clean_unix


def test_sanitization_truncates_multiline_tracebacks():
    multiline = """
Traceback (most recent call last):
  File "C:\\Users\\dev\\app.py", line 42, in fetch
    raise ConnectionResetError("Connection refused by host 10.0.0.1")
ConnectionResetError: Connection refused by host 10.0.0.1
"""
    cat, clean = sanitize_error(multiline)
    assert cat == "network_error"
    assert "\n" not in clean
    assert "dev" not in clean
    assert "Connection refused by host" in clean


# =========================================================================
# 2. Source Operational State Transitions & Max Consecutive Failures
# =========================================================================

def test_source_lifecycle_transitions(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "sources": {
            "github": {"interval_minutes": 60, "max_consecutive_failures": 3, "enabled": True}
        }
    }

    # 1. Unattempted -> unknown
    is_due, reason = is_source_due("github", temp_db, now=now, config=config)
    assert is_due is True
    assert reason == "INITIAL_RUN"

    # 2. Success with 0 events -> healthy
    cp = record_source_success("github", temp_db, now=now)
    assert cp.health_status == "healthy"
    assert cp.consecutive_failures == 0
    assert cp.failure_threshold_reached is False

    # Check is_due immediately after success
    is_due, reason = is_source_due("github", temp_db, now=now + timedelta(minutes=10), config=config)
    assert is_due is False
    assert "SKIPPED_NOT_DUE" in reason

    # 3. 1st failure -> retrying with 15m backoff
    now_f1 = now + timedelta(minutes=61)
    cp_f1 = record_source_failure("github", "Temporary socket timeout", temp_db, now=now_f1, config=config)
    assert cp_f1.health_status == "retrying"
    assert cp_f1.consecutive_failures == 1
    assert cp_f1.failure_threshold_reached is False
    assert cp_f1.next_retry_at == now_f1 + timedelta(minutes=15)

    # In backoff window -> not due
    is_due, reason = is_source_due("github", temp_db, now=now_f1 + timedelta(minutes=5), config=config)
    assert is_due is False
    assert "BACKOFF_DELAY" in reason

    # 4. HTTP 429 -> rate_limited
    now_f2 = now_f1 + timedelta(minutes=16)
    cp_f2 = record_source_failure("github", "HTTP 429 Too Many Requests: Rate limit exceeded", temp_db, now=now_f2, config=config)
    assert cp_f2.health_status == "rate_limited"
    assert cp_f2.consecutive_failures == 2
    assert cp_f2.last_error_category == "rate_limit"

    # 5. 3rd failure reaches max_consecutive_failures threshold -> degraded with threshold flag
    now_f3 = now_f2 + timedelta(minutes=31)
    cp_f3 = record_source_failure("github", "500 Server Error", temp_db, now=now_f3, config=config)
    assert cp_f3.health_status == "degraded"
    assert cp_f3.consecutive_failures == 3
    assert cp_f3.failure_threshold_reached is True

    # 6. Continues retrying past threshold, capped at max 240m backoff
    now_f4 = now_f3 + timedelta(minutes=61)
    cp_f4 = record_source_failure("github", "500 Server Error", temp_db, now=now_f4, config=config)
    assert cp_f4.health_status == "degraded"
    assert cp_f4.consecutive_failures == 4
    assert cp_f4.failure_threshold_reached is True
    # Backoff for fail 4 is 15 * 2^3 = 120m
    assert cp_f4.next_retry_at == now_f4 + timedelta(minutes=120)

    # 7. Successful recovery resets failure counter and threshold
    now_rec = now_f4 + timedelta(minutes=125)
    cp_rec = record_source_success("github", temp_db, now=now_rec)
    assert cp_rec.health_status == "healthy"
    assert cp_rec.consecutive_failures == 0
    assert cp_rec.failure_threshold_reached is False
    assert cp_rec.last_error is None


# =========================================================================
# 3. Disabled Adapters & Constructor Spy Tests
# =========================================================================

def test_disabled_adapter_constructor_never_called(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "sources": {
            "github": {"interval_minutes": 60, "enabled": False},
            "arxiv": {"interval_minutes": 60, "enabled": True},
        }
    }

    mock_github_cls = MagicMock()
    mock_arxiv_cls = MagicMock()
    mock_arxiv_inst = MagicMock()
    mock_arxiv_inst.fetch.return_value = []
    mock_arxiv_cls.return_value = mock_arxiv_inst

    with patch("app.runtime.jobs.load_runtime_config", return_value=config), \
         patch("app.runtime.state.load_runtime_config", return_value=config), \
         patch("app.runtime.jobs._get_adapter_factories", return_value={
             "github": (lambda: mock_github_cls(), 30),
             "arxiv": (lambda: mock_arxiv_cls(), 30),
         }):

        res = run_source_ingestion(temp_db, now=now)

        # GitHub is disabled -> constructor NEVER called!
        mock_github_cls.assert_not_called()

        # Arxiv is enabled -> constructor called
        mock_arxiv_cls.assert_called_once()
        assert any(s["source"] == "github" and s["reason"] == "CONFIG_DISABLED" for s in res["sources_skipped"])


# =========================================================================
# 4. Runner Outcomes, Partial Outcomes, and Interrupted Job Recovery
# =========================================================================

def test_ingestion_partial_and_failed_status_mapping(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "sources": {
            "s1": {"interval_minutes": 60, "enabled": True},
            "s2": {"interval_minutes": 60, "enabled": True},
        }
    }

    with patch("app.runtime.jobs.load_runtime_config", return_value=config), \
         patch("app.runtime.state.load_runtime_config", return_value=config):

        # Factory where s1 succeeds (0 events) and s2 raises error
        mock_s1 = MagicMock()
        mock_s1.fetch.return_value = []
        mock_s2 = MagicMock()
        mock_s2.fetch.side_effect = ConnectionError("Network down")

        with patch("app.runtime.jobs._get_adapter_factories", return_value={
            "s1": (lambda: mock_s1, 10),
            "s2": (lambda: mock_s2, 10),
        }):
            res = run_source_ingestion(temp_db, now=now)
            assert res["status"] == "partial"
            assert len(res["sources_polled"]) == 1
            assert len(res["sources_failed"]) == 1

            # Execute via scheduler to verify runtime metric and job run status
            with patch("app.runtime.scheduler.load_runtime_config", return_value={"jobs": {"ingestion": {"interval_minutes": 60}}}):
                with patch("app.runtime.scheduler.JOB_RUNNERS", {"ingestion": lambda db, **kwargs: res}):
                    exec_res = execute_job("ingestion", temp_db, now=now)
                    assert exec_res["status"] == "partial"

                    # Verify metric jobs_partial was incremented
                    metrics = temp_db.get_runtime_metrics()
                    assert metrics.get("jobs_partial") == 1


def test_interrupted_jobs_recovered_on_startup(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    # Simulate an abandoned running job run
    abandoned_run = RuntimeJobRun(
        id="run:semantic:100",
        job_name="semantic",
        started_at=now - timedelta(minutes=10),
        status="running",
    )
    temp_db.save_runtime_job_run(abandoned_run)

    job_rec = RuntimeJob(
        job_name="semantic",
        last_started_at=now - timedelta(minutes=10),
        last_status="running",
        updated_at=now - timedelta(minutes=10),
    )
    temp_db.save_runtime_job(job_rec)

    # Recover interrupted jobs
    recovered = recover_interrupted_jobs(temp_db, now=now)
    assert len(recovered) == 1
    assert recovered[0].id == "run:semantic:100"
    assert recovered[0].status == "interrupted"
    assert recovered[0].error_category == "runtime_error"

    # Verify runtime job record is updated
    updated_job = temp_db.get_runtime_job("semantic")
    assert updated_job.last_status == "interrupted"

    # Verify metric incremented
    metrics = temp_db.get_runtime_metrics()
    assert metrics.get("jobs_interrupted") == 1

    # Running recovery again does not re-increment
    recovered2 = recover_interrupted_jobs(temp_db, now=now)
    assert len(recovered2) == 0
    metrics2 = temp_db.get_runtime_metrics()
    assert metrics2.get("jobs_interrupted") == 1


# =========================================================================
# 5. Dependency Graph Satisfaction & Blocked Job Semantics
# =========================================================================

def test_dependency_satisfaction_fresh_vs_stale_vs_failed(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "jobs": {
            "ingestion": {"interval_minutes": 60, "max_dependency_age_minutes": 120},
            "semantic": {"interval_minutes": 60, "max_dependency_age_minutes": 120},
        }
    }

    # 1. Prerequisite never run -> blocked
    ok, blocked_by, reason = check_job_dependencies("semantic", temp_db, {}, now, config)
    assert ok is False
    assert blocked_by == "ingestion"
    assert "never completed successfully" in reason

    # 2. Prerequisite completed freshly -> satisfied
    job_ingest = RuntimeJob(
        job_name="ingestion",
        last_completed_at=now - timedelta(minutes=30),
        last_status="completed",
        updated_at=now - timedelta(minutes=30),
    )
    temp_db.save_runtime_job(job_ingest)

    ok, blocked_by, reason = check_job_dependencies("semantic", temp_db, {}, now, config)
    assert ok is True
    assert blocked_by is None

    # 3. Prerequisite stale (elapsed 150m > max 120m) -> blocked
    job_ingest.last_completed_at = now - timedelta(minutes=150)
    temp_db.save_runtime_job(job_ingest)

    ok, blocked_by, reason = check_job_dependencies("semantic", temp_db, {}, now, config)
    assert ok is False
    assert blocked_by == "ingestion"
    assert "is stale" in reason

    # 4. Prerequisite failed in current scheduler cycle -> blocks downstream
    cycle_results = {"ingestion": "failed"}
    ok, blocked_by, reason = check_job_dependencies("semantic", temp_db, cycle_results, now, config)
    assert ok is False
    assert blocked_by == "ingestion"
    assert "failed during current cycle" in reason

    # 5. Partial ingestion in current cycle SATISFIES semantic
    cycle_results_partial = {"ingestion": "partial"}
    ok, blocked_by, reason = check_job_dependencies("semantic", temp_db, cycle_results_partial, now, config)
    assert ok is True


def test_zero_projects_marks_context_match_not_applicable_and_satisfies_inbox(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "jobs": {
            "claims": {"interval_minutes": 60},
            "context_match": {"interval_minutes": 60},
            "inbox_refresh": {"interval_minutes": 60},
        }
    }

    # Ensure 0 active projects
    assert temp_db.get_active_project_count() == 0

    # Claims completed freshly
    job_claims = RuntimeJob(
        job_name="claims",
        last_completed_at=now - timedelta(minutes=15),
        last_status="completed",
        updated_at=now,
    )
    temp_db.save_runtime_job(job_claims)

    # inbox_refresh checks dependencies (claims and context_match)
    # Since active_projects == 0, context_match is not_applicable and does not block!
    ok, blocked_by, reason = check_job_dependencies("inbox_refresh", temp_db, {}, now, config)
    assert ok is True


def test_blocked_job_does_not_create_run_record(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "jobs": {
            "health_check": {"interval_minutes": 15},
            "ingestion": {"interval_minutes": 60},
            "semantic": {"interval_minutes": 60},
        }
    }

    with patch("app.runtime.scheduler.load_runtime_config", return_value=config), \
         patch("app.runtime.scheduler.is_job_due", side_effect=lambda j, *args: (True, "DUE")), \
         patch("app.runtime.scheduler.execute_job", return_value={"status": "failed"}):

        # When ingestion fails, semantic becomes blocked
        results = run_all_due_jobs(temp_db, dry_run=False, now=now, config=config)

        semantic_res = next((r for r in results if r["job_name"] == "semantic"), None)
        assert semantic_res is not None
        assert semantic_res["status"] == "blocked"

        # Verify NO execution run record was created for semantic
        runs = temp_db.get_recent_runtime_job_runs(job_name="semantic")
        assert len(runs) == 0

        # Verify runtime_jobs table records status blocked with reason
        job_rec = temp_db.get_runtime_job("semantic")
        assert job_rec.last_status == "blocked"
        assert job_rec.blocked_by == "ingestion"


# =========================================================================
# 6. Morning Briefing Scheduled vs Standalone Orchestration
# =========================================================================

def test_morning_briefing_scheduled_vs_standalone(temp_db):
    now = datetime(2026, 8, 22, 7, 35, 0, tzinfo=timezone.utc)

    with patch("app.runtime.jobs.generate_morning_briefing") as mock_gen_brief, \
         patch("app.runtime.jobs.export_briefing_markdown", return_value="data/briefings/2026-08-22.md"), \
         patch("app.runtime.jobs.run_source_ingestion") as mock_ingest:

        mock_brief = MagicMock()
        mock_brief.id = "brief:2026-08-22"
        mock_brief.total_items = 5
        mock_brief.high_priority_count = 2
        mock_brief.project_relevant_count = 1
        mock_brief.summary_text = "# Morning Briefing"
        mock_gen_brief.return_value = mock_brief

        # Scheduled generation does NOT invoke upstream source ingestion
        res_sched = generate_scheduled_morning_briefing(temp_db, now=now)
        assert res_sched["status"] in ("completed", "success")
        assert res_sched["total_items"] == 5
        mock_ingest.assert_not_called()

        # Standalone orchestration DOES invoke upstream source ingestion
        with patch("app.runtime.jobs.run_semantic_processing"), \
             patch("app.runtime.jobs.run_claims_processing"), \
             patch("app.runtime.jobs.run_longitudinal_recheck"), \
             patch("app.runtime.jobs.run_context_match"), \
             patch("app.runtime.jobs.run_inbox_generation"):

            res_orch = run_morning_pipeline_orchestration(temp_db, now=now, refresh=True)
            assert res_orch["status"] in ("completed", "success")
            mock_ingest.assert_called_once()


# =========================================================================
# 7. Timezone Engine & Scheduling
# =========================================================================

def test_timezone_engine_iana_and_invalid_fallback():
    # 1. Valid IANA timezone
    cfg_ny = {"timezone": "America/New_York"}
    tz_obj, name, warn = get_effective_timezone(cfg_ny)
    assert name == "America/New_York"
    assert warn is None

    # 2. Invalid timezone falls back to UTC with warning
    cfg_bad = {"timezone": "NonExistent/Mars_Time"}
    tz_obj_bad, name_bad, warn_bad = get_effective_timezone(cfg_bad)
    assert name_bad == "UTC"
    assert warn_bad is not None
    assert "Invalid timezone" in warn_bad


def test_daily_morning_briefing_calendar_date_due_check(temp_db):
    config = {
        "timezone": "UTC",
        "jobs": {
            "morning_brief": {"time": "07:30"},
        }
    }

    # 1. Before scheduled time (06:00) -> not due
    now_early = datetime(2026, 8, 22, 6, 0, 0, tzinfo=timezone.utc)
    is_due, reason = is_job_due("morning_brief", temp_db, now=now_early, config=config)
    assert is_due is False
    assert "SCHEDULED_AT_07:30" in reason

    # 2. After scheduled time (08:00) with no briefing generated -> due
    now_due = datetime(2026, 8, 22, 8, 0, 0, tzinfo=timezone.utc)
    is_due, reason = is_job_due("morning_brief", temp_db, now=now_due, config=config)
    assert is_due is True
    assert "MISSED_OR_DUE_TODAY" in reason

    # 3. Briefing exists for today -> completed today
    briefing = DailyBriefing(
        id="brief:2026-08-22",
        briefing_date="2026-08-22",
        generated_at=now_due,
        total_items=3,
    )
    temp_db.save_daily_briefing(briefing)

    is_due, reason = is_job_due("morning_brief", temp_db, now=now_due, config=config)
    assert is_due is False
    assert reason == "ALREADY_COMPLETED_TODAY"


# =========================================================================
# 8. Health Probes & Database-Safe Cache Isolation
# =========================================================================

def test_health_cache_database_isolation():
    fd1, path1 = tempfile.mkstemp(suffix="_db1.db")
    fd2, path2 = tempfile.mkstemp(suffix="_db2.db")
    os.close(fd1)
    os.close(fd2)

    db1 = Database(path1)
    db2 = Database(path2)
    invalidate_health_cache()

    try:
        now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

        with patch("app.runtime.health.check_network_connectivity", return_value=True):
            # Probe DB1
            h1 = check_system_health(db1, now=now, use_cache=True)
            assert h1["is_cached"] is False

            # Probe DB1 again -> should be cached
            h1_cached = check_system_health(db1, now=now + timedelta(seconds=2), use_cache=True)
            assert h1_cached["is_cached"] is True

            # Probe DB2 -> must NOT return cached result from DB1!
            h2 = check_system_health(db2, now=now + timedelta(seconds=3), use_cache=True)
            assert h2["is_cached"] is False
    finally:
        db1.close()
        db2.close()
        invalidate_health_cache()
        if os.path.exists(path1):
            os.remove(path1)
        if os.path.exists(path2):
            os.remove(path2)


def test_probe_isolation_socket_timeout_does_not_fail_database(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    # Force network probe offline
    with patch("app.runtime.health.check_network_connectivity", return_value=False):
        h = check_system_health(temp_db, now=now, use_cache=False)
        assert h["network"] == "offline"
        assert h["database"] == "ok"
        assert h["status"] == "DEGRADED"  # Degraded due to network, but not UNHEALTHY


# =========================================================================
# 9. Schema Migration & Null versus Zero Strategy
# =========================================================================

def test_null_vs_zero_storage_and_serialization(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    # Never-run job: duration_seconds, run_count, failure_count must be None
    unrun = RuntimeJob(
        job_name="clean_job",
        last_status="pending",
        duration_seconds=None,
        run_count=None,
        failure_count=None,
        updated_at=now,
    )
    temp_db.save_runtime_job(unrun)

    loaded = temp_db.get_runtime_job("clean_job")
    assert loaded.duration_seconds is None
    assert loaded.run_count is None
    assert loaded.failure_count is None

    # Completed zero-item run: duration_seconds=0.0, items_processed=0
    zero_run = RuntimeJobRun(
        id="run:zero:1",
        job_name="clean_job",
        started_at=now,
        completed_at=now,
        status="completed",
        items_processed=0,
        duration_seconds=0.0,
    )
    temp_db.save_runtime_job_run(zero_run)

    loaded_run = temp_db.get_recent_runtime_job_runs(job_name="clean_job")[0]
    assert loaded_run.items_processed == 0
    assert loaded_run.duration_seconds == 0.0


# =========================================================================
# 10. Aggregated Overview API & Query Budget
# =========================================================================

def test_runtime_overview_response_and_query_budget(temp_db):
    # Insert some dummy checkpoints and jobs
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="github",
        health_status="healthy",
        consecutive_failures=0,
        last_success_at=datetime.now(timezone.utc),
    ))
    temp_db.save_runtime_job(RuntimeJob(
        job_name="ingestion",
        last_status="completed",
        duration_seconds=1.5,
        run_count=3,
        failure_count=0,
        last_completed_at=datetime.now(timezone.utc),
    ))

    # Instrument SQLite query count budget (<= 6 queries)
    statements = []
    temp_db.conn.set_trace_callback(lambda stmt: statements.append(stmt))

    try:
        with patch("app.runtime.health.check_network_connectivity", return_value=True):
            overview = get_runtime_overview(temp_db)
    finally:
        temp_db.conn.set_trace_callback(None)

    assert overview.schema_version == "v1"
    assert overview.status in ("HEALTHY", "DEGRADED", "UNHEALTHY")
    assert len(overview.sources) >= 1
    assert len(overview.jobs) >= 1
    assert overview.job_summary.total >= 1
    assert overview.source_summary.total >= 1

    # Filter out SQLite internal engine sub-traces (which start with '--')
    app_queries = [s for s in statements if not s.strip().startswith("--")]

    # Verify query count is bounded <= 7 (6 batch queries + 1 PRAGMA check)
    assert len(app_queries) <= 7


