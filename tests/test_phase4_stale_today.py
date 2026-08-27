"""Phase 4 — Requirement 3: Stop stale Today-item reuse.

Proves:
1. The storage layer exposes queries that retrieve inbox items for an EXACT
   surface_date / daily_run_id, and a date-scoped active query that includes
   legacy (NULL surface_date) rows but never dated rows from other days.
2. /inbox defaults to the current runtime-local date and never returns every
   historically active row.
3. At daily materialization, prior-day non-starred active items are suppressed
   WITHOUT deleting history; starred items survive.
4. A quiet day may contain zero items — nothing is padded to a target.
5. Only unresolved high-value / project-critical items carry forward, under an
   explicit configurable cap, labeled carried_forward and never presented as
   newly published / newly released.
6. Materialization returns counts for new, updated, corrected and
   carried-forward items.

All tests use isolated temporary databases — never the tracked baseline.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.inbox.generator import generate_daily_inbox
from app.models.schemas import Claim, Event, InboxItem, StoryCluster
from app.storage.db import Database

UTC = timezone.utc


def _make_db(tmp_path: Path, name: str = "stale.db") -> Database:
    return Database(db_path=str(tmp_path / name))


def _base_inbox_config(**overrides) -> dict:
    cfg = {
        "ttl_hours": 24,
        "discovery_lookback_hours": 36,
        "change_lookback_hours": 36,
        "initial_history_max_days": 7,
        "max_daily_items": 30,
        "min_inbox_score": 0.45,
        "max_must_know": 5,
        "max_project_items_per_project": 6,
        "max_section_items": 6,
        "max_carried_forward": 5,
        "carry_forward_min_score": 0.55,
        "carry_forward_min_project_impact": 0.70,
    }
    cfg.update(overrides)
    return cfg


def _seed_cluster(db, cid, title, score, sources, event_time, v_score=0.70, url=None):
    """Creates a cluster + one github release event + one claim."""
    cluster = StoryCluster(
        id=cid, canonical_title=title, sources=sources, cluster_score=score,
        created_at=event_time,
    )
    ev = Event(
        id=f"ev:{cid}", source="github", event_type="release",
        source_type="release", title=title,
        url=url or f"https://github.com/org/{cid.replace(':', '_')}",
        published_at=event_time,
    )
    claim = Claim(
        id=f"claim:{cid}", cluster_id=cid, claim_type="release",
        assertion_level="artifact_fact", subject="s", predicate="released",
        object="v1", claim_text=f"{title} released", status="supported",
        verification_score=v_score,
    )
    db.save_event(ev)
    db.save_cluster(cluster)
    db.add_event_to_cluster(cid, ev.id)
    db.save_claim(claim)
    return cluster


# ---------------------------------------------------------------------------
# 1. Exact surface_date / daily_run_id storage queries
# ---------------------------------------------------------------------------

def test_exact_surface_date_query_isolates_snapshots(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(UTC)

    def _item(iid, date, state="unseen"):
        return InboxItem(
            id=iid, entity_type="cluster", entity_id=f"cl:{iid}",
            story_cluster_id=f"cl:{iid}", title=f"Item {iid}",
            section="ai_ml", inbox_score=0.7, state=state,
            created_at=now, expires_at=now + timedelta(days=2),
            surface_date=date, daily_run_id=f"daily-run:{date}",
            freshness_kind="new",
        )

    db.save_inbox_item(_item("a", "2026-08-25"))
    db.save_inbox_item(_item("b", "2026-08-26"))
    db.save_inbox_item(_item("c", "2026-08-26", state="expired"))
    # Legacy row with no surface_date
    legacy = _item("legacy", None)
    db.save_inbox_item(legacy)

    day26 = db.get_inbox_items_by_surface_date("2026-08-26")
    assert {it.id for it in day26} == {"b"}  # expired 'c' excluded by default

    day26_all = db.get_inbox_items_by_surface_date("2026-08-26", include_expired=True)
    assert {it.id for it in day26_all} == {"b", "c"}

    day25 = db.get_inbox_items_by_surface_date("2026-08-25")
    assert {it.id for it in day25} == {"a"}

    # No cross-day leakage
    assert all(it.surface_date == "2026-08-26" for it in day26)
    db.close()


def test_exact_daily_run_id_query(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(UTC)

    def _item(iid, run_id):
        return InboxItem(
            id=iid, entity_type="cluster", entity_id=f"cl:{iid}",
            story_cluster_id=f"cl:{iid}", title=f"Item {iid}",
            section="ai_ml", inbox_score=0.7, state="unseen",
            created_at=now, expires_at=now + timedelta(days=2),
            surface_date="2026-08-26", daily_run_id=run_id,
        )

    db.save_inbox_item(_item("r1", "daily-run:2026-08-26"))
    db.save_inbox_item(_item("r2", "daily-run:2026-08-26"))
    db.save_inbox_item(_item("r3", "daily-run:2026-08-25"))

    run26 = db.get_inbox_items_by_daily_run_id("daily-run:2026-08-26")
    assert {it.id for it in run26} == {"r1", "r2"}
    db.close()


def test_active_for_date_includes_legacy_excludes_other_days(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(UTC)

    def _item(iid, date):
        return InboxItem(
            id=iid, entity_type="cluster", entity_id=f"cl:{iid}",
            story_cluster_id=f"cl:{iid}", title=f"Item {iid}",
            section="ai_ml", inbox_score=0.7, state="unseen",
            created_at=now, expires_at=now + timedelta(days=2),
            surface_date=date,
        )

    db.save_inbox_item(_item("today", "2026-08-26"))
    db.save_inbox_item(_item("yesterday", "2026-08-25"))
    db.save_inbox_item(_item("legacy", None))

    active = db.get_active_inbox_items_for_date("2026-08-26")
    assert {it.id for it in active} == {"today", "legacy"}
    assert "yesterday" not in {it.id for it in active}
    db.close()


# ---------------------------------------------------------------------------
# 2. /inbox defaults to the current runtime-local date
# ---------------------------------------------------------------------------

def test_inbox_endpoint_defaults_to_runtime_date(tmp_path, monkeypatch):
    db_file = tmp_path / "api_inbox.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))
    monkeypatch.setenv("HERMES_TEST_INSTANCE_ID", "phase4-req3")

    # Pin the route's runtime config to UTC for a deterministic "today".
    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    db = Database(db_path=str(db_file))
    for iid, date in (("t_today", today), ("t_yesterday", yesterday), ("t_legacy", None)):
        db.save_inbox_item(InboxItem(
            id=iid, entity_type="cluster", entity_id=f"cl:{iid}",
            story_cluster_id=f"cl:{iid}", title=f"Item {iid}",
            section="ai_ml", inbox_score=0.7, state="unseen",
            created_at=now, expires_at=now + timedelta(days=2),
            surface_date=date, freshness_kind="new",
        ))
    db.close()

    client = TestClient(app)
    resp = client.get("/inbox")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    returned_ids = {it["id"] for it in data["inbox_items"]}
    # Today + legacy only; yesterday's dated row must NOT leak into Today.
    assert returned_ids == {"t_today", "t_legacy"}
    assert data["surface_date"] == today
    assert "freshness_counts" in data
    assert data["freshness_counts"]["new"] == 1  # only the dated 'today' row


def test_inbox_endpoint_rejects_invalid_date(tmp_path, monkeypatch):
    db_file = tmp_path / "api_inbox_bad.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))
    monkeypatch.setenv("HERMES_TEST_INSTANCE_ID", "phase4-req3")

    client = TestClient(app)
    resp = client.get("/inbox", params={"date": "not-a-date"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 3. Prior-day suppression without deleting history
# ---------------------------------------------------------------------------

def test_prior_day_nonstarred_suppressed_starred_survives(tmp_path, monkeypatch):
    from app.inbox import generator as gen_mod
    monkeypatch.setattr(gen_mod, "load_inbox_config", lambda: _base_inbox_config())
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    db = _make_db(tmp_path)
    day1_now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    day2_now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    event_time = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

    _seed_cluster(db, "cl:plain", "Plain Story", 0.80, ["github"], event_time)
    _seed_cluster(db, "cl:star", "Starred Story", 0.80, ["github"], event_time)

    # Day 1 materialization
    day1 = generate_daily_inbox(db=db, now=day1_now, surface_date="2026-08-25")
    assert len(day1) == 2

    # Star one item (creates an active SavedItem)
    from app.inbox.lifecycle import star_inbox_item
    star_item = next(it for it in day1 if it.story_cluster_id == "cl:star")
    star_inbox_item(star_item.id, db, now=day1_now)

    # Day 2 materialization with no new signals
    day2 = generate_daily_inbox(db=db, now=day2_now, surface_date="2026-08-26")

    plain_row = db.get_inbox_item("inbox:cl:plain:20260825")
    assert plain_row is not None  # history preserved
    assert plain_row.state == "suppressed"  # not deleted, not active

    # Starred prior-day item must remain active (not suppressed)
    star_row = db.get_inbox_item("inbox:cl:star:20260825")
    assert star_row is not None
    assert star_row.state in ("starred", "unseen", "seen", "opened")

    # The plain prior-day item must not appear as an active Today item
    active_day2_ids = {it.id for it in db.get_active_inbox_items()}
    assert "inbox:cl:plain:20260825" not in active_day2_ids
    db.close()


# ---------------------------------------------------------------------------
# 4. Quiet day = zero items (no padding)
# ---------------------------------------------------------------------------

def test_quiet_day_contains_zero_items(tmp_path, monkeypatch):
    from app.inbox import generator as gen_mod
    monkeypatch.setattr(gen_mod, "load_inbox_config", lambda: _base_inbox_config())
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    db = _make_db(tmp_path)
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    res = generate_daily_inbox(db=db, now=now, surface_date="2026-08-26")
    assert len(res) == 0
    assert res.counts == {"new": 0, "updated": 0, "corrected": 0, "carried_forward": 0}
    db.close()


# ---------------------------------------------------------------------------
# 5. Carry-forward policy: high-value only, explicit cap, labeled
# ---------------------------------------------------------------------------

def test_carry_forward_high_value_only(tmp_path, monkeypatch):
    from app.inbox import generator as gen_mod
    monkeypatch.setattr(gen_mod, "load_inbox_config", lambda: _base_inbox_config())
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    db = _make_db(tmp_path)
    day1_now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    day2_now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    event_time = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

    # High-value: high cluster score + multi-source -> score >= carry_min_score
    _seed_cluster(db, "cl:high", "High Value Story", 0.95,
                  ["github", "hacker_news", "rss"], event_time)
    # Low-value: passes quality floor but below carry_forward_min_score
    _seed_cluster(db, "cl:low", "Low Value Story", 0.70, ["github"], event_time)

    generate_daily_inbox(db=db, now=day1_now, surface_date="2026-08-25")
    day2 = generate_daily_inbox(db=db, now=day2_now, surface_date="2026-08-26")

    carried_ids = {it.story_cluster_id for it in day2 if it.freshness_kind == "carried_forward"}
    assert "cl:high" in carried_ids
    assert "cl:low" not in carried_ids

    # Low-value prior-day item is suppressed with an auditable reason
    low_row = db.get_inbox_item("inbox:cl:low:20260826")
    assert low_row is not None
    assert low_row.state == "suppressed"
    db.close()


def test_carry_forward_explicit_cap(tmp_path, monkeypatch):
    from app.inbox import generator as gen_mod
    monkeypatch.setattr(
        gen_mod, "load_inbox_config",
        lambda: _base_inbox_config(max_carried_forward=1),
    )
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    db = _make_db(tmp_path)
    day1_now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    day2_now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    event_time = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

    # Two high-value candidates; cap=1 admits only the top scorer.
    _seed_cluster(db, "cl:h1", "High One", 0.95, ["github", "hacker_news", "rss"], event_time)
    _seed_cluster(db, "cl:h2", "High Two", 0.90, ["github", "hacker_news", "rss"], event_time)

    generate_daily_inbox(db=db, now=day1_now, surface_date="2026-08-25")
    day2 = generate_daily_inbox(db=db, now=day2_now, surface_date="2026-08-26")

    carried = [it for it in day2 if it.freshness_kind == "carried_forward"]
    assert len(carried) == 1  # explicit cap enforced
    assert day2.counts["carried_forward"] == 1
    db.close()


def test_carried_items_never_presented_as_new(tmp_path, monkeypatch):
    from app.inbox import generator as gen_mod
    monkeypatch.setattr(gen_mod, "load_inbox_config", lambda: _base_inbox_config())
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    db = _make_db(tmp_path)
    day1_now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    day2_now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    event_time = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

    _seed_cluster(db, "cl:carry", "Carried Release", 0.95,
                  ["github", "hacker_news", "rss"], event_time)

    day1 = generate_daily_inbox(db=db, now=day1_now, surface_date="2026-08-25")
    assert day1[0].freshness_kind == "new"
    assert day1[0].item_type == "new_release"

    day2 = generate_daily_inbox(db=db, now=day2_now, surface_date="2026-08-26")
    carried = next(it for it in day2 if it.story_cluster_id == "cl:carry")
    assert carried.freshness_kind == "carried_forward"
    # Never presented as newly released / newly published
    assert carried.item_type not in ("new_release", "new_story")
    assert "carried_forward" in carried.reason_codes
    db.close()


# ---------------------------------------------------------------------------
# 6. Freshness counts: new / updated / corrected / carried_forward
# ---------------------------------------------------------------------------

def test_materialization_returns_freshness_counts(tmp_path, monkeypatch):
    from app.inbox import generator as gen_mod
    monkeypatch.setattr(gen_mod, "load_inbox_config", lambda: _base_inbox_config())
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    db = _make_db(tmp_path)
    day1_now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    day2_now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    event_time = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

    # carried: first seen day 1, no new signal day 2
    _seed_cluster(db, "cl:carry", "Carry Story", 0.95,
                  ["github", "hacker_news", "rss"], event_time)
    # updated: first seen day 1, gains a NEW event on day 2
    _seed_cluster(db, "cl:update", "Update Story", 0.95,
                  ["github", "hacker_news", "rss"], event_time)

    generate_daily_inbox(db=db, now=day1_now, surface_date="2026-08-25")

    # new: first appears ONLY on day 2 (seeded after day-1 materialization)
    new_event_time = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    _seed_cluster(db, "cl:new", "Brand New Story", 0.95,
                  ["github", "hacker_news", "rss"], new_event_time)

    # Add a day-2 event to the "update" cluster so it becomes 'updated'
    upd_ev = Event(
        id="ev:cl:update:day2", source="github", event_type="release",
        source_type="release", title="Update Story v2",
        url="https://github.com/org/cl_update", published_at=new_event_time,
    )
    db.save_event(upd_ev)
    db.add_event_to_cluster("cl:update", upd_ev.id)

    day2 = generate_daily_inbox(db=db, now=day2_now, surface_date="2026-08-26")

    kinds = {it.story_cluster_id: it.freshness_kind for it in day2}
    assert kinds.get("cl:new") == "new"
    assert kinds.get("cl:update") == "updated"
    assert kinds.get("cl:carry") == "carried_forward"

    assert day2.counts["new"] == 1
    assert day2.counts["updated"] == 1
    assert day2.counts["carried_forward"] == 1
    assert day2.counts["corrected"] == 0
    db.close()


def test_run_inbox_generation_returns_counts(tmp_path, monkeypatch):
    from app.inbox import generator as gen_mod
    from app.runtime import jobs as jobs_mod
    monkeypatch.setattr(gen_mod, "load_inbox_config", lambda: _base_inbox_config())

    db = _make_db(tmp_path)
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    event_time = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    _seed_cluster(db, "cl:fresh", "Fresh Story", 0.95,
                  ["github", "hacker_news", "rss"], event_time)

    # run_inbox_generation resolves the runtime date from config; pin to the
    # seeded event's date so the item is 'new'.
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})
    monkeypatch.setattr(jobs_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"}, raising=False)

    res = jobs_mod.run_inbox_generation(db=db, now=now)
    assert res["status"] == "completed"
    assert res["active_inbox_items"] == 1
    assert res["new_items"] == 1
    assert res["updated_items"] == 0
    assert res["corrected_items"] == 0
    assert res["carried_forward_items"] == 0
    db.close()
