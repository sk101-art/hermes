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
