"""Phase 4 — Requirement 2: Autonomous daily intelligence runtime.

Proves:
1. config/runtime.yaml defines the canonical daily_refresh schedule and
   morning_brief remains a separate repair/fallback job.
2. The scheduler runs a missed daily cycle automatically and never
   duplicates a completed cycle on the same runtime day.
3. Failed cycles retry per the configured retry policy; settled days
   (completed / completed_empty / partial_sources) never re-run.
4. process_next_queued_operation() claims, completes, fails, and skips
   queued operations correctly (the canonical worker dispatch).
5. startup_daily_catch_up() inspects daily-run STATUS (not briefing
   existence): skips settled days, waits before the scheduled time, runs
   missed days, and retries failed days only per the retry policy.
6. The supervisor dry-run/status commands work and manage API + daemon as
   separate children; the single-instance lock prevents duplicates; the
   Windows installer dry-run targets the supervisor (no activation).

All tests use isolated temporary databases — never the tracked baseline.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.api import routes
from app.models.schemas import DailySignalRun, RefreshOperation
from app.runtime import install_windows, jobs, runner, scheduler
from app.runtime import locks as runtime_locks
from app.runtime import state as runtime_state
from app.runtime import supervisor
from app.storage.db import Database


def _utc_config(daily_time: str = "07:00") -> dict:
    """Deterministic runtime config pinned to UTC for schedule assertions."""
    return {
        "timezone": "UTC",
        "jobs": {
            "daily_refresh": {
                "time": daily_time,
                "timeout_minutes": 60,
                "max_retries": 8,
                "retry_interval_minutes": 15,
            },
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
        "sources": {},
    }


def _make_db(tmp_path: Path, name: str = "autonomy.db") -> Database:
    return Database(db_path=str(tmp_path / name))


def _make_run(
    date_str: str,
    status: str,
    retry_count: int = 0,
    completed_at=None,
    started_at=None,
    run_id: str = None,
) -> DailySignalRun:
    wall_now = datetime.now(timezone.utc)
    return DailySignalRun(
        id=run_id or f"daily-run:{date_str}",
        runtime_date=date_str,
        runtime_timezone="UTC",
        run_kind="daily_refresh",
        started_at=started_at or (wall_now - timedelta(hours=1)),
        completed_at=completed_at,
        status=status,
        retry_count=retry_count,
        error_summary="simulated failure" if status == "failed" else None,
        content_hash=f"{date_str}:{status}",
    )


def _queued_op(scope: str, op_id: str, now: datetime, target_id: str = None) -> RefreshOperation:
    return RefreshOperation(
        id=op_id,
        scope=scope,
        target_id=target_id,
        status="queued",
        requested_at=now,
    )


# ---------------------------------------------------------------------------
# 1. Canonical configuration
# ---------------------------------------------------------------------------

def test_runtime_yaml_defines_canonical_daily_refresh():
    """daily_refresh is configured with the canonical local schedule and
    morning_brief remains a distinct repair/fallback job."""
    cfg = runtime_state.load_runtime_config()
    dr = cfg["jobs"]["daily_refresh"]
    assert dr["time"] == "07:00"
    assert int(dr["max_retries"]) >= 1
    assert int(dr["retry_interval_minutes"]) >= 1
    assert cfg["jobs"]["morning_brief"]["time"] == "07:30"
    # The canonical pipeline job must be registered with the scheduler.
    assert "daily_refresh" in scheduler.JOB_RUNNERS
    assert scheduler.JOB_RUNNERS["daily_refresh"] is jobs.run_daily_refresh


# ---------------------------------------------------------------------------
# 2. Scheduler runs missed cycles automatically, never duplicates completed
# ---------------------------------------------------------------------------

def test_scheduler_runs_missed_daily_cycle_and_does_not_duplicate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolate heartbeat/lock files
    db = _make_db(tmp_path, "sched.db")
    config = _utc_config("07:00")
    now = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)  # past 07:00 UTC
    executed = []

    def fake_daily(db_, dry_run=False, now=None, **kw):
        executed.append("daily_refresh")
        db_.save_daily_signal_run(_make_run("2026-08-27", "completed", completed_at=now))
        return {"status": "completed"}

    def fake_ok(db_, dry_run=False, now=None, **kw):
        return {"status": "completed"}

    for name in list(scheduler.JOB_RUNNERS):
        monkeypatch.setitem(scheduler.JOB_RUNNERS, name, fake_ok)
    monkeypatch.setitem(scheduler.JOB_RUNNERS, "daily_refresh", fake_daily)

    # Cycle 1: no run record exists and the scheduled time has passed, so the
    # missed daily cycle must execute automatically.
    results = scheduler.run_all_due_jobs(db, now=now, config=config)
    by_name = {r["job_name"]: r for r in results}
    assert by_name["daily_refresh"]["status"] == "completed"
    assert "MISSED_OR_DUE_TODAY" in by_name["daily_refresh"]["reason"]
    assert executed == ["daily_refresh"]
    run = db.get_daily_signal_run_by_date("2026-08-27")
    assert run is not None and run.status == "completed"

    # Cycle 2 (same day): the completed cycle must NOT run again.
    results2 = scheduler.run_all_due_jobs(db, now=now, config=config)
    by_name2 = {r["job_name"]: r for r in results2}
    assert by_name2["daily_refresh"]["status"] == "skipped"
    assert by_name2["daily_refresh"]["reason"] == "ALREADY_COMPLETED_TODAY"
    assert executed == ["daily_refresh"]
    db.close()


def test_is_job_due_daily_refresh_retry_matrix(tmp_path):
    db = _make_db(tmp_path, "matrix.db")
    config = _utc_config("07:00")
    today = "2026-08-27"
    now = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)

    # No run yet, before scheduled time -> wait for the normal schedule.
    due, reason = scheduler.is_job_due(
        "daily_refresh", db, datetime(2026, 8, 27, 6, 0, tzinfo=timezone.utc), config
    )
    assert not due and reason.startswith("SCHEDULED_AT")

    # No run, past scheduled time -> missed cycle is due.
    due, reason = scheduler.is_job_due("daily_refresh", db, now, config)
    assert due and "MISSED_OR_DUE_TODAY" in reason

    # Settled days are never re-run (same run id is replaced each save).
    for settled in ("completed", "completed_empty", "partial_sources"):
        db.save_daily_signal_run(_make_run(today, settled, completed_at=now - timedelta(hours=1)))
        due, reason = scheduler.is_job_due("daily_refresh", db, now, config)
        assert not due and reason == "ALREADY_COMPLETED_TODAY", settled

    # A run already in progress is never double-started.
    db.save_daily_signal_run(_make_run(today, "running", started_at=now - timedelta(minutes=5)))
    due, reason = scheduler.is_job_due("daily_refresh", db, now, config)
    assert not due and reason == "ALREADY_RUNNING_TODAY"

    # Failed 20m ago (>= 15m retry interval) -> retry is due.
    db.save_daily_signal_run(
        _make_run(today, "failed", retry_count=0, completed_at=now - timedelta(minutes=20))
    )
    due, reason = scheduler.is_job_due("daily_refresh", db, now, config)
    assert due and reason.startswith("RETRY_DUE")

    # Failed 5m ago -> still inside the retry interval -> wait.
    db.save_daily_signal_run(
        _make_run(today, "failed", retry_count=1, completed_at=now - timedelta(minutes=5))
    )
    due, reason = scheduler.is_job_due("daily_refresh", db, now, config)
    assert not due and reason.startswith("RETRY_IN_")

    # Retry budget exhausted -> stop retrying for the day.
    db.save_daily_signal_run(
        _make_run(today, "failed", retry_count=8, completed_at=now - timedelta(hours=5))
    )
    due, reason = scheduler.is_job_due("daily_refresh", db, now, config)
    assert not due and reason.startswith("FAILED_MAX_RETRIES_REACHED")
    db.close()


def test_failed_daily_cycle_retries_with_incremented_retry_count(tmp_path, monkeypatch):
    """A failed run is retried through the same pipeline with retry_count+1."""
    db = _make_db(tmp_path, "retry.db")
    now = datetime.now(timezone.utc)
    today = "2026-08-27"
    db.save_daily_signal_run(
        _make_run(
            today,
            "failed",
            retry_count=0,
            started_at=now - timedelta(hours=1),
            completed_at=now - timedelta(minutes=30),
        )
    )

    class FakeBriefing:
        id = f"briefing:{today}"
        content_hash = "bh"
        total_items = 0

    monkeypatch.setattr(
        jobs,
        "run_source_ingestion",
        lambda *a, **k: {
            "status": "completed",
            "sources_polled": [],
            "sources_skipped": [],
            "sources_failed": [],
            "events_ingested": 0,
        },
    )
    monkeypatch.setattr(jobs, "run_semantic_processing", lambda *a, **k: {"status": "completed", "events_processed": 0})
    monkeypatch.setattr(jobs, "run_claims_processing", lambda *a, **k: {"status": "completed"})
    monkeypatch.setattr(jobs, "run_longitudinal_recheck", lambda *a, **k: {"status": "completed"})
    monkeypatch.setattr(jobs, "run_context_scan", lambda *a, **k: {"status": "completed"})
    monkeypatch.setattr(jobs, "run_context_match", lambda *a, **k: {"status": "completed"})
    monkeypatch.setattr(jobs, "generate_daily_inbox", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "generate_morning_briefing", lambda *a, **k: FakeBriefing())

    res = jobs.run_daily_refresh(db=db, now=now, surface_date=today)
    assert res["status"] == "completed"

    saved = db.get_daily_signal_run_by_date(today)
    assert saved is not None
    # Phase 4 Req 5: truthful terminal statuses — a zero-item briefing settles
    # the day as completed_empty, not completed.
    assert saved.status == "completed_empty"
    assert saved.retry_count == 1  # incremented from the failed attempt
    assert saved.briefing_id == f"briefing:{today}"
    db.close()


# ---------------------------------------------------------------------------
# 3. process_next_queued_operation — canonical worker dispatch
# ---------------------------------------------------------------------------

def test_process_next_queued_operation_claims_and_completes(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "ops.db")
    now = datetime.now(timezone.utc)
    calls = []
    monkeypatch.setattr(
        runner, "run_health_check_job",
        lambda *a, **k: calls.append("health") or {"status": "completed"},
    )

    db.save_refresh_operation(_queued_op("health_check", "op:hc-1", now))
    res = runner.process_next_queued_operation(db, worker_id="worker-test", now=now)
    assert res is not None
    assert res["operation_id"] == "op:hc-1"
    assert res["scope"] == "health_check"
    assert res["status"] == "completed"
    assert calls == ["health"]

    stored = db.get_refresh_operation("op:hc-1")
    assert stored.status == "completed"
    assert stored.worker_id == "worker-test"
    assert stored.completed_at is not None
    assert stored.lease_expires_at is None  # lease cleared on completion

    # Queue drained -> no further work.
    assert runner.process_next_queued_operation(db, worker_id="worker-test", now=now) is None
    db.close()


def test_process_next_queued_operation_daily_refresh_and_saved_hydration_scopes(tmp_path, monkeypatch):
    """The user-facing 'Run Daily Refresh' and Saved hydration scopes both
    dispatch through the worker FIFO (earliest requested_at first)."""
    assert "saved_hydration" in routes.VALID_REFRESH_SCOPES
    assert "daily_refresh" in routes.VALID_REFRESH_SCOPES

    db = _make_db(tmp_path, "ops2.db")
    now = datetime.now(timezone.utc)
    calls = []
    monkeypatch.setattr(
        runner, "run_daily_refresh",
        lambda *a, **k: calls.append("daily") or {"status": "completed"},
    )
    monkeypatch.setattr(
        runner, "run_saved_hydration",
        lambda *a, **k: calls.append("saved") or {"status": "completed"},
    )

    db.save_refresh_operation(_queued_op("daily_refresh", "op:dr-1", now))
    db.save_refresh_operation(_queued_op("saved_hydration", "op:sh-1", now + timedelta(seconds=1)))

    r1 = runner.process_next_queued_operation(db, worker_id="w", now=now)
    r2 = runner.process_next_queued_operation(db, worker_id="w", now=now)
    assert r1["operation_id"] == "op:dr-1" and r1["status"] == "completed"
    assert r2["operation_id"] == "op:sh-1" and r2["status"] == "completed"
    assert calls == ["daily", "saved"]
    db.close()


def test_process_next_queued_operation_unknown_scope_fails(tmp_path):
    db = _make_db(tmp_path, "ops3.db")
    now = datetime.now(timezone.utc)
    db.save_refresh_operation(_queued_op("totally_bogus", "op:bad-1", now))

    res = runner.process_next_queued_operation(db, worker_id="w", now=now)
    assert res["status"] == "failed"
    assert "Unknown operation scope" in res["error"]

    stored = db.get_refresh_operation("op:bad-1")
    assert stored.status == "failed"
    assert stored.error_summary and "Unknown operation scope" in stored.error_summary
    db.close()


def test_process_next_queued_operation_scope_exception_marks_failed(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "ops4.db")
    now = datetime.now(timezone.utc)

    def boom(*a, **k):
        raise RuntimeError("simulated worker failure")

    monkeypatch.setattr(runner, "run_health_check_job", boom)
    db.save_refresh_operation(_queued_op("health_check", "op:ex-1", now))

    res = runner.process_next_queued_operation(db, worker_id="w", now=now)
    assert res["status"] == "failed"
    assert "simulated worker failure" in res["error"]

    stored = db.get_refresh_operation("op:ex-1")
    assert stored.status == "failed"
    assert stored.error_summary and "simulated worker failure" in stored.error_summary
    db.close()


def test_process_next_queued_operation_claim_lost_leaves_op_queued(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "ops5.db")
    now = datetime.now(timezone.utc)
    db.save_refresh_operation(_queued_op("health_check", "op:cl-1", now))

    # Simulate another worker winning the claim race.
    monkeypatch.setattr(db, "claim_refresh_operation", lambda *a, **k: False)
    res = runner.process_next_queued_operation(db, worker_id="w", now=now)
    assert res == {"operation_id": "op:cl-1", "status": "skipped", "reason": "claim_lost"}

    # Operation remains queued for the winning worker.
    assert db.get_refresh_operation("op:cl-1").status == "queued"
    db.close()


# ---------------------------------------------------------------------------
# 4. startup_daily_catch_up — daily-run status driven catch-up
# ---------------------------------------------------------------------------

def test_startup_catch_up_skips_settled_days(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = _utc_config("07:00")
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)

    def explode(*a, **k):
        raise AssertionError("run_daily_refresh must not run for a settled day")

    for i, settled in enumerate(("completed", "completed_empty", "partial_sources")):
        db = _make_db(tmp_path, f"settled{i}.db")
        db.save_daily_signal_run(_make_run("2026-08-27", settled, completed_at=now - timedelta(hours=1)))
        monkeypatch.setattr(runner, "run_daily_refresh", explode)
        res = runner.startup_daily_catch_up(db, now=now, config=config)
        assert res["action"] == "skipped", settled
        assert res["reason"] == "ALREADY_COMPLETED_TODAY", settled
        assert res["surface_date"] == "2026-08-27"
        db.close()


def test_startup_catch_up_runs_missed_day(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = _utc_config("07:00")
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    db = _make_db(tmp_path, "missed.db")

    calls = {}

    def fake_refresh(db_, now=None, surface_date=None, **kw):
        calls["surface_date"] = surface_date
        return {"status": "completed"}

    monkeypatch.setattr(runner, "run_daily_refresh", fake_refresh)
    res = runner.startup_daily_catch_up(db, now=now, config=config)
    assert res["action"] == "executed"
    assert "MISSED_OR_DUE_TODAY" in res["reason"]
    assert calls["surface_date"] == "2026-08-27"
    db.close()


def test_startup_catch_up_waits_before_scheduled_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = _utc_config("07:00")
    now = datetime(2026, 8, 27, 6, 30, tzinfo=timezone.utc)  # before 07:00
    db = _make_db(tmp_path, "early.db")

    def explode(*a, **k):
        raise AssertionError("catch-up must not run before the scheduled time")

    monkeypatch.setattr(runner, "run_daily_refresh", explode)
    res = runner.startup_daily_catch_up(db, now=now, config=config)
    assert res["action"] == "skipped"
    assert res["reason"].startswith("SCHEDULED_AT")
    db.close()


def test_startup_catch_up_retries_failed_day_per_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = _utc_config("07:00")
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)

    # Failed 30m ago -> past the 15m retry interval -> catch-up retries.
    db = _make_db(tmp_path, "failedretry.db")
    db.save_daily_signal_run(
        _make_run("2026-08-27", "failed", retry_count=1, completed_at=now - timedelta(minutes=30))
    )
    monkeypatch.setattr(runner, "run_daily_refresh", lambda *a, **k: {"status": "completed"})
    res = runner.startup_daily_catch_up(db, now=now, config=config)
    assert res["action"] == "executed"
    assert res["reason"].startswith("RETRY_DUE")
    db.close()

    # Failed 5m ago -> inside the retry interval -> wait, do not retry yet.
    db2 = _make_db(tmp_path, "failedwait.db")
    db2.save_daily_signal_run(
        _make_run("2026-08-27", "failed", retry_count=1, completed_at=now - timedelta(minutes=5))
    )

    def explode(*a, **k):
        raise AssertionError("must not retry inside the retry interval")

    monkeypatch.setattr(runner, "run_daily_refresh", explode)
    res2 = runner.startup_daily_catch_up(db2, now=now, config=config)
    assert res2["action"] == "skipped"
    assert res2["reason"].startswith("RETRY_IN_")
    db2.close()


# ---------------------------------------------------------------------------
# 5. Supervisor + installer (dry-run only; activation belongs to Phase 5)
# ---------------------------------------------------------------------------

def test_supervisor_dry_run_status_and_child_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    cmds = supervisor.build_child_commands()
    assert set(cmds) == {"api", "daemon"}
    assert "app.api.server" in cmds["api"]
    assert "--port" in cmds["api"]
    assert "app.runtime.runner" in cmds["daemon"]
    # Both children share the same interpreter/env lineage.
    assert cmds["api"][0] == cmds["daemon"][0]

    rc = supervisor.run_supervisor(dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "app.api.server" in out and "app.runtime.runner" in out

    # No state file -> status reports not running (non-zero exit code).
    assert supervisor.supervisor_status() == 1
    assert "Not running" in capsys.readouterr().out

    # CLI dispatch works for the dry-run entry point.
    assert supervisor.main(["--dry-run"]) == 0


def test_supervisor_single_instance_lock_prevents_duplicates(tmp_path, monkeypatch):
    lock_path = tmp_path / "supervisor.lock"
    lock_path.write_text(json.dumps({"pid": 424242}), encoding="utf-8")

    # Another LIVE process holds the lock -> acquire must fail.
    monkeypatch.setattr(runtime_locks, "is_pid_alive", lambda pid: True)
    lock = runtime_locks.SingleInstanceLock(lock_path=str(lock_path))
    assert lock.acquire() is False

    # Stale lock (dead owner) -> recovered and acquired.
    monkeypatch.setattr(runtime_locks, "is_pid_alive", lambda pid: False)
    lock2 = runtime_locks.SingleInstanceLock(lock_path=str(lock_path))
    assert lock2.acquire() is True
    lock2.release()
    assert not lock_path.exists()


def test_windows_installer_dry_run_targets_supervisor(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    task_name, py_exe, wd, action_cmd = install_windows.build_task_parameters()
    assert task_name == install_windows.TASK_NAME
    assert "app.runtime.supervisor" in action_cmd  # supervisor, not bare runner

    ok, msg = install_windows.install_scheduled_task(dry_run=True)
    assert ok is True
    assert "No changes" in msg
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "app.runtime.supervisor" in out
    assert "ONLOGON" in out

    # Uninstall command exists and targets the same task name.
    from app.runtime import uninstall_windows
    assert uninstall_windows.TASK_NAME == task_name
    assert callable(uninstall_windows.uninstall_scheduled_task)
