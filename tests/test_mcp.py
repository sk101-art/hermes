import os
import shutil
import tempfile
from datetime import datetime, timezone
import pytest

from app.mcp import tools as mcp_tools
from app.mcp.config import generate_mcp_config
from app.models.schemas import Event, StoryCluster, Claim, Evidence, Project, ProjectMatch, InboxItem
from app.storage.db import Database


@pytest.fixture
def mcp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_mcp.db")
    db = Database(db_path=db_path)

    now = datetime.now(timezone.utc)

    # Insert test data
    ev = Event(
        id="ev_vllm_1",
        source="github_releases",
        source_type="code_repository",
        event_type="release",
        title="vLLM v0.7.0 PagedAttention Release",
        text="High-throughput LLM serving engine with PagedAttention",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.7.0",
        discovered_at=now,
        final_score=0.95,
    )
    db.save_event(ev)

    cl = StoryCluster(
        id="cluster_vllm",
        canonical_title="vLLM v0.7.0 PagedAttention Release",
        event_ids=["ev_vllm_1"],
        sources=["github_releases"],
        cluster_score=0.95,
        source_diversity_score=0.50,
        max_event_score=0.95,
        created_at=now,
        updated_at=now,
    )
    db.save_cluster(cl)

    claim = Claim(
        id="claim_vllm_1",
        cluster_id="cluster_vllm",
        subject="vLLM",
        predicate="achieves",
        object="2-4x higher throughput with PagedAttention",
        claim_text="vLLM achieves 2-4x higher throughput with PagedAttention",
        claim_type="performance",
        assertion_level="empirical_benchmark",
        status="supported",
        verification_score=0.88,
    )
    db.save_claim(claim)

    ev_rec = Evidence(
        id="ev_vllm_rec",
        claim_id="claim_vllm_1",
        event_id="ev_vllm_1",
        source="github_releases",
        evidence_type="benchmark",
        stance="support",
        quality_score=0.90,
        url="https://github.com/vllm-project/vllm",
    )
    db.save_evidence(ev_rec)

    proj = Project(
        id="project:rag-agent",
        name="local-rag-agent",
        path=os.path.join(temp_dir, "rag_proj"),
        languages=["Python"],
        frameworks=["FastAPI"],
        libraries=["vLLM", "torch"],
        topics=["rag", "llm-serving"],
    )
    db.save_project(proj)

    match = ProjectMatch(
        id="match_vllm",
        project_id="project:rag-agent",
        entity_type="cluster",
        entity_id="cluster_vllm",
        match_type="direct_dependency",
        relevance_score=0.95,
        recommendation="upgrade",
    )
    db.save_project_match(match)

    inbox = InboxItem(
        id="inbox_vllm_1",
        entity_type="cluster",
        entity_id="cluster_vllm",
        story_cluster_id="cluster_vllm",
        title="vLLM v0.7.0 PagedAttention Release",
        section="ai_ml",
        inbox_score=0.90,
        rank_score=0.95,
        project_impact_score=0.95,
        state="unseen",
        matched_project_ids=["project:rag-agent"],
    )
    db.save_inbox_item(inbox)

    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_mcp_health_tool(mcp_db):
    res = mcp_tools.tool_health(db=mcp_db)
    assert res["status"] == "healthy"
    assert res["database"] == "ok"


def test_mcp_search_tool(mcp_db):
    res = mcp_tools.tool_search_intelligence({"query": "vLLM PagedAttention", "mode": "lexical"}, db=mcp_db)
    assert "results" in res
    assert res["count"] >= 1
    top = res["results"][0]
    assert "vLLM" in top["title"]
    assert top["verification_score"] >= 0.80


def test_mcp_search_limit_validation(mcp_db):
    # Limit exceeding 50 should trigger validation error
    res = mcp_tools.tool_search_intelligence({"query": "vLLM", "limit": 10000}, db=mcp_db)
    assert "error" in res


def test_mcp_story_tool(mcp_db):
    # Found
    story = mcp_tools.tool_get_story({"cluster_id": "cluster_vllm"}, db=mcp_db)
    assert story["cluster_id"] == "cluster_vllm"
    assert len(story["events"]) == 1
    assert len(story["claims"]) == 1

    # Not found
    not_found = mcp_tools.tool_get_story({"cluster_id": "nonexistent_cluster"}, db=mcp_db)
    assert not_found["status"] == "not_found"


def test_mcp_claim_tool(mcp_db):
    claim = mcp_tools.tool_get_claim({"claim_id": "claim_vllm_1"}, db=mcp_db)
    assert claim["claim_id"] == "claim_vllm_1"
    assert claim["verification_score"] >= 0.80
    assert len(claim["evidence"]) == 1
    assert claim["evidence"][0]["source"] == "github_releases"


def test_mcp_projects_privacy(mcp_db):
    res = mcp_tools.tool_list_projects(db=mcp_db)
    assert res["count"] == 1
    proj = res["projects"][0]
    assert proj["name"] == "local-rag-agent"
    assert "Python" in proj["languages"]
    # Ensure no raw source files or secrets
    assert "extracted_text" not in proj
    assert "source_code" not in proj


def test_mcp_project_intelligence(mcp_db):
    res = mcp_tools.tool_get_project_intelligence({"project": "local-rag-agent"}, db=mcp_db)
    assert res["name"] == "local-rag-agent"
    assert len(res["recommendations"]) == 1
    assert res["recommendations"][0]["recommendation"] == "upgrade"


def test_mcp_star_and_note_tools(mcp_db):
    star_res = mcp_tools.tool_star_item({"inbox_item_id": "inbox_vllm_1"}, db=mcp_db)
    assert star_res["success"] is True
    assert star_res["saved_item"] is not None

    note_res = mcp_tools.tool_add_saved_note({"saved_id": "saved:cluster_vllm", "note": "Verified vLLM 0.7.0 release"}, db=mcp_db)
    assert note_res["success"] is True

    tag_res = mcp_tools.tool_add_saved_tag({"saved_id": "saved:cluster_vllm", "tag": "production-eval"}, db=mcp_db)
    assert tag_res["success"] is True


def test_mcp_config_generation():
    cfg = generate_mcp_config()
    assert "mcpServers" in cfg
    assert "hermes" in cfg["mcpServers"]
    assert cfg["mcpServers"]["hermes"]["args"] == ["-m", "app.mcp.server"]
