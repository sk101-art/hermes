"""Phase 4 — Requirement 4: Correct freshness and provenance.

Proves:
1. "new_release" is only used when an actual release publication/update
   qualifies for the current runtime day.
2. An old publication discovered today is shown as "Newly discovered today",
   never "New Release", and its old source publication time is preserved.
3. Missing publication timestamps remain null end-to-end.
4. Repeated unchanged content is not relabeled new on later days.
5. Freshness/provenance is derived from source/discovery/content evidence,
   never cluster bookkeeping timestamps.
6. The /inbox API exposes the full provenance set.

All tests use isolated temporary databases — never the tracked baseline.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.server import app
from app.inbox.generator import generate_daily_inbox
from app.models.schemas import Claim, Event, InboxItem, StoryCluster
from app.storage.db import Database

UTC = timezone.utc


def _make_db(tmp_path: Path, name: str = "provenance.db") -> Database:
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
        # Low enough that a release whose novelty decayed one step (1.0 -> 0.75)
        # after 24h still qualifies for carry-forward; these tests exercise
        # carry-forward labeling/provenance, not the production threshold.
        "carry_forward_min_score": 0.50,
        "carry_forward_min_project_impact": 0.70,
    }
    cfg.update(overrides)
    return cfg


def _seed_release_cluster(
    db,
    cid,
    title,
    published_at,
    discovered_at=None,
    cluster_created_at=None,
    v_score=0.70,
    include_published=True,
):
    """Cluster + one github release event + one supported claim."""
    cluster = StoryCluster(
        id=cid,
        canonical_title=title,
        sources=["github", "hacker_news", "rss"],
        cluster_score=0.85,
        created_at=cluster_created_at or published_at or datetime.now(UTC),
    )
    ev_kwargs = dict(
        id=f"ev:{cid}",
        source="github",
        event_type="release",
        source_type="release",
        title=title,
        url=f"https://github.com/org/{cid.replace(':', '_')}",
    )
    if include_published:
        ev_kwargs["published_at"] = published_at
    if discovered_at is not None:
        ev_kwargs["discovered_at"] = discovered_at
    ev = Event(**ev_kwargs)
    claim = Claim(
        id=f"claim:{cid}",
        cluster_id=cid,
        claim_type="release",
        assertion_level="artifact_fact",
        subject="s",
        predicate="released",
        object="v1",
        claim_text=f"{title} released",
        status="supported",
        verification_score=v_score,
    )
    db.save_event(ev)
    db.save_cluster(cluster)
    db.add_event_to_cluster(cid, ev.id)
    db.save_claim(claim)
    return cluster


def _patch_configs(monkeypatch):
    from app.inbox import generator as gen_mod
    monkeypatch.setattr(gen_mod, "load_inbox_config", lambda: _base_inbox_config())
    monkeypatch.setattr(gen_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})


# ---------------------------------------------------------------------------
# 1. Release published on the current runtime day -> new_release
# ---------------------------------------------------------------------------

def test_release_published_today_is_new_release(tmp_path, monkeypatch):
    _patch_configs(monkeypatch)
    db = _make_db(tmp_path)
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    published = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)

    _seed_release_cluster(db, "cl:rel", "Fresh Release", published, discovered_at=published)

    items = generate_daily_inbox(db=db, lookback_hours=36, now=now, surface_date="2026-08-26")
    assert len(items) == 1
    it = items[0]
    assert it.item_type == "new_release"
    assert it.freshness_kind == "new"
    assert it.source_published_at == published
    assert it.source_updated_at == published
    assert it.latest_event_at == published.isoformat()
    db.close()


# ---------------------------------------------------------------------------
# 2. Old publication discovered today -> Newly discovered today, never
#    "New Release"; old publication time preserved
# ---------------------------------------------------------------------------

def test_old_release_discovered_today_is_newly_discovered(tmp_path, monkeypatch):
    _patch_configs(monkeypatch)
    db = _make_db(tmp_path)
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    old_published = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)  # prior runtime day, inside lookback

    _seed_release_cluster(
        db, "cl:old", "Old Release Found Late", old_published, discovered_at=now
    )

    items = generate_daily_inbox(db=db, lookback_hours=36, now=now, surface_date="2026-08-26")
    assert len(items) == 1
    it = items[0]
    assert it.item_type != "new_release"
    assert it.item_type == "newly_discovered"
    assert "old_release_discovered_today" in it.reason_codes
    # The truthful (old) publication time is preserved, not rewritten to now.
    assert it.source_published_at == old_published
    assert it.freshness_kind == "new"  # new to the inbox, but not a new release
    db.close()


# ---------------------------------------------------------------------------
# 3. Missing publication timestamp stays null end-to-end
# ---------------------------------------------------------------------------

def test_missing_publication_time_stays_null(tmp_path, monkeypatch):
    _patch_configs(monkeypatch)
    db = _make_db(tmp_path)
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    discovered = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)

    _seed_release_cluster(
        db, "cl:nopub", "Release Without Timestamp",
        published_at=None, discovered_at=discovered, include_published=False,
    )

    items = generate_daily_inbox(db=db, lookback_hours=36, now=now, surface_date="2026-08-26")
    assert len(items) == 1
    it = items[0]
    assert it.source_published_at is None
    assert it.source_updated_at is None
    # Never claimed to be a same-day release without publication evidence.
    assert it.item_type != "new_release"
    assert it.item_type == "newly_discovered"
    assert "release_publication_time_missing" in it.reason_codes
    # Latest event evidence comes from discovery time, not bookkeeping.
    assert it.latest_event_at == discovered.isoformat()

    # Persisted row keeps NULL publication time.
    row = db.get_inbox_item(it.id)
    assert row is not None
    assert row.source_published_at is None
    db.close()


# ---------------------------------------------------------------------------
# 4. Repeated unchanged content is not relabeled new
# ---------------------------------------------------------------------------

def test_repeated_unchanged_content_not_relabeled_new(tmp_path, monkeypatch):
    _patch_configs(monkeypatch)
    db = _make_db(tmp_path)
    day1_now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    day2_now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    published = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

    _seed_release_cluster(db, "cl:same", "Unchanged Release", published, discovered_at=published)

    day1 = generate_daily_inbox(db=db, lookback_hours=36, now=day1_now, surface_date="2026-08-25")
    assert len(day1) == 1
    assert day1[0].item_type == "new_release"
    assert day1[0].freshness_kind == "new"

    day2 = generate_daily_inbox(db=db, lookback_hours=36, now=day2_now, surface_date="2026-08-26")
    carried = next(it for it in day2 if it.story_cluster_id == "cl:same")
    assert carried.freshness_kind == "carried_forward"
    assert carried.freshness_reason == "no_new_source_evidence_today"
    assert carried.item_type not in ("new_release", "new_story", "newly_discovered")
    assert "carried_forward" in carried.reason_codes
    # Provenance still points at the original source publication.
    assert carried.source_published_at == published
    db.close()


# ---------------------------------------------------------------------------
# 5. Provenance from source evidence, never cluster bookkeeping timestamps
# ---------------------------------------------------------------------------

def test_provenance_never_uses_cluster_bookkeeping_time(tmp_path, monkeypatch):
    _patch_configs(monkeypatch)
    db = _make_db(tmp_path)
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    old_bookkeeping = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    published = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    discovered = datetime(2026, 8, 26, 8, 30, tzinfo=UTC)

    # Cluster bookkeeping (created_at) is 5 days old; the source event is fresh.
    _seed_release_cluster(
        db, "cl:src", "Source Evidence Wins", published,
        discovered_at=discovered, cluster_created_at=old_bookkeeping,
    )

    items = generate_daily_inbox(db=db, lookback_hours=36, now=now, surface_date="2026-08-26")
    assert len(items) == 1
    it = items[0]
    assert it.source_published_at == published
    assert it.latest_event_at == published.isoformat()
    # First discovery by HERMES is the earliest event discovered_at.
    assert it.first_seen_at == discovered
    # No bookkeeping leakage anywhere.
    assert it.source_published_at != old_bookkeeping
    assert it.latest_event_at != old_bookkeeping.isoformat()
    db.close()


# ---------------------------------------------------------------------------
# 6. /inbox API exposes the full provenance set
# ---------------------------------------------------------------------------

def test_inbox_api_exposes_provenance_fields(tmp_path, monkeypatch):
    db_file = tmp_path / "api_provenance.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))
    monkeypatch.setenv("HERMES_TEST_INSTANCE_ID", "phase4-req4")

    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "load_runtime_config", lambda *a, **k: {"timezone": "UTC"})

    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    published = now - timedelta(hours=2)

    db = Database(db_path=str(db_file))
    db.save_inbox_item(InboxItem(
        id="p_with", entity_type="cluster", entity_id="cl:p_with",
        story_cluster_id="cl:p_with", title="With Provenance",
        section="ai_ml", inbox_score=0.7, state="unseen",
        created_at=now, expires_at=now + timedelta(days=2),
        surface_date=today, freshness_kind="new",
        freshness_reason="first_seen_today",
        source_published_at=published, source_updated_at=published,
        first_seen_at=now - timedelta(hours=3), last_evaluated_at=now,
        surfaced_at=now, latest_event_at=published.isoformat(),
        daily_run_id=f"daily-run:{today}",
    ))
    db.save_inbox_item(InboxItem(
        id="p_without", entity_type="cluster", entity_id="cl:p_without",
        story_cluster_id="cl:p_without", title="Without Publication Time",
        section="ai_ml", inbox_score=0.6, state="unseen",
        created_at=now, expires_at=now + timedelta(days=2),
        surface_date=today, freshness_kind="new",
        freshness_reason="new_to_inbox",
        source_published_at=None, source_updated_at=None,
        first_seen_at=now, last_evaluated_at=now, surfaced_at=now,
        daily_run_id=f"daily-run:{today}",
    ))
    db.close()

    client = TestClient(app)
    resp = client.get("/inbox")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    by_id = {it["id"]: it for it in data["inbox_items"]}

    with_prov = by_id["p_with"]
    for field in (
        "source_published_at", "source_updated_at", "first_seen_at",
        "last_changed_at", "last_evaluated_at", "surfaced_at",
        "freshness_reason",
    ):
        assert field in with_prov, f"missing provenance field: {field}"
    assert with_prov["source_published_at"] == published.isoformat()
    assert with_prov["freshness_reason"] == "first_seen_today"

    without_prov = by_id["p_without"]
    assert without_prov["source_published_at"] is None
    assert without_prov["source_updated_at"] is None
    assert without_prov["freshness_reason"] == "new_to_inbox"
