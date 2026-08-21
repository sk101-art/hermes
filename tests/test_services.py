import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
import pytest
import numpy as np

from app.models.schemas import (
    Claim,
    Evidence,
    Event,
    InboxItem,
    Project,
    ProjectMatch,
    SavedItem,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.services import claims as claims_service
from app.services import intelligence as intel_service
from app.services import projects as projects_service
from app.services import runtime as runtime_service
from app.services import saved as saved_service
from app.storage.db import Database


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_services.db")
    db = Database(db_path=db_path)

    now = datetime.now(timezone.utc)

    # 1. Insert Events
    ev1 = Event(
        id="ev_llvm_1",
        source="github",
        source_type="code_repository",
        event_type="release",
        title="LLVM 20.0 JIT Optimization Engine",
        text="Fast compiler backend with CUDA optimization passes",
        url="https://github.com/llvm/llvm-project/releases/tag/llvmorg-20.0.0",
        published_at=now - timedelta(days=2),
        discovered_at=now,
        final_score=0.90,
    )
    ev2 = Event(
        id="ev_rag_1",
        source="arxiv",
        source_type="academic_paper",
        event_type="paper",
        title="Vector Database Indexing for RAG",
        text="High-throughput vector indexing on disk",
        url="https://arxiv.org/abs/2608.12345",
        published_at=now - timedelta(days=5),
        discovered_at=now,
        final_score=0.85,
    )
    ev3 = Event(
        id="ev_css_1",
        source="github",
        source_type="code_repository",
        event_type="repository",
        title="Unrelated CSS UI Library",
        text="Styling toolkit for modern buttons and layouts",
        url="https://github.com/example/css-ui",
        published_at=now - timedelta(days=10),
        discovered_at=now,
        final_score=0.40,
    )
    db.save_event(ev1)
    db.save_event(ev2)
    db.save_event(ev3)

    # 2. Insert Clusters
    cl1 = StoryCluster(
        id="cluster_llvm",
        canonical_title="LLVM 20.0 JIT Optimization Engine",
        event_ids=["ev_llvm_1"],
        sources=["github"],
        cluster_score=0.90,
        source_diversity_score=0.50,
        max_event_score=0.90,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    cl2 = StoryCluster(
        id="cluster_rag",
        canonical_title="Vector Database Indexing for RAG",
        event_ids=["ev_rag_1"],
        sources=["arxiv"],
        cluster_score=0.85,
        source_diversity_score=0.50,
        max_event_score=0.85,
        created_at=now - timedelta(days=5),
        updated_at=now - timedelta(days=5),
    )
    cl3 = StoryCluster(
        id="cluster_css",
        canonical_title="Unrelated CSS UI Library",
        event_ids=["ev_css_1"],
        sources=["github"],
        cluster_score=0.40,
        source_diversity_score=0.30,
        max_event_score=0.40,
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=10),
    )
    db.save_cluster(cl1)
    db.save_cluster(cl2)
    db.save_cluster(cl3)

    # 3. Insert Claims & Evidence
    claim1 = Claim(
        id="claim_llvm_1",
        cluster_id="cluster_llvm",
        subject="LLVM 20.0 JIT",
        predicate="improves",
        object="compile latency by 45%",
        claim_text="LLVM 20.0 JIT improves compile latency by 45%",
        claim_type="performance",
        assertion_level="empirical_benchmark",
        status="supported",
        verification_score=0.82,
        self_reported=False,
    )
    db.save_claim(claim1)

    ev_rec = Evidence(
        id="ev_rec_1",
        claim_id="claim_llvm_1",
        event_id="ev_llvm_1",
        source="github",
        evidence_type="benchmark",
        evidence_class="independent",
        stance="support",
        quality_score=0.85,
        independence_score=0.90,
        url="https://github.com/llvm/llvm-project/benchmark",
    )
    db.save_evidence(ev_rec)

    # 4. Insert Assessments
    db.save_technology_assessment(
        TechnologyAssessment(
            cluster_id="cluster_llvm",
            maturity_stage="production_ready",
            assessment_score=0.85,
        )
    )
    db.save_technology_assessment(
        TechnologyAssessment(
            cluster_id="cluster_rag",
            maturity_stage="maturing",
            assessment_score=0.75,
        )
    )
    db.save_technology_assessment(
        TechnologyAssessment(
            cluster_id="cluster_css",
            maturity_stage="prototype",
            assessment_score=0.30,
        )
    )

    # 5. Insert Project & Match
    proj = Project(
        id="project:cuda-compiler-lab",
        name="cuda-compiler-lab",
        path=os.path.join(temp_dir, "ref_proj"),
        languages=["C++", "Cuda"],
        frameworks=["LLVM"],
        libraries=["CUDA"],
        databases=[],
        infrastructure=[],
        topics=["compiler-optimization", "jit"],
    )
    db.save_project(proj)

    match1 = ProjectMatch(
        id="match_1",
        project_id="project:cuda-compiler-lab",
        entity_type="cluster",
        entity_id="cluster_llvm",
        match_type="direct_dependency",
        relevance_score=0.92,
        impact_score=0.80,
        recommendation="evaluate",
        reason_codes=["direct_dependency", "framework_match"],
    )
    db.save_project_match(match1)

    # 6. Insert Inbox Item
    inbox_item = InboxItem(
        id="inbox_llvm_1",
        entity_type="cluster",
        entity_id="cluster_llvm",
        story_cluster_id="cluster_llvm",
        title="LLVM 20.0 JIT Optimization Engine",
        section="systems_compilers",
        inbox_score=0.85,
        rank_score=0.92,
        project_impact_score=0.80,
        state="unseen",
        matched_project_ids=["project:cuda-compiler-lab"],
        reason_codes=["high_relevance"],
    )
    db.save_inbox_item(inbox_item)

    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_search_intelligence_lexical(temp_db):
    results = intel_service.search_intelligence(
        query="LLVM optimization",
        mode="lexical",
        explain=True,
        db=temp_db,
    )
    assert len(results) >= 1
    top = results[0]
    assert "LLVM" in top.title
    assert top.verification_score >= 0.80
    assert top.explain is not None
    assert top.explain["lexical_score"] > 0.0


def test_search_project_boost(temp_db):
    res_without_proj = intel_service.search_intelligence(
        query="compiler",
        mode="lexical",
        explain=True,
        db=temp_db,
    )
    res_with_proj = intel_service.search_intelligence(
        query="compiler",
        project="cuda-compiler-lab",
        mode="lexical",
        explain=True,
        db=temp_db,
    )
    assert len(res_with_proj) >= 1
    assert res_with_proj[0].explain["project_boost"] > 0.0
    assert res_with_proj[0].score > res_without_proj[0].score


def test_search_filters(temp_db):
    # Source filter
    arxiv_only = intel_service.search_intelligence(query="database", source="arxiv", mode="lexical", db=temp_db)
    assert all("arxiv" in r.sources for r in arxiv_only)

    # Days filter (1 day should exclude all 2+ day old items)
    recent_only = intel_service.search_intelligence(query="database", days=1, mode="lexical", db=temp_db)
    assert len(recent_only) == 0

    # Verified only
    verified = intel_service.search_intelligence(query="CSS", verified_only=True, mode="lexical", db=temp_db)
    assert len(verified) == 0


def test_malformed_fts_query_safety(temp_db):
    # Queries with syntax that would break naive FTS concatenation
    bad_queries = ['"(" AND *', 'OR NOT ()', '"unterminated quote', '***', 'AND OR NEAR']
    for bq in bad_queries:
        res = intel_service.search_intelligence(query=bq, mode="lexical", db=temp_db)
        assert isinstance(res, list)


def test_story_details(temp_db):
    story = intel_service.get_story("cluster_llvm", db=temp_db)
    assert story is not None
    assert story.canonical_title == "LLVM 20.0 JIT Optimization Engine"
    assert len(story.events) == 1
    assert len(story.claims) == 1
    assert story.claims[0]["text"] == "LLVM 20.0 JIT improves compile latency by 45%"
    assert story.verification["maturity_stage"] == "production_ready"
    assert len(story.project_matches) == 1


def test_claim_details_and_provenance(temp_db):
    claim = claims_service.get_claim("claim_llvm_1", db=temp_db)
    assert claim is not None
    assert claim.claim_text == "LLVM 20.0 JIT improves compile latency by 45%"
    assert claim.status == "supported"
    assert claim.evidence_count == 1
    assert claim.evidence[0]["source"] == "github"
    assert claim.evidence[0]["is_independent"] is True


def test_claim_revision_preserves_none_verification_score(temp_db):
    from app.models.schemas import ClaimRevision
    # Insert a revision where new_verification_score and previous_verification_score are None
    rev = ClaimRevision(
        id="rev_unassessed_1",
        claim_id="claim_llvm_1",
        previous_status=None,
        new_status="unverified",
        previous_verification_score=None,
        new_verification_score=None,
        reason="Initial ingestion without verification",
    )
    temp_db.insert_claim_revision(rev)

    claim = claims_service.get_claim("claim_llvm_1", db=temp_db)
    assert claim is not None
    assert len(claim.revisions) == 1
    r = claim.revisions[0]
    assert r.revision_id == "rev_unassessed_1"
    assert r.new_status == "unverified"
    assert r.new_verification_score is None
    assert r.previous_verification_score is None


def test_project_summaries_privacy(temp_db):
    projects = projects_service.list_projects(db=temp_db)
    assert len(projects) == 1
    p = projects[0]
    assert p.name == "cuda-compiler-lab"
    assert "C++" in p.languages
    # Verify no raw source code attributes exist on ProjectSummary
    assert not hasattr(p, "raw_content")
    assert not hasattr(p, "file_bodies")


def test_saved_items_and_star_idempotence(temp_db):
    # Star once
    ok1, msg1, saved1 = saved_service.star_inbox_item("inbox_llvm_1", db=temp_db)
    assert ok1 is True
    assert saved1 is not None
    assert saved1["title"] == "LLVM 20.0 JIT Optimization Engine"

    # Star second time (idempotent)
    ok2, msg2, saved2 = saved_service.star_inbox_item("inbox_llvm_1", db=temp_db)
    assert ok2 is True
    all_saved = saved_service.get_saved_items(db=temp_db)
    assert len(all_saved) == 1


def test_saved_note_length_limit(temp_db):
    saved_service.star_inbox_item("inbox_llvm_1", db=temp_db)
    saved_id = "saved:cluster_llvm"

    # Valid note
    ok, msg = saved_service.add_saved_note(saved_id, "Fast JIT engine for CUDA kernels.", db=temp_db)
    assert ok is True

    # Oversized note (>2000 chars)
    giant_note = "A" * 2500
    ok_bad, msg_bad = saved_service.add_saved_note(saved_id, giant_note, db=temp_db)
    assert ok_bad is False
    assert "exceeds" in msg_bad


def test_legacy_schema_migration_preserves_rows_and_allows_null(tmp_path):
    import sqlite3
    from app.storage.db import Database

    db_file = tmp_path / "legacy_test.db"
    
    # 1. Create a pre-Phase-6 database with NOT NULL constraint on new_verification_score and new_score
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE claim_revisions (
            id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT NOT NULL,
            previous_verification_score REAL,
            new_verification_score REAL NOT NULL,
            reason TEXT NOT NULL,
            trigger_event_id TEXT,
            trigger_evidence_id TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE technology_assessment_revisions (
            id TEXT PRIMARY KEY,
            cluster_id TEXT NOT NULL,
            previous_stage TEXT,
            new_stage TEXT NOT NULL,
            previous_score REAL,
            new_score REAL NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    # Insert existing rows
    conn.execute("""
        INSERT INTO claim_revisions VALUES (
            'rev_legacy_1', 'claim_1', 'unverified', 'supported', 0.5, 0.85, 'Initial verification', NULL, NULL, '2026-08-01T00:00:00Z'
        )
    """)
    conn.execute("""
        INSERT INTO technology_assessment_revisions VALUES (
            'tech_rev_legacy_1', 'cluster_1', 'concept', 'research', 0.4, 0.6, 'Stage transition', '2026-08-01T00:00:00Z'
        )
    """)
    conn.commit()
    conn.close()

    # 2. Open via Database class, which should trigger _migrate_columns automatically
    db = Database(str(db_file))

    # 3. Verify existing rows survived intact
    cur = db.conn.cursor()
    cur.execute("SELECT * FROM claim_revisions WHERE id = 'rev_legacy_1'")
    cr_row = cur.fetchone()
    assert cr_row is not None
    assert cr_row["new_verification_score"] == 0.85

    cur.execute("SELECT * FROM technology_assessment_revisions WHERE id = 'tech_rev_legacy_1'")
    tar_row = cur.fetchone()
    assert tar_row is not None
    assert tar_row["new_score"] == 0.6

    # 4. Verify inserting NULL into new_verification_score and new_score succeeds
    cur.execute("""
        INSERT INTO claim_revisions VALUES (
            'rev_null_score', 'claim_1', NULL, 'unverified', NULL, NULL, 'Unassessed claim revision', NULL, NULL, '2026-08-21T00:00:00Z'
        )
    """)
    cur.execute("""
        INSERT INTO technology_assessment_revisions VALUES (
            'tech_rev_null_score', 'cluster_1', NULL, 'concept', NULL, NULL, 'Unassessed technology stage', '2026-08-21T00:00:00Z'
        )
    """)
    db.conn.commit()

    cur.execute("SELECT new_verification_score FROM claim_revisions WHERE id = 'rev_null_score'")
    assert cur.fetchone()[0] is None

    cur.execute("SELECT new_score FROM technology_assessment_revisions WHERE id = 'tech_rev_null_score'")
    assert cur.fetchone()[0] is None

