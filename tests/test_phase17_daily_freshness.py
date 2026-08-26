import os
import sqlite3
from datetime import datetime, timezone, timedelta
import pytest
from app.storage.db import Database
from app.runtime.timezone import (
    runtime_now_utc,
    runtime_local_datetime,
    runtime_date_string,
    runtime_day_bounds_utc
)
from app.inbox.generator import generate_daily_inbox
from app.inbox.briefing import generate_morning_briefing
from app.models.schemas import DailySignalRun

def test_daily_freshness_boundaries(tmp_path):
    db_file = str(tmp_path / "test_freshness.db")
    db = Database(db_path=db_file)
    
    # 1. Test timezone helpers
    now = runtime_now_utc()
    local_dt = runtime_local_datetime(now)
    date_str = runtime_date_string(now)
    
    assert len(date_str) == 10  # YYYY-MM-DD
    start_utc, end_utc = runtime_day_bounds_utc(date_str)
    assert start_utc < end_utc
    assert end_utc - start_utc >= timedelta(hours=23, minutes=59)

    # 2. Add sample inbox items and test status classification
    # Let's verify inbox generation works with zero items (completed_empty)
    inbox_res = generate_daily_inbox(db, surface_date=date_str)
    assert inbox_res == []

    # 3. Test generate_morning_briefing with zero items (completed_empty)
    briefing = generate_morning_briefing(
        db,
        target_date=date_str,
        daily_run_id="run-001",
        data_cutoff_at=now
    )
    
    assert briefing is not None
    assert briefing.total_items == 0
    assert briefing.summary_text is not None
    assert briefing.generation_status == "completed_empty"
    assert briefing.daily_run_id == "run-001"
    
    # Verify DB contains the briefing
    stored_briefing = db.get_daily_briefing(date_str)
    assert stored_briefing is not None
    assert stored_briefing.total_items == 0


def test_daily_signal_run_round_trip(tmp_path):
    """Direct DailySignalRun save/load round-trip through the storage layer."""
    db = Database(db_path=str(tmp_path / "roundtrip.db"))
    now = datetime.now(timezone.utc)
    run = DailySignalRun(
        id="daily-run:2026-08-26",
        runtime_date="2026-08-26",
        runtime_timezone="Asia/Kolkata",
        run_kind="daily_refresh",
        started_at=now,
        completed_at=now,
        data_cutoff_at=now,
        status="completed",
        new_signal_count=5,
        updated_signal_count=3,
        carried_signal_count=2,
        retry_count=0,
        briefing_id="briefing:2026-08-26",
        source_status_json='{"sources_polled": []}',
        error_summary=None,
        content_hash="hash-abc",
    )
    assert db.save_daily_signal_run(run) is True

    loaded = db.get_daily_signal_run("daily-run:2026-08-26")
    assert loaded is not None
    assert loaded.id == run.id
    assert loaded.runtime_date == run.runtime_date
    assert loaded.runtime_timezone == run.runtime_timezone
    assert loaded.run_kind == "daily_refresh"
    assert loaded.status == "completed"
    assert loaded.new_signal_count == 5
    assert loaded.updated_signal_count == 3
    assert loaded.carried_signal_count == 2
    assert loaded.briefing_id == "briefing:2026-08-26"
    assert loaded.source_status_json == '{"sources_polled": []}'
    assert loaded.error_summary is None
    assert loaded.content_hash == "hash-abc"
    db.close()


def test_runtime_job_success_and_failure_records(tmp_path, monkeypatch):
    """run_daily_refresh success and failure paths construct canonical DailySignalRun
    records (runtime_date/runtime_timezone/run_kind) that persist to the database."""
    from app.runtime import jobs as jobs_mod

    db_file = str(tmp_path / "jobs.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    db = Database(db_path=db_file)
    now = datetime.now(timezone.utc)

    fake_ingest = {
        "status": "completed",
        "sources_polled": [{"source": "github", "new_events": 1}],
        "sources_skipped": [],
        "sources_failed": [],
        "events_ingested": 1,
    }
    fake_semantic = {"status": "completed", "events_processed": 1}
    fake_claims = {"status": "completed", "claims_processed": 0}
    fake_recheck = {"status": "completed"}
    fake_scan = {"status": "completed"}
    fake_match = {"status": "completed", "matches_created": 0}

    class FakeBriefing:
        id = "briefing:2026-08-26"
        total_items = 0
        generation_status = "completed_empty"
        content_hash = "bh"

    monkeypatch.setattr(jobs_mod, "run_source_ingestion", lambda *a, **k: dict(fake_ingest))
    monkeypatch.setattr(jobs_mod, "run_semantic_processing", lambda *a, **k: dict(fake_semantic))
    monkeypatch.setattr(jobs_mod, "run_claims_processing", lambda *a, **k: dict(fake_claims))
    monkeypatch.setattr(jobs_mod, "run_longitudinal_recheck", lambda *a, **k: dict(fake_recheck))
    monkeypatch.setattr(jobs_mod, "run_context_scan", lambda *a, **k: dict(fake_scan))
    monkeypatch.setattr(jobs_mod, "run_context_match", lambda *a, **k: dict(fake_match))
    monkeypatch.setattr(jobs_mod, "generate_daily_inbox", lambda *a, **k: [])
    monkeypatch.setattr(jobs_mod, "generate_morning_briefing", lambda *a, **k: FakeBriefing())

    res = jobs_mod.run_daily_refresh(
        db=db,
        now=now,
        surface_date="2026-08-26",
        daily_run_id="daily-run:2026-08-26",
        data_cutoff_at=now,
    )
    assert res["status"] == "completed"

    saved = db.get_daily_signal_run("daily-run:2026-08-26")
    assert saved is not None
    assert saved.runtime_date == "2026-08-26"
    assert saved.runtime_timezone  # populated from effective timezone resolution
    assert saved.run_kind == "daily_refresh"
    assert saved.status in ("completed", "partial_sources")
    assert saved.briefing_id == "briefing:2026-08-26"
    assert saved.completed_at is not None
    db.close()

    # Failure path
    db2_file = str(tmp_path / "jobs_fail.db")
    db2 = Database(db_path=db2_file)

    def _boom(*a, **k):
        raise RuntimeError("simulated pipeline failure")

    monkeypatch.setattr(jobs_mod, "run_source_ingestion", _boom)

    with pytest.raises(RuntimeError):
        jobs_mod.run_daily_refresh(
            db=db2,
            now=now,
            surface_date="2026-08-26",
            daily_run_id="daily-run:fail",
            data_cutoff_at=now,
        )

    failed = db2.get_daily_signal_run("daily-run:fail")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.run_kind == "daily_refresh"
    assert failed.runtime_date == "2026-08-26"
    assert failed.runtime_timezone
    assert failed.error_summary is not None and "simulated pipeline failure" in failed.error_summary
    assert failed.completed_at is not None
    db2.close()
