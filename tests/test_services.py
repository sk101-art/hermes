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
            maturity_stage="established",
            assessment_score=0.85,
        )
    )
    db.save_technology_assessment(
        TechnologyAssessment(
            cluster_id="cluster_rag",
            maturity_stage="early_adoption",
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
    assert story.verification["maturity_stage"] == "established"
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


def test_aggregate_cluster_claim_status_branches():
    from app.services.intelligence import aggregate_cluster_claim_status

    # 1. No claims -> None
    assert aggregate_cluster_claim_status([]) is None

    # 2. Retracted present -> retracted
    claims_retracted = [{"status": "supported"}, {"status": "retracted"}]
    assert aggregate_cluster_claim_status(claims_retracted) == "retracted"

    # 3. Contradicted + Positively supported -> mixed
    claims_contra_pos = [{"status": "contradicted"}, {"status": "supported"}]
    assert aggregate_cluster_claim_status(claims_contra_pos) == "mixed"
    claims_contra_strongly = [{"status": "contradicted"}, {"status": "strongly_supported"}]
    assert aggregate_cluster_claim_status(claims_contra_strongly) == "mixed"

    # 4. Contradicted only / no positive -> contradicted
    claims_contra_only = [{"status": "contradicted"}, {"status": "unverified"}]
    assert aggregate_cluster_claim_status(claims_contra_only) == "contradicted"

    # 5. Mixed present -> mixed
    claims_mixed = [{"status": "mixed"}, {"status": "unverified"}]
    assert aggregate_cluster_claim_status(claims_mixed) == "mixed"

    # 6. All strongly supported -> strongly_supported
    claims_all_strong = [{"status": "strongly_supported"}, {"status": "strongly_supported"}]
    assert aggregate_cluster_claim_status(claims_all_strong) == "strongly_supported"

    # 7. Supported + strongly supported -> supported
    claims_supp_strong = [{"status": "supported"}, {"status": "strongly_supported"}]
    assert aggregate_cluster_claim_status(claims_supp_strong) == "supported"

    # 8. Weakly supported only -> weakly_supported
    claims_weak = [{"status": "weakly_supported"}, {"status": "unverified"}]
    assert aggregate_cluster_claim_status(claims_weak) == "weakly_supported"

    # 9. Superseded only -> superseded
    claims_superseded = [{"status": "superseded"}, {"status": "superseded"}]
    assert aggregate_cluster_claim_status(claims_superseded) == "superseded"

    # 10. Unverified only -> unverified
    claims_unverif = [{"status": "unverified"}]
    assert aggregate_cluster_claim_status(claims_unverif) == "unverified"


def test_search_intelligence_contract_transport_and_explain(tmp_path):
    from app.services.intelligence import search_intelligence
    from app.models.schemas import Event, StoryCluster, Claim, TechnologyAssessment, TechnologyState, RiskStatus

    db = Database(str(tmp_path / "test_search_intel.db"))

    # Seed event and cluster: Grounded synthesis + strongly_supported + explain
    ev1 = Event(id="ev_1", source="github", title="Sparse Kernel Release", url="https://github.com/cuda/sparse", final_score=0.9, raw_payload={})
    db.save_event(ev1)
    cl1 = StoryCluster(id="cluster_1", canonical_title="CUDA Sparse Kernel Compiler Optimization", cluster_score=0.85, sources=["github"], event_ids=["ev_1"])
    db.save_cluster(cl1)

    clm1 = Claim(
        id="clm_1",
        cluster_id="cluster_1",
        subject="Sparse kernel",
        predicate="achieves",
        object="2.5x speedup",
        claim_text="Sparse kernel achieves 2.5x speedup.",
        status="strongly_supported",
        verification_score=0.92,
        is_self_reported=True,
        claim_type="performance",
    )
    db.save_claim(clm1)
    db.save_technology_assessment(TechnologyAssessment(cluster_id="cluster_1", maturity_stage="prototype", score=0.8))
    db.save_technology_state(TechnologyState(cluster_id="cluster_1", maturity_stage="prototype", risk_score=0.25, risk_status=RiskStatus.ASSESSED))

    # Search with explain=True
    results = search_intelligence("sparse kernel", explain=True, db=db)
    assert len(results) >= 1
    r1 = next(r for r in results if r.entity_id == "cluster_1")
    assert r1.is_synthesized is True
    assert r1.claim_status == "strongly_supported"
    assert r1.verification_score == 0.92
    assert r1.score > 0.0
    assert r1.explain is not None
    assert "lexical_score" in r1.explain
    assert "semantic_score" in r1.explain
    assert "verification_adjustment" in r1.explain
    assert "freshness_adjustment" in r1.explain
    assert "project_boost" in r1.explain
    assert "final_score" in r1.explain

    # Verified only filter
    verif_results = search_intelligence("sparse kernel", verified_only=True, db=db)
    assert any(r.entity_id == "cluster_1" for r in verif_results)

    # Max risk filter: low (max_risk='low' should exclude medium risk score 0.25)
    low_risk_results = search_intelligence("sparse kernel", max_risk="low", db=db)
    assert not any(r.entity_id == "cluster_1" for r in low_risk_results)


def test_search_intelligence_uses_retrieved_current_claims_for_aggregation(tmp_path):
    """Proves search_intelligence fetches canonical claims via db.get_claims_by_cluster rather than an unhydrated attribute."""
    from app.services.intelligence import search_intelligence
    from app.models.schemas import Event, StoryCluster, Claim

    db = Database(str(tmp_path / "test_claims_hydrated.db"))
    ev = Event(id="ev_hydrated", source="github", title="Quantum compiler engine", url="https://github.com/qc/engine", final_score=0.9, raw_payload={})
    db.save_event(ev)
    cl = StoryCluster(id="cluster_qc", canonical_title="Quantum compiler engine optimization", cluster_score=0.9, sources=["github"], event_ids=["ev_hydrated"])
    db.save_cluster(cl)

    # Current claim: supported
    c1 = Claim(id="c1", cluster_id="cluster_qc", subject="QC", predicate="speeds", object="run", claim_text="QC speeds run", status="supported", verification_score=0.85, is_self_reported=False)
    db.save_claim(c1)

    results = search_intelligence("Quantum compiler", db=db)
    assert len(results) == 1
    assert results[0].claim_status == "supported"
    assert results[0].verification_score == 0.85


def test_search_verified_only_all_nine_claim_permutations(tmp_path):
    """Comprehensive test covering all 9 claim status permutations under verified_only=True."""
    from app.services.intelligence import search_intelligence
    from app.models.schemas import Event, StoryCluster, Claim

    db = Database(str(tmp_path / "test_verif_permutations.db"))

    permutations = [
        ("strongly_supported", 0.90, True),
        ("supported", 0.75, True),
        ("weakly_supported", 0.80, False),  # status not in (supported, strongly_supported)
        ("mixed", 0.70, False),
        ("contradicted", 0.80, False),
        ("unverified", 0.65, False),
        ("superseded", 0.90, False),
        ("retracted", 0.90, False),
        ("no_claims", 0.0, False),
    ]

    for status_name, verif_score, should_pass in permutations:
        cid = f"cluster_{status_name}"
        evid = f"ev_{status_name}"
        ev = Event(id=evid, source="github", title=f"Bench {status_name} system", url=f"https://github.com/{status_name}", final_score=0.8, raw_payload={})
        db.save_event(ev)
        cl = StoryCluster(id=cid, canonical_title=f"Benchmark {status_name} evaluation", cluster_score=0.8, sources=["github"], event_ids=[evid])
        db.save_cluster(cl)

        if status_name != "no_claims":
            clm = Claim(
                id=f"clm_{status_name}",
                cluster_id=cid,
                subject=f"System {status_name}",
                predicate="passes",
                object="test",
                claim_text=f"System {status_name} test claim",
                status=status_name,
                verification_score=verif_score,
                is_self_reported=False,
            )
            db.save_claim(clm)

    # Search with verified_only=True
    verif_results = search_intelligence("Benchmark", verified_only=True, db=db)
    returned_ids = {r.entity_id for r in verif_results}

    assert "cluster_strongly_supported" in returned_ids
    assert "cluster_supported" in returned_ids
    assert "cluster_weakly_supported" not in returned_ids
    assert "cluster_mixed" not in returned_ids
    assert "cluster_contradicted" not in returned_ids
    assert "cluster_unverified" not in returned_ids
    assert "cluster_superseded" not in returned_ids
    assert "cluster_retracted" not in returned_ids
    assert "cluster_no_claims" not in returned_ids


def test_search_symbol_queries_cpp_cuda_aes(tmp_path):
    """Regression test proving C++, CUDA 13, and AES-256 can be searched accurately."""
    from app.services.intelligence import search_intelligence
    from app.models.schemas import Event, StoryCluster

    db = Database(str(tmp_path / "test_symbol_search.db"))

    # Seed C++ cluster
    db.save_event(Event(id="ev_cpp", source="github", title="Llama C++ inference engine", url="https://github.com/llama/cpp", final_score=0.9, raw_payload={}))
    db.save_cluster(StoryCluster(id="cl_cpp", canonical_title="ggml-org/llama.cpp - LLM inference in C/C++", cluster_score=0.9, sources=["github"], event_ids=["ev_cpp"]))

    # Seed CUDA 13 cluster
    db.save_event(Event(id="ev_cuda", source="github", title="CUDA 13 compiler kernels", url="https://github.com/cuda/kernels", final_score=0.9, raw_payload={}))
    db.save_cluster(StoryCluster(id="cl_cuda", canonical_title="NVIDIA CUDA 13 kernel architecture", cluster_score=0.9, sources=["github"], event_ids=["ev_cuda"]))

    # Seed AES-256 cluster
    db.save_event(Event(id="ev_aes", source="github", title="AES-256 hardware acceleration", url="https://github.com/crypto/aes", final_score=0.9, raw_payload={}))
    db.save_cluster(StoryCluster(id="cl_aes", canonical_title="AES-256 cryptographic hardware module", cluster_score=0.9, sources=["github"], event_ids=["ev_aes"]))

    # Test C++
    res_cpp = search_intelligence("C++", db=db)
    assert any(r.entity_id == "cl_cpp" for r in res_cpp)

    # Test CUDA 13
    res_cuda = search_intelligence("CUDA 13", db=db)
    assert any(r.entity_id == "cl_cuda" for r in res_cuda)

    # Test AES-256
    res_aes = search_intelligence("AES-256", db=db)
    assert any(r.entity_id == "cl_aes" for r in res_aes)


# =========================================================================
# Phase 8: Saved Intelligence Library & Snapshot Contract Tests
# =========================================================================

def test_saved_schema_migration_preserves_legacy_rows_without_backfill(tmp_path):
    """Proves legacy SavedItem rows with pre-Phase-8 schema migrate safely with NULL snapshot statuses without backfill."""
    import sqlite3
    db_path = str(tmp_path / "legacy_saved.db")

    # Create pre-Phase-8 saved_items table manually without the 3 new columns
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE saved_items (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL DEFAULT 'cluster',
            entity_id TEXT NOT NULL,
            story_cluster_id TEXT NOT NULL,
            inbox_item_id TEXT,
            title_snapshot TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            verification_snapshot REAL,
            maturity_snapshot TEXT,
            risk_snapshot REAL,
            user_note TEXT,
            tags_json TEXT,
            project_ids_json TEXT,
            is_active INTEGER DEFAULT 1,
            link_status TEXT DEFAULT 'resolved',
            event_ids_snapshot_json TEXT
        )
    """)
    conn.execute("""
        INSERT INTO saved_items (
            id, entity_type, entity_id, story_cluster_id, title_snapshot,
            saved_at, verification_snapshot, maturity_snapshot, risk_snapshot,
            user_note, tags_json, project_ids_json, is_active
        ) VALUES (
            'saved:cl_legacy', 'cluster', 'cl_legacy', 'cl_legacy', 'Legacy Cluster Title',
            '2026-01-01T10:00:00+00:00', 0.64, 'established', 0.31,
            'Original note', '["research"]', '[]', 1
        )
    """)
    conn.commit()
    conn.close()

    # Now open with Database class which runs schema migrations
    db = Database(db_path)

    # Verify columns were added
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(saved_items)").fetchall()}
    assert "claim_status_snapshot" in cols
    assert "risk_status_snapshot" in cols
    assert "risk_level_snapshot" in cols

    # Verify legacy row has exact preserved fields and NULL for new snapshot statuses (no backfill)
    item = db.get_saved_item("saved:cl_legacy")
    assert item is not None
    assert item.title_snapshot == "Legacy Cluster Title"
    assert item.verification_snapshot == 0.64
    assert item.maturity_snapshot == "established"
    assert item.risk_snapshot == 0.31
    assert item.claim_status_snapshot is None
    assert item.risk_status_snapshot is None
    assert item.risk_level_snapshot is None


def test_saved_item_direct_save_truthful_snapshot_and_idempotence(tmp_path):
    """Proves direct saving captures full truthful snapshot, is idempotent, and supports deactivation/reactivation."""
    from app.models.schemas import Claim, StoryCluster, TechnologyAssessment, TechnologyState
    from app.services.saved import get_saved_items, save_cluster_item, delete_saved_item

    db = Database(str(tmp_path / "test_saved_idemp.db"))

    # Seed story cluster, claims, assessment, and tech state
    cid = "cl_test_phase8"
    db.save_cluster(StoryCluster(id=cid, canonical_title="Quantum Compiler Optimization", cluster_score=0.88, event_ids=["ev1", "ev2"]))
    db.save_claim(Claim(id="c1", cluster_id=cid, subject="Compiler", predicate="optimizes", object="Circuits", claim_text="Reduces gate depth by 40%", status="supported", verification_score=0.85, is_current=True))
    db.save_claim(Claim(id="c2", cluster_id=cid, subject="Compiler", predicate="supports", object="Transmon", claim_text="Verified on transmon hardware", status="strongly_supported", verification_score=0.95, is_current=True))
    db.save_technology_assessment(TechnologyAssessment(cluster_id=cid, maturity_stage="production_candidate", assessment_score=0.85))
    db.save_technology_state(TechnologyState(cluster_id=cid, current_status="active", risk_score=0.15, trend="improving"))

    # 1. Save directly
    success, msg, saved = save_cluster_item(story_cluster_id=cid, user_note="Initial analysis", tags=["quantum", "compiler"], db=db)
    assert success is True
    assert saved is not None
    assert saved["id"] == f"saved:{cid}"
    assert saved["title"] == "Quantum Compiler Optimization"
    assert saved["verification_score"] == 0.9  # mean of 0.85 and 0.95
    assert saved["claim_status"] == "supported"  # 1 strongly_supported, 1 supported -> supported
    assert saved["maturity_stage"] == "production_candidate"
    assert saved["risk_status"] == "assessed"
    assert saved["risk_level"] == "low"  # risk_score 0.15 < 0.2
    assert saved["risk_score"] == 0.15
    assert saved["user_note"] == "Initial analysis"
    assert "quantum" in saved["tags"]

    # 2. Re-save (idempotent): merges tags and updates note if provided
    success2, msg2, saved2 = save_cluster_item(story_cluster_id=cid, user_note="Updated note", tags=["compiler", "benchmark"], db=db)
    assert success2 is True
    assert saved2["id"] == f"saved:{cid}"
    assert saved2["user_note"] == "Updated note"
    assert set(saved2["tags"]) == {"quantum", "compiler", "benchmark"}

    # 3. Soft Delete by SavedItem ID
    del_ok, del_msg = delete_saved_item(saved["id"], db=db)
    assert del_ok is True
    active_saved = get_saved_items(db=db)
    assert not any(s["id"] == saved["id"] for s in active_saved)

    # 4. Re-saving reactivates the record
    success3, msg3, saved3 = save_cluster_item(story_cluster_id=cid, db=db)
    assert success3 is True
    assert "reactivated" in msg3.lower() or "already" in msg3.lower()
    active_saved2 = get_saved_items(db=db)
    assert any(s["id"] == saved["id"] for s in active_saved2)


def test_saved_hydration_uses_canonical_aggregate_claim_status(tmp_path):
    """Proves CurrentIntelligenceState hydration uses aggregate_cluster_claim_status and does not cause N+1 queries."""
    from app.models.schemas import Claim, StoryCluster, TechnologyAssessment, TechnologyState
    from app.services.saved import get_saved_items, save_cluster_item

    db = Database(str(tmp_path / "test_saved_hydration.db"))

    # Seed 3 clusters with different claim distributions
    for i in range(3):
        cid = f"cl_batch_{i}"
        db.save_cluster(StoryCluster(id=cid, canonical_title=f"Cluster {i}", cluster_score=0.75, event_ids=[f"ev_{i}"]))
        if i == 0:
            # 1 supported, 1 contradicted -> mixed
            db.save_claim(Claim(id=f"c_{i}_1", cluster_id=cid, subject="S", predicate="P", object="O", claim_text="Fact 1", status="supported", verification_score=0.8, is_current=True))
            db.save_claim(Claim(id=f"c_{i}_2", cluster_id=cid, subject="S", predicate="P", object="O", claim_text="Fact 2", status="contradicted", verification_score=0.2, is_current=True))
        else:
            db.save_claim(Claim(id=f"c_{i}_1", cluster_id=cid, subject="S", predicate="P", object="O", claim_text="Fact 1", status="strongly_supported", verification_score=0.9, is_current=True))
        db.save_technology_assessment(TechnologyAssessment(cluster_id=cid, maturity_stage="experimental"))
        db.save_technology_state(TechnologyState(cluster_id=cid, current_status="active", risk_score=0.3))

        save_cluster_item(story_cluster_id=cid, db=db)

    # Hydrate with include_current=True
    items = get_saved_items(limit=10, include_current=True, db=db)
    assert len(items) == 3

    # Check cluster 0 current state has mixed claim_status
    c0 = next(it for it in items if it["story_cluster_id"] == "cl_batch_0")
    assert c0["current_state"] is not None
    assert c0["current_state"]["claim_status"] == "mixed"
    assert c0["current_state"]["maturity_stage"] == "experimental"
    assert c0["current_state"]["risk_level"] == "medium"
    assert c0["current_state"]["risk_status"] == "assessed"


def test_save_item_request_contract_validation(tmp_path):
    """Proves SaveItemRequest validation enforces non-empty story_cluster_id, string lengths, and inbox association."""
    import pytest
    from pydantic import ValidationError
    from app.models.schemas import InboxItem, StoryCluster
    from app.services.schemas import SaveItemRequest
    from app.services.saved import save_cluster_item

    db = Database(str(tmp_path / "test_saved_req.db"))
    db.save_cluster(StoryCluster(id="cl_match", canonical_title="Matching Cluster", cluster_score=0.8))
    db.save_inbox_item(InboxItem(id="inbox_123", entity_id="cl_match", story_cluster_id="cl_match", title="Inbox Match", summary="", priority_score=0.8, why_it_matters=""))

    # Empty story_cluster_id raises ValidationError
    with pytest.raises(ValidationError):
        SaveItemRequest(story_cluster_id="")

    # Note > 2000 chars raises ValidationError
    with pytest.raises(ValidationError):
        SaveItemRequest(story_cluster_id="cl_match", user_note="x" * 2001)

    # Tag > 50 chars raises ValidationError
    with pytest.raises(ValidationError):
        SaveItemRequest(story_cluster_id="cl_match", tags=["valid", "t" * 51])

    # Valid SaveItemRequest succeeds
    req = SaveItemRequest(story_cluster_id="cl_match", inbox_item_id="inbox_123", user_note="Note", tags=["tag1"])
    assert req.story_cluster_id == "cl_match"

    # Mismatch between inbox_item_id and story_cluster_id is rejected by service
    ok, msg, res = save_cluster_item(story_cluster_id="cl_unrelated", inbox_item_id="inbox_123", db=db)
    assert ok is False
    assert "does not belong" in msg.lower()


def test_save_identity_and_reactivation_all_five_sequences(tmp_path):
    """Proves all 5 save sequences resolve strictly to canonical saved:{story_cluster_id} with no duplicate active rows."""
    from app.models.schemas import InboxItem, StoryCluster
    from app.services.saved import save_cluster_item, star_inbox_item, delete_saved_item

    db = Database(str(tmp_path / "test_saved_5_seq.db"))
    cid = "cl_seq_test"
    db.save_cluster(StoryCluster(id=cid, canonical_title="Sequence Test Story", cluster_score=0.8))
    db.save_inbox_item(InboxItem(id="inbox_seq_1", entity_id=cid, story_cluster_id=cid, title="Inbox Item", summary="", priority_score=0.75, why_it_matters=""))

    # 1. First save
    ok1, msg1, item1 = save_cluster_item(story_cluster_id=cid, user_note="First save note", tags=["tag1"], db=db)
    assert ok1 is True
    assert item1["id"] == f"saved:{cid}"
    all_rows1 = db.get_all_saved_items(active_only=False)
    assert len([r for r in all_rows1 if r.story_cluster_id == cid]) == 1
    assert len([r for r in all_rows1 if r.story_cluster_id == cid and r.is_active]) == 1

    # 2. Duplicate active save (idempotent, merges tags & updates note)
    ok2, msg2, item2 = save_cluster_item(story_cluster_id=cid, user_note="Updated note", tags=["tag2"], db=db)
    assert ok2 is True
    assert item2["id"] == f"saved:{cid}"
    assert set(item2["tags"]) == {"tag1", "tag2"}
    all_rows2 = db.get_all_saved_items(active_only=False)
    assert len([r for r in all_rows2 if r.story_cluster_id == cid]) == 1
    assert len([r for r in all_rows2 if r.story_cluster_id == cid and r.is_active]) == 1

    # 3. Re-save after soft deletion (reactivates record)
    del_ok, _ = delete_saved_item(f"saved:{cid}", db=db)
    assert del_ok is True
    all_rows3_del = db.get_all_saved_items(active_only=False)
    assert len([r for r in all_rows3_del if r.story_cluster_id == cid and r.is_active]) == 0
    ok3, msg3, item3 = save_cluster_item(story_cluster_id=cid, db=db)
    assert ok3 is True
    assert item3["id"] == f"saved:{cid}"
    all_rows3 = db.get_all_saved_items(active_only=False)
    assert len([r for r in all_rows3 if r.story_cluster_id == cid]) == 1
    assert len([r for r in all_rows3 if r.story_cluster_id == cid and r.is_active]) == 1

    # 4. Inbox save followed by Story Dossier save
    cid_inbox = "cl_inbox_seq"
    db.save_cluster(StoryCluster(id=cid_inbox, canonical_title="Inbox Flow Story", cluster_score=0.85))
    db.save_inbox_item(InboxItem(id="inbox_seq_2", entity_id=cid_inbox, story_cluster_id=cid_inbox, title="Inbox Item 2", summary="", priority_score=0.8, why_it_matters=""))
    # (a) Inbox star/save
    ok_inbox, _, res_inbox = star_inbox_item("inbox_seq_2", db=db)
    assert ok_inbox is True
    assert res_inbox["id"] == f"saved:{cid_inbox}"
    # (b) Followed by Story Dossier save
    ok_dossier, _, res_dossier = save_cluster_item(story_cluster_id=cid_inbox, user_note="Dossier save note", tags=["dossier"], db=db)
    assert ok_dossier is True
    assert res_dossier["id"] == f"saved:{cid_inbox}"
    all_rows4 = db.get_all_saved_items(active_only=False)
    assert len([r for r in all_rows4 if r.story_cluster_id == cid_inbox]) == 1
    assert len([r for r in all_rows4 if r.story_cluster_id == cid_inbox and r.is_active]) == 1

    # 5. Search save followed by Story Dossier save
    cid_search = "cl_search_seq"
    db.save_cluster(StoryCluster(id=cid_search, canonical_title="Search Flow Story", cluster_score=0.9))
    # (a) Save initiated from search context
    ok_search, _, res_search = save_cluster_item(story_cluster_id=cid_search, tags=["search_origin"], db=db)
    assert ok_search is True
    assert res_search["id"] == f"saved:{cid_search}"
    # (b) Followed by Story Dossier save
    ok_dossier2, _, res_dossier2 = save_cluster_item(story_cluster_id=cid_search, user_note="Deep analysis note", tags=["dossier_detail"], db=db)
    assert ok_dossier2 is True
    assert res_dossier2["id"] == f"saved:{cid_search}"
    all_rows5 = db.get_all_saved_items(active_only=False)
    assert len([r for r in all_rows5 if r.story_cluster_id == cid_search]) == 1
    assert len([r for r in all_rows5 if r.story_cluster_id == cid_search and r.is_active]) == 1


def test_changes_contract_detected_at_and_provenance(tmp_path):
    """Proves Changes service exposes canonical detected_at, preserves provenance, and filters accurately."""
    from datetime import datetime, timezone, timedelta
    from app.models.schemas import IntelligenceChange, StoryCluster, Claim, Project, ProjectMatch
    from app.services.intelligence import get_recent_changes

    db = Database(str(tmp_path / "test_changes_p9.db"))
    now = datetime.now(timezone.utc)

    # 1. Seed Story Clusters and Claims
    cid1 = "cl_p9_1"
    cid2 = "cl_p9_2"
    db.save_cluster(StoryCluster(id=cid1, canonical_title="Quantum Speedup", cluster_score=0.9))
    db.save_cluster(StoryCluster(id=cid2, canonical_title="Database Scaling", cluster_score=0.7))

    db.save_claim(Claim(id="claim_q1", cluster_id=cid1, subject="Quantum", predicate="proves", object="Speedup", claim_text="100x speedup verified", status="supported", is_current=True))

    # 2. Seed Project and Match
    db.save_project(Project(id="proj_quantum", name="Quantum Core Project", path="/quantum"))
    db.save_project_match(ProjectMatch(id="pm_1", project_id="proj_quantum", entity_id=cid1, entity_type="cluster", relevance_score=0.95, reasoning="Core quantum tech"))

    # 3. Seed Changes with various timestamps and origins
    # (a) Critical revision within 2h
    db.save_intelligence_change(IntelligenceChange(
        id="ch_1",
        entity_type="claim",
        entity_id="claim_q1",
        change_type="verification_weakened",
        old_value="supported (0.8500)",
        new_value="contradicted (0.1500)",
        importance=0.95,
        reason="Independent reproduction failed.",
        origin="actual_revision",
        created_at=now - timedelta(hours=2),
    ))

    # (b) Migration system record within 5h
    db.save_intelligence_change(IntelligenceChange(
        id="ch_2",
        entity_type="cluster",
        entity_id=cid2,
        change_type="cluster_migrated",
        old_value="prototype",
        new_value="experimental",
        importance=0.30,
        reason="Database migration backfill.",
        origin="migration",
        created_at=now - timedelta(hours=5),
    ))

    # (c) High-importance new evidence within 10h
    db.save_intelligence_change(IntelligenceChange(
        id="ch_3",
        entity_type="cluster",
        entity_id=cid1,
        change_type="maturity_stage_changed",
        old_value="concept",
        new_value="prototype",
        importance=0.75,
        reason="Prototype released publicly.",
        origin="new_evidence",
        created_at=now - timedelta(hours=10),
    ))

    # (d) Older change outside 24h cutoff (e.g. 48h ago)
    db.save_intelligence_change(IntelligenceChange(
        id="ch_4",
        entity_type="cluster",
        entity_id=cid2,
        change_type="risk_level_changed",
        old_value="not_assessed",
        new_value="assessed/medium",
        importance=0.60,
        reason="Threat model completed.",
        origin="live_update",
        created_at=now - timedelta(hours=48),
    ))

    # Test Case 1: Default 24h lookup
    recent_24 = get_recent_changes(hours=24, db=db)
    assert len(recent_24) == 3
    # Check canonical fields
    c1 = next(c for c in recent_24 if c["id"] == "ch_1")
    assert c1["detected_at"] is not None
    assert c1["created_at"] is not None
    assert c1["detected_at"] == c1["created_at"]
    assert c1["origin"] == "actual_revision"
    assert c1["importance_level"] == "critical"
    assert c1["cluster_id"] == cid1  # resolved from claim_q1 -> cl_p9_1
    assert c1["old_value"] == "supported (0.8500)"
    assert c1["new_value"] == "contradicted (0.1500)"

    # Test Case 2: Minimum importance filter
    high_plus = get_recent_changes(hours=24, importance_min="high", db=db)
    assert len(high_plus) == 2  # ch_1 (0.95 critical) and ch_3 (0.75 high)
    assert not any(c["id"] == "ch_2" for c in high_plus)

    critical_only = get_recent_changes(hours=24, importance_min="critical", db=db)
    assert len(critical_only) == 1
    assert critical_only[0]["id"] == "ch_1"

    # Test Case 3: Project relevance filter
    proj_filtered = get_recent_changes(hours=24, project="proj_quantum", db=db)
    assert len(proj_filtered) == 2
    assert all(c["id"] in ("ch_1", "ch_3") for c in proj_filtered)
    assert not any(c["id"] == "ch_2" for c in proj_filtered)

    # Test Case 4: Extended 72h window includes ch_4
    recent_72 = get_recent_changes(hours=72, db=db)
    assert len(recent_72) == 4
    c4 = next(c for c in recent_72 if c["id"] == "ch_4")
    assert c4["origin"] == "live_update"
    assert c4["old_value"] == "not_assessed"
    assert c4["new_value"] == "assessed/medium"




