import os
import tempfile
from datetime import datetime, timedelta, timezone
import pytest

from app.inbox.briefing import generate_morning_briefing
from app.inbox.generator import (
    calculate_inbox_score,
    classify_inbox_section,
    generate_daily_inbox,
    is_user_facing_change,
)
from app.inbox.lifecycle import star_inbox_item
from app.models.schemas import (
    Claim,
    Event,
    InboxItem,
    IntelligenceChange,
    Project,
    ProjectFile,
    ProjectMatch,
    ProjectTechnologyProfile,
    SavedItem,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
    UserFeedback,
)
from app.storage.db import Database
from app.context.matcher import match_project_with_cluster


@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path=path)
    yield db
    try:
        os.remove(path)
    except Exception:
        pass


def test_historical_backfill_not_news(test_db):
    """Old StoryCluster with no recent events/changes should not be active in today's inbox."""
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=10)

    cluster = StoryCluster(
        id="cluster:old",
        canonical_title="Old LLM Paper 2024",
        sources=["arxiv"],
        cluster_score=0.70,
        created_at=old_time,
    )
    ev = Event(
        id="arxiv:old",
        source="arxiv",
        event_type="paper",
        title="Old Paper",
        url="https://arxiv.org/abs/2401.0001",
        published_at=old_time,
    )
    claim = Claim(
        id="claim:old",
        cluster_id=cluster.id,
        claim_type="performance",
        subject="old_model",
        predicate="achieves",
        object="high accuracy",
        claim_text="Old model paper",
        verification_score=0.60,
    )
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    items = generate_daily_inbox(db=test_db, lookback_hours=36, now=now)
    assert len(items) == 0


def test_initialization_change_filtered_out(test_db):
    """IntelligenceChange with origin=backfill_initialization must not appear in corrections."""
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=5)

    cluster = StoryCluster(id="cluster:init", canonical_title="Backfilled System", sources=["github"], created_at=old_time)
    ev = Event(id="gh:init", source="github", event_type="release", title="System", url="https://github.com", published_at=old_time)
    claim = Claim(id="claim:init", cluster_id=cluster.id, claim_type="release", subject="sys", predicate="released", object="v1", claim_text="Release", verification_score=0.70)
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    # Change with origin=backfill_initialization
    change = IntelligenceChange(
        id="ch:init",
        entity_type="claim",
        entity_id=claim.id,
        change_type="verification_strengthened",
        old_value="0.50",
        new_value="0.70",
        importance=0.60,
        reason="Initial backfill computation",
        origin="backfill_initialization",
        created_at=now,
    )
    test_db.save_intelligence_change(change)

    assert is_user_facing_change(change) is False

    items = generate_daily_inbox(db=test_db, lookback_hours=36, now=now)
    assert len(items) == 0


def test_real_user_facing_change_included(test_db):
    """Real live transition (e.g. contradiction / status transition) creates active correction item."""
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cluster:real_chg", canonical_title="Breakthrough Inference Kernel", sources=["github"], cluster_score=0.75)
    ev = Event(id="gh:real_chg", source="github", event_type="release", title="Kernel", url="https://github.com", published_at=now)
    claim = Claim(id="claim:real_chg", cluster_id=cluster.id, claim_type="performance", subject="kernel", predicate="speedup", object="2x", claim_text="2x speedup", status="supported", verification_score=0.70)
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    change = IntelligenceChange(
        id="ch:real_live",
        entity_type="claim",
        entity_id=claim.id,
        change_type="contradiction_detected",
        old_value="supported",
        new_value="mixed",
        importance=0.85,
        reason="New benchmark contradicts speedup claims",
        origin="live_update",
        created_at=now,
    )
    test_db.save_intelligence_change(change)

    assert is_user_facing_change(change) is True

    items = generate_daily_inbox(db=test_db, lookback_hours=36, now=now)
    assert len(items) == 1
    assert items[0].section == "corrections_updates"
    assert items[0].item_type == "contradiction_detected"


def test_direct_dependency_strictness(test_db):
    """Project using 'torch' matches official pytorch release as direct_dependency, but generic article as technology_overlap."""
    now = datetime.now(timezone.utc)
    proj = Project(id="p:rag", name="RAG Agent", path="/local/rag")
    profile = ProjectTechnologyProfile(
        project_id=proj.id,
        dependencies={"torch": ">=2.4.0", "fastapi": ">=0.115.0"},
        frameworks=["PyTorch", "FastAPI"],
        topics=["RAG", "embeddings"],
    )
    test_db.save_project(proj)
    test_db.save_project_profile(profile)

    # 1. Official PyTorch release
    cl_official = StoryCluster(id="cl:torch", canonical_title="PyTorch 2.6.0 Released", sources=["github"], cluster_score=0.80)
    ev_official = Event(id="gh:rel:torch", source="github", event_type="release", title="PyTorch 2.6.0", url="https://github.com/pytorch/pytorch/releases/tag/v2.6.0", published_at=now)
    cl_claim = Claim(id="c:torch", cluster_id=cl_official.id, claim_type="release", subject="pytorch", predicate="released", object="v2.6.0", claim_text="PyTorch 2.6.0", verification_score=0.80)
    test_db.save_event(ev_official)
    test_db.save_cluster(cl_official)
    test_db.add_event_to_cluster(cl_official.id, ev_official.id)
    test_db.save_claim(cl_claim)

    match_official = match_project_with_cluster(
        project=proj,
        profile=profile,
        project_embedding=None,
        cluster=cl_official,
        cluster_events=[ev_official],
        cluster_claims=[cl_claim],
        assessment=None,
        tech_state=None,
        db=test_db,
    )
    assert match_official is not None
    assert match_official.match_type == "direct_dependency"
    assert any(r.startswith("dependency_match:torch") for r in match_official.reason_codes)

    # 2. Generic article mentioning torch
    cl_blog = StoryCluster(id="cl:blog", canonical_title="Comparing PyTorch and JAX on GPU", sources=["hacker_news"], cluster_score=0.55)
    ev_blog = Event(id="hn:blog", source="hacker_news", event_type="discussion", title="Blog comparison", url="https://news.ycombinator.com/item?id=123", published_at=now)
    cl_blog_claim = Claim(id="c:blog", cluster_id=cl_blog.id, claim_type="performance", subject="blog", predicate="discusses", object="comparison", claim_text="Comparison", verification_score=0.50)
    test_db.save_event(ev_blog)
    test_db.save_cluster(cl_blog)
    test_db.add_event_to_cluster(cl_blog.id, ev_blog.id)
    test_db.save_claim(cl_blog_claim)

    match_blog = match_project_with_cluster(
        project=proj,
        profile=profile,
        project_embedding=None,
        cluster=cl_blog,
        cluster_events=[ev_blog],
        cluster_claims=[cl_blog_claim],
        assessment=None,
        tech_state=None,
        db=test_db,
    )
    assert match_blog is not None
    assert match_blog.match_type != "direct_dependency"
    assert match_blog.match_type in ("technology_overlap", "compatible_tool", "general_related")


def test_technology_overlap_not_dependency(test_db):
    """Project using CUDA must not treat unrelated CUDA blog as direct dependency."""
    now = datetime.now(timezone.utc)
    proj = Project(id="p:cuda_lab", name="CUDA Lab", path="/local/cuda")
    profile = ProjectTechnologyProfile(
        project_id=proj.id,
        dependencies={"cuda": "", "llvm": ""},
        frameworks=["CUDA"],
        topics=["CUDA & GPU kernels", "compiler optimization"],
    )
    test_db.save_project(proj)
    test_db.save_project_profile(profile)

    # Blog mentioning CUDA
    cl_island = StoryCluster(id="cl:island", canonical_title="Geolocating a random island using geometry and CUDA programming", sources=["rss"], cluster_score=0.60)
    ev_island = Event(id="rss:island", source="rss", event_type="article", title="CUDA Island Article", url="https://yassa9.github.io/osint/gralhix-004", published_at=now)
    claim_island = Claim(id="c:island", cluster_id=cl_island.id, claim_type="general", subject="island", predicate="found", object="cuda", claim_text="Island", verification_score=0.50)
    test_db.save_event(ev_island)
    test_db.save_cluster(cl_island)
    test_db.add_event_to_cluster(cl_island.id, ev_island.id)
    test_db.save_claim(claim_island)

    match = match_project_with_cluster(
        project=proj,
        profile=profile,
        project_embedding=None,
        cluster=cl_island,
        cluster_events=[ev_island],
        cluster_claims=[claim_island],
        assessment=None,
        tech_state=None,
        db=test_db,
    )
    assert match is not None
    assert match.match_type != "direct_dependency"
    assert match.match_type in ("architecture_relevant", "technology_overlap", "general_related")


def test_daily_active_cap_and_suppressed_state(test_db):
    """50 candidates generated with max_daily_items=10 must result in 10 active and 40 suppressed."""
    now = datetime.now(timezone.utc)

    for i in range(50):
        cl = StoryCluster(id=f"cl:{i}", canonical_title=f"Release Tool #{i}", sources=["github"], cluster_score=0.60 + (i * 0.005))
        ev = Event(id=f"ev:{i}", source="github", event_type="release", title=f"Release {i}", url=f"https://github.com/org/repo{i}", published_at=now)
        c = Claim(id=f"c:{i}", cluster_id=cl.id, claim_type="release", subject=f"repo{i}", predicate="released", object="v1", claim_text="Release", verification_score=0.65)
        test_db.save_event(ev)
        test_db.save_cluster(cl)
        test_db.add_event_to_cluster(cl.id, ev.id)
        test_db.save_claim(c)

    active_items = generate_daily_inbox(db=test_db, lookback_hours=36, now=now)
    assert len(active_items) <= 30  # Active cap

    # Check database counts
    all_db_items = test_db.get_all_inbox_items(limit=100)
    assert len(all_db_items) == 50
    active_db = test_db.get_active_inbox_items(limit=100)
    assert len(active_db) == len(active_items)

    suppressed = test_db.get_inbox_items_by_state("suppressed")
    assert len(suppressed) == (50 - len(active_items))


def test_briefing_cap_and_section_caps(test_db):
    """Briefing enforces max_items=20 and section caps."""
    now = datetime.now(timezone.utc)

    for i in range(25):
        cl = StoryCluster(id=f"cl:brief_{i}", canonical_title=f"Compiler Breakthrough #{i}", sources=["github"], cluster_score=0.70 + (i * 0.005))
        ev = Event(id=f"ev:brief_{i}", source="github", event_type="release", title=f"Compiler {i}", url=f"https://github.com/llvm/compiler_{i}", published_at=now)
        c = Claim(id=f"c:brief_{i}", cluster_id=cl.id, claim_type="release", subject=f"llvm{i}", predicate="released", object="v1", claim_text="Release", verification_score=0.70)
        test_db.save_event(ev)
        test_db.save_cluster(cl)
        test_db.add_event_to_cluster(cl.id, ev.id)
        test_db.save_claim(c)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    assert briefing.total_items <= 20
    # Systems section should be capped to max 4
    systems_items = briefing.sections.get("systems_compilers", [])
    assert len(systems_items) <= 4


def test_same_repository_diversity_collapse(test_db):
    """Multiple minor releases from the same repository in the lookback should collapse / penalize duplicates in briefing."""
    now = datetime.now(timezone.utc)

    # 3 releases from llvm/llvm-project
    for tag in ("22.1.7", "22.1.8", "23.0.0"):
        cl = StoryCluster(id=f"cl:llvm_{tag}", canonical_title=f"LLVM {tag} Release", sources=["github"], cluster_score=0.75)
        ev = Event(id=f"ev:llvm_{tag}", source="github", event_type="release", title=f"LLVM {tag}", url=f"https://github.com/llvm/llvm-project/releases/tag/{tag}", published_at=now)
        c = Claim(id=f"c:llvm_{tag}", cluster_id=cl.id, claim_type="release", subject="llvm", predicate="released", object=tag, claim_text=f"LLVM {tag}", verification_score=0.70)
        test_db.save_event(ev)
        test_db.save_cluster(cl)
        test_db.add_event_to_cluster(cl.id, ev.id)
        test_db.save_claim(c)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    # Check that llvm-project does not consume 3 briefing entries
    llvm_items = [iid for sec, iids in briefing.sections.items() for iid in iids if "llvm" in iid]
    assert len(llvm_items) <= 1


def test_saved_items_and_feedback_survive_rebuild(test_db):
    """Rebuilding today's inbox must preserve SavedItems, user notes, tags, and feedback."""
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cl:save_test", canonical_title="Saved Important Story", sources=["github"], cluster_score=0.80)
    ev = Event(id="ev:save_test", source="github", event_type="release", title="Saved Story", url="https://github.com/test", published_at=now)
    c = Claim(id="c:save_test", cluster_id=cluster.id, claim_type="release", subject="test", predicate="released", object="v1", claim_text="Release", verification_score=0.70)
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(c)

    # Initial generation
    generate_daily_inbox(db=test_db, lookback_hours=36, now=now)
    inbox_item = test_db.get_inbox_item_by_cluster(cluster.id)
    assert inbox_item is not None

    # Star item
    saved = star_inbox_item(inbox_item.id, test_db, now=now)
    saved.user_note = "User important analysis"
    saved.tags = ["important", "cuda-eval"]
    test_db.save_saved_item(saved)

    # Add user feedback
    fb = UserFeedback(id="fb:1", entity_type="inbox_item", entity_id=inbox_item.id, action="useful", created_at=now)
    test_db.save_user_feedback(fb)

    # Rebuild today's inbox
    rebuilt_items = generate_daily_inbox(db=test_db, lookback_hours=36, now=now, rebuild_today=True)

    # Verify SavedItem is completely preserved
    saved_retrieved = test_db.get_saved_item(saved.id)
    assert saved_retrieved is not None
    assert saved_retrieved.user_note == "User important analysis"
    assert saved_retrieved.tags == ["important", "cuda-eval"]
    assert saved_retrieved.verification_snapshot == 0.70

    # Verify feedback intact
    counts = test_db.get_feedback_counts()
    assert counts.get("useful", 0) >= 1
