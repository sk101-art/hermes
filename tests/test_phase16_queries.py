import os
import shutil
import tempfile
from datetime import datetime, timezone
import pytest

from app.models.schemas import (
    Claim,
    DailyBriefing,
    DailyBriefingItem,
    Event,
    InboxItem,
    IntelligenceChange,
    Project,
    ProjectMatch,
    SavedItem,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.services.intelligence import get_morning_brief, get_recent_changes, get_top_developments, search_intelligence
from app.services.projects import get_project_intelligence, list_projects
from app.services.runtime import get_runtime_overview
from app.services.saved import get_saved_items
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


class QueryCounter:
    def __init__(self, db: Database):
        self.db = db
        self.queries = []
        self.db.conn.set_trace_callback(self._trace)

    def _trace(self, sql):
        clean = sql.strip()
        if clean and not clean.startswith("--"):
            self.queries.append(clean)

    def reset(self):
        self.queries = []

    @property
    def count(self):
        return len(self.queries)


def seed_cluster_fixtures(db: Database, count: int):
    now = datetime.now(timezone.utc)
    for i in range(count):
        cid = f"cluster:perf:{i}"
        cl = StoryCluster(
            id=cid,
            canonical_title=f"Performance Cluster {i}",
            sources=["github", "arxiv"],
            cluster_score=0.85,
            created_at=now,
        )
        db.save_cluster(cl)

        ev = Event(
            id=f"evt:perf:{i}",
            source="github",
            url=f"https://github.com/org/repo_{i}",
            title=f"Event {i}",
            discovered_at=now,
            metadata={},
            raw_payload={},
            authors=["Alice"],
            topics=["ai"],
        )
        db.save_event(ev)
        db.add_event_to_cluster(cid, ev.id)

        clm = Claim(
            id=f"claim:perf:{i}",
            cluster_id=cid,
            subject=f"tech_{i}",
            predicate="improves",
            object="speed",
            claim_text=f"Claim statement for {i}",
            status="supported",
            verification_score=0.90,
            is_current=True,
            created_at=now,
        )
        db.save_claim(clm)

        assess = TechnologyAssessment(
            cluster_id=cid,
            maturity_stage="production_candidate",
            assessment_score=0.88,
            updated_at=now,
        )
        db.save_technology_assessment(assess)

        ts = TechnologyState(
            cluster_id=cid,
            current_status="supported",
            risk_score=0.15,
            updated_at=now,
        )
        db.save_technology_state(ts)

        inbox = InboxItem(
            id=f"inbox:perf:{i}",
            entity_id=cid,
            story_cluster_id=cid,
            title=f"Inbox Title {i}",
            section="must_know",
            rank_score=0.92,
            project_impact_score=0.85,
            matched_project_ids=["project:alpha"],
            state="active",
            created_at=now,
        )
        db.save_inbox_item(inbox)

        saved = SavedItem(
            id=f"saved:{cid}",
            entity_type="cluster",
            entity_id=cid,
            story_cluster_id=cid,
            inbox_item_id=inbox.id,
            title_snapshot=f"Saved Title {i}",
            saved_at=now,
            verification_snapshot=0.90,
            maturity_snapshot="production_candidate",
            risk_snapshot=0.15,
            claim_status_snapshot="supported",
            risk_status_snapshot="assessed",
            risk_level_snapshot="low",
            user_note=f"Note {i}",
            tags=["perf"],
            project_ids=["project:alpha"],
            is_active=True,
        )
        db.save_saved_item(saved)


def test_top_developments_query_ceiling(temp_db):
    counter = QueryCounter(temp_db)
    counts_by_n = {}

    for n in [1, 10, 50]:
        # Reset DB and seed N items
        temp_db.conn.execute("DELETE FROM inbox_items")
        temp_db.conn.execute("DELETE FROM story_clusters")
        temp_db.conn.execute("DELETE FROM events")
        temp_db.conn.execute("DELETE FROM cluster_events")
        temp_db.conn.execute("DELETE FROM claims")
        temp_db.conn.execute("DELETE FROM technology_assessments")
        temp_db.conn.execute("DELETE FROM technology_states")
        temp_db.conn.commit()

        seed_cluster_fixtures(temp_db, n)
        counter.reset()

        res = get_top_developments(limit=n, db=temp_db)
        counts_by_n[n] = counter.count
        assert len(res) == n

    # Exact query ceiling verification: query count must not scale with N
    # For N=1, 10, 50, all must be <= 10 queries (constant bounded batch)
    assert counts_by_n[1] <= 10
    assert counts_by_n[10] <= 10
    assert counts_by_n[50] <= 10
    # Assert flat bound: N=50 uses no more than 2 queries above N=1
    assert abs(counts_by_n[50] - counts_by_n[10]) <= 2


def test_saved_library_query_ceiling(temp_db):
    counter = QueryCounter(temp_db)
    counts_by_n = {}

    for n in [1, 10, 50]:
        temp_db.conn.execute("DELETE FROM saved_items")
        temp_db.conn.execute("DELETE FROM story_clusters")
        temp_db.conn.execute("DELETE FROM events")
        temp_db.conn.execute("DELETE FROM cluster_events")
        temp_db.conn.execute("DELETE FROM claims")
        temp_db.conn.execute("DELETE FROM technology_assessments")
        temp_db.conn.execute("DELETE FROM technology_states")
        temp_db.conn.commit()

        seed_cluster_fixtures(temp_db, n)
        counter.reset()

        res = get_saved_items(limit=n, include_current=True, db=temp_db)
        counts_by_n[n] = counter.count
        assert len(res) == n

    assert counts_by_n[1] <= 10
    assert counts_by_n[10] <= 10
    assert counts_by_n[50] <= 10
    assert abs(counts_by_n[50] - counts_by_n[10]) <= 2


def test_search_stories_query_ceiling(temp_db):
    counter = QueryCounter(temp_db)
    counts_by_n = {}

    for n in [1, 10, 50]:
        temp_db.conn.execute("DELETE FROM story_clusters")
        temp_db.conn.execute("DELETE FROM events")
        temp_db.conn.execute("DELETE FROM cluster_events")
        temp_db.conn.execute("DELETE FROM claims")
        temp_db.conn.execute("DELETE FROM technology_assessments")
        temp_db.conn.execute("DELETE FROM technology_states")
        temp_db.conn.commit()

        seed_cluster_fixtures(temp_db, n)
        counter.reset()

        res = search_intelligence(query="Performance", mode="lexical", limit=n, db=temp_db)
        counts_by_n[n] = counter.count
        assert len(res) <= n

    assert counts_by_n[1] <= 15
    assert counts_by_n[10] <= 15
    assert counts_by_n[50] <= 15
    assert max(counts_by_n.values()) <= 15


def test_project_intelligence_query_ceiling(temp_db):
    counter = QueryCounter(temp_db)
    counts_by_n = {}
    now = datetime.now(timezone.utc)

    # Seed project
    p = Project(
        id="project:alpha",
        name="Alpha",
        path="/workspace/alpha",
        description="Alpha project",
        languages=["python"],
        frameworks=["fastapi"],
        libraries=[],
        databases=["sqlite"],
        infrastructure=[],
        models=[],
        tools=[],
        topics=["ai"],
        keywords=["performance"],
        is_active=True,
        last_indexed_at=now,
    )
    temp_db.save_project(p)

    for n in [1, 10, 50]:
        temp_db.conn.execute("DELETE FROM story_clusters")
        temp_db.conn.execute("DELETE FROM events")
        temp_db.conn.execute("DELETE FROM cluster_events")
        temp_db.conn.execute("DELETE FROM claims")
        temp_db.conn.execute("DELETE FROM technology_assessments")
        temp_db.conn.execute("DELETE FROM technology_states")
        temp_db.conn.execute("DELETE FROM project_matches")
        temp_db.conn.commit()

        seed_cluster_fixtures(temp_db, n)
        # Seed project matches
        for i in range(n):
            pm = ProjectMatch(
                id=f"pm:alpha:{i}",
                project_id="project:alpha",
                entity_type="cluster",
                entity_id=f"cluster:perf:{i}",
                match_type="vulnerability",
                relevance_score=0.90,
                impact_score=0.85,
                recommendation=f"Update cluster {i}",
                reason_codes=["vulnerability"],
                created_at=now,
                updated_at=now,
            )
            temp_db.save_project_match(pm)

        counter.reset()
        res = get_project_intelligence("project:alpha", limit=n, db=temp_db)
        counts_by_n[n] = counter.count
        assert res is not None
        assert len(res.risks) <= n

    assert counts_by_n[1] <= 25
    assert counts_by_n[10] <= 25
    assert counts_by_n[50] <= 25
    assert counts_by_n[1] == counts_by_n[10] == counts_by_n[50]


def test_morning_brief_query_ceiling(temp_db):
    counter = QueryCounter(temp_db)
    counts_by_n = {}
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    for n in [1, 10, 50]:
        temp_db.conn.execute("DELETE FROM daily_briefings")
        temp_db.conn.execute("DELETE FROM story_clusters")
        temp_db.conn.execute("DELETE FROM events")
        temp_db.conn.execute("DELETE FROM cluster_events")
        temp_db.conn.execute("DELETE FROM claims")
        temp_db.conn.execute("DELETE FROM technology_assessments")
        temp_db.conn.execute("DELETE FROM technology_states")
        temp_db.conn.commit()

        seed_cluster_fixtures(temp_db, n)
        brief_items = [
            DailyBriefingItem(
                briefing_id=f"brief:{date_str}",
                inbox_item_id=f"inbox:perf:{i}",
                position=i,
                cluster_id=f"cluster:perf:{i}",
                title=f"Brief Title {i}",
                summary=f"Brief Summary {i}",
                section="must_know",
                rank_score=0.9,
            )
            for i in range(n)
        ]
        brief = DailyBriefing(
            id=f"brief:{date_str}",
            briefing_date=date_str,
            items=brief_items,
            executive_summary="Executive summary test",
            total_items=n,
            created_at=now,
        )
        temp_db.save_daily_briefing(brief)

        counter.reset()
        res = get_morning_brief(date_str=date_str, db=temp_db)
        counts_by_n[n] = counter.count
        assert res is not None
        assert res.get("total_items") == n

    # Reading a daily briefing must take exactly 1 query regardless of N items
    assert counts_by_n[1] <= 2
    assert counts_by_n[10] <= 2
    assert counts_by_n[50] <= 2
    assert counts_by_n[1] == counts_by_n[10] == counts_by_n[50]
    assert counts_by_n[50] <= 2


def test_changes_query_ceiling(temp_db):
    counter = QueryCounter(temp_db)
    counts_by_n = {}
    now = datetime.now(timezone.utc)

    for n in [1, 10, 50]:
        temp_db.conn.execute("DELETE FROM intelligence_changes")
        temp_db.conn.execute("DELETE FROM claims")
        temp_db.conn.execute("DELETE FROM story_clusters")
        temp_db.conn.commit()

        # Seed N claims and N changes referencing those claims
        for i in range(n):
            cid = f"cluster:chg:{i}"
            clm_id = f"claim:chg:{i}"
            clm = Claim(
                id=clm_id,
                cluster_id=cid,
                subject=f"tech_{i}",
                predicate="advances",
                object="state",
                claim_text=f"Claim text {i}",
                status="supported",
                verification_score=0.88,
                is_current=True,
                created_at=now,
            )
            temp_db.save_claim(clm)

            chg = IntelligenceChange(
                id=f"chg:{i}",
                entity_type="claim",
                entity_id=clm_id,
                change_type="status_change",
                old_value="unverified",
                new_value="supported",
                importance=0.80,
                reason=f"Verification confirmed for {i}",
                created_at=now,
            )
            temp_db.save_intelligence_change(chg)

        counter.reset()
        res = get_recent_changes(hours=24, limit=n, db=temp_db)
        counts_by_n[n] = counter.count
        assert len(res) == n
        # Check that cluster_id is properly resolved for each
        for item in res:
            assert item["cluster_id"] is not None

    # Exact query ceiling verification: batch queries must remain constant regardless of N
    assert counts_by_n[1] <= 5
    assert counts_by_n[10] <= 5
    assert counts_by_n[50] <= 5
    assert counts_by_n[1] == counts_by_n[10] == counts_by_n[50]


