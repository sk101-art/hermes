import os
import shutil
import tempfile
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.models.schemas import DailyBriefing, Event, SourceCheckpoint
from app.runtime.jobs import (
    generate_scheduled_morning_briefing,
    run_source_ingestion,
)
from app.runtime.sanitization import sanitize_error
from app.runtime.scheduler import is_job_due, run_all_due_jobs
from app.runtime.state import record_source_failure
from app.runtime.timezone import (
    get_effective_timezone,
    runtime_date_string,
    to_runtime_local,
)
from app.storage.db import Database


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_tech_intel.db")
    db = Database(db_path=db_path)
    old_env = os.environ.get("HERMES_DB_PATH")
    os.environ["HERMES_DB_PATH"] = db_path
    yield db
    if old_env is not None:
        os.environ["HERMES_DB_PATH"] = old_env
    else:
        os.environ.pop("HERMES_DB_PATH", None)
    try:
        db.conn.close()
    except Exception:
        pass
    shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# 1. TIMEZONE & CALENDAR DATE TESTS
# =============================================================================

def test_timezone_resolution_and_fallback():
    # Valid IANA
    tz_obj, name, warn = get_effective_timezone({"runtime": {"timezone": "Asia/Kolkata"}})
    assert name == "Asia/Kolkata"
    assert warn is None

    # Invalid IANA -> fallback to UTC with warning
    tz_obj, name, warn = get_effective_timezone({"runtime": {"timezone": "Invalid/Fake_Zone"}})
    assert name == "UTC"
    assert "Invalid timezone" in warn


def test_timezone_naive_datetime_normalization():
    naive_dt = datetime(2026, 8, 24, 12, 0, 0)
    config = {"runtime": {"timezone": "Asia/Kolkata"}}
    local_dt = to_runtime_local(naive_dt, config)
    assert local_dt.tzinfo is not None
    # 12:00 UTC + 5:30 = 17:30 IST
    assert local_dt.hour == 17
    assert local_dt.minute == 30


def test_0200_utc_equals_0730_kolkata_and_is_due(temp_db):
    config = {
        "timezone": "Asia/Kolkata",
        "jobs": {"morning_brief": {"time": "07:30", "timeout_minutes": 30}},
    }
    # 02:00 UTC is exactly 07:30 IST
    now_utc = datetime(2026, 8, 24, 2, 0, 0, tzinfo=timezone.utc)
    due, reason = is_job_due("morning_brief", db=temp_db, now=now_utc, config=config)
    assert due is True
    assert "MISSED_OR_DUE_TODAY" in reason


def test_before_0730_local_is_not_due(temp_db):
    config = {
        "timezone": "Asia/Kolkata",
        "jobs": {"morning_brief": {"time": "07:30", "timeout_minutes": 30}},
    }
    # 01:59 UTC is 07:29 IST (1 minute before schedule)
    now_utc = datetime(2026, 8, 24, 1, 59, 0, tzinfo=timezone.utc)
    due, reason = is_job_due("morning_brief", db=temp_db, now=now_utc, config=config)
    assert due is False
    assert "SCHEDULED_AT_07:30" in reason


def test_starting_after_0730_catches_up_same_day(temp_db):
    config = {
        "timezone": "Asia/Kolkata",
        "jobs": {"morning_brief": {"time": "07:30", "timeout_minutes": 30}},
    }
    # 10:00 UTC is 15:30 IST (later on same day)
    now_utc = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
    due, reason = is_job_due("morning_brief", db=temp_db, now=now_utc, config=config)
    assert due is True
    assert "MISSED_OR_DUE_TODAY" in reason


def test_utc_and_local_dates_differ_boundary(temp_db):
    config = {"timezone": "Asia/Kolkata"}
    # 2026-08-23 20:00 UTC is 2026-08-24 01:30 IST (next calendar day in Kolkata)
    now_utc = datetime(2026, 8, 23, 20, 0, 0, tzinfo=timezone.utc)
    date_str = runtime_date_string(now_utc, config)
    assert date_str == "2026-08-24"


# =============================================================================
# 2. BRIEFING GENERATION, IDEMPOTENCY & EXPORT RECOVERY
# =============================================================================

def test_existing_briefing_and_markdown_already_exists(temp_db, tmp_path):
    target_date = "2026-08-24"
    briefing = DailyBriefing(
        id=f"briefing:{target_date}",
        briefing_date=target_date,
        generated_at=datetime(2026, 8, 24, 8, 0, 0, tzinfo=timezone.utc),
        total_items=5,
        summary_text="# Morning Briefing",
    )
    temp_db.save_daily_briefing(briefing)

    # Create matching markdown file
    export_dir = Path("data/briefings")
    export_dir.mkdir(parents=True, exist_ok=True)
    md_file = export_dir / f"{target_date}.md"
    md_file.write_text("# Morning Briefing", encoding="utf-8")

    now = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
    res = generate_scheduled_morning_briefing(db=temp_db, now=now, target_date=target_date)
    assert res["status"] == "already_exists"
    assert res["total_items"] == 5


def test_existing_briefing_missing_markdown_recovers_without_replacing_rows(temp_db):
    target_date = "2026-08-25"
    briefing = DailyBriefing(
        id=f"briefing:{target_date}",
        briefing_date=target_date,
        generated_at=datetime(2026, 8, 25, 8, 0, 0, tzinfo=timezone.utc),
        total_items=7,
        high_priority_count=2,
        project_relevant_count=3,
        summary_text="# Stored Summary Text",
    )
    temp_db.save_daily_briefing(briefing)

    md_file = Path("data/briefings") / f"{target_date}.md"
    if md_file.exists():
        md_file.unlink()

    now = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)
    res = generate_scheduled_morning_briefing(db=temp_db, now=now, target_date=target_date)

    assert res["status"] == "completed"
    assert res.get("recovered_export") is True
    assert md_file.exists()
    assert "# Stored Summary Text" in md_file.read_text(encoding="utf-8")

    # Verify no row duplication
    all_b = temp_db.conn.execute("SELECT COUNT(*) FROM daily_briefings WHERE briefing_date = ?", (target_date,)).fetchone()[0]
    assert all_b == 1
    md_file.unlink(missing_ok=True)


def test_invalid_target_date_strictly_rejected(temp_db):
    with pytest.raises(ValueError):
        generate_scheduled_morning_briefing(db=temp_db, target_date="invalid-date")


# =============================================================================
# 3. RUNNER HERMES_DB_PATH & READ-ONLY DIAGNOSTIC GUARANTEES
# =============================================================================

def test_runner_respects_hermes_db_path(temp_db, monkeypatch):
    import app.runtime.runner as runner_mod
    monkeypatch.setenv("HERMES_DB_PATH", str(temp_db.db_path))

    with patch("sys.argv", ["runner.py", "--dry-run"]):
        with patch.object(runner_mod, "run_daemon") as mock_run:
            runner_mod.main()
            assert mock_run.called
            assert mock_run.call_args.kwargs["db"].db_path == temp_db.db_path


def test_diagnostic_script_non_mutating(temp_db):
    from scripts.diagnose_sources import run_source_diagnosis

    # Ensure no items/checkpoints exist in temp_db initially
    initial_checkpoints = temp_db.get_all_source_checkpoints_map()
    assert len(initial_checkpoints) == 0

    results = run_source_diagnosis(source_filter="all", limit=1, no_persist=True)
    assert isinstance(results, list)
    assert len(results) > 0

    # Verify DB has zero mutations
    after_checkpoints = temp_db.get_all_source_checkpoints_map()
    assert len(after_checkpoints) == 0


# =============================================================================
# 4. ADAPTER CONTRACTS, ERROR SANITIZATION & INGESTION STAGES
# =============================================================================

def test_sanitize_error_preserves_exception_class_name():
    exc = AttributeError("'dict' object has no attribute 'items'")
    cat, san_msg = sanitize_error(exc)
    assert cat == "schema_error"
    assert "AttributeError" in san_msg


def test_record_source_failure_preserves_category_and_status(temp_db):
    now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    exc = TimeoutError("Connection timed out after 30s")
    cp = record_source_failure("github", exc, temp_db, now=now, error_category="timeout")
    assert cp.last_error_category == "timeout"
    assert cp.health_status == "retrying"


def test_source_ingestion_malformed_fetch_shape(temp_db):
    # Mock adapter where fetch() returns a dict instead of a list
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {"error": "bad shape"}

    factories = {"mock_src": (lambda: mock_adapter, 10)}
    with patch("app.runtime.jobs._get_adapter_factories", return_value=factories):
        with patch("app.runtime.jobs.is_source_due", return_value=(True, "INITIAL_RUN")):
            res = run_source_ingestion(db=temp_db)
            assert res["status"] == "failed"
            assert len(res["sources_failed"]) == 1
            assert res["sources_failed"][0]["stage"] == "validate_fetch_shape"
            assert res["sources_failed"][0]["error_category"] == "schema_error"


def test_source_ingestion_partial_and_failed_items(temp_db):
    # Mock adapter where 1 item is valid and 1 item is malformed
    valid_event = Event(
        id="evt:test:1",
        source="mock_src",
        url="https://example.com/1",
        title="Valid Test Event",
        discovered_at=datetime.now(timezone.utc),
        metadata={},
        raw_payload={},
        authors=["Alice"],
        topics=["ai"],
    )

    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [
        {"valid": True},
        "not-a-dict",  # Malformed item
    ]
    mock_adapter.normalize.side_effect = [valid_event, Exception("normalization failure")]

    factories = {"mock_src": (lambda: mock_adapter, 10)}
    with patch("app.runtime.jobs._get_adapter_factories", return_value=factories):
        with patch("app.runtime.jobs.is_source_due", return_value=(True, "INITIAL_RUN")):
            res = run_source_ingestion(db=temp_db)
            assert res["status"] == "completed"
            assert len(res["sources_polled"]) == 1
            assert res["sources_polled"][0]["items_failed"] == 1
            assert res["sources_polled"][0]["items_normalized"] == 1
