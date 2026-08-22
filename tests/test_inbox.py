from datetime import datetime, timedelta, timezone
import pytest

from app.inbox.briefing import generate_morning_briefing
from app.inbox.generator import calculate_inbox_score, classify_inbox_section, generate_daily_inbox
from app.inbox.lifecycle import (
    add_saved_item_note,
    add_saved_item_tag,
    cleanup_expired_inbox_items,
    open_inbox_item,
    star_inbox_item,
    unstar_inbox_item,
)
from app.models.schemas import (
    Claim,
    Event,
    InboxItem,
    IntelligenceChange,
    Project,
    ProjectMatch,
    SavedItem,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
    UserFeedback,
)
from app.storage.db import Database


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_inbox.db")
    db = Database(db_path=db_file)
    yield db
    db.close()


def test_inbox_creation_and_scoring(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(
        id="cluster:vllm_high",
        canonical_title="vLLM 0.7.0 High Performance Inference Engine",
        sources=["github"],
        cluster_score=0.85,
        created_at=now,
    )
    ev = Event(
        id="github:vllm",
        source="github",
        event_type="release",
        source_type="release",
        title="vLLM v0.7.0",
        url="https://github.com/vllm-project/vllm/releases/v0.7.0",
        published_at=now,
    )
    claim = Claim(
        id="claim:vllm",
        cluster_id=cluster.id,
        claim_type="release",
        assertion_level="artifact_fact",
        subject="vllm",
        predicate="released",
        object="v0.7.0",
        claim_text="vLLM released version 0.7.0",
        status="supported",
        verification_score=0.75,
    )
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    items = generate_daily_inbox(db=test_db, now=now)
    assert len(items) == 1
    assert items[0].story_cluster_id == cluster.id
    assert items[0].inbox_score >= 0.50
    assert items[0].state == "unseen"
    assert items[0].item_type == "new_release"


def test_24_hour_expiry_and_cleanup(test_db):
    now = datetime.now(timezone.utc)
    past_time = now - timedelta(hours=25)
    expired_time = past_time + timedelta(hours=24)  # 1 hour ago

    item = InboxItem(
        id="inbox:item1",
        entity_type="cluster",
        entity_id="cluster:c1",
        story_cluster_id="cluster:c1",
        title="Old Unstarred Story",
        section="ai_ml",
        inbox_score=0.60,
        state="unseen",
        created_at=past_time,
        expires_at=expired_time,
        is_starred=False,
    )
    test_db.save_inbox_item(item)

    # Run cleanup
    expired_count = cleanup_expired_inbox_items(test_db, now=now)
    assert expired_count == 1

    updated = test_db.get_inbox_item("inbox:item1")
    assert updated is not None
    assert updated.state == "expired"


def test_star_survives_expiry(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(
        id="cluster:star_test",
        canonical_title="Important Kernel Pass",
        sources=["github"],
        cluster_score=0.80,
    )
    ev = Event(id="gh:star", source="github", event_type="release", title="Kernel Pass", url="https://github.com/test")
    claim = Claim(
        id="claim:star",
        cluster_id=cluster.id,
        claim_type="release",
        subject="kernel",
        predicate="released",
        object="v1",
        claim_text="Kernel pass released",
        status="supported",
        verification_score=0.70,
    )
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    inbox_item = InboxItem(
        id="inbox:star_item",
        entity_type="cluster",
        entity_id=cluster.id,
        story_cluster_id=cluster.id,
        title=cluster.canonical_title,
        section="systems_compilers",
        inbox_score=0.85,
        state="unseen",
        created_at=now,
        expires_at=now - timedelta(hours=1),  # Already expired by time
        is_starred=False,
    )
    test_db.save_inbox_item(inbox_item)

    # Star the item
    saved = star_inbox_item("inbox:star_item", test_db, now=now)
    assert saved is not None
    assert saved.id == f"saved:{cluster.id}"

    # Run cleanup with time advanced
    expired_count = cleanup_expired_inbox_items(test_db, now=now + timedelta(days=2))
    assert expired_count == 0  # Starred item must not be expired

    # Check SavedItem still active
    saved_retrieved = test_db.get_saved_item(saved.id)
    assert saved_retrieved is not None
    assert saved_retrieved.is_active is True


def test_star_idempotence(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cluster:idem", canonical_title="Idempotent Story", sources=["github"])
    ev = Event(id="ev:idem", source="github", event_type="release", title="Story", url="https://github.com")
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)

    item = InboxItem(
        id="inbox:idem_item",
        entity_type="cluster",
        entity_id=cluster.id,
        story_cluster_id=cluster.id,
        title=cluster.canonical_title,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    test_db.save_inbox_item(item)

    # Star first time
    s1 = star_inbox_item("inbox:idem_item", test_db, now=now)
    # Star second time
    s2 = star_inbox_item("inbox:idem_item", test_db, now=now)

    assert s1.id == s2.id
    all_saved = test_db.get_all_saved_items()
    assert len(all_saved) == 1


def test_saved_snapshot_preservation(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cluster:snap", canonical_title="Snapshot Story", sources=["github"])
    ev = Event(id="ev:snap", source="github", event_type="release", title="Story", url="https://github.com")
    claim = Claim(
        id="claim:snap",
        cluster_id=cluster.id,
        claim_type="release",
        subject="test",
        predicate="released",
        object="v1",
        claim_text="Initial Release",
        status="supported",
        verification_score=0.60,
    )
    assessment = TechnologyAssessment(
        cluster_id=cluster.id,
        maturity_stage="experimental",
        assessment_score=0.50,
    )
    tech_state = TechnologyState(cluster_id=cluster.id, risk_score=0.20)

    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)
    test_db.save_technology_assessment(assessment)
    test_db.save_technology_state(tech_state)

    item = InboxItem(
        id="inbox:snap_item",
        entity_type="cluster",
        entity_id=cluster.id,
        story_cluster_id=cluster.id,
        title=cluster.canonical_title,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    test_db.save_inbox_item(item)

    # Save to library
    saved = star_inbox_item("inbox:snap_item", test_db, now=now)
    assert saved.verification_snapshot == 0.60
    assert saved.maturity_snapshot == "experimental"
    assert saved.risk_snapshot == 0.20

    # Simulate later longitudinal change
    later_claim = Claim(
        id="claim:snap",
        cluster_id=cluster.id,
        claim_type="release",
        subject="test",
        predicate="released",
        object="v1",
        claim_text="Initial Release",
        status="strongly_supported",
        verification_score=0.90,
    )
    later_assessment = TechnologyAssessment(
        cluster_id=cluster.id,
        maturity_stage="established",
        assessment_score=0.95,
    )
    later_tech_state = TechnologyState(cluster_id=cluster.id, risk_score=0.05)

    test_db.save_claim(later_claim)
    test_db.save_technology_assessment(later_assessment)
    test_db.save_technology_state(later_tech_state)

    # Verify snapshot remains preserved
    saved_after = test_db.get_saved_item(saved.id)
    assert saved_after.verification_snapshot == 0.60
    assert saved_after.maturity_snapshot == "experimental"
    assert saved_after.risk_snapshot == 0.20


def test_reinbox_update(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cluster:reinbox", canonical_title="Reinbox Story", sources=["github"])
    ev = Event(id="ev:reinbox", source="github", event_type="release", title="Story", url="https://github.com")
    claim = Claim(
        id="claim:reinbox",
        cluster_id=cluster.id,
        claim_type="release",
        subject="test",
        predicate="released",
        object="v1",
        claim_text="Story release",
        status="supported",
        verification_score=0.60,
    )
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    # Simulate expired inbox item from yesterday
    past_item = InboxItem(
        id="inbox:old_item",
        entity_type="cluster",
        entity_id=cluster.id,
        story_cluster_id=cluster.id,
        title=cluster.canonical_title,
        created_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        state="expired",
    )
    test_db.save_inbox_item(past_item)

    # Run generation without changes -> should NOT reinbox
    items1 = generate_daily_inbox(db=test_db, now=now)
    assert len(items1) == 0

    # Add meaningful intelligence change
    change = IntelligenceChange(
        id="ch:1",
        entity_type="claim",
        entity_id=claim.id,
        change_type="claim_strengthened",
        old_value="supported",
        new_value="strongly_supported",
        importance=0.85,
        reason="New independent reproduction verified claim",
        created_at=now,
    )
    test_db.save_intelligence_change(change)

    # Run generation with change -> MUST reinbox as update item
    items2 = generate_daily_inbox(db=test_db, now=now)
    assert len(items2) == 1
    assert items2[0].item_type == "claim_strengthened"
    assert items2[0].section == "corrections_updates"


def test_no_duplicate_daily_items(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cluster:nodup", canonical_title="No Dup Story", sources=["github"], cluster_score=0.80)
    ev = Event(id="ev:nodup", source="github", event_type="release", title="No Dup", url="https://github.com", published_at=now)
    claim = Claim(id="claim:nodup", cluster_id=cluster.id, claim_type="release", subject="a", predicate="b", object="c", claim_text="Release", verification_score=0.70)
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    items1 = generate_daily_inbox(db=test_db, now=now)
    items2 = generate_daily_inbox(db=test_db, now=now)
    assert len(items1) == 1
    assert len(items2) == 1
    assert items1[0].id == items2[0].id

    all_inbox = test_db.get_all_inbox_items()
    assert len(all_inbox) == 1


def test_project_priority_ranking(test_db):
    now = datetime.now(timezone.utc)

    # Story A: Direct dependency for local project
    cluster_a = StoryCluster(id="cluster:a", canonical_title="PyTorch Direct Release", sources=["github"], cluster_score=0.60)
    ev_a = Event(id="ev:a", source="github", event_type="release", title="PyTorch", url="https://github.com/pytorch/pytorch", published_at=now)
    claim_a = Claim(id="claim:a", cluster_id=cluster_a.id, claim_type="release", subject="pytorch", predicate="released", object="v2.6", claim_text="PyTorch 2.6", verification_score=0.70)
    match_a = ProjectMatch(
        id="match:a",
        project_id="project:local_rag",
        entity_id=cluster_a.id,
        match_type="direct_dependency",
        relevance_score=0.85,
        impact_score=0.88,
        recommendation="upgrade_candidate",
        reason_codes=["dependency_match:torch"],
    )

    # Story B: Generic popular story, no project relevance
    cluster_b = StoryCluster(id="cluster:b", canonical_title="Generic Popular Announcement", sources=["hacker_news"], cluster_score=0.75)
    ev_b = Event(id="ev:b", source="hacker_news", event_type="discussion", title="HN Buzz", url="https://news.ycombinator.com", published_at=now)
    claim_b = Claim(id="claim:b", cluster_id=cluster_b.id, claim_type="performance", subject="buzz", predicate="reports", object="fast", claim_text="Fast buzz", verification_score=0.50)

    test_db.save_event(ev_a)
    test_db.save_cluster(cluster_a)
    test_db.add_event_to_cluster(cluster_a.id, ev_a.id)
    test_db.save_claim(claim_a)
    test_db.save_project_match(match_a)

    test_db.save_event(ev_b)
    test_db.save_cluster(cluster_b)
    test_db.add_event_to_cluster(cluster_b.id, ev_b.id)
    test_db.save_claim(claim_b)

    items = generate_daily_inbox(db=test_db, now=now)
    assert len(items) == 2
    # Story A with direct project dependency should outrank Story B
    assert items[0].story_cluster_id == cluster_a.id
    assert items[0].inbox_score > items[1].inbox_score


def test_briefing_idempotence_and_grounding(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cluster:brief", canonical_title="LLVM Compiler Breakthrough", sources=["github"], cluster_score=0.85)
    ev = Event(id="ev:brief", source="github", event_type="release", title="LLVM 23", url="https://github.com/llvm/llvm-project", published_at=now)
    claim = Claim(id="claim:brief", cluster_id=cluster.id, claim_type="release", subject="llvm", predicate="released", object="23.0", claim_text="LLVM released 23.0", status="supported", verification_score=0.80)
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)
    test_db.save_claim(claim)

    b1 = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=False, now=now)
    b2 = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=False, now=now)

    assert b1.id == b2.id
    assert b1.content_hash == b2.content_hash
    assert "LLVM Compiler Breakthrough" in b1.summary_text
    assert b1.total_items == 1


def test_user_feedback_and_notes(test_db):
    now = datetime.now(timezone.utc)
    cluster = StoryCluster(id="cluster:fb", canonical_title="Feedback Story", sources=["github"])
    ev = Event(id="ev:fb", source="github", event_type="release", title="Feedback", url="https://github.com")
    test_db.save_event(ev)
    test_db.save_cluster(cluster)
    test_db.add_event_to_cluster(cluster.id, ev.id)

    item = InboxItem(
        id="inbox:fb_item",
        entity_type="cluster",
        entity_id=cluster.id,
        story_cluster_id=cluster.id,
        title=cluster.canonical_title,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    test_db.save_inbox_item(item)

    # Open item
    opened = open_inbox_item("inbox:fb_item", test_db, now=now)
    assert opened.state == "opened"

    # Star item
    saved = star_inbox_item("inbox:fb_item", test_db, now=now)
    assert saved is not None

    # Add note & tag
    add_saved_item_note(saved.id, "Evaluate for local RAG pipeline", test_db, now=now)
    add_saved_item_tag(saved.id, "rag-eval", test_db, now=now)

    saved_updated = test_db.get_saved_item(saved.id)
    assert saved_updated.user_note == "Evaluate for local RAG pipeline"
    assert "rag-eval" in saved_updated.tags

    # Check feedback counts
    fb_counts = test_db.get_feedback_counts()
    assert fb_counts["open"] >= 1
    assert fb_counts["star"] >= 1


def test_saved_item_recovery(test_db):
    now = datetime.now(timezone.utc)
    saved_item = SavedItem(
        id="saved:cluster:old_cluster",
        entity_type="cluster",
        entity_id="cluster:old_cluster",
        story_cluster_id="cluster:old_cluster",
        title_snapshot="Resilient Saved Item",
        saved_at=now,
        verification_snapshot=0.75,
        maturity_snapshot="early_adoption",
        risk_snapshot=0.15,
        user_note="Important item",
        is_active=True,
        link_status="resolved",
        event_ids_snapshot=["github:release:pytorch/pytorch:v2.6.0"],
    )
    test_db.save_saved_item(saved_item)

    # Simulate rebuild where cluster:old_cluster is gone, but event exists in new cluster
    all_saved = test_db.get_all_saved_items(active_only=True)
    assert len(all_saved) == 1
    assert all_saved[0].id == saved_item.id
    assert all_saved[0].title_snapshot == "Resilient Saved Item"
    assert all_saved[0].event_ids_snapshot == ["github:release:pytorch/pytorch:v2.6.0"]


def test_briefing_sections_routing(test_db):
    now = datetime.now(timezone.utc)

    # 1. Systems item
    cl_sys = StoryCluster(id="cl:sys", canonical_title="CUDA Kernel LLVM Pass", sources=["github"], cluster_score=0.75)
    ev_sys = Event(id="ev:sys", source="github", event_type="release", title="CUDA Pass", url="https://github.com", published_at=now)
    cl_sys_claim = Claim(id="c:sys", cluster_id=cl_sys.id, claim_type="release", subject="cuda", predicate="released", object="v1", claim_text="CUDA v1", verification_score=0.70)
    test_db.save_event(ev_sys)
    test_db.save_cluster(cl_sys)
    test_db.add_event_to_cluster(cl_sys.id, ev_sys.id)
    test_db.save_claim(cl_sys_claim)

    # 2. Storage item
    cl_db = StoryCluster(id="cl:db", canonical_title="Qdrant Vector Database 1.10", sources=["github"], cluster_score=0.75)
    ev_db = Event(id="ev:db", source="github", event_type="release", title="Qdrant 1.10", url="https://github.com", published_at=now)
    cl_db_claim = Claim(id="c:db", cluster_id=cl_db.id, claim_type="release", subject="qdrant", predicate="released", object="1.10", claim_text="Qdrant 1.10", verification_score=0.70)
    test_db.save_event(ev_db)
    test_db.save_cluster(cl_db)
    test_db.add_event_to_cluster(cl_db.id, ev_db.id)
    test_db.save_claim(cl_db_claim)

    briefing = generate_morning_briefing(db=test_db, target_date="2026-08-20", refresh=True, now=now)
    assert "SYSTEMS / COMPILERS / ACCELERATION" in briefing.summary_text
    assert "STORAGE / DATABASES / VECTOR SEARCH" in briefing.summary_text
    assert "CUDA Kernel LLVM Pass" in briefing.summary_text
    assert "Qdrant Vector Database 1.10" in briefing.summary_text

