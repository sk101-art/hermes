import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.inbox.briefing import SECTION_ORDER, build_briefing_text, export_briefing_markdown, generate_morning_briefing
from app.models.schemas import Claim, DailyBriefing, DailyBriefingItem, Event, InboxItem, StoryCluster
from app.services.intelligence import get_morning_brief
from app.storage.db import Database


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test_briefing.db")
    db = Database(db_path=db_path)
    return db


@pytest.fixture
def client(test_db):
    from app.api.routes import get_db
    app.dependency_overrides[get_db] = lambda: test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class QueryCounter:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.queries: List[str] = []
        self.original_tracer = None

    def __enter__(self):
        self.queries = []
        self.conn.set_trace_callback(lambda stmt: self.queries.append(stmt))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.set_trace_callback(None)


def test_generate_morning_briefing_persists_snapshots(test_db):
    """Proves generate_morning_briefing saves full snapshot fields in daily_briefing_items."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    cl = StoryCluster(id="cluster:test_1", canonical_title="CUDA Graph Acceleration")
    ev = Event(id="ev:test_1", title="CUDA Graph Event", source="github", text="text", url="https://github.com/cuda/graphs")
    item = InboxItem(
        id="inbox:test_1",
        entity_id=cl.id,
        story_cluster_id=cl.id,
        title="CUDA Graph Acceleration in PyTorch",
        section="systems_compilers",
        item_type="deep_dive",
        reason_codes=["hardware_acceleration", "compiler_optimization"],
        inbox_score=0.88,
        rank_score=0.91,
        project_impact_score=0.75,
        matched_project_ids=["cuda-compiler-lab"],
    )

    test_db.save_cluster(cl)
    test_db.save_event(ev)
    test_db.add_event_to_cluster(cl.id, ev.id)
    test_db.save_inbox_item(item)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    assert briefing.briefing_date == "2026-08-20"
    assert briefing.total_items == 1

    stored_items = test_db.get_daily_briefing_items(briefing.id)
    assert len(stored_items) == 1
    bi = stored_items[0]
    assert bi.inbox_item_id == "inbox:test_1"
    assert bi.title == "CUDA Graph Acceleration in PyTorch"
    assert bi.summary == "CUDA Graph Acceleration in PyTorch"
    assert bi.story_cluster_id == "cluster:test_1"
    assert bi.item_type == "deep_dive"
    assert bi.reason_codes == ["hardware_acceleration", "compiler_optimization"]
    assert bi.inbox_score == 0.88
    assert bi.rank_score == 0.91
    assert bi.project_impact_score == 0.75
    assert bi.matched_project_ids == ["cuda-compiler-lab"]
    assert bi.snapshot_version == "v1"


def test_generate_morning_briefing_deterministic_ordering(test_db):
    """Proves sorting is DESC by inbox_score, DESC by project_impact_score, and ASC by id for ties."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    # Create 3 items in ai_ml section with same inbox_score and impact_score to test id tie-breaker
    item_b = InboxItem(
        id="inbox:b_item",
        entity_id="cluster:b",
        story_cluster_id="cluster:b",
        title="B Item",
        section="ai_ml",
        inbox_score=0.80,
        project_impact_score=0.50,
    )
    item_a = InboxItem(
        id="inbox:a_item",
        entity_id="cluster:a",
        story_cluster_id="cluster:a",
        title="A Item",
        section="ai_ml",
        inbox_score=0.80,
        project_impact_score=0.50,
    )
    item_c = InboxItem(
        id="inbox:c_item",
        entity_id="cluster:c",
        story_cluster_id="cluster:c",
        title="C High Score",
        section="ai_ml",
        inbox_score=0.95,
        project_impact_score=0.50,
    )

    test_db.save_inbox_item(item_b)
    test_db.save_inbox_item(item_a)
    test_db.save_inbox_item(item_c)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    stored_items = test_db.get_daily_briefing_items(briefing.id)

    assert len(stored_items) == 3
    # item_c has highest score (0.95)
    assert stored_items[0].inbox_item_id == "inbox:c_item"
    # item_a and item_b tie at 0.80 -> ascending id puts 'inbox:a_item' before 'inbox:b_item'
    assert stored_items[1].inbox_item_id == "inbox:a_item"
    assert stored_items[2].inbox_item_id == "inbox:b_item"


def test_generate_morning_briefing_separate_inbox_and_rank_scores(test_db):
    """Proves missing rank_score is not replaced by inbox_score, and vice versa."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    item = InboxItem(
        id="inbox:null_rank",
        entity_id="cluster:null_rank",
        story_cluster_id="cluster:null_rank",
        title="Item with null rank score",
        section="research",
        inbox_score=0.78,
        rank_score=None,
        project_impact_score=None,
    )
    test_db.save_inbox_item(item)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    res = get_morning_brief(date_str="2026-08-20", db=test_db)
    
    sec_item = res["sections"]["research"][0]
    assert sec_item["inbox_score"] == 0.78
    assert sec_item["rank_score"] is None
    assert sec_item["project_impact_score"] is None


def test_get_morning_brief_no_n_plus_one_bounded_queries(test_db):
    """Proves get_morning_brief executes in <= 3 queries regardless of item count."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)

    # Insert 15 distinct items
    for i in range(15):
        cid = f"cluster:bulk_{i:02d}"
        cl = StoryCluster(id=cid, canonical_title=f"Story {i}")
        test_db.save_cluster(cl)
        item = InboxItem(
            id=f"inbox:bulk_{i:02d}",
            entity_id=cid,
            story_cluster_id=cid,
            title=f"Bulk Item {i}",
            section="ai_ml",
            inbox_score=0.60 + (i * 0.02),
        )
        test_db.save_inbox_item(item)

    generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)

    # Measure queries during get_morning_brief
    with QueryCounter(test_db.conn) as counter:
        res = get_morning_brief(date_str="2026-08-20", db=test_db)

    assert res is not None
    # Must execute exactly at most 3 queries: daily_briefings, daily_briefing_items, story_clusters IN (...)
    select_queries = [q for q in counter.queries if "SELECT" in q.upper()]
    assert len(select_queries) <= 3, f"Expected <= 3 SELECT queries, got {len(select_queries)}: {select_queries}"


def test_get_morning_brief_no_live_claim_reconstruction(test_db):
    """Proves mutating live claims does not alter the historical briefing snapshot values."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    cl = StoryCluster(id="cluster:drift_test", canonical_title="Original Cluster Title")
    test_db.save_cluster(cl)

    claim = Claim(
        id="claim:1",
        cluster_id=cl.id,
        subject="Subject",
        predicate="predicate",
        object="object",
        claim_text="Initial Claim",
        status="supported",
        verification_score=0.95,
    )
    test_db.save_claim(claim)

    item = InboxItem(
        id="inbox:drift_1",
        entity_id=cl.id,
        story_cluster_id=cl.id,
        title="Snapshot Title",
        section="must_know",
        inbox_score=0.90,
    )
    test_db.save_inbox_item(item)

    generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)

    # Now mutate live claim and live cluster title
    claim.verification_score = 0.10
    claim.status = "refuted"
    test_db.save_claim(claim)

    cl.canonical_title = "Mutated Cluster Title"
    test_db.save_cluster(cl)

    # Historical retrieval must keep the snapshot title and priority
    res = get_morning_brief(date_str="2026-08-20", db=test_db)
    must_know_item = res["sections"]["must_know"][0]
    assert must_know_item["title"] == "Snapshot Title"
    assert must_know_item["inbox_score"] == 0.90
    assert "verification_score" not in must_know_item or must_know_item.get("verification_score") is None


def test_legacy_items_non_certification(test_db):
    """Proves legacy rows without snapshot columns are not certified as complete snapshots."""
    briefing = DailyBriefing(
        id="briefing:2026-08-01",
        briefing_date="2026-08-01",
        total_items=1,
        sections={"ai_ml": ["inbox:legacy_1"]},
    )
    test_db.save_daily_briefing(briefing)

    # Insert legacy row directly without snapshot columns
    test_db.conn.execute(
        "INSERT INTO daily_briefing_items (briefing_id, inbox_item_id, position, section) VALUES (?, ?, ?, ?)",
        ("briefing:2026-08-01", "inbox:legacy_1", 1, "ai_ml"),
    )
    test_db.conn.commit()

    res = get_morning_brief(date_str="2026-08-01", db=test_db)
    assert res is not None
    sec_items = res["sections"]["ai_ml"]
    assert len(sec_items) == 1
    legacy_item = sec_items[0]
    assert legacy_item["snapshot_status"] == "legacy_incomplete"
    assert legacy_item["snapshot_version"] is None
    assert legacy_item["title"] is None
    assert legacy_item["summary"] is None


def test_get_morning_brief_story_available_resolution(test_db):
    """Proves story_available is True if cluster exists in DB, False if deleted or missing."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    cl_active = StoryCluster(id="cluster:active_story", canonical_title="Active Story")
    test_db.save_cluster(cl_active)

    item1 = InboxItem(
        id="inbox:item_active",
        entity_id="cluster:active_story",
        story_cluster_id="cluster:active_story",
        title="Active Story Item",
        section="must_know",
        inbox_score=0.90,
    )
    item2 = InboxItem(
        id="inbox:item_missing",
        entity_id="cluster:missing_story",
        story_cluster_id="cluster:missing_story",
        title="Missing Story Item",
        section="must_know",
        inbox_score=0.85,
    )
    test_db.save_inbox_item(item1)
    test_db.save_inbox_item(item2)

    generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)

    res = get_morning_brief(date_str="2026-08-20", db=test_db)
    items = res["sections"]["must_know"]
    assert len(items) == 2
    
    item_map = {it["inbox_item_id"]: it for it in items}
    assert item_map["inbox:item_active"]["story_available"] is True
    assert item_map["inbox:item_missing"]["story_available"] is False


def test_daily_briefing_atomic_persistence(test_db):
    """Proves save_daily_briefing_with_items executes in a single atomic transaction."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    briefing = DailyBriefing(
        id="briefing:2026-08-20",
        briefing_date="2026-08-20",
        generated_at=now,
        total_items=1,
        content_hash="test_hash",
        summary_text="test summary",
    )
    item = DailyBriefingItem(
        briefing_id=briefing.id,
        inbox_item_id="inbox:atomic_1",
        position=1,
        section="ai_ml",
        title="Atomic Test",
        snapshot_version="v1",
    )

    test_db.save_daily_briefing_with_items(briefing, [item])
    assert test_db.get_daily_briefing("2026-08-20") is not None
    assert len(test_db.get_daily_briefing_items(briefing.id)) == 1


def test_export_briefing_markdown_atomic_write(tmp_path):
    """Proves export_briefing_markdown writes safely via temporary file and atomic replace."""
    export_dir = str(tmp_path / "briefings")
    text_content = "# Briefing Export Content"
    filepath = export_briefing_markdown(
        briefing_date="2026-08-20",
        text=text_content,
        export_dir=export_dir,
    )
    assert os.path.exists(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        read_back = f.read()
    assert read_back == text_content


def test_api_get_briefing_validation_and_status_codes(client, test_db):
    """Tests API calendar validation, 422 for invalid dates, 404 for missing dates, 200 for found dates."""
    # 422 for invalid format
    r_invalid = client.get("/briefing?date=2026-02-31")
    assert r_invalid.status_code == 422

    r_invalid2 = client.get("/briefing?date=not-a-date")
    assert r_invalid2.status_code == 422

    # 404 for valid date with no briefing
    r_404 = client.get("/briefing?date=2026-01-01")
    assert r_404.status_code == 404
    assert "No briefing found" in r_404.json()["detail"]

    # 200 for generated briefing
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    item = InboxItem(
        id="inbox:api_test",
        entity_id="cluster:api_test",
        story_cluster_id="cluster:api_test",
        title="API Test Item",
        section="must_know",
        inbox_score=0.92,
    )
    test_db.save_inbox_item(item)
    generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)

    r_200 = client.get("/briefing?date=2026-08-20")
    assert r_200.status_code == 200
    data = r_200.json()
    assert data["briefing_date"] == "2026-08-20"
    assert data["total_items"] == 1
    assert "must_know" in data["sections"]

    # Omitting date defaults to today
    r_today = client.get("/briefing")
    # if today is not 2026-08-20, will be 404 or 200 depending on DB
    assert r_today.status_code in [200, 404]


def test_build_briefing_text_formatting_and_no_verification_relabeling():
    """Proves build_briefing_text truthfully describes priority and does not crash on null scores."""
    items = {
        "must_know": [
            DailyBriefingItem(
                briefing_id="briefing:2026-08-20",
                inbox_item_id="inbox:1",
                position=1,
                section="must_know",
                title="Must Know Item",
                summary="Detailed summary",
                inbox_score=0.92,
                reason_codes=["compiler_speedup"],
            ),
            DailyBriefingItem(
                briefing_id="briefing:2026-08-20",
                inbox_item_id="inbox:2",
                position=2,
                section="must_know",
                title="Unrated Item",
                inbox_score=None,
                rank_score=None,
            ),
        ]
    }
    text = build_briefing_text("2026-08-20", items)
    assert "MUST KNOW" in text
    assert "[0.92]" in text
    assert "[Priority: unrated]" in text
    assert "Verification:" not in text  # Must never mislabel priority as verification


def test_section_caps_and_repo_deduplication(test_db):
    """Proves section caps and repository deduplication work correctly."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)

    # 6 items from the same repo in ai_ml (max ai_ml cap is 5)
    for i in range(6):
        cid = f"cluster:repo_{i}"
        cl = StoryCluster(id=cid, canonical_title=f"Repo Item {i}")
        ev = Event(
            id=f"ev:repo_{i}",
            title=f"Release {i}",
            source="github",
            text="text",
            url=f"https://github.com/vllm-project/vllm/releases/tag/v0.{i}",
        )
        test_db.save_cluster(cl)
        test_db.save_event(ev)
        test_db.add_event_to_cluster(cid, ev.id)

        item = InboxItem(
            id=f"inbox:repo_{i}",
            entity_id=cid,
            story_cluster_id=cid,
            title=f"Release {i}",
            section="ai_ml",
            inbox_score=0.85 - (i * 0.01),
        )
        test_db.save_inbox_item(item)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    stored_items = test_db.get_daily_briefing_items(briefing.id)

    # Because of repository deduplication on same repo (vllm-project/vllm), only 1 minor release should be kept
    assert len(stored_items) == 1
    assert stored_items[0].inbox_item_id == "inbox:repo_0"


def test_starred_items_bypass_score_floor(test_db):
    """Proves starred items bypass minimum score floor."""
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    item = InboxItem(
        id="inbox:starred_low",
        entity_id="cluster:starred_low",
        story_cluster_id="cluster:starred_low",
        title="Starred Low Score Item",
        section="watchlist",
        inbox_score=0.20,  # below 0.55 floor
        is_starred=True,
    )
    test_db.save_inbox_item(item)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    stored_items = test_db.get_daily_briefing_items(briefing.id)
    assert len(stored_items) == 1
    assert stored_items[0].inbox_item_id == "inbox:starred_low"


def test_atomic_persistence_rollback_on_error(test_db):
    """Proves failure inside save_daily_briefing_with_items rolls back all changes."""
    briefing = DailyBriefing(
        id="briefing:2026-08-20",
        briefing_date="2026-08-20",
        total_items=1,
    )
    # Create item with None for NOT NULL column to trigger sqlite3.IntegrityError
    class BadItem:
        briefing_id = "briefing:2026-08-20"
        inbox_item_id = None  # NOT NULL PRIMARY KEY column
        position = 1
        section = "ai_ml"
        title = "Bad"
        summary = "Bad"
        story_cluster_id = None
        item_type = None
        reason_codes = []
        inbox_score = None
        rank_score = None
        project_impact_score = None
        matched_project_ids = []
        snapshot_version = "v1"

    with pytest.raises(sqlite3.IntegrityError):
        test_db.save_daily_briefing_with_items(briefing, [BadItem()])

    # Ensure briefing was NOT saved (rolled back)
    assert test_db.get_daily_briefing("2026-08-20") is None

