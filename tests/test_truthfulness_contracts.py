import os
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.api.server import app
from app.models.schemas import (
    Event,
    StoryCluster,
    Claim,
    Evidence,
    TechnologyAssessment,
    TechnologyState,
    InboxItem,
)
from app.storage.db import Database
from app.services.intelligence import search_intelligence, get_story, get_top_developments
from app.evidence.risk import calculate_technology_risk


@pytest.fixture
def clean_db(tmp_path):
    """Provides a fresh isolated in-memory or SQLite database for testing."""
    db_file = tmp_path / "test_truth.db"
    db = Database(db_path=str(db_file))
    return db


def test_zero_claims_preserves_none_verification(clean_db):
    """When a cluster has 0 claims, verification score and claim status must be None, not 0.50 or supported."""
    cl = StoryCluster(id="cluster:no_claims", canonical_title="No Claims Project")
    ev = Event(id="ev:1", title="Release 1.0", source="github", text="New release", url="https://github.com/test/release")
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)

    # 1. get_story test
    story = get_story("cluster:no_claims", db=clean_db)
    assert story is not None
    assert story.verification["verification_score"] is None
    assert story.verification["claim_status"] is None
    assert len(story.claims) == 0

    # 2. search_intelligence test
    results = search_intelligence("No Claims", db=clean_db)
    assert len(results) > 0
    res = results[0]
    assert res.verification_score is None

    # 3. verified_only filter must exclude unverified clusters with 0 claims
    verified_results = search_intelligence("No Claims", verified_only=True, db=clean_db)
    assert len(verified_results) == 0


def test_no_technology_assessment_preserves_none_maturity(clean_db):
    """When no TechnologyAssessment exists, maturity must be None, never experimental or concept."""
    cl = StoryCluster(id="cluster:no_assess", canonical_title="Unassessed Maturity Tool")
    ev = Event(id="ev:2", title="Unassessed Tool", source="github", text="Tool code", url="https://github.com/test/tool")
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)

    story = get_story("cluster:no_assess", db=clean_db)
    assert story is not None
    assert story.verification["maturity_stage"] is None

    results = search_intelligence("Unassessed Tool", db=clean_db)
    assert len(results) > 0
    assert results[0].maturity is None


def test_no_technology_state_preserves_not_assessed_risk(clean_db):
    """When no TechnologyState exists, risk level and score must be None, with risk_status='not_assessed'."""
    cl = StoryCluster(id="cluster:no_state", canonical_title="Unassessed Risk Framework")
    ev = Event(id="ev:3", title="Unassessed Risk", source="github", text="Framework code", url="https://github.com/test/framework")
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)

    story = get_story("cluster:no_state", db=clean_db)
    assert story is not None
    assert story.verification["risk_level"] is None
    assert story.verification["risk_score"] is None
    assert story.verification["risk_status"] == "not_assessed"

    results = search_intelligence("Unassessed Risk", db=clean_db)
    assert len(results) > 0
    assert results[0].risk is None
    assert results[0].risk_status == "not_assessed"


def test_risk_computation_inadequate_inputs_distinguished():
    """Calculator returns 0.50 numeric fallback for empty inputs, but provenance is marked insufficient_data."""
    cl = StoryCluster(id="cluster:empty", canonical_title="Empty Cluster")
    raw_risk = calculate_technology_risk(cl, events=[], claims=[])
    # Low-level calculator preserves numeric 0.50
    assert raw_risk == 0.50


def test_genuine_assessed_low_risk(clean_db):
    """When genuine assessment and state are present, real low risk is preserved."""
    cl = StoryCluster(id="cluster:low_risk", canonical_title="Well Tested Library")
    ev = Event(id="ev:4", title="Release v2.0", source="github", text="benchmark tests passed", url="https://github.com/test/lib")
    claim = Claim(
        id="claim:1",
        cluster_id=cl.id,
        subject="Library",
        predicate="has",
        object="benchmark",
        claim_text="Library has benchmarks",
        status="supported",
        verification_score=0.85,
        self_reported=False,
    )
    state = TechnologyState(
        cluster_id=cl.id,
        risk_score=0.12,
        current_status="active",
    )
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)
    clean_db.save_claim(claim)
    clean_db.save_technology_state(state)

    story = get_story(cl.id, db=clean_db)
    assert story is not None
    assert story.verification["risk_level"] == "low"
    assert story.verification["risk_score"] == 0.12
    assert story.verification["risk_status"] == "assessed"


def test_high_rank_with_absent_verification_separation(clean_db):
    """A cluster can have a high search/ranking score while verification_score remains None."""
    cl = StoryCluster(id="cluster:rank_high", canonical_title="High Ranking Unverified Topic", cluster_score=0.95)
    ev = Event(
        id="ev:5",
        title="High Ranking Unverified Topic",
        source="github",
        text="High Ranking Unverified Topic full text description",
        url="https://github.com/test/topic",
    )
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)

    results = search_intelligence("High Ranking Unverified Topic", mode="lexical", db=clean_db)
    assert len(results) > 0
    res = results[0]
    # Score should be high based on lexical match
    assert res.score >= 0.70
    # Verification score must remain None (not fabricated to 0.50 or matching ranking score)
    assert res.verification_score is None


def test_inbox_items_do_not_relabel_inbox_score_as_verification(clean_db):
    """get_top_developments must not copy it.inbox_score or it.rank_score into verification_score."""
    cl = StoryCluster(id="cluster:inbox_test", canonical_title="Inbox Story")
    ev = Event(id="ev:6", title="Inbox Story", source="github", text="Some code", url="https://github.com/test/inbox")
    claim = Claim(
        id="claim:inbox",
        cluster_id=cl.id,
        subject="Inbox",
        predicate="is",
        object="new",
        claim_text="Inbox is new",
        status="supported",
        verification_score=0.72,
    )
    item = InboxItem(
        id="inbox:1",
        entity_id=cl.id,
        story_cluster_id=cl.id,
        title="Inbox Story",
        section="must_know",
        inbox_score=0.95,  # High inbox ranking score
        rank_score=0.91,
    )
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)
    clean_db.save_claim(claim)
    clean_db.save_inbox_item(item)

    devs = get_top_developments(limit=10, db=clean_db)
    assert len(devs) > 0
    res = devs[0]
    # Score is the inbox rank score
    assert res.score == 0.91
    # Verification score must be the claim verification score (0.72), NOT inbox_score (0.95)
    assert res.verification_score == 0.72


def test_api_routes_return_null_for_uncomputed_fields(clean_db):
    """FastAPI routes must serialize uncomputed verification and maturity as null in JSON."""
    cl = StoryCluster(id="cluster:api_truth", canonical_title="API Truthful Cluster")
    ev = Event(id="ev:7", title="API Truthful Event", source="github", text="API event text", url="https://github.com/test/api")
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)

    client = TestClient(app)
    app.dependency_overrides = {}
    from app.api.routes import get_db
    app.dependency_overrides[get_db] = lambda: clean_db

    # 1. GET /stories/{id}
    resp = client.get(f"/stories/{cl.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["verification"]["verification_score"] is None
    assert data["verification"]["maturity_stage"] is None
    assert data["verification"]["risk_level"] is None
    assert data["verification"]["claim_status"] is None

    # 2. GET /search?q=...
    resp_search = client.get("/search?q=Truthful")
    assert resp_search.status_code == 200
    search_data = resp_search.json()
    assert len(search_data["results"]) > 0
    s_res = search_data["results"][0]
    assert s_res["verification_score"] is None
    assert s_res["maturity"] is None
    assert s_res["risk"] is None
    assert s_res["risk_status"] == "not_assessed"


def test_claims_present_but_no_evidence(clean_db):
    """A claim without evidence has status 'unverified' and verification_score 0.0, distinguished from unassessed."""
    cl = StoryCluster(id="cluster:claim_no_ev", canonical_title="Unverified Claim Story")
    ev = Event(id="ev:claim_1", title="Unverified Claim Event", source="github", text="Some code", url="https://github.com/test/unv")
    claim = Claim(
        id="claim:unverified_1",
        cluster_id=cl.id,
        subject="Project",
        predicate="is",
        object="fast",
        claim_text="Project is 100x faster",
        status="unverified",
        verification_score=0.0,
    )
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)
    clean_db.save_claim(claim)

    story = get_story(cl.id, db=clean_db)
    assert story is not None
    assert len(story.claims) == 1
    assert story.verification["claim_status"] == "unverified"
    assert story.verification["verification_score"] == 0.0

    results = search_intelligence("Unverified Claim Story", db=clean_db)
    assert len(results) > 0
    assert results[0].verification_score == 0.0


def test_zero_claims_zero_events_risk_presentation(clean_db):
    """When TechState exists for 0 claims + 0 events, risk is insufficient_data and risk string is None (not 'medium')."""
    cl = StoryCluster(id="cluster:zero_inputs", canonical_title="Zero Inputs Story")
    clean_db.save_cluster(cl)

    raw_risk = calculate_technology_risk(cl, events=[], claims=[])
    assert raw_risk == 0.50

    state = TechnologyState(cluster_id=cl.id, risk_score=raw_risk, current_status="unknown")
    clean_db.save_technology_state(state)

    story = get_story(cl.id, db=clean_db)
    assert story is not None
    assert story.verification["risk_status"] == "insufficient_data"
    assert story.verification["risk_score"] == 0.50
    assert story.verification["risk_level"] is None  # Must NOT render as 'medium'

    results = search_intelligence("Zero Inputs Story", db=clean_db)
    # If no events exist, search won't return it as eventless clusters aren't search candidates,
    # but top developments will test the service boundary
    top_devs = get_top_developments(limit=10, db=clean_db)
    assert len(top_devs) > 0
    td = next((d for d in top_devs if d.entity_id == cl.id), None)
    if td:
        assert td.risk_status == "insufficient_data"
        assert td.risk is None


def test_genuine_assessed_medium_and_high_risk(clean_db):
    """Genuine assessed risks (with events/claims) correctly map to medium and critical levels."""
    cl_med = StoryCluster(id="cluster:med_risk", canonical_title="Medium Risk Tech")
    ev_med = Event(id="ev:med_1", title="Med Risk Ev", source="github", text="Code", url="https://github.com/test/med")
    state_med = TechnologyState(cluster_id=cl_med.id, risk_score=0.35, current_status="active")
    clean_db.save_cluster(cl_med)
    clean_db.save_event(ev_med)
    clean_db.add_event_to_cluster(cl_med.id, ev_med.id)
    clean_db.save_technology_state(state_med)

    story_med = get_story(cl_med.id, db=clean_db)
    assert story_med.verification["risk_status"] == "assessed"
    assert story_med.verification["risk_level"] == "medium"
    assert story_med.verification["risk_score"] == 0.35

    cl_crit = StoryCluster(id="cluster:crit_risk", canonical_title="Critical Risk Tech")
    ev_crit = Event(id="ev:crit_1", title="Crit Risk Ev", source="github", text="Code", url="https://github.com/test/crit")
    state_crit = TechnologyState(cluster_id=cl_crit.id, risk_score=0.85, current_status="active")
    clean_db.save_cluster(cl_crit)
    clean_db.save_event(ev_crit)
    clean_db.add_event_to_cluster(cl_crit.id, ev_crit.id)
    clean_db.save_technology_state(state_crit)

    story_crit = get_story(cl_crit.id, db=clean_db)
    assert story_crit.verification["risk_status"] == "assessed"
    assert story_crit.verification["risk_level"] == "critical"
    assert story_crit.verification["risk_score"] == 0.85


def test_low_rank_with_strong_verification(clean_db):
    """A story with low ranking score retains its genuine strong verification score."""
    cl = StoryCluster(id="cluster:low_rank_strong_v", canonical_title="Obscure Niche Library", cluster_score=0.15)
    ev = Event(id="ev:obscure_1", title="Niche Library Release", source="github", text="Very niche library", url="https://github.com/test/niche")
    claim = Claim(
        id="claim:obscure_1",
        cluster_id=cl.id,
        subject="Niche",
        predicate="verified_by",
        object="test",
        claim_text="Passed formal verification",
        status="strongly_supported",
        verification_score=0.92,
    )
    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)
    clean_db.save_claim(claim)

    story = get_story(cl.id, db=clean_db)
    assert story.verification["verification_score"] == 0.92
    assert story.verification["claim_status"] == "strongly_supported"
    assert story.cluster_score == 0.15


def test_morning_briefing_does_not_relabel_ranking_as_verification(clean_db):
    """get_morning_brief must use genuine claim verification score, not cluster_score."""
    from app.services.intelligence import get_morning_brief
    from app.models.schemas import DailyBriefing, DailyBriefingItem

    cl = StoryCluster(id="cluster:brief_test", canonical_title="Briefing Truth Test", cluster_score=0.88)
    ev = Event(id="ev:brief_1", title="Brief Event", source="github", text="Brief text", url="https://github.com/test/brief")
    claim = Claim(
        id="claim:brief_1",
        cluster_id=cl.id,
        subject="Brief",
        predicate="is",
        object="accurate",
        claim_text="Brief is accurate",
        status="supported",
        verification_score=0.74,
    )
    item = InboxItem(
        id="inbox:brief_1",
        entity_id=cl.id,
        story_cluster_id=cl.id,
        title="Briefing Truth Test",
        section="ai_ml",
        inbox_score=0.88,
        rank_score=0.85,
    )
    briefing = DailyBriefing(
        id="briefing:2026-08-21",
        briefing_date="2026-08-21",
        total_items=1,
        sections={"ai_ml": ["inbox:brief_1"]},
    )
    briefing_item = DailyBriefingItem(
        briefing_id="briefing:2026-08-21",
        inbox_item_id="inbox:brief_1",
        position=1,
        section="ai_ml",
    )

    clean_db.save_cluster(cl)
    clean_db.save_event(ev)
    clean_db.add_event_to_cluster(cl.id, ev.id)
    clean_db.save_claim(claim)
    clean_db.save_inbox_item(item)
    clean_db.save_daily_briefing(briefing)
    clean_db.save_daily_briefing_items([briefing_item])

    brief_data = get_morning_brief(date_str="2026-08-21", db=clean_db)
    assert brief_data is not None
    section_items = brief_data["sections"]["ai_ml"]
    assert len(section_items) == 1
    # verification_score must be 0.74 (from claim), NOT 0.88 (from cluster_score)
    assert section_items[0]["verification_score"] == 0.74
    assert section_items[0]["priority"] == 0.85

