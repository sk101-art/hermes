import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.api.routes import get_db
from app.evidence.verification import is_independent_evidence
from app.models.schemas import (
    Claim,
    ClaimRevision,
    Event,
    Evidence,
    InboxItem,
    Project,
    ProjectMatch,
    SavedItem,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.services import saved as saved_service
from app.storage.db import Database


@pytest.fixture
def api_test_env():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_api_enrichment.db")
    db = Database(db_path=db_path)
    now = datetime.now(timezone.utc)

    # 1. Standard Rich Story Cluster
    ev1 = Event(
        id="ev_jit_1",
        source="github",
        source_type="code_repository",
        event_type="release",
        title="vLLM v0.4.0 Engine Release",
        text="vLLM v0.4.0 released with chunked prefill and PagedAttention v2.",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.4.0",
        discovered_at=now,
        published_at=now,
        final_score=0.92,
    )
    db.save_event(ev1)

    ev2 = Event(
        id="ev_jit_2",
        source="arxiv",
        source_type="academic_paper",
        event_type="paper",
        title="Efficient Memory Management for Large Language Model Serving with PagedAttention",
        text="Academic evaluation demonstrating 2x-4x throughput gains.",
        url="https://arxiv.org/abs/2309.06180",
        discovered_at=now,
        published_at=now,
        final_score=0.88,
    )
    db.save_event(ev2)

    cl1 = StoryCluster(
        id="cluster:vllm_engine",
        canonical_title="vLLM v0.4.0 Engine Architecture",
        event_ids=["ev_jit_1", "ev_jit_2"],
        sources=["github", "arxiv"],
        cluster_score=0.94,
        source_diversity_score=0.75,
        max_event_score=0.92,
        created_at=now,
        updated_at=now,
    )
    db.save_cluster(cl1)
    db.add_event_to_cluster(cl1.id, ev1.id)
    db.add_event_to_cluster(cl1.id, ev2.id)

    c1 = Claim(
        id="claim:vllm_paged_attn",
        cluster_id=cl1.id,
        subject="PagedAttention",
        predicate="improves",
        object="serving throughput by 2x-4x",
        claim_text="PagedAttention improves serving throughput by 2x-4x across diverse workloads",
        claim_type="performance",
        assertion_level="performance_claim",
        status="supported",
        verification_score=0.89,
        self_reported=False,
    )
    db.save_claim(c1)

    c2 = Claim(
        id="claim:vllm_self_rep",
        cluster_id=cl1.id,
        subject="vLLM",
        predicate="claims",
        object="seamless drop-in compatibility",
        claim_text="vLLM claims seamless drop-in OpenAI API compatibility",
        claim_type="compatibility",
        assertion_level="self_reported_claim",
        status="weakly_supported",
        verification_score=0.55,
        self_reported=True,
    )
    db.save_claim(c2)

    evi1 = Evidence(
        id="evi:vllm_ind_rep",
        claim_id=c1.id,
        event_id=ev2.id,
        source="arxiv",
        source_type="academic_paper",
        evidence_type="independent_reproduction",
        evidence_class="secondary",
        stance="supports",
        quality_score=0.95,
        independence_score=0.90,
        reproducibility_score=0.88,
        url="https://arxiv.org/abs/2309.06180",
        excerpt="Independent benchmarks reproduce 2.2x throughput increase.",
    )
    db.save_evidence(evi1)

    evi2 = Evidence(
        id="evi:vllm_ctx",
        claim_id=c2.id,
        event_id=ev1.id,
        source="github",
        source_type="code_repository",
        evidence_type="repository_readme",
        evidence_class="primary",
        stance="context",
        quality_score=0.80,
        independence_score=0.30,
        reproducibility_score=0.50,
        url="https://github.com/vllm-project/vllm",
        excerpt="OpenAI compatible API server documentation.",
    )
    db.save_evidence(evi2)

    ass1 = TechnologyAssessment(
        cluster_id=cl1.id,
        maturity_stage="production_candidate",
        research_score=0.90,
        implementation_score=0.88,
        adoption_score=0.85,
        reproducibility_score=0.88,
        community_score=0.92,
        assessment_score=0.89,
    )
    db.save_technology_assessment(ass1)

    ts1 = TechnologyState(
        cluster_id=cl1.id,
        current_status="active",
        latest_event_at=now,
        latest_release="v0.4.0",
        active_claim_count=2,
        supported_claim_count=1,
        contradicted_claim_count=0,
        superseded_claim_count=0,
        risk_score=0.15,
        trend="stable",
    )
    db.save_technology_state(ts1)

    proj = Project(
        id="project:inference_platform",
        name="Inference Gateway",
        path=os.path.join(temp_dir, "proj_gateway"),
        languages=["Python", "C++"],
        frameworks=["FastAPI", "PyTorch"],
        libraries=["vllm", "transformers"],
        topics=["llm-serving"],
    )
    db.save_project(proj)
    pm = ProjectMatch(
        id="pm:inference_vllm",
        project_id=proj.id,
        entity_type="cluster",
        entity_id=cl1.id,
        relevance_score=0.92,
        impact_score=0.90,
        match_type="direct_dependency",
        recommendation="Upgrade to v0.4.0 for chunked prefill",
    )
    db.save_project_match(pm)

    # 2. Saved Item Snapshot
    saved = SavedItem(
        id="saved:vllm_snap",
        entity_type="cluster",
        entity_id=cl1.id,
        story_cluster_id=cl1.id,
        inbox_item_id="inbox:vllm",
        title_snapshot="vLLM v0.4.0 Historical Title",
        verification_snapshot=0.80,
        maturity_snapshot="experimental",
        risk_snapshot=0.25,
        user_note="Pinned for deployment review",
        tags=["serving", "infrastructure"],
        project_ids=[proj.id],
    )
    db.save_saved_item(saved)

    # 3. Bare Cluster (No claims, no assessment, no tech state)
    cl_bare = StoryCluster(
        id="cluster:bare_tool",
        canonical_title="Bare Diagnostic Tool",
        event_ids=[],
        sources=["github"],
        cluster_score=0.45,
    )
    db.save_cluster(cl_bare)

    # 4. Cluster with Contradiction
    cl_contra = StoryCluster(
        id="cluster:contra_lib",
        canonical_title="Contradicted Async Library",
        event_ids=[],
        sources=["reddit"],
        cluster_score=0.60,
    )
    db.save_cluster(cl_contra)
    c_contra = Claim(
        id="claim:contra_1",
        cluster_id=cl_contra.id,
        subject="AsyncLib",
        predicate="guarantees",
        object="zero memory leak",
        claim_text="AsyncLib guarantees zero memory leak under high concurrency",
        claim_type="safety",
        status="contradicted",
        verification_score=0.15,
        self_reported=False,
    )
    db.save_claim(c_contra)
    evi_contra = Evidence(
        id="evi:contra_mem",
        claim_id=c_contra.id,
        event_id="ev_jit_1",
        source="github_issue",
        source_type="discussion",
        evidence_type="issue_reproduction",
        evidence_class="community",
        stance="contradicts",
        quality_score=0.85,
        independence_score=0.90,
        reproducibility_score=0.85,
        url=None,  # Explicitly null URL
        excerpt="Reproduced memory leak exceeding 2GB per hour.",
    )
    db.save_evidence(evi_contra)

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    yield client, db, {
        "cl1": cl1,
        "c1": c1,
        "c2": c2,
        "evi1": evi1,
        "evi2": evi2,
        "pm": pm,
        "ass1": ass1,
        "cl_bare": cl_bare,
        "cl_contra": cl_contra,
        "c_contra": c_contra,
        "saved": saved,
        "proj": proj,
    }

    app.dependency_overrides.clear()
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_story_endpoint_returns_typed_grounded_synthesis(api_test_env):
    client, db, data = api_test_env
    cl1 = data["cl1"]

    resp = client.get(f"/stories/{cl1.id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["cluster_id"] == cl1.id
    assert body["canonical_title"] == cl1.canonical_title
    assert body["cluster_score"] == 0.94
    assert "github" in body["sources"]
    assert "arxiv" in body["sources"]

    # Synthesis payload
    synth = body["synthesis"]
    assert synth is not None
    assert synth["is_synthesized"] is True
    assert synth["what_happened"] is not None
    assert len(synth["what_happened"]["grounding_references"]) > 0
    assert synth["evidence_position"] is not None
    assert len(synth["evidence_position"]["grounding_references"]) > 0

    # Key claims in synthesis
    assert len(synth["key_claims"]) >= 1
    assert synth["key_claims"][0]["claim_id"] == data["c1"].id

    # Technology maturity and risk
    assert body["technology_maturity"] == "production_candidate"
    assert body["risk"]["status"] == "assessed"
    assert body["risk"]["score"] == 0.15
    assert body["risk"]["level"] == "low"

    # Claims summary list
    assert len(body["claims"]) == 2
    c_sum = body["claims"][0]
    assert c_sum["claim_id"] == data["c1"].id
    assert c_sum["claim_text"] == data["c1"].claim_text
    assert c_sum["status"] == "supported"
    assert c_sum["verification_score"] == 0.89
    assert c_sum["is_self_reported"] is False
    assert c_sum["evidence_count"] == 1


def test_partial_synthesis_serializes_correctly(api_test_env):
    client, db, data = api_test_env
    cl_bare = data["cl_bare"]

    resp = client.get(f"/stories/{cl_bare.id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["cluster_id"] == cl_bare.id
    synth = body["synthesis"]
    # Bare cluster has no events and no claims -> partial synthesis remains None
    assert synth["what_happened"] is None
    assert synth["why_it_matters"] is None
    assert synth["evidence_position"] is None
    assert synth["key_claims"] == []
    assert synth["project_implications"] is None
    assert synth["change_summary"] is None


def test_story_claim_summaries_contain_resolvable_claim_ids(api_test_env):
    client, db, data = api_test_env
    cl1 = data["cl1"]

    resp = client.get(f"/stories/{cl1.id}")
    assert resp.status_code == 200
    story = resp.json()

    for claim_summary in story["claims"]:
        cid = claim_summary["claim_id"]
        assert cid is not None
        claim_resp = client.get(f"/claims/{cid}")
        assert claim_resp.status_code == 200
        claim_detail = claim_resp.json()
        assert claim_detail["claim_id"] == cid
        assert claim_detail["claim_text"] == claim_summary["claim_text"]
        assert claim_detail["status"] == claim_summary["status"]


def test_claim_endpoint_returns_complete_evidence_records(api_test_env):
    client, db, data = api_test_env
    c1 = data["c1"]

    resp = client.get(f"/claims/{c1.id}")
    assert resp.status_code == 200
    claim = resp.json()

    assert claim["claim_id"] == c1.id
    assert claim["claim_text"] == c1.claim_text
    assert claim["assertion_level"] == "performance_claim"
    assert claim["status"] == "supported"
    assert claim["verification_score"] == 0.89
    assert claim["is_self_reported"] is False
    assert claim["evidence_count"] == 1

    ev = claim["evidence"][0]
    assert ev["evidence_id"] == data["evi1"].id
    assert ev["claim_id"] == c1.id
    assert ev["event_id"] == "ev_jit_2"
    assert ev["source"] == "arxiv"
    assert ev["evidence_type"] == "independent_reproduction"
    assert ev["evidence_class"] == "secondary"
    assert ev["stance"] == "supports"
    assert ev["quality_score"] == 0.95
    assert ev["independence_score"] == 0.90
    assert ev["reproducibility_score"] == 0.88
    assert ev["is_independent"] is True
    assert ev["url"] == "https://arxiv.org/abs/2309.06180"
    assert "Independent benchmarks reproduce" in ev["excerpt"]


def test_evidence_is_independent_matches_canonical_helper(api_test_env):
    client, db, data = api_test_env

    # 1. Independent reproduction with low score -> True
    ev_rep = Evidence(
        id="evi:test_ind_rep",
        claim_id=data["c2"].id,
        event_id="ev_jit_1",
        source="github",
        evidence_type="independent_reproduction",
        evidence_class="secondary",
        stance="supports",
        independence_score=0.40,
    )
    db.save_evidence(ev_rep)

    # 2. Secondary evidence with independence_score 0.84 -> False
    ev_84 = Evidence(
        id="evi:test_84",
        claim_id=data["c2"].id,
        event_id="ev_jit_1",
        source="reddit",
        evidence_type="benchmark_run",
        evidence_class="secondary",
        stance="supports",
        independence_score=0.84,
    )
    db.save_evidence(ev_84)

    # 3. Secondary evidence with independence_score 0.85 -> True
    ev_85 = Evidence(
        id="evi:test_85",
        claim_id=data["c2"].id,
        event_id="ev_jit_1",
        source="bench_suite",
        evidence_type="benchmark_run",
        evidence_class="secondary",
        stance="supports",
        independence_score=0.85,
    )
    db.save_evidence(ev_85)

    resp = client.get(f"/claims/{data['c2'].id}")
    assert resp.status_code == 200
    evidence_list = resp.json()["evidence"]
    ev_map = {e["evidence_id"]: e for e in evidence_list}

    assert ev_map["evi:test_ind_rep"]["is_independent"] is True
    assert ev_map["evi:test_84"]["is_independent"] is False
    assert ev_map["evi:test_85"]["is_independent"] is True

    # Double check against canonical helper directly
    assert is_independent_evidence(ev_rep) == ev_map["evi:test_ind_rep"]["is_independent"]
    assert is_independent_evidence(ev_84) == ev_map["evi:test_84"]["is_independent"]
    assert is_independent_evidence(ev_85) == ev_map["evi:test_85"]["is_independent"]


def test_self_reported_claim_with_independent_evidence(api_test_env):
    client, db, data = api_test_env
    # Attach independent evidence to self-reported claim c2
    evi_ind = Evidence(
        id="evi:c2_ind",
        claim_id=data["c2"].id,
        event_id="ev_jit_2",
        source="arxiv",
        evidence_type="independent_reproduction",
        evidence_class="secondary",
        stance="supports",
        independence_score=0.92,
    )
    db.save_evidence(evi_ind)

    resp = client.get(f"/claims/{data['c2'].id}")
    assert resp.status_code == 200
    claim = resp.json()
    assert claim["is_self_reported"] is True
    ev_item = [e for e in claim["evidence"] if e["evidence_id"] == "evi:c2_ind"][0]
    assert ev_item["is_independent"] is True


def test_contextual_evidence_remains_contextual(api_test_env):
    client, db, data = api_test_env
    resp = client.get(f"/claims/{data['c2'].id}")
    assert resp.status_code == 200
    ev = [e for e in resp.json()["evidence"] if e["evidence_id"] == data["evi2"].id][0]
    assert ev["stance"] == "context"
    assert ev["evidence_class"] == "primary"


def test_contradictions_survive_api_serialization(api_test_env):
    client, db, data = api_test_env
    cl_contra = data["cl_contra"]
    c_contra = data["c_contra"]

    # Claim route check
    resp_claim = client.get(f"/claims/{c_contra.id}")
    assert resp_claim.status_code == 200
    body_claim = resp_claim.json()
    assert body_claim["status"] == "contradicted"
    assert body_claim["evidence"][0]["stance"] == "contradicts"

    # Story route check
    resp_story = client.get(f"/stories/{cl_contra.id}")
    assert resp_story.status_code == 200
    body_story = resp_story.json()
    assert body_story["evidence_summary"]["contradiction"] == 1


def test_missing_source_url_stays_null(api_test_env):
    client, db, data = api_test_env
    c_contra = data["c_contra"]
    resp = client.get(f"/claims/{c_contra.id}")
    assert resp.status_code == 200
    ev = resp.json()["evidence"][0]
    assert ev["url"] is None


def test_no_claims_nullable_verification(api_test_env):
    client, db, data = api_test_env
    cl_bare = data["cl_bare"]
    resp = client.get(f"/stories/{cl_bare.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["verification"]["verification_score"] is None
    assert body["verification"]["claim_status"] is None
    assert body["claims"] == []


def test_no_assessment_nullable_maturity(api_test_env):
    client, db, data = api_test_env
    cl_bare = data["cl_bare"]
    resp = client.get(f"/stories/{cl_bare.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["technology_maturity"] is None
    assert body["verification"]["maturity_stage"] is None


def test_no_technology_state_not_assessed(api_test_env):
    client, db, data = api_test_env
    cl_bare = data["cl_bare"]
    resp = client.get(f"/stories/{cl_bare.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk"]["status"] == "not_assessed"
    assert body["risk"]["level"] is None
    assert body["risk"]["score"] is None
    assert body["verification"]["risk_status"] == "not_assessed"


def test_insufficient_risk_input_insufficient_data(api_test_env):
    client, db, _ = api_test_env
    # Cluster with tech_state but 0 events and 0 claims
    cl_empty = StoryCluster(id="cluster:empty_state", canonical_title="Empty Cluster")
    db.save_cluster(cl_empty)
    ts = TechnologyState(cluster_id=cl_empty.id, risk_score=0.50)
    db.save_technology_state(ts)

    resp = client.get(f"/stories/{cl_empty.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk"]["status"] == "insufficient_data"
    assert body["risk"]["level"] is None
    assert body["verification"]["risk_status"] == "insufficient_data"


def test_ranking_cluster_score_remains_separate_from_verification(api_test_env):
    client, db, data = api_test_env
    cl1 = data["cl1"]
    resp = client.get(f"/stories/{cl1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cluster_score"] == 0.94
    assert body["verification"]["verification_score"] == 0.72  # Average of 0.89 and 0.55
    assert body["cluster_score"] != body["verification"]["verification_score"]


def test_story_to_claim_to_evidence_provenance_chain(api_test_env):
    client, db, data = api_test_env
    cl1 = data["cl1"]

    # 1. Start from Story
    story_resp = client.get(f"/stories/{cl1.id}")
    assert story_resp.status_code == 200
    story = story_resp.json()
    assert len(story["claims"]) > 0

    first_claim_id = story["claims"][0]["claim_id"]

    # 2. Traverse to Claim
    claim_resp = client.get(f"/claims/{first_claim_id}")
    assert claim_resp.status_code == 200
    claim = claim_resp.json()
    assert claim["cluster_id"] == cl1.id
    assert len(claim["evidence"]) > 0

    # 3. Traverse to Evidence and Underlying Event
    first_evidence = claim["evidence"][0]
    assert first_evidence["claim_id"] == first_claim_id
    assert first_evidence["event_id"] in story["sources"] or any(e["id"] == first_evidence["event_id"] for e in story["events"])
    assert first_evidence["url"].startswith("http")


def test_saved_default_behavior_backward_compatible(api_test_env):
    client, db, data = api_test_env
    resp = client.get("/saved")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["saved_items"][0]
    assert item["id"] == data["saved"].id
    assert item["title"] == "vLLM v0.4.0 Historical Title"
    assert item["verification_score"] == 0.80
    assert item["maturity_stage"] == "experimental"
    assert item["risk_score"] == 0.25
    assert "current_state" not in item or item.get("current_state") is None


def test_saved_include_current_true_separated_state(api_test_env):
    client, db, data = api_test_env
    resp = client.get("/saved?include_current=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["saved_items"][0]

    # Historical snapshot unchanged
    assert item["title"] == "vLLM v0.4.0 Historical Title"
    assert item["verification_score"] == 0.80
    assert item["maturity_stage"] == "experimental"
    assert item["risk_score"] == 0.25

    # Current state hydrated separately
    cur = item["current_state"]
    assert cur is not None
    assert cur["title"] == data["cl1"].canonical_title
    assert cur["cluster_score"] == 0.94
    assert cur["verification_score"] == 0.72
    assert cur["maturity_stage"] == "production_candidate"
    assert cur["risk_level"] == "low"
    assert cur["risk_score"] == 0.15
    assert cur["risk_status"] == "assessed"
    assert cur["claims_count"] == 2
    assert cur["events_count"] == 2
    assert cur["is_active"] is True


def test_saved_batch_hydration_avoids_n_plus_one(api_test_env):
    client, db, data = api_test_env
    # Create 10 saved items pointing to the same cluster
    for i in range(10):
        s = SavedItem(
            id=f"saved:batch_{i}",
            entity_type="cluster",
            entity_id=data["cl1"].id,
            story_cluster_id=data["cl1"].id,
            title_snapshot=f"Snapshot {i}",
        )
        db.save_saved_item(s)

    # Query with include_current=True
    resp = client.get("/saved?limit=15&include_current=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 11
    for it in body["saved_items"]:
        assert it["current_state"] is not None
        assert it["current_state"]["title"] == data["cl1"].canonical_title


def test_nonexistent_story_404(api_test_env):
    client, _, _ = api_test_env
    resp = client.get("/stories/cluster:does_not_exist_12345")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_nonexistent_claim_404(api_test_env):
    client, _, _ = api_test_env
    resp = client.get("/claims/claim:does_not_exist_98765")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_malformed_invalid_identifiers_fail_safely(api_test_env):
    client, _, _ = api_test_env
    for bad_id in ["%20", "null", "undefined", "   "]:
        resp_s = client.get(f"/stories/{bad_id}")
        assert resp_s.status_code == 404
        resp_c = client.get(f"/claims/{bad_id}")
        assert resp_c.status_code == 404


def test_phase3_grounding_references_valid_after_serialization(api_test_env):
    client, db, data = api_test_env
    cl1 = data["cl1"]

    resp = client.get(f"/stories/{cl1.id}")
    assert resp.status_code == 200
    story = resp.json()

    synth = story["synthesis"]
    assert synth is not None

    all_refs = []
    if synth.get("what_happened"):
        all_refs.extend(synth["what_happened"]["grounding_references"])
    if synth.get("why_it_matters"):
        all_refs.extend(synth["why_it_matters"]["grounding_references"])
    if synth.get("evidence_position"):
        all_refs.extend(synth["evidence_position"]["grounding_references"])
    if synth.get("project_implications"):
        all_refs.extend(synth["project_implications"]["grounding_references"])

    canonical_types = {"event", "claim", "evidence", "assessment", "project_match", "change"}
    for ref in all_refs:
        etype = ref["entity_type"]
        eid = ref["entity_id"]
        assert etype in canonical_types, f"Non-canonical entity_type: {etype}"
        if etype == "event":
            assert db.get_event(eid) is not None
        elif etype == "claim":
            assert db.get_claim(eid) is not None
        elif etype == "evidence":
            assert db.get_evidence(eid) is not None
        elif etype == "project_match":
            assert eid == data["pm"].id
            matches = db.get_project_matches(data["pm"].project_id)
            assert any(m.id == eid for m in matches)


def test_project_match_grounding_references_match_id(api_test_env):
    client, db, data = api_test_env
    cl1 = data["cl1"]
    pm = data["pm"]

    resp = client.get(f"/stories/{cl1.id}")
    assert resp.status_code == 200
    story = resp.json()

    synth = story.get("synthesis")
    assert synth is not None
    proj_imp = synth.get("project_implications")
    assert proj_imp is not None
    
    # Verify GroundingRef entity_id == ProjectMatch.id
    match_refs = [r for r in proj_imp["grounding_references"] if r["entity_type"] == "project_match"]
    assert len(match_refs) >= 1
    ref = match_refs[0]
    assert ref["entity_id"] == pm.id
    assert ref["entity_id"] != pm.project_id
    matches = db.get_project_matches(pm.project_id)
    assert any(m.id == ref["entity_id"] for m in matches)


def test_typed_verification_detail_contract(api_test_env):
    client, _, data = api_test_env
    cl1 = data["cl1"]

    resp = client.get(f"/stories/{cl1.id}")
    assert resp.status_code == 200
    story = resp.json()

    verif = story.get("verification")
    assert isinstance(verif, dict)
    assert "verification_score" in verif
    assert verif["verification_score"] == 0.72  # mean of 0.89 and 0.55 rounded
    assert verif["claim_status"] == "supported"
    assert verif["claims_count"] == 2
    assert verif["evidence_count"] >= 2
    assert verif["contradiction_detected"] is False
    assert verif["contradictions_count"] == 0

    risk = story.get("risk")
    assert isinstance(risk, dict)
    assert risk["status"] in ("assessed", "not_assessed", "insufficient_data")
    assert risk["level"] == "low"
    assert risk["score"] == 0.15


def test_event_summary_timestamps_preservation(api_test_env):
    client, db, data = api_test_env
    now = datetime.now(timezone.utc)

    # 1. Published and Discovered present
    e_both = Event(
        id="ev_both",
        source="github",
        title="Release with both timestamps",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.4.1",
        published_at=now,
        discovered_at=now,
        final_score=0.9,
    )
    db.save_event(e_both)

    # 2. Discovery-only (missing publication)
    e_disc = Event(
        id="ev_disc",
        source="hackernews",
        title="Discussion discovered",
        url="https://news.ycombinator.com/item?id=123456",
        published_at=None,
        discovered_at=now,
        final_score=0.8,
    )
    db.save_event(e_disc)

    cl_time = StoryCluster(
        id="cluster:timestamp_test",
        canonical_title="Timestamp Test Story",
        event_ids=["ev_both", "ev_disc"],
        cluster_score=0.8,
    )
    db.save_cluster(cl_time)
    db.add_event_to_cluster(cl_time.id, e_both.id)
    db.add_event_to_cluster(cl_time.id, e_disc.id)

    resp = client.get(f"/stories/{cl_time.id}")
    assert resp.status_code == 200
    events_map = {e["event_id"]: e for e in resp.json()["events"]}

    assert events_map["ev_both"]["published_at"] is not None
    assert events_map["ev_both"]["discovered_at"] is not None

    assert events_map["ev_disc"]["published_at"] is None
    assert events_map["ev_disc"]["discovered_at"] is not None

    # 3. Direct EventSummary schema validation for missing discovery timestamp
    from app.services.schemas import EventSummary
    ev_pub_only = EventSummary(
        event_id="ev_pub_only",
        source="arxiv",
        title="Paper published",
        url="https://arxiv.org/abs/2401.0001",
        published_at=now.isoformat(),
        discovered_at=None,
    )
    assert ev_pub_only.published_at is not None
    assert ev_pub_only.discovered_at is None


def test_provenance_chain_survives_compact_events_summary_limit(api_test_env):
    client, db, data = api_test_env
    now = datetime.now(timezone.utc)

    # Create cluster with 15 events in descending score order
    ev_ids = []
    for i in range(15):
        e = Event(
            id=f"ev_cap_{i}",
            source="github",
            title=f"Event {i}",
            url=f"https://github.com/org/repo/commit/{i}",
            published_at=now,
            discovered_at=now,
            final_score=0.90 - (i * 0.02),
        )
        db.save_event(e)
        ev_ids.append(e.id)

    cl_large = StoryCluster(
        id="cluster:large_events_story",
        canonical_title="Large Events Story",
        event_ids=ev_ids,
        cluster_score=0.85,
    )
    db.save_cluster(cl_large)
    for eid in ev_ids:
        db.add_event_to_cluster(cl_large.id, eid)

    # Claim points to evidence linked to event index 14 (which exceeds 10-cap)
    c_cap = Claim(
        id="claim:cap_test",
        cluster_id=cl_large.id,
        subject="Performance",
        predicate="improves",
        object="speed",
        claim_text="Speed improves 5x",
        status="supported",
        verification_score=0.92,
    )
    db.save_claim(c_cap)

    evi_cap = Evidence(
        id="evi:cap_14",
        claim_id=c_cap.id,
        event_id="ev_cap_14",
        source="github",
        evidence_type="commit_benchmark",
        evidence_class="primary",
        stance="supports",
        quality_score=0.9,
        independence_score=0.5,
        reproducibility_score=0.8,
        url="https://github.com/org/repo/commit/14",
        excerpt="Benchmark commit 14 showed 5x improvement.",
    )
    db.save_evidence(evi_cap)

    resp_story = client.get(f"/stories/{cl_large.id}")
    assert resp_story.status_code == 200
    story_body = resp_story.json()

    assert story_body["events_count"] == 15
    assert len(story_body["events"]) == 10  # Capped summary list
    assert not any(e["event_id"] == "ev_cap_14" for e in story_body["events"])

    # Traverse Claim -> Evidence -> persisted Event
    resp_claim = client.get(f"/claims/{c_cap.id}")
    assert resp_claim.status_code == 200
    claim_body = resp_claim.json()

    assert len(claim_body["evidence"]) == 1
    ev_detail = claim_body["evidence"][0]
    assert ev_detail["event_id"] == "ev_cap_14"
    assert ev_detail["url"] == "https://github.com/org/repo/commit/14"

    # Invariant: persisted event is fully resolvable
    persisted_event = db.get_event(ev_detail["event_id"])
    assert persisted_event is not None
    assert persisted_event.id == "ev_cap_14"
    assert persisted_event.url == "https://github.com/org/repo/commit/14"


def test_claim_revision_detail_fields_correspond_to_persisted_model(api_test_env):
    client, db, data = api_test_env
    c1 = data["c1"]
    now = datetime.now(timezone.utc)

    rev = ClaimRevision(
        id="rev:test_audit_1",
        claim_id=c1.id,
        previous_status="weakly_supported",
        new_status="supported",
        previous_verification_score=0.55,
        new_verification_score=0.89,
        reason="Independent reproduction published on arXiv",
        trigger_event_id="ev_jit_2",
        trigger_evidence_id="evi:vllm_ind_rep",
        created_at=now,
    )
    db.insert_claim_revision(rev)

    resp = client.get(f"/claims/{c1.id}")
    assert resp.status_code == 200
    claim_body = resp.json()

    assert len(claim_body["revisions"]) >= 1
    r0 = claim_body["revisions"][0]
    assert r0["revision_id"] == "rev:test_audit_1"
    assert r0["claim_id"] == c1.id
    assert r0["previous_status"] == "weakly_supported"
    assert r0["new_status"] == "supported"
    assert r0["previous_verification_score"] == 0.55
    assert r0["new_verification_score"] == 0.89
    assert r0["reason"] == "Independent reproduction published on arXiv"
    assert r0["trigger_event_id"] == "ev_jit_2"
    assert r0["trigger_evidence_id"] == "evi:vllm_ind_rep"
    assert "old_staleness_score" not in r0


def test_saved_exact_json_contract_when_include_current_false(api_test_env):
    client, _, data = api_test_env

    # include_current=false (default)
    resp_false = client.get("/saved?limit=10")
    assert resp_false.status_code == 200
    items_false = resp_false.json()["saved_items"]
    assert len(items_false) >= 1
    for it in items_false:
        assert "current_state" not in it
        assert "title" in it
        assert "verification_score" in it
        assert "maturity_stage" in it
        assert "risk_score" in it
        assert "tags" in it
        assert "user_note" in it
        assert "project_ids" in it
        assert "saved_at" in it

    # include_current=true
    resp_true = client.get("/saved?limit=10&include_current=true")
    assert resp_true.status_code == 200
    items_true = resp_true.json()["saved_items"]
    assert len(items_true) >= 1
    for it in items_true:
        assert "current_state" in it
        assert isinstance(it["current_state"], dict)

