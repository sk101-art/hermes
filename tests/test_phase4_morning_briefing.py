"""Phase 4 — Requirement 5: Morning Briefing guaranteed every day.

Proves:
1. A quiet day persists a completed_empty briefing snapshot (zero items,
   never padded) AND a completed_empty DailySignalRun.
2. A day with qualifying items persists a completed run + briefing with items.
3. Source failures yield a partial_sources run status.
4. A pipeline exception persists a failed run record; a subsequent retry
   increments retry_count and settles the day.
5. A settled (completed) day is never re-run (already_completed).
6. Refreshing a successful briefing creates immutable revisions instead of
   replacing it; original_generated_at is preserved.
7. /briefing exposes daily_run, revision_count, last_successful_briefing_date
   and source_contribution.
8. On a failed day /briefing returns 200 with the failed daily-run state,
   sanitized error, next retry time and last-successful link (not 404).
9. get_last_successful_briefing_date skips failed/absent days.

All tests use isolated temporary databases — never the tracked baseline.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.inbox.briefing import generate_morning_briefing
from app.models.schemas import DailyBriefing, DailySignalRun, InboxItem
from app.runtime import jobs
from app.storage.db import Database

UTC = timezone.utc

TODAY = "2026-08-26"
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _make_db(tmp_path: Path, name: str = "briefing5.db") -> Database:
    return Database(db_path=str(tmp_path / name))


def _utc_config() -> dict:
    return {
        "timezone": "UTC",
        "jobs": {
            "daily_refresh": {
                "time": "07:00",
                "timeout_minutes": 60,
                "max_retries": 8,
                "retry_interval_minutes": 15,
            },
            "morning_brief": {"time": "07:30", "timeout_minutes": 30},
        },
        "sources": {},
    }


def _mock_stages(monkeypatch, sources_failed=None, ingest_error=None):
    """Mock the six upstream pipeline stages; inbox + briefing stay real."""
    if ingest_error is not None:
        def _boom(*a, **k):
            raise ingest_error
        monkeypatch.setattr(jobs, "run_source_ingestion", _boom)
    else:
        monkeypatch.setattr(
            jobs,
            "run_source_ingestion",
            lambda *a, **k: {
                "status": "completed",
                "sources_polled": ["github", "hacker_news"],
                "sources_skipped": [],
                "sources_failed": sources_failed or [],
                "events_ingested": 0,
            },
        )
    monkeypatch.setattr(jobs, "run_semantic_processing", lambda *a, **k: {"status": "completed", "events_processed": 0})
    monkeypatch.setattr(jobs, "run_claims_processing", lambda *a, **k: {"status": "completed"})
    monkeypatch.setattr(jobs, "run_longitudinal_recheck", lambda *a, **k: {"status": "completed"})
    monkeypatch.setattr(jobs, "run_context_scan", lambda *a, **k: {"status": "completed"})
    monkeypatch.setattr(jobs, "run_context_match", lambda *a, **k: {"status": "completed"})


def _seed_qualifying_inbox_item(db, item_id="ii:qualify", surface_date=TODAY):
    db.save_inbox_item(InboxItem(
        id=item_id,
        entity_type="cluster",
        entity_id=f"cl:{item_id}",
        story_cluster_id=f"cl:{item_id}",
        title="Qualifying intelligence signal",
        section="must_know",
        inbox_score=0.9,
        state="unseen",
        created_at=NOW,
        expires_at=NOW + timedelta(days=2),
        surface_date=surface_date,
        freshness_kind="new",
        freshness_reason="first_seen_today",
        first_seen_at=NOW,
        last_evaluated_at=NOW,
        surfaced_at=NOW,
        daily_run_id=f"daily-run:{surface_date}",
    ))


def _seed_briefing(db, date_str, status, total_items=0, source_status_json=None):
    briefing = DailyBriefing(
        id=f"briefing:{date_str}",
        briefing_date=date_str,
        generated_at=NOW,
        total_items=total_items,
        content_hash=f"hash:{date_str}",
        summary_text=f"Briefing for {date_str}",
        sections={},
        runtime_timezone="UTC",
        generation_status=status,
        source_status_json=source_status_json,
        daily_run_id=f"daily-run:{date_str}",
        original_generated_at=NOW.isoformat(),
    )
    db.save_daily_briefing_with_items(briefing, [])
    return briefing


# ---------------------------------------------------------------------------
# 1. Quiet day -> completed_empty briefing snapshot + completed_empty run
# ---------------------------------------------------------------------------

def test_quiet_day_persists_completed_empty_snapshot(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "quiet.db")
    _mock_stages(monkeypatch)

    res = jobs.run_daily_refresh(db=db, now=NOW, surface_date=TODAY)
    assert res["status"] == "completed"

    run = db.get_daily_signal_run_by_date(TODAY)
    assert run is not None
    assert run.status == "completed_empty"
    assert run.briefing_id == f"briefing:{TODAY}"

    briefing = db.get_daily_briefing(TODAY)
    assert briefing is not None
    assert briefing.generation_status == "completed_empty"
    assert briefing.total_items == 0
    db.close()


# ---------------------------------------------------------------------------
# 2. Day with qualifying items -> completed run + briefing with items
# ---------------------------------------------------------------------------

def test_qualifying_day_persists_completed_briefing(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "qualify.db")
    _seed_qualifying_inbox_item(db)
    _mock_stages(monkeypatch)

    res = jobs.run_daily_refresh(db=db, now=NOW, surface_date=TODAY)
    assert res["status"] == "completed"

    run = db.get_daily_signal_run_by_date(TODAY)
    assert run is not None
    assert run.status == "completed"

    briefing = db.get_daily_briefing(TODAY)
    assert briefing is not None
    assert briefing.generation_status == "completed"
    assert briefing.total_items == 1
    db.close()


# ---------------------------------------------------------------------------
# 3. Source failure -> partial_sources
# ---------------------------------------------------------------------------

def test_source_failure_yields_partial_sources(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "partial.db")
    _mock_stages(monkeypatch, sources_failed=["github"])

    res = jobs.run_daily_refresh(db=db, now=NOW, surface_date=TODAY)
    assert res["status"] == "completed"

    run = db.get_daily_signal_run_by_date(TODAY)
    assert run is not None
    assert run.status == "partial_sources"
    parsed = json.loads(run.source_status_json)
    assert parsed["sources_failed"] == ["github"]
    db.close()


# ---------------------------------------------------------------------------
# 4. Pipeline exception -> failed run; retry increments retry_count
# ---------------------------------------------------------------------------

def test_pipeline_exception_records_failed_run_and_retry(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "failed.db")
    _mock_stages(monkeypatch, ingest_error=RuntimeError("simulated pipeline failure"))

    with pytest.raises(RuntimeError):
        jobs.run_daily_refresh(db=db, now=NOW, surface_date=TODAY)

    failed_run = db.get_daily_signal_run_by_date(TODAY)
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.retry_count == 0
    assert failed_run.error_summary is not None
    assert "simulated pipeline failure" in failed_run.error_summary
    assert failed_run.briefing_id is None

    # Retry with fixed pipeline: same run id, retry_count incremented.
    _mock_stages(monkeypatch)
    res = jobs.run_daily_refresh(db=db, now=NOW, surface_date=TODAY)
    assert res["status"] == "completed"

    retried = db.get_daily_signal_run_by_date(TODAY)
    assert retried is not None
    assert retried.status == "completed_empty"
    assert retried.retry_count == 1
    assert retried.id == failed_run.id
    db.close()


# ---------------------------------------------------------------------------
# 5. Settled day is never re-run
# ---------------------------------------------------------------------------

def test_settled_day_returns_already_completed(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "settled.db")
    _mock_stages(monkeypatch)

    first = jobs.run_daily_refresh(db=db, now=NOW, surface_date=TODAY)
    assert first["status"] == "completed"

    def _explode(*a, **k):
        raise AssertionError("settled day must not re-run any pipeline stage")

    monkeypatch.setattr(jobs, "run_source_ingestion", _explode)
    second = jobs.run_daily_refresh(db=db, now=NOW, surface_date=TODAY)
    assert second["status"] == "already_completed"
    assert second["surface_date"] == TODAY
    db.close()


# ---------------------------------------------------------------------------
# 6. Refreshing a successful briefing creates revisions, preserves original
# ---------------------------------------------------------------------------

def test_refresh_creates_revisions_and_preserves_original(tmp_path):
    db = _make_db(tmp_path, "revisions.db")
    _seed_qualifying_inbox_item(db)

    original = generate_morning_briefing(db=db, target_date=TODAY, now=NOW)
    assert original.generation_status == "completed"
    original_generated_at = original.original_generated_at
    assert original_generated_at is not None
    assert db.count_briefing_revisions(original.id) == 0

    # First refresh: prior successful snapshot must be preserved as a revision.
    generate_morning_briefing(db=db, target_date=TODAY, refresh=True, now=NOW + timedelta(minutes=5))
    assert db.count_briefing_revisions(original.id) >= 1

    # Second refresh: another revision; original_generated_at never moves.
    refreshed = generate_morning_briefing(db=db, target_date=TODAY, refresh=True, now=NOW + timedelta(minutes=10))
    assert db.count_briefing_revisions(original.id) >= 2
    assert refreshed.id == original.id
    assert refreshed.original_generated_at == original_generated_at
    db.close()


# ---------------------------------------------------------------------------
# 7. /briefing API exposes the enriched Req 5 fields
# ---------------------------------------------------------------------------

def test_briefing_api_exposes_enriched_fields(tmp_path, monkeypatch):
    db_file = tmp_path / "api_briefing.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))
    monkeypatch.setenv("HERMES_TEST_INSTANCE_ID", "phase4-req5")

    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "load_runtime_config", lambda *a, **k: _utc_config())

    prior_day = "2026-08-25"
    db = Database(db_path=str(db_file))
    _seed_briefing(db, prior_day, "completed", total_items=2)

    run = DailySignalRun(
        id=f"daily-run:{TODAY}",
        runtime_date=TODAY,
        runtime_timezone="UTC",
        run_kind="daily_refresh",
        started_at=NOW - timedelta(hours=1),
        completed_at=NOW,
        status="completed",
        briefing_id=f"briefing:{TODAY}",
        source_status_json=json.dumps({
            "sources_polled": ["github", "hacker_news"],
            "sources_skipped": ["arxiv"],
            "sources_failed": [],
        }),
        content_hash=f"{TODAY}:completed",
    )
    db.save_daily_signal_run(run)
    # source_status_json left None so the run-level contribution is used.
    _seed_briefing(db, TODAY, "completed", total_items=1)
    db.close()

    client = TestClient(app)
    resp = client.get(f"/briefing?date={TODAY}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["daily_run"] is not None
    assert data["daily_run"]["id"] == f"daily-run:{TODAY}"
    assert data["daily_run"]["status"] == "completed"
    assert data["revision_count"] == 0
    assert data["last_successful_briefing_date"] == prior_day
    assert data["source_contribution"]["sources_polled"] == ["github", "hacker_news"]
    assert data["source_contribution"]["sources_skipped"] == ["arxiv"]
    assert data["source_contribution"]["sources_failed"] == []


# ---------------------------------------------------------------------------
# 8. Failed-day /briefing: 200 with failed state, sanitized error, retry
# ---------------------------------------------------------------------------

def test_briefing_api_failed_day_visibility(tmp_path, monkeypatch):
    db_file = tmp_path / "api_failed.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))
    monkeypatch.setenv("HERMES_TEST_INSTANCE_ID", "phase4-req5")

    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "load_runtime_config", lambda *a, **k: _utc_config())

    prior_day = "2026-08-25"
    failed_at = NOW - timedelta(minutes=30)
    db = Database(db_path=str(db_file))
    _seed_briefing(db, prior_day, "completed", total_items=2)
    db.save_daily_signal_run(DailySignalRun(
        id=f"daily-run:{TODAY}",
        runtime_date=TODAY,
        runtime_timezone="UTC",
        run_kind="daily_refresh",
        started_at=NOW - timedelta(hours=1),
        completed_at=failed_at,
        status="failed",
        error_summary="Connection failed: api_key=supersecret123",
        content_hash=f"{TODAY}:failed",
    ))
    db.close()

    client = TestClient(app)
    resp = client.get(f"/briefing?date={TODAY}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["briefing_date"] == TODAY
    assert data["generation_status"] == "failed"
    assert data["sections"] == {}
    assert data["total_items"] == 0
    assert data["daily_run"]["status"] == "failed"
    # Error must be sanitized — the secret never reaches the client.
    assert "supersecret123" not in json.dumps(data)
    assert "[REDACTED]" in data["daily_run"]["error_summary"]
    # Next retry = failed completed_at + retry_interval_minutes (15).
    expected_retry = (failed_at + timedelta(minutes=15)).isoformat()
    assert data["next_retry_at"] == expected_retry
    # Last successful briefing link skips the failed day.
    assert data["last_successful_briefing_date"] == prior_day

    # A date with neither briefing nor daily run still returns 404.
    resp404 = client.get("/briefing?date=2026-08-20")
    assert resp404.status_code == 404


# ---------------------------------------------------------------------------
# 9. get_last_successful_briefing_date skips failed/absent days
# ---------------------------------------------------------------------------

def test_last_successful_briefing_date_skips_failed_days(tmp_path):
    db = _make_db(tmp_path, "lastsuccess.db")
    _seed_briefing(db, "2026-08-20", "completed", total_items=3)
    _seed_briefing(db, "2026-08-21", "failed")
    _seed_briefing(db, "2026-08-22", "completed_empty")
    # 2026-08-23 intentionally absent.

    # completed_empty counts as a successful (truthful quiet) day.
    assert db.get_last_successful_briefing_date("2026-08-24") == "2026-08-22"
    # Failed day is skipped; absent day is skipped.
    assert db.get_last_successful_briefing_date("2026-08-22") == "2026-08-20"
    # Strictly-before semantics: nothing before the first success.
    assert db.get_last_successful_briefing_date("2026-08-20") is None
    db.close()
