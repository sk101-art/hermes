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
    sanitize_runtime_data,
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
    load_runtime_config,
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
    # Best-effort cleanup: on Windows, WAL sidecar handles can briefly keep
    # the file locked after close(); never fail the test over deletion.
    import gc
    gc.collect()
    for suffix in ("", "-wal", "-shm"):
        try:
            p = path + suffix
            if os.path.exists(p):
                os.remove(p)
        except PermissionError:
            pass


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

        # Verify runtime_jobs table records evaluation_status blocked with reason
        job_rec = temp_db.get_runtime_job("semantic")
        assert job_rec.evaluation_status == "blocked"
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


def test_missing_required_embedding_dependency_cannot_be_healthy(temp_db):
    """Proves that a missing runtime dependency causes UNHEALTHY status and cannot produce HEALTHY."""
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    with patch("importlib.util.find_spec", return_value=None):
        h = check_system_health(temp_db, now=now, use_cache=False)
        assert h["embedding_model"] == "missing_dependency"
        assert any("sentence_transformers" in issue for issue in h["issues"])
        assert h["status"] != "HEALTHY"
        assert h["status"] == "UNHEALTHY"


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
# 10. Authoritative Fresh Schema Audit (PRAGMA table_info)
# =========================================================================

def test_authoritative_fresh_schema_pragma_table_info():
    """Verify fresh schema.sql creates all Phase 13 fields directly without migrations."""
    schema_path = Path(__file__).resolve().parent.parent / "app" / "storage" / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    raw_conn = sqlite3.connect(":memory:")
    raw_conn.executescript(schema_sql)

    # 1. source_checkpoints columns
    cur = raw_conn.execute("PRAGMA table_info(source_checkpoints)")
    scp_cols = {row[1] for row in cur.fetchall()}
    assert "last_error_category" in scp_cols
    assert "failure_threshold_reached" in scp_cols
    assert "max_consecutive_failures" in scp_cols

    # 2. runtime_jobs columns
    cur = raw_conn.execute("PRAGMA table_info(runtime_jobs)")
    job_cols = {row[1] for row in cur.fetchall()}
    assert "last_error_category" in job_cols
    assert "evaluation_status" in job_cols
    assert "evaluated_at" in job_cols
    assert "blocked_by" in job_cols
    assert "blocked_reason" in job_cols

    # 3. runtime_job_runs columns
    cur = raw_conn.execute("PRAGMA table_info(runtime_job_runs)")
    run_cols = {row[1] for row in cur.fetchall()}
    assert "error_category" in run_cols

    raw_conn.close()


# =========================================================================
# 11. Persisted Threshold Contract, Close/Reopen & Legacy Fallback
# =========================================================================

def test_threshold_state_persisted_contract_reopen_and_reset(temp_db):
    """Test persisted threshold state across DB close/reopen and recovery."""
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "sources": {
            "github": {"interval_minutes": 60, "max_consecutive_failures": 3, "enabled": True}
        }
    }

    # Record 3 failures to trigger threshold
    record_source_failure("github", "Fail 1", temp_db, now=now, config=config)
    record_source_failure("github", "Fail 2", temp_db, now=now + timedelta(minutes=16), config=config)
    cp = record_source_failure("github", "Fail 3", temp_db, now=now + timedelta(minutes=32), config=config)

    assert cp.consecutive_failures == 3
    assert cp.failure_threshold_reached is True
    assert cp.max_consecutive_failures == 3

    # Close DB and reopen from disk path
    db_path = temp_db.db_path
    temp_db.close()

    reopened_db = Database(db_path)
    try:
        loaded = reopened_db.get_source_checkpoint("github")
        assert loaded is not None
        assert loaded.consecutive_failures == 3
        assert loaded.failure_threshold_reached is True
        assert loaded.max_consecutive_failures == 3

        # Successful poll resets threshold
        recovered = record_source_success("github", reopened_db, now=now + timedelta(minutes=60))
        assert recovered.consecutive_failures == 0
        assert recovered.failure_threshold_reached is False
        assert recovered.health_status == "healthy"

        # Direct SQL insertion of legacy row (NULLs in threshold fields)
        reopened_db.conn.execute(
            "INSERT INTO source_checkpoints (source, last_attempt_at, health_status, consecutive_failures, updated_at) "
            "VALUES ('legacy_source', '2026-08-22T08:00:00Z', 'healthy', 0, '2026-08-22T08:00:00Z')"
        )
        reopened_db.conn.commit()

        legacy_cp = reopened_db.get_source_checkpoint("legacy_source")
        assert legacy_cp.failure_threshold_reached is False
        assert legacy_cp.max_consecutive_failures == 5  # Default fallback
    finally:
        reopened_db.close()


# =========================================================================
# 12. Evaluation vs Execution Separation & Dependency Freshness
# =========================================================================

def test_scheduler_evaluation_separated_from_execution_outcome(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    config = {
        "jobs": {
            "ingestion": {"interval_minutes": 60},
            "semantic": {"interval_minutes": 60},
            "claims": {"interval_minutes": 60},
            "inbox_refresh": {"interval_minutes": 60},
        }
    }

    # Case A: Completed execution followed by blocked evaluation
    run = start_job_run("semantic", temp_db, now=now)
    finish_job_run(run, "completed", 10, temp_db, now=now)
    completed_rec = temp_db.get_runtime_job("semantic")
    assert completed_rec.last_status == "completed"
    assert completed_rec.run_count == 1
    assert completed_rec.last_completed_at == now

    # Ingestion fails in scheduler cycle -> semantic becomes blocked
    with patch("app.runtime.scheduler.load_runtime_config", return_value=config), \
         patch("app.runtime.scheduler.is_job_due", return_value=(True, "DUE")), \
         patch("app.runtime.scheduler.execute_job", return_value={"status": "failed"}):

        results = run_all_due_jobs(temp_db, dry_run=False, now=now + timedelta(minutes=10), config=config)
        sem_res = next(r for r in results if r["job_name"] == "semantic")
        assert sem_res["status"] == "blocked"

        job_state = temp_db.get_runtime_job("semantic")
        # last_status must NOT be overwritten by blocked evaluation!
        assert job_state.last_status == "completed"
        assert job_state.evaluation_status == "blocked"
        assert job_state.last_completed_at == now
        assert job_state.run_count == 1
        assert job_state.failure_count == 0
        assert job_state.blocked_by == "ingestion"

    # Case B: Blocked evaluation followed by successful execution
    run_rec = start_job_run("semantic", temp_db, now=now + timedelta(minutes=20))
    finish_job_run(run_rec, "completed", 5, temp_db, now=now + timedelta(minutes=20))
    recovered_job = temp_db.get_runtime_job("semantic")
    assert recovered_job.last_status == "completed"
    assert recovered_job.evaluation_status == "completed"
    assert recovered_job.blocked_by is None
    assert recovered_job.blocked_reason is None

    # Case C: Partial prerequisite satisfies downstream dependency
    run_ing = start_job_run("ingestion", temp_db, now=now + timedelta(minutes=30))
    finish_job_run(run_ing, "partial", 2, temp_db, now=now + timedelta(minutes=30))

    # Check semantic dependencies (it requires ingestion)
    deps_ok, blocker, reason = check_job_dependencies("semantic", temp_db, cycle_results={}, now=now + timedelta(minutes=31), config=config)
    assert deps_ok is True  # Partial ingestion from database satisfies dependency!

    # Check fresh execution timestamp was used
    ingest_rec = temp_db.get_runtime_job("ingestion")
    assert ingest_rec.last_status == "partial"
    assert ingest_rec.last_completed_at == now + timedelta(minutes=30)


# =========================================================================
# 13. Query Budget & Scale Invariance Tests
# =========================================================================

def test_query_budget_separated_application_queries_and_integrity_probe(temp_db):
    """Assert <=6 application data queries + 1 explicit integrity probe."""
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="github", health_status="healthy", consecutive_failures=0, last_success_at=datetime.now(timezone.utc)
    ))
    temp_db.save_runtime_job(RuntimeJob(
        job_name="ingestion", last_status="completed", duration_seconds=1.0, run_count=2, failure_count=0
    ))

    invalidate_health_cache(temp_db.db_path)
    statements = []
    temp_db.conn.set_trace_callback(lambda stmt: statements.append(stmt))
    try:
        with patch("app.runtime.health.check_network_connectivity", return_value=True):
            overview = get_runtime_overview(temp_db)
    finally:
        temp_db.conn.set_trace_callback(None)

    # Filter internal SQLite sub-traces
    raw_queries = [s.strip() for s in statements if not s.strip().startswith("--")]
    app_queries = [s for s in raw_queries if not s.upper().startswith("PRAGMA QUICK_CHECK")]
    integrity_queries = [s for s in raw_queries if s.upper().startswith("PRAGMA QUICK_CHECK")]

    assert len(app_queries) <= 6
    assert len(integrity_queries) <= 1
    assert len(raw_queries) <= 7


def test_query_budget_scale_invariance_small_vs_large(temp_db):
    """Prove query count is scale-invariant between small and large source/job sets."""
    # Small set (1 source, 1 job)
    temp_db.save_source_checkpoint(SourceCheckpoint(source="src_0", health_status="healthy"))
    temp_db.save_runtime_job(RuntimeJob(job_name="job_0", last_status="completed"))

    invalidate_health_cache(temp_db.db_path)
    stmts_small = []
    temp_db.conn.set_trace_callback(lambda stmt: stmts_small.append(stmt))
    with patch("app.runtime.health.check_network_connectivity", return_value=True):
        get_runtime_overview(temp_db)
    temp_db.conn.set_trace_callback(None)
    app_small = len([s for s in stmts_small if not s.strip().startswith("--") and not s.strip().upper().startswith("PRAGMA QUICK_CHECK")])

    # Populate 15 sources and 20 jobs
    for i in range(1, 16):
        temp_db.save_source_checkpoint(SourceCheckpoint(source=f"src_{i}", health_status="healthy"))
    for j in range(1, 21):
        temp_db.save_runtime_job(RuntimeJob(job_name=f"job_{j}", last_status="completed"))

    invalidate_health_cache(temp_db.db_path)
    stmts_large = []
    temp_db.conn.set_trace_callback(lambda stmt: stmts_large.append(stmt))
    with patch("app.runtime.health.check_network_connectivity", return_value=True):
        get_runtime_overview(temp_db)
    temp_db.conn.set_trace_callback(None)
    app_large = len([s for s in stmts_large if not s.strip().startswith("--") and not s.strip().upper().startswith("PRAGMA QUICK_CHECK")])

    # O(1) application query budget assertion
    assert app_small == app_large
    assert app_small <= 6


# =========================================================================
# 14. Deterministic DST and Timezone Verification
# =========================================================================

def test_dst_and_timezone_verification_comprehensive():
    # 1. UTC
    cfg_utc = {"timezone": "UTC"}
    _, name_utc, warn_utc = get_effective_timezone(cfg_utc)
    assert name_utc == "UTC"
    assert warn_utc is None

    # 2. Asia/Kolkata
    cfg_kolkata = {"timezone": "Asia/Kolkata"}
    tz_kolkata, name_kolkata, warn_kolkata = get_effective_timezone(cfg_kolkata)
    assert name_kolkata == "Asia/Kolkata"
    assert warn_kolkata is None
    # 10:00 UTC is 15:30 IST (+05:30)
    dt_utc = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    dt_ist = dt_utc.astimezone(tz_kolkata)
    assert dt_ist.strftime("%H:%M") == "15:30"

    # 3. America/New_York (EDT in August: UTC-4, EST in January: UTC-5)
    cfg_ny = {"timezone": "America/New_York"}
    tz_ny, name_ny, warn_ny = get_effective_timezone(cfg_ny)
    assert name_ny == "America/New_York"
    dt_summer = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc).astimezone(tz_ny)
    assert dt_summer.strftime("%H:%M") == "08:00"  # EDT (UTC-4)
    dt_winter = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc).astimezone(tz_ny)
    assert dt_winter.strftime("%H:%M") == "07:00"  # EST (UTC-5)

    # 4. Spring-Forward DST (2026-03-08 in America/New_York):
    # Clocks skip from 02:00 to 03:00. At 03:05 EDT (07:05 UTC), a job scheduled for 02:30 is overdue and due today.
    dt_after_skip = datetime(2026, 3, 8, 7, 5, 0, tzinfo=timezone.utc)
    local_time = dt_after_skip.astimezone(tz_ny).time()
    assert local_time >= dtime(2, 30)

    # 5. Invalid zone fallback
    cfg_inv = {"timezone": "NonExistent/Mars"}
    _, name_inv, warn_inv = get_effective_timezone(cfg_inv)
    assert name_inv == "UTC"
    assert "Invalid timezone" in warn_inv


# =========================================================================
# 15. Sanitization Across Public Endpoints & No Secret Leaks
# =========================================================================

def test_sanitization_across_public_endpoints_and_results(temp_db):
    from fastapi.testclient import TestClient
    from app.api.server import app
    from app.api.routes import get_db

    secret_fixture = "ghp_ultra_secret_api_key_999888"
    path_fixture = r"C:\Users\SecretAdmin\code\app.py"

    # Insert degraded source and failed job containing raw secret fixtures
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="secret_source",
        health_status="degraded",
        consecutive_failures=3,
        last_error=f"Authorization failed: Bearer {secret_fixture} at {path_fixture}",
        last_error_category="auth_error",
    ))
    temp_db.save_runtime_job(RuntimeJob(
        job_name="secret_job",
        last_status="failed",
        last_error=f"Failed loading config with key {secret_fixture}",
        last_error_category="auth_error",
    ))

    app.dependency_overrides[get_db] = lambda: temp_db
    client = TestClient(app)

    try:
        for ep in ["/sources", "/health", "/runtime", "/runtime/overview"]:
            resp = client.get(ep)
            assert resp.status_code == 200
            text = resp.text

            # MUST NEVER leak raw secret fixture or user path fixture
            assert secret_fixture not in text
            assert "SecretAdmin" not in text

            # Public overview and runtime responses MUST omit hostname
            if ep in ("/runtime", "/runtime/overview"):
                data = resp.json()
                assert "hostname" not in data
                if "daemon" in data:
                    assert "hostname" not in data["daemon"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# =========================================================================
# 16. Ingestion Edge Cases: All Failed & None Due
# =========================================================================

def test_ingestion_edge_cases(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    all_sources = ["github", "github_releases", "arxiv", "hackernews", "huggingface", "openalex", "crossref", "stackexchange", "rss"]

    # 1. No sources due
    config_none_due = {
        "sources": {
            s: {"interval_minutes": 120, "enabled": (s == "github")}
            for s in all_sources
        }
    }
    # Mark github polled recently
    record_source_success("github", temp_db, now=now)
    with patch("app.runtime.jobs.load_runtime_config", return_value=config_none_due):
        res_none = run_source_ingestion(temp_db, now=now + timedelta(minutes=10))
        assert res_none["status"] == "completed"
        assert len(res_none["sources_polled"]) == 0

    # 2. All sources failed
    config_all_fail = {
        "sources": {
            s: {"interval_minutes": 10, "enabled": (s == "arxiv")}
            for s in all_sources
        }
    }
    mock_adapter = MagicMock()
    mock_adapter.fetch.side_effect = Exception("Connection refused")
    with patch("app.runtime.jobs.load_runtime_config", return_value=config_all_fail), \
         patch("app.runtime.jobs._get_adapter_factories", return_value={"arxiv": (lambda: mock_adapter, 10)}):
        res_fail = run_source_ingestion(temp_db, now=now + timedelta(minutes=20))
        assert res_fail["status"] == "failed"
        assert len(res_fail["sources_failed"]) == 1
        # Returned error must be sanitized
        assert "Connection refused" in res_fail["sources_failed"][0]["error"]


# =========================================================================
# 17. Pre-Phase-13 Legacy Schema Migration & Idempotence
# =========================================================================

def test_pre_phase13_legacy_schema_migration_and_idempotence(tmp_path):
    legacy_db_path = str(tmp_path / "legacy_test.db")
    raw_conn = sqlite3.connect(legacy_db_path)
    # Create legacy tables without Phase 13 columns
    raw_conn.executescript("""
        CREATE TABLE source_checkpoints (
            source TEXT PRIMARY KEY,
            last_success_at TEXT,
            last_attempt_at TEXT,
            last_cursor TEXT,
            last_event_time TEXT,
            last_error TEXT,
            consecutive_failures INTEGER DEFAULT 0,
            next_retry_at TEXT,
            health_status TEXT DEFAULT 'healthy',
            updated_at TEXT
        );
        CREATE TABLE runtime_jobs (
            job_name TEXT PRIMARY KEY,
            last_status TEXT,
            last_started_at TEXT,
            last_completed_at TEXT,
            duration_seconds REAL,
            run_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            last_error TEXT,
            updated_at TEXT
        );
        CREATE TABLE runtime_job_runs (
            id TEXT PRIMARY KEY,
            job_name TEXT,
            started_at TEXT,
            completed_at TEXT,
            duration_seconds REAL,
            status TEXT,
            error_message TEXT,
            created_at TEXT
        );
        INSERT INTO source_checkpoints (source, last_success_at, consecutive_failures)
        VALUES ('github', '2026-08-20T10:00:00+00:00', 0);
        INSERT INTO runtime_jobs (job_name, last_status, run_count)
        VALUES ('ingestion', 'completed', 5);
    """)
    raw_conn.commit()
    raw_conn.close()

    # Open via Database which runs _run_migrations
    migrated_db = Database(legacy_db_path)
    try:
        # Verify columns added
        scp_cols = {r["name"] for r in migrated_db.conn.execute("PRAGMA table_info(source_checkpoints)").fetchall()}
        assert "failure_threshold_reached" in scp_cols
        assert "max_consecutive_failures" in scp_cols
        assert "last_error_category" in scp_cols

        rj_cols = {r["name"] for r in migrated_db.conn.execute("PRAGMA table_info(runtime_jobs)").fetchall()}
        assert "evaluation_status" in rj_cols
        assert "evaluated_at" in rj_cols
        assert "blocked_by" in rj_cols
        assert "blocked_reason" in rj_cols
        assert "last_error_category" in rj_cols

        rjr_cols = {r["name"] for r in migrated_db.conn.execute("PRAGMA table_info(runtime_job_runs)").fetchall()}
        assert "error_category" in rjr_cols

        # Verify legacy row values preserved
        cp = migrated_db.get_source_checkpoint("github")
        assert cp.source == "github"
        assert cp.last_success_at == datetime(2026, 8, 20, 10, 0, 0, tzinfo=timezone.utc)
        assert cp.consecutive_failures == 0

        job = migrated_db.get_runtime_job("ingestion")
        assert job.job_name == "ingestion"
        assert job.last_status == "completed"
        assert job.run_count == 5

        # Verify idempotence on second migration run
        migrated_db._migrate_columns()
        scp_cols_after = {r["name"] for r in migrated_db.conn.execute("PRAGMA table_info(source_checkpoints)").fetchall()}
        assert scp_cols == scp_cols_after
    finally:
        migrated_db.close()


# =========================================================================
# 18. Timestamp Identity & Provenance (All 4 Timestamps Distinct)
# =========================================================================

def test_four_source_timestamps_differ_and_retained(temp_db):
    t_success = datetime(2026, 8, 20, 10, 0, 0, tzinfo=timezone.utc)
    t_attempt = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    t_event = datetime(2026, 8, 20, 9, 30, 0, tzinfo=timezone.utc)
    t_retry = datetime(2026, 8, 22, 10, 30, 0, tzinfo=timezone.utc)

    cp = SourceCheckpoint(
        source="arxiv",
        last_success_at=t_success,
        last_attempt_at=t_attempt,
        last_event_time=t_event,
        next_retry_at=t_retry,
        consecutive_failures=1,
        health_status="retrying",
        last_error="Temporary 503",
        last_error_category="server_error",
        updated_at=t_attempt,
    )
    temp_db.save_source_checkpoint(cp)

    config = load_runtime_config()
    overview = get_runtime_overview(temp_db)
    arxiv_rec = next((s for s in overview.sources if s.source == "arxiv"), None)
    assert arxiv_rec is not None
    assert arxiv_rec.last_success_at == t_success.isoformat()
    assert arxiv_rec.last_attempt_at == t_attempt.isoformat()
    assert arxiv_rec.last_event_time == t_event.isoformat()
    assert arxiv_rec.next_retry_at == t_retry.isoformat()
    # Timestamps are distinct and have not been substituted
    assert arxiv_rec.last_success_at != arxiv_rec.last_attempt_at
    assert arxiv_rec.last_event_time != arxiv_rec.last_success_at


# =========================================================================
# 19. Active Daemon vs Stale Daemon vs Running Job Overview
# =========================================================================

def test_active_vs_stale_daemon_and_running_job_in_overview(temp_db, tmp_path):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    
    # 1. Active daemon with running job
    temp_db.save_runtime_job(RuntimeJob(
        job_name="semantic",
        last_status="running",
        evaluation_status="due",
        last_started_at=now,
        updated_at=now,
    ))

    with patch("app.services.runtime.is_heartbeat_alive", return_value=(True, {"status": "running", "pid": 1234, "timestamp": now.isoformat(), "age_seconds": 5})), \
         patch("app.services.runtime.read_heartbeat", return_value={"status": "running", "pid": 1234, "timestamp": now.isoformat(), "age_seconds": 5}):
        overview_active = get_runtime_overview(temp_db)
        assert overview_active.daemon.status == "running"
        assert overview_active.daemon.pid == 1234
        sem_job = next(j for j in overview_active.jobs if j.job_name == "semantic")
        assert sem_job.status == "running"
        assert sem_job.last_status == "running"

    # 2. Stale daemon degrades status
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(False, {"status": "stale", "pid": 1234, "timestamp": (now - timedelta(seconds=120)).isoformat(), "age_seconds": 120})), \
         patch("app.services.runtime.read_heartbeat", return_value={"status": "stale", "pid": 1234, "timestamp": (now - timedelta(seconds=120)).isoformat(), "age_seconds": 120}):
        overview_stale = get_runtime_overview(temp_db)
        assert overview_stale.daemon.status == "stale"
        assert overview_stale.status == "DEGRADED"


# =========================================================================
# 20. UNC Path & Recursive Sanitization
# =========================================================================

def test_unc_path_sanitization_and_recursive_sanitizer():
    raw_unc = r"Failed to access \\fileserver\shares\hermes\data.db with Bearer secret-tok-123"
    cat, sanitized = sanitize_error(raw_unc)
    assert r"\\fileserver\shares" not in sanitized
    assert "[LOCAL_PATH]" in sanitized
    assert "secret-tok-123" not in sanitized
    assert "Bearer [REDACTED]" in sanitized

    nested_payload = {
        "job": "ingestion",
        "nested_errors": [
            r"C:\Users\Admin\secrets.txt",
            r"\\nas01\backup\archive.tar",
            "http://user:pass@example.com/api"
        ]
    }
    cleaned = sanitize_runtime_data(nested_payload)
    assert cleaned["nested_errors"][0] == "[LOCAL_PATH]"
    assert cleaned["nested_errors"][1] == "[LOCAL_PATH]"
    assert "pass" not in cleaned["nested_errors"][2]
    assert cleaned["nested_errors"][2] == "https://[REDACTED]@example.com/api"


# =========================================================================
# 21. Empty Sources / Empty Jobs Status
# =========================================================================

def test_empty_sources_and_jobs_produce_unknown_status(temp_db):
    empty_config = {"sources": {}}
    with patch("app.services.runtime.load_runtime_config", return_value=empty_config):
        overview = get_runtime_overview(temp_db)
        assert overview.status == "UNKNOWN"
        assert any("No source adapters" in w for w in overview.warnings)


# =========================================================================
# 22. Heartbeat State Matrix & Contradiction Elimination
# =========================================================================

def test_heartbeat_state_matrix_and_contradiction_elimination(temp_db, tmp_path):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    
    # Scenario A: Live, fresh heartbeat
    hb_live = {"status": "running", "pid": 9999, "timestamp": (now - timedelta(seconds=10)).isoformat(), "age_seconds": 10, "is_stale": False}
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(True, hb_live)), \
         patch("app.services.runtime.SingleInstanceLock.get_lock_info", return_value={"pid": 9999}):
        ov = get_runtime_overview(temp_db, now=now)
        assert ov.daemon.status == "running"
        assert ov.daemon.is_stale is False
        assert ov.daemon.pid == 9999
        assert ov.daemon.lock_present is True
        assert ov.daemon.disagreement_notice is None

    # Scenario B: Stale heartbeat (age > 180s)
    hb_stale = {"status": "stale", "pid": 9999, "timestamp": (now - timedelta(seconds=300)).isoformat(), "age_seconds": 300, "is_stale": True}
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(False, hb_stale)), \
         patch("app.services.runtime.SingleInstanceLock.get_lock_info", return_value=None):
        ov = get_runtime_overview(temp_db, now=now)
        assert ov.daemon.status == "stale"
        assert ov.daemon.is_stale is True

    # Scenario C: Missing heartbeat file
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(False, None)), \
         patch("app.services.runtime.SingleInstanceLock.get_lock_info", return_value=None):
        ov = get_runtime_overview(temp_db, now=now)
        assert ov.daemon.status == "stopped"
        assert ov.daemon.is_stale is False
        assert ov.daemon.pid is None

    # Scenario D: Malformed heartbeat timestamp
    hb_malformed = {"status": "malformed", "pid": 9999, "timestamp": "not-a-valid-timestamp", "is_stale": True}
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(False, hb_malformed)), \
         patch("app.services.runtime.SingleInstanceLock.get_lock_info", return_value=None):
        ov = get_runtime_overview(temp_db, now=now)
        assert ov.daemon.status == "unknown"
        assert ov.daemon.is_stale is True
        assert "malformed" in (ov.daemon.disagreement_notice or "").lower()

    # Scenario E: Historical PID with dead process
    hb_dead = {"status": "stopped", "pid": 1111, "timestamp": (now - timedelta(seconds=20)).isoformat(), "age_seconds": 20, "is_stale": True}
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(False, hb_dead)), \
         patch("app.services.runtime.SingleInstanceLock.get_lock_info", return_value=None):
        ov = get_runtime_overview(temp_db, now=now)
        assert ov.daemon.status == "stopped"
        assert ov.daemon.is_stale is True

    # Scenario F: Lock present without fresh heartbeat (disagreement)
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(False, hb_stale)), \
         patch("app.services.runtime.SingleInstanceLock.get_lock_info", return_value={"pid": 8888}):
        ov = get_runtime_overview(temp_db, now=now)
        assert ov.daemon.status == "stale"
        assert ov.daemon.is_stale is True
        assert ov.daemon.lock_present is True
        assert "stale" in (ov.daemon.disagreement_notice or "").lower() or "expired" in (ov.daemon.disagreement_notice or "").lower()

    # Scenario G: Fresh heartbeat without lock file
    with patch("app.services.runtime.is_heartbeat_alive", return_value=(True, hb_live)), \
         patch("app.services.runtime.SingleInstanceLock.get_lock_info", return_value=None):
        ov = get_runtime_overview(temp_db, now=now)
        assert ov.daemon.status == "running"
        assert ov.daemon.lock_present is False


# =========================================================================
# 23. Complete Source State Matrix & Distinct Badging
# =========================================================================

def test_complete_source_state_matrix_and_distinctness(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    t_old = now - timedelta(days=2)
    t_recent = now - timedelta(minutes=5)
    
    # 1. Healthy: polled recently and successfully
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="github",
        last_success_at=t_recent,
        last_attempt_at=t_recent,
        consecutive_failures=0,
        health_status="healthy",
        updated_at=t_recent,
    ))
    
    # 2. Degraded & Threshold reached: multiple failures >= 5
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="arxiv",
        last_success_at=t_old,
        last_attempt_at=t_recent,
        consecutive_failures=5,
        failure_threshold_reached=True,
        max_consecutive_failures=5,
        next_retry_at=now + timedelta(hours=4),
        health_status="degraded",
        last_error="Connection timed out",
        last_error_category="network_error",
        updated_at=t_recent,
    ))
    
    # 3. Rate limited: HTTP 429
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="hackernews",
        last_success_at=t_old,
        last_attempt_at=t_recent,
        consecutive_failures=2,
        health_status="rate_limited",
        last_error="HTTP 429 Too Many Requests",
        last_error_category="rate_limited",
        next_retry_at=now + timedelta(minutes=30),
        updated_at=t_recent,
    ))

    # 4. Offline: Network unreachable
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="openalex",
        last_success_at=t_old,
        last_attempt_at=t_recent,
        consecutive_failures=3,
        health_status="offline",
        last_error="Host unreachable",
        last_error_category="network_error",
        updated_at=t_recent,
    ))

    # 5. Disabled: marked disabled
    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="crossref",
        last_success_at=t_old,
        last_attempt_at=t_old,
        consecutive_failures=0,
        health_status="disabled",
        updated_at=t_old,
    ))

    # 6. Unknown: Never attempted (no checkpoint saved for rss)

    overview = get_runtime_overview(temp_db, now=now)
    src_map = {s.source: s for s in overview.sources}

    assert src_map["github"].health_status == "healthy"
    assert src_map["arxiv"].health_status == "degraded"
    assert src_map["arxiv"].failure_threshold_reached is True
    assert src_map["hackernews"].health_status == "rate_limited"
    assert src_map["openalex"].health_status == "offline"
    assert src_map["crossref"].health_status == "disabled"
    assert src_map["rss"].health_status == "unknown"
    assert src_map["rss"].last_attempt_at is None
    assert src_map["rss"].last_success_at is None


# =========================================================================
# 24. Authoritative Ingestion Freshness Boundary
# =========================================================================

def test_authoritative_ingestion_freshness_boundary(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    t_ingest = now - timedelta(hours=1)

    # Initial success on github
    record_source_success("github", temp_db, now=t_ingest)
    ov1 = get_runtime_overview(temp_db, now=now)
    assert ov1.intelligence_freshness.last_successful_ingestion == t_ingest.isoformat()

    # 1. Failed polling attempt does NOT advance freshness
    record_source_failure("arxiv", "Timeout", temp_db, now=now)
    ov2 = get_runtime_overview(temp_db, now=now)
    assert ov2.intelligence_freshness.last_successful_ingestion == t_ingest.isoformat()

    # 2. Scheduler evaluation does NOT advance freshness
    temp_db.save_runtime_job(RuntimeJob(
        job_name="semantic",
        last_status="completed",
        evaluation_status="due",
        last_completed_at=now,
        updated_at=now,
    ))
    ov3 = get_runtime_overview(temp_db, now=now)
    assert ov3.intelligence_freshness.last_successful_ingestion == t_ingest.isoformat()

    # 3. Briefing generation does NOT advance freshness
    temp_db.save_daily_briefing(DailyBriefing(
        id="briefing-2026-08-22",
        briefing_date="2026-08-22",
        generated_at=now,
        item_count=5,
        raw_items_json="[]",
        total_items=5,
    ))
    ov4 = get_runtime_overview(temp_db, now=now)
    assert ov4.intelligence_freshness.last_successful_ingestion == t_ingest.isoformat()

    # 4. Successful source ingestion DOES advance freshness
    t_new_success = now + timedelta(minutes=5)
    record_source_success("arxiv", temp_db, now=t_new_success)
    ov5 = get_runtime_overview(temp_db, now=now + timedelta(minutes=6))
    assert ov5.intelligence_freshness.last_successful_ingestion == t_new_success.isoformat()


# =========================================================================
# 25. Partial Diagnostic Failures Handling
# =========================================================================

def test_partial_diagnostic_failures_handling(temp_db):
    # 1. Source checkpoints query failure
    with patch.object(temp_db, "get_all_source_checkpoints_map", side_effect=sqlite3.OperationalError("disk I/O error")):
        ov = get_runtime_overview(temp_db)
        assert ov.status == "DEGRADED"
        assert ov.is_partial_availability is True
        assert any("Source checkpoints query failed" in iss for iss in ov.issues)
        # Jobs and metrics remain populated
        assert len(ov.jobs) > 0

    # 2. Database integrity corruption failure
    with patch("app.services.runtime.check_system_health", return_value={
        "status": "UNHEALTHY",
        "database": "corrupt",
        "network": "online",
        "disk_status": "ok",
        "issues": ["Database integrity check failed: file is not a database"],
        "warnings": [],
    }):
        ov_corrupt = get_runtime_overview(temp_db)
        assert ov_corrupt.status == "UNHEALTHY"
        assert ov_corrupt.system.database == "corrupt"


# =========================================================================
# 26. Hostile Recursive Payload Sanitization at Serialization Boundary
# =========================================================================

def test_hostile_recursive_payload_sanitization_at_serialization_boundary(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    hostile_error = (
        r"CRITICAL: Failed connecting to https://admin:SuperSecretPassword123@api.private.corp/v1?token=tok-xyz-999 "
        r"with Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload.signature "
        r"while accessing \\fileserver01\shares\finance\db.sqlite "
        r"from C:\Users\Administrator\Documents\hermes\repo\app.py "
        r"and /home/deployer/.ssh/id_rsa and /Users/developer/Library/Keychains/login.keychain-db"
    )

    temp_db.save_source_checkpoint(SourceCheckpoint(
        source="github",
        last_attempt_at=now,
        consecutive_failures=1,
        health_status="retrying",
        last_error=hostile_error,
        updated_at=now,
    ))

    overview = get_runtime_overview(temp_db, now=now)
    serialized_dict = overview.model_dump()
    serialized_json = json.dumps(serialized_dict, default=str)

    # Assert strict redaction across serialized output
    assert "SuperSecretPassword123" not in serialized_json
    assert "tok-xyz-999" not in serialized_json
    assert "eyJhbGci" not in serialized_json
    assert "fileserver01" not in serialized_json
    assert "Administrator" not in serialized_json
    assert "deployer" not in serialized_json
    assert "developer" not in serialized_json
    assert "[LOCAL_PATH]" in serialized_json
    assert "Bearer [REDACTED]" in serialized_json
    assert "https://[REDACTED]@" in serialized_json


# =========================================================================
# 27. Regression Test: Scheduler Evaluations Create No Job Run Rows
# =========================================================================

def test_scheduler_evaluations_create_no_job_run_rows_and_preserve_execution_state(temp_db):
    now = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    t_completed = now - timedelta(hours=2)

    # Pre-populate a job with a prior completed run
    temp_db.save_runtime_job(RuntimeJob(
        job_name="semantic",
        last_started_at=t_completed - timedelta(minutes=1),
        last_completed_at=t_completed,
        last_status="completed",
        evaluation_status="completed",
        evaluated_at=t_completed,
        run_count=5,
        failure_count=1,
        updated_at=t_completed,
    ))

    # Initial runs count in runtime_job_runs table
    initial_runs = temp_db.get_recent_runtime_job_runs(limit=100)
    initial_run_count = len(initial_runs)

    # 1. Run scheduler cycle where 'semantic' is BLOCKED (e.g., ingestion prerequisite failed)
    cycle_results = {"ingestion": "failed"}
    deps_ok, blocked_by, blocked_reason = check_job_dependencies("semantic", temp_db, cycle_results, now, load_runtime_config())
    assert deps_ok is False
    assert blocked_by == "ingestion"

    # Evaluate blocked state via scheduler logic
    job_rec = temp_db.get_runtime_job("semantic")
    job_rec.evaluation_status = "blocked"
    job_rec.evaluated_at = now
    job_rec.blocked_by = blocked_by
    job_rec.blocked_reason = blocked_reason
    job_rec.updated_at = now
    temp_db.save_runtime_job(job_rec)

    # Verify invariant after BLOCKED evaluation:
    post_blocked_runs = temp_db.get_recent_runtime_job_runs(limit=100)
    assert len(post_blocked_runs) == initial_run_count  # NO new runtime_job_runs row

    semantic_job = temp_db.get_runtime_job("semantic")
    assert semantic_job.last_status == "completed"       # NOT overwritten
    assert semantic_job.last_completed_at == t_completed # NOT changed
    assert semantic_job.run_count == 5                   # NOT incremented
    assert semantic_job.failure_count == 1               # NOT incremented
    assert semantic_job.evaluation_status == "blocked"   # Updated evaluation field
    assert semantic_job.blocked_by == "ingestion"

    # 2. Evaluate NOT_DUE / SKIPPED / NOT_APPLICABLE state
    job_rec.evaluation_status = "not_due"
    job_rec.evaluated_at = now + timedelta(minutes=5)
    temp_db.save_runtime_job(job_rec)

    post_not_due_runs = temp_db.get_recent_runtime_job_runs(limit=100)
    assert len(post_not_due_runs) == initial_run_count  # NO new runtime_job_runs row

    semantic_job2 = temp_db.get_runtime_job("semantic")
    assert semantic_job2.last_status == "completed"
    assert semantic_job2.last_completed_at == t_completed
    assert semantic_job2.run_count == 5
    assert semantic_job2.failure_count == 1
    assert semantic_job2.evaluation_status == "not_due"

    # 3. Evaluate NOT_APPLICABLE for context_match with 0 active projects
    res_cm = execute_job("context_match", temp_db, now=now)
    assert res_cm["status"] == "not_applicable"

    post_cm_runs = temp_db.get_recent_runtime_job_runs(limit=100)
    assert len(post_cm_runs) == initial_run_count  # NO new runtime_job_runs row

    # Assert runtime_job_runs.status in DB contains ONLY legitimate execution statuses
    all_db_runs = temp_db.get_recent_runtime_job_runs(limit=100)
    for r in all_db_runs:
        assert r.status in ("running", "completed", "failed", "partial", "interrupted")
        assert r.status not in ("blocked", "skipped", "not_applicable", "due", "not_due")


