import json
import os
import tempfile
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.backup import create_database_backup, prune_old_backups, verify_backup
from app.models.schemas import DailyBriefing, RuntimeJobRun, SourceCheckpoint, StoryCluster
from app.runtime.health import check_system_health
from app.runtime.install_windows import build_task_parameters, install_scheduled_task
from app.runtime.locks import SingleInstanceLock
from app.runtime.scheduler import execute_job, is_job_due, run_all_due_jobs
from app.runtime.state import (
    is_heartbeat_alive,
    is_source_due,
    load_runtime_config,
    record_source_failure,
    record_source_success,
    recover_interrupted_jobs,
    write_heartbeat,
)
from app.storage.db import Database


@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path=path)
    yield db
    try:
        db.close()
        os.remove(path)
    except Exception:
        pass


def test_single_instance_lock_refuses_second_process(tmp_path):
    lock_file = tmp_path / "hermes.lock"
    lock1 = SingleInstanceLock(lock_path=str(lock_file))
    assert lock1.acquire() is True
    assert lock_file.exists()

    # Second lock with simulated other active PID
    lock2 = SingleInstanceLock(lock_path=str(lock_file))
    lock2.owner_pid = 999999  # Different PID

    # Mock is_pid_alive to return True for lock1.owner_pid
    with patch("app.runtime.locks.is_pid_alive", return_value=True):
        assert lock2.acquire() is False

    lock1.release()
    assert not lock_file.exists()


def test_stale_lock_recovery(tmp_path):
    lock_file = tmp_path / "hermes.lock"
    payload = {"pid": 999998, "created_at": "2026-01-01T00:00:00Z", "hostname": "old-host"}
    lock_file.write_text(json.dumps(payload), encoding="utf-8")

    lock = SingleInstanceLock(lock_path=str(lock_file))
    # PID 999998 is not alive
    with patch("app.runtime.locks.is_pid_alive", return_value=False):
        assert lock.acquire() is True
        info = lock.get_lock_info()
        assert info["pid"] == os.getpid()

    lock.release()


def test_source_checkpoint_failure_and_retry_backoff(test_db):
    now = datetime.now(timezone.utc)
    source = "arxiv"

    cp1 = record_source_failure(source, "HTTP 500 Server Error", test_db, now=now)
    assert cp1.consecutive_failures == 1
    assert cp1.last_error == "HTTP 500 Server Error"
    assert cp1.next_retry_at is not None
    # First failure -> 15 min backoff
    assert cp1.next_retry_at == now + timedelta(minutes=15)

    # Check due logic immediately after failure -> should be delayed
    due, reason = is_source_due(source, test_db, now=now + timedelta(minutes=5))
    assert due is False
    assert "BACKOFF_DELAY" in reason

    # After retry delay elapsed -> should become due
    due_after, _ = is_source_due(source, test_db, now=now + timedelta(minutes=16))
    assert due_after is True


def test_source_checkpoint_success_resets_failures(test_db):
    now = datetime.now(timezone.utc)
    source = "github"

    # Pre-record failures
    record_source_failure(source, "Network Timeout", test_db, now=now)
    record_source_failure(source, "Network Timeout", test_db, now=now)
    cp_fail = test_db.get_source_checkpoint(source)
    assert cp_fail.consecutive_failures == 2

    # Record success
    cp_succ = record_source_success(source, test_db, cursor="cursor_123", now=now + timedelta(minutes=20))
    assert cp_succ.consecutive_failures == 0
    assert cp_succ.last_error is None
    assert cp_succ.health_status == "healthy"
    assert cp_succ.last_cursor == "cursor_123"


def test_source_not_due_skipped(test_db):
    now = datetime.now(timezone.utc)
    source = "openalex"

    record_source_success(source, test_db, now=now)

    cfg = {"sources": {"openalex": {"interval_minutes": 180}}}
    # 30 mins later -> not due
    due, reason = is_source_due(source, test_db, now=now + timedelta(minutes=30), config=cfg)
    assert due is False
    assert "SKIPPED_NOT_DUE" in reason

    # 181 mins later -> due
    due_after, reason_after = is_source_due(source, test_db, now=now + timedelta(minutes=181), config=cfg)
    assert due_after is True
    assert reason_after == "DUE"


def test_missed_morning_run_detection(test_db):
    now = datetime.now(timezone.utc).replace(hour=9, minute=15)  # 09:15 AM
    cfg = {"jobs": {"morning_brief": {"time": "07:30"}}}

    # No briefing exists for today -> missed morning run must trigger!
    due, reason = is_job_due("morning_brief", test_db, now=now, config=cfg)
    assert due is True
    assert "MISSED_OR_DUE_TODAY" in reason


def test_morning_already_complete_skipped(test_db):
    now = datetime.now(timezone.utc).replace(hour=9, minute=15)
    today_str = now.strftime("%Y-%m-%d")

    # Briefing exists for today
    briefing = DailyBriefing(
        id=f"briefing:{today_str}",
        briefing_date=today_str,
        generated_at=now - timedelta(hours=1),
        total_items=15,
    )
    test_db.save_daily_briefing(briefing)

    cfg = {"jobs": {"morning_brief": {"time": "07:30"}}}
    due, reason = is_job_due("morning_brief", test_db, now=now, config=cfg)
    assert due is False
    assert reason == "ALREADY_COMPLETED_TODAY"


def test_database_backup_and_integrity_verification(test_db, tmp_path):
    # Insert a cluster into test_db
    cl = StoryCluster(id="cluster:backup_test", canonical_title="Backup Verification Cluster", sources=["github"])
    test_db.save_cluster(cl)

    backup_dir = tmp_path / "backups"
    success, bpath, msg = create_database_backup(
        db_path=test_db.db_path,
        backup_dir=str(backup_dir),
        retention_days=7,
    )

    assert success is True
    assert bpath is not None
    assert Path(bpath).exists()

    # Verify backup independently
    is_ok, v_msg = verify_backup(bpath)
    assert is_ok is True

    # Verify row exists in backup
    backup_db = Database(db_path=bpath)
    retrieved = backup_db.get_cluster(cl.id)
    assert retrieved is not None
    assert retrieved.canonical_title == "Backup Verification Cluster"
    backup_db.close()


def test_backup_retention_pruning(tmp_path):
    b_dir = tmp_path / "backups"
    b_dir.mkdir()

    now = datetime.now(timezone.utc)
    old_backup = b_dir / "hermes_20260101_000000.db"
    new_backup = b_dir / "hermes_20260820_000000.db"

    old_backup.write_text("dummy", encoding="utf-8")
    new_backup.write_text("dummy", encoding="utf-8")

    # Set old mtime (30 days ago)
    old_time = (now - timedelta(days=30)).timestamp()
    os.utime(str(old_backup), (old_time, old_time))

    pruned = prune_old_backups(str(b_dir), retention_days=7)
    assert str(old_backup) in pruned
    assert not old_backup.exists()
    assert new_backup.exists()


def test_crash_recovery_marks_interrupted(test_db):
    now = datetime.now(timezone.utc)
    # Simulate a job run that was running when process crashed
    run = RuntimeJobRun(
        id="run:interrupted_test",
        job_name="semantic",
        started_at=now - timedelta(minutes=10),
        status="running",
    )
    test_db.save_runtime_job_run(run)

    recovered = recover_interrupted_jobs(test_db, now=now)
    assert len(recovered) == 1
    assert recovered[0].id == "run:interrupted_test"
    assert recovered[0].status == "interrupted"

    # Verify persisted in database
    runs = test_db.get_recent_runtime_job_runs(limit=10)
    assert runs[0].status == "interrupted"


def test_dry_run_non_mutating(test_db):
    now = datetime.now(timezone.utc)
    cfg = load_runtime_config()

    results = run_all_due_jobs(test_db, dry_run=True, now=now, config=cfg)
    assert len(results) > 0

    # Verify no job runs or source checkpoints were written
    runs = test_db.get_recent_runtime_job_runs()
    assert len(runs) == 0
    cps = test_db.get_all_source_checkpoints()
    assert len(cps) == 0


def test_health_check_offline_degraded_and_db_unhealthy(test_db):
    now = datetime.now(timezone.utc)

    # 1. Mock offline network -> DEGRADED
    with patch("app.runtime.health.check_network_connectivity", return_value=False):
        h = check_system_health(test_db, now=now)
        assert h["status"] == "DEGRADED"
        assert h["network"] == "offline"
        assert h["database"] == "ok"

    # 2. Mock database failure -> UNHEALTHY
    test_db.conn.close()
    with patch("app.runtime.health.check_network_connectivity", return_value=True):
        h_unhealthy = check_system_health(test_db, now=now)
        assert h_unhealthy["status"] == "UNHEALTHY"


def test_heartbeat_lifecycle(tmp_path):
    hb_file = tmp_path / "runtime_heartbeat.json"

    write_heartbeat(status="running", heartbeat_path=str(hb_file))
    assert hb_file.exists()

    with patch("app.runtime.locks.is_pid_alive", return_value=True):
        alive, data = is_heartbeat_alive(max_stale_seconds=60, heartbeat_path=str(hb_file))
        assert alive is True
        assert data["status"] == "running"


def test_windows_install_parameters_and_dry_run():
    task_name, python_exe, working_dir, action_cmd = build_task_parameters()
    assert task_name == "HERMES-Tech-Intelligence"
    assert "python" in python_exe.lower()
    assert Path(working_dir).exists()
    assert python_exe in action_cmd

    # Test dry run without modifying OS Task Scheduler
    success, msg = install_scheduled_task(dry_run=True)
    assert success is True
    assert "Dry-run complete" in msg
