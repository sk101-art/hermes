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


def test_inbox_contract_transport_and_filtering(tmp_path):
    from app.storage.db import Database
    from app.services.intelligence import get_today_inbox
    from app.services.saved import save_cluster_item, delete_saved_item
    from app.models.schemas import InboxItem, StoryCluster, Project

    db_path = tmp_path / "test_inbox.db"
    db = Database(str(db_path))

    # Setup 2 projects
    db.save_project(Project(
        id="project:proj_ml",
        name="Machine Learning Lab",
        path="/tmp/ml",
        description="ML project",
    ))
    db.save_project(Project(
        id="project:proj_sys",
        name="Systems Lab",
        path="/tmp/sys",
        description="Compiler project",
    ))

    # Setup Story Clusters: cl_1 exists, cl_3 does not exist (unavailable)
    db.save_cluster(StoryCluster(
        id="cl_inbox_1",
        canonical_title="PyTorch Compiler Optimization",
        summary="Speedup in tensor graphs",
        category="ai_ml",
        score=0.85,
    ))
    db.save_cluster(StoryCluster(
        id="cl_inbox_2",
        canonical_title="LLVM Vectorization Pipeline",
        summary="New loop vectorizer",
        category="systems_compilers",
        score=0.75,
    ))

    now = datetime.now(timezone.utc)

    # Item 1: High priority, unseen, ai_ml, matched to proj_ml, resolvable cluster
    db.save_inbox_item(InboxItem(
        id="ib_1",
        entity_type="cluster",
        entity_id="cl_inbox_1",
        story_cluster_id="cl_inbox_1",
        title="PyTorch Compiler Optimization",
        section="ai_ml",
        inbox_score=0.92,
        rank_score=0.92,
        project_impact_score=0.80,
        state="unseen",
        item_type="claim_strengthened",
        created_at=now,
        expires_at=now + timedelta(days=2),
        matched_project_ids=["project:proj_ml"],
        reason_codes=["intel_change:verification_strengthened", "recent_discovery"],
    ))

    # Item 2: Medium priority, seen, systems_compilers, matched to proj_sys
    db.save_inbox_item(InboxItem(
        id="ib_2",
        entity_type="cluster",
        entity_id="cl_inbox_2",
        story_cluster_id="cl_inbox_2",
        title="LLVM Vectorization Pipeline",
        section="systems_compilers",
        inbox_score=0.78,
        rank_score=0.78,
        project_impact_score=0.65,
        state="seen",
        item_type="new_release",
        created_at=now,
        expires_at=now + timedelta(days=1),
        matched_project_ids=["project:proj_sys"],
        reason_codes=["official_release"],
    ))

    # Item 3: Low priority, unseen, corrections_updates, unresolvable cluster (cl_missing)
    db.save_inbox_item(InboxItem(
        id="ib_3",
        entity_type="claim",
        entity_id="claim_missing",
        story_cluster_id="cl_missing_nonexistent",
        title="Retraction Notice for Flawed Benchmark",
        section="corrections_updates",
        inbox_score=0.60,
        rank_score=0.60,
        project_impact_score=0.0,
        state="unseen",
        item_type="claim_weakened",
        created_at=now,
        expires_at=now + timedelta(days=3),
        matched_project_ids=[],
        reason_codes=["claim_weakened", "contradictory_evidence"],
    ))

    # Test 1: Full active list order preservation
    items = get_today_inbox(db=db)
    assert len(items) == 3
    assert items[0]["id"] == "ib_1"
    assert items[1]["id"] == "ib_2"
    assert items[2]["id"] == "ib_3"

    # Test 2: Truthful field transport
    it1 = items[0]
    assert it1["id"] == "ib_1"
    assert it1["entity_type"] == "cluster"
    assert it1["entity_id"] == "cl_inbox_1"
    assert it1["story_cluster_id"] == "cl_inbox_1"
    assert it1["title"] == "PyTorch Compiler Optimization"
    assert it1["section"] == "ai_ml"
    assert it1["state"] == "unseen"
    assert it1["item_type"] == "claim_strengthened"
    assert it1["inbox_score"] == 0.92
    assert it1["rank_score"] == 0.92
    assert it1["project_impact_score"] == 0.80
    assert it1["matched_project_ids"] == ["project:proj_ml"]
    assert it1["reason_codes"] == ["intel_change:verification_strengthened", "recent_discovery"]
    assert it1["story_available"] is True
    assert it1["is_starred"] is False
    assert it1["saved_item_id"] is None

    # Test 3: Unresolvable story cluster reflects story_available=False
    it3 = items[2]
    assert it3["story_cluster_id"] == "cl_missing_nonexistent"
    assert it3["story_available"] is False
    assert it3["item_type"] == "claim_weakened"

    # Test 4: unseen_only filter
    unseen_items = get_today_inbox(unseen_only=True, db=db)
    assert len(unseen_items) == 2
    assert {i["id"] for i in unseen_items} == {"ib_1", "ib_3"}

    # Test 5: section filter
    sec_items = get_today_inbox(section="systems_compilers", db=db)
    assert len(sec_items) == 1
    assert sec_items[0]["id"] == "ib_2"

    # Test 6: project filter
    proj_items = get_today_inbox(project="proj_ml", db=db)
    assert len(proj_items) == 1
    assert proj_items[0]["id"] == "ib_1"

    # Test 7: limit
    limited = get_today_inbox(limit=1, db=db)
    assert len(limited) == 1
    assert limited[0]["id"] == "ib_1"

    # Test 8: Saved item synchronization & active truthfulness
    ok, msg, saved_obj = save_cluster_item(story_cluster_id="cl_inbox_1", inbox_item_id="ib_1", db=db)
    assert ok is True
    assert saved_obj is not None

    items_after_save = get_today_inbox(db=db)
    saved_it1 = next(i for i in items_after_save if i["id"] == "ib_1")
    assert saved_it1["is_starred"] is True
    assert saved_it1["saved_item_id"] == f"saved:cl_inbox_1"

    # Test 9: Deactivating saved item synchronizes back truthfully
    del_ok, del_msg = delete_saved_item(saved_id=f"saved:cl_inbox_1", db=db)
    assert del_ok is True

    items_after_delete = get_today_inbox(db=db)
    unstarred_it1 = next(i for i in items_after_delete if i["id"] == "ib_1")
    assert unstarred_it1["is_starred"] is False
    assert unstarred_it1["saved_item_id"] is None


def test_inbox_null_score_preservation_and_stale_saved_isolation(tmp_path):
    from app.storage.db import Database
    from app.services.intelligence import get_today_inbox
    from app.services.saved import save_cluster_item, delete_saved_item
    from app.models.schemas import InboxItem, StoryCluster, SavedItem

    db_path = tmp_path / "test_remediation_null_stale.db"
    db = Database(str(db_path))

    now = datetime.now(timezone.utc)

    # Setup Story Cluster
    db.save_cluster(StoryCluster(
        id="cl_stale_1",
        canonical_title="Historical Research Cluster",
        summary="Quantum memory coherence",
        category="research",
        score=0.80,
    ))

    # Save a SavedItem directly with is_active = 0 (inactive historical saved item)
    db.save_saved_item(SavedItem(
        id="saved:cl_stale_1",
        entity_type="cluster",
        entity_id="cl_stale_1",
        story_cluster_id="cl_stale_1",
        title_snapshot="Historical Research Cluster",
        is_active=False,
        created_at=now,
        updated_at=now,
    ))

    # Inbox row contains stale is_starred=True and stale saved_item_id
    # Scores are None (null)
    db.save_inbox_item(InboxItem(
        id="ib_stale_1",
        entity_type="cluster",
        entity_id="cl_stale_1",
        story_cluster_id="cl_stale_1",
        title="Historical Research Cluster",
        section="research",
        inbox_score=None,
        rank_score=None,
        project_impact_score=None,
        is_starred=True,
        saved_item_id="saved:cl_stale_1",
        state="unseen",
        item_type="new_story",
        created_at=now,
        matched_project_ids=[],
        reason_codes=["recent_discovery"],
    ))

    # Fetch inbox: Assert null scores remain None and stale saved state is isolated
    items = get_today_inbox(db=db)
    assert len(items) == 1
    it = items[0]
    assert it["inbox_score"] is None
    assert it["rank_score"] is None
    assert it["project_impact_score"] is None
    assert it["is_starred"] is False
    assert it["saved_item_id"] is None

    # Reactivate via save_cluster_item
    ok, msg, saved_obj = save_cluster_item(story_cluster_id="cl_stale_1", db=db)
    assert ok is True
    assert saved_obj is not None

    items_after_reactivate = get_today_inbox(db=db)
    it_reactivated = items_after_reactivate[0]
    assert it_reactivated["is_starred"] is True
    assert it_reactivated["saved_item_id"] == "saved:cl_stale_1"

    # Soft-delete again
    del_ok, _ = delete_saved_item(saved_id="saved:cl_stale_1", db=db)
    assert del_ok is True

    items_after_soft_delete = get_today_inbox(db=db)
    it_deleted = items_after_soft_delete[0]
    assert it_deleted["is_starred"] is False
    assert it_deleted["saved_item_id"] is None


def test_inbox_complete_candidate_filtering_beyond_100_rows(tmp_path):
    from app.storage.db import Database
    from app.services.intelligence import get_today_inbox
    from app.models.schemas import InboxItem, StoryCluster, Project

    db_path = tmp_path / "test_remediation_100_rows.db"
    db = Database(str(db_path))

    now = datetime.now(timezone.utc)

    # Setup Target Project and Common Project
    db.save_project(Project(
        id="project:proj_target",
        name="Target Project",
        path="/tmp/target",
    ))
    db.save_project(Project(
        id="project:proj_common",
        name="Common Project",
        path="/tmp/common",
    ))

    # Insert 120 active InboxItem rows:
    # Rows 0..104: section="ai_ml", matched_project_ids=["project:proj_common"], scores 0.99 down to 0.47
    for i in range(105):
        score = round(0.99 - (i * 0.005), 4)
        db.save_inbox_item(InboxItem(
            id=f"ib_common_{i}",
            entity_type="cluster",
            entity_id=f"cl_common_{i}",
            story_cluster_id=f"cl_common_{i}",
            title=f"Common AI Item {i}",
            section="ai_ml",
            inbox_score=score,
            rank_score=score,
            project_impact_score=0.5,
            state="unseen",
            item_type="new_story",
            created_at=now,
            matched_project_ids=["project:proj_common"],
            reason_codes=["recent_discovery"],
        ))

    # Row 105 (position 106, score 0.40): ONLY match for developer_tooling and project:proj_target
    db.save_inbox_item(InboxItem(
        id="ib_target_105",
        entity_type="cluster",
        entity_id="cl_target_105",
        story_cluster_id="cl_target_105",
        title="Target Developer Tooling Item",
        section="developer_tooling",
        inbox_score=0.40,
        rank_score=0.40,
        project_impact_score=0.88,
        state="unseen",
        item_type="new_release",
        created_at=now,
        matched_project_ids=["project:proj_target"],
        reason_codes=["official_release"],
    ))

    # Rows 106..119: section="ai_ml", matched_project_ids=["project:proj_common"], scores 0.35 down to 0.285
    for i in range(106, 120):
        score = round(0.35 - ((i - 106) * 0.005), 4)
        db.save_inbox_item(InboxItem(
            id=f"ib_common_{i}",
            entity_type="cluster",
            entity_id=f"cl_common_{i}",
            story_cluster_id=f"cl_common_{i}",
            title=f"Common AI Item {i}",
            section="ai_ml",
            inbox_score=score,
            rank_score=score,
            project_impact_score=0.5,
            state="unseen",
            item_type="new_story",
            created_at=now,
            matched_project_ids=["project:proj_common"],
            reason_codes=["recent_discovery"],
        ))

    # Test Section Filter: Even though ib_target_105 is beyond top 100, filtering retrieves it
    sec_results = get_today_inbox(section="developer_tooling", limit=20, db=db)
    assert len(sec_results) == 1
    assert sec_results[0]["id"] == "ib_target_105"
    assert sec_results[0]["section"] == "developer_tooling"

    # Test Project Filter: Project proj_target retrieves ib_target_105 beyond position 100
    proj_results = get_today_inbox(project="proj_target", limit=20, db=db)
    assert len(proj_results) == 1
    assert proj_results[0]["id"] == "ib_target_105"
    assert proj_results[0]["matched_project_ids"] == ["project:proj_target"]

    # Test Limit Applied After Filtering: Limit 10 returns top 10 AI items in order
    ai_results = get_today_inbox(section="ai_ml", limit=10, db=db)
    assert len(ai_results) == 10
    scores = [r["inbox_score"] for r in ai_results]
    assert scores == sorted(scores, reverse=True)
    assert ai_results[0]["id"] == "ib_common_0"
    assert ai_results[9]["id"] == "ib_common_9"


def test_top_developments_null_score_and_genuine_zero_preservation(tmp_path):
    from app.storage.db import Database
    from app.services.intelligence import get_top_developments
    from app.models.schemas import InboxItem, StoryCluster, Event

    db_path = tmp_path / "test_top_devs_null_zero.db"
    db = Database(str(db_path))

    now = datetime.now(timezone.utc)

    # Setup Clusters
    cl1 = StoryCluster(id="cl_null", canonical_title="Null Scores Cluster", score=0.8)
    cl2 = StoryCluster(id="cl_zero", canonical_title="Zero Scores Cluster", score=0.8)
    cl3 = StoryCluster(id="cl_norm", canonical_title="Normal Scores Cluster", score=0.8)
    db.save_cluster(cl1)
    db.save_cluster(cl2)
    db.save_cluster(cl3)

    # Setup Events
    ev1 = Event(id="ev_null", title="Null Scores Event", source="github", url="https://github.com/null/null")
    ev2 = Event(id="ev_zero", title="Zero Scores Event", source="github", url="https://github.com/zero/zero")
    ev3 = Event(id="ev_norm", title="Normal Scores Event", source="github", url="https://github.com/norm/norm")
    db.save_event(ev1)
    db.save_event(ev2)
    db.save_event(ev3)
    db.add_event_to_cluster(cl1.id, ev1.id)
    db.add_event_to_cluster(cl2.id, ev2.id)
    db.add_event_to_cluster(cl3.id, ev3.id)

    # Inbox item 1: Missing scores (None)
    db.save_inbox_item(InboxItem(
        id="ib_null",
        entity_type="cluster",
        entity_id=cl1.id,
        story_cluster_id=cl1.id,
        title="Null Scores Cluster",
        section="ai_ml",
        inbox_score=0.9,
        rank_score=None,
        project_impact_score=None,
        state="unseen",
        created_at=now,
    ))

    # Inbox item 2: Genuine numeric zero scores (0.0)
    db.save_inbox_item(InboxItem(
        id="ib_zero",
        entity_type="cluster",
        entity_id=cl2.id,
        story_cluster_id=cl2.id,
        title="Zero Scores Cluster",
        section="ai_ml",
        inbox_score=0.8,
        rank_score=0.0,
        project_impact_score=0.0,
        state="unseen",
        created_at=now,
    ))

    # Inbox item 3: Genuine positive scores
    db.save_inbox_item(InboxItem(
        id="ib_norm",
        entity_type="cluster",
        entity_id=cl3.id,
        story_cluster_id=cl3.id,
        title="Normal Scores Cluster",
        section="ai_ml",
        inbox_score=0.7,
        rank_score=0.87654,
        project_impact_score=0.43219,
        state="unseen",
        created_at=now,
    ))

    results = get_top_developments(limit=10, db=db)
    assert len(results) == 3

    by_id = {r.entity_id: r for r in results}

    # 1. Null preservation
    r_null = by_id["ib_null"]
    assert r_null.score is None
    assert r_null.project_relevance is None
    dump_null = r_null.model_dump()
    assert dump_null["score"] is None
    assert dump_null["project_relevance"] is None

    # 2. Genuine numeric zero preservation
    r_zero = by_id["ib_zero"]
    assert r_zero.score == 0.0
    assert r_zero.project_relevance == 0.0
    assert isinstance(r_zero.score, float)
    assert isinstance(r_zero.project_relevance, float)
    dump_zero = r_zero.model_dump()
    assert dump_zero["score"] == 0.0
    assert dump_zero["project_relevance"] == 0.0

    # 3. Non-null rounding
    r_norm = by_id["ib_norm"]
    assert r_norm.score == 0.8765
    assert r_norm.project_relevance == 0.4322


# --- Phase 11: Project Intelligence & Engineering Context Tests ---


def test_list_projects_excludes_path_and_inactive(temp_db):
    db = temp_db
    now = datetime.now(timezone.utc)

    # Insert an active project and an inactive project
    db.save_project(Project(
        id="project:active_app",
        name="Active App",
        path="/secret/local/path/active",
        description="Active test application",
        languages=["python", "rust"],
        frameworks=["fastapi"],
        is_active=True,
        last_indexed_at=now,
    ))
    db.save_project(Project(
        id="project:inactive_app",
        name="Inactive App",
        path="/secret/local/path/inactive",
        description="Inactive test application",
        languages=["c++"],
        is_active=False,
        last_indexed_at=now,
    ))

    projects = projects_service.list_projects(db=db)
    # Only active projects are listed
    proj_ids = [p.project_id for p in projects]
    assert "project:active_app" in proj_ids
    assert "project:inactive_app" not in proj_ids

    # Path must not be in model dump or schema
    for p in projects:
        dump = p.model_dump()
        assert "path" not in dump

    p_active = next(p for p in projects if p.project_id == "project:active_app")
    assert p_active.name == "Active App"
    assert "python" in p_active.languages
    assert "fastapi" in p_active.frameworks


def test_get_project_profile_resolution_and_no_path(temp_db):
    db = temp_db
    now = datetime.now(timezone.utc)

    db.save_project(Project(
        id="project:custom_engine",
        name="Custom Engine",
        path="/sensitive/workspace/engine",
        description="High-performance engine",
        languages=["c++", "cuda"],
        frameworks=["tensorrt"],
        is_active=False,
        last_indexed_at=now,
    ))

    # Resolved by canonical id
    prof_by_id = projects_service.get_project_profile("project:custom_engine", db=db)
    assert prof_by_id is not None
    assert prof_by_id["project_id"] == "project:custom_engine"
    assert prof_by_id["name"] == "Custom Engine"
    assert prof_by_id["is_active"] is False
    assert "path" not in prof_by_id

    # Resolved by case-insensitive name
    prof_by_name = projects_service.get_project_profile("custom engine", db=db)
    assert prof_by_name is not None
    assert prof_by_name["project_id"] == "project:custom_engine"
    assert "path" not in prof_by_name


def test_get_project_intelligence_aggregated_contract_and_batch_resolution(temp_db):
    db = temp_db
    now = datetime.now(timezone.utc)

    # Create project
    proj_id = "project:rag_pipeline"
    db.save_project(Project(
        id=proj_id,
        name="RAG Pipeline",
        path="/local/rag",
        description="Local RAG pipeline",
        languages=["python"],
        frameworks=["langchain"],
        is_active=True,
        last_indexed_at=now,
    ))

    # Existing cluster
    cl_avail = StoryCluster(
        id="cl_avail_1",
        canonical_title="FAISS Vector Index Optimization",
        event_ids=["ev_1"],
        sources=["github"],
        cluster_score=0.85,
        created_at=now,
        updated_at=now,
    )
    db.save_cluster(cl_avail)

    # 1. Match with available cluster and non-null scores
    db.save_project_match(ProjectMatch(
        id="pm_1",
        project_id=proj_id,
        entity_id="cl_avail_1",
        match_type="technology_overlap",
        relevance_score=0.88765,
        impact_score=0.76543,
        recommendation="upgrade_candidate",
        reason_codes=["framework_match", "technology_overlap"],
    ))

    # 2. Match with unavailable cluster and null scores
    db.save_project_match(ProjectMatch(
        id="pm_2",
        project_id=proj_id,
        entity_id="cl_missing_cluster_99",
        match_type="general_related",
        relevance_score=None,
        impact_score=None,
        recommendation="consider",
        reason_codes=["topic_match"],
    ))

    # 3. Match with genuine 0.0 scores
    db.save_project_match(ProjectMatch(
        id="pm_3",
        project_id=proj_id,
        entity_id="cl_avail_1",
        match_type="compatible_tool",
        relevance_score=0.0,
        impact_score=0.0,
        recommendation="watch",
        reason_codes=["tool_match"],
    ))

    intel = projects_service.get_project_intelligence(proj_id, db=db)
    assert intel is not None
    assert intel.project_id == proj_id
    assert intel.intelligence_available is True

    matches = intel.top_matches
    assert len(matches) == 3

    # Match 1: story_available=True, rounded scores
    m1 = next(m for m in matches if m["cluster_id"] == "cl_avail_1" and m["match_type"] == "technology_overlap")
    assert m1["story_available"] is True
    assert m1["title"] == "FAISS Vector Index Optimization"
    assert m1["relevance_score"] == 0.8877
    assert m1["impact_score"] == 0.7654
    assert m1["recommendation"] == "upgrade_candidate"
    assert "framework_match" in m1["reason_codes"]

    # Match 2: story_available=False, None scores preserved
    m2 = next(m for m in matches if m["cluster_id"] == "cl_missing_cluster_99")
    assert m2["story_available"] is False
    assert m2["title"] == "cl_missing_cluster_99"
    assert m2["relevance_score"] is None
    assert m2["impact_score"] is None

    # Match 3: genuine 0.0 preserved
    m3 = next(m for m in matches if m["cluster_id"] == "cl_avail_1" and m["match_type"] == "compatible_tool")
    assert m3["story_available"] is True
    assert m3["relevance_score"] == 0.0
    assert m3["impact_score"] == 0.0
    assert isinstance(m3["relevance_score"], float)
    assert isinstance(m3["impact_score"], float)


def test_empty_project_intelligence_computed_false(temp_db):
    db = temp_db
    now = datetime.now(timezone.utc)

    proj_id = "project:empty_app"
    db.save_project(Project(
        id=proj_id,
        name="Empty App",
        path="/local/empty",
        description="Empty app profile",
        is_active=True,
        last_indexed_at=now,
    ))

    intel = projects_service.get_project_intelligence(proj_id, db=db)
    assert intel is not None
    assert intel.project_id == proj_id
    assert intel.intelligence_available is False
    assert len(intel.top_matches) == 0
    assert len(intel.risks) == 0
    assert len(intel.recommendations) == 0
    assert len(intel.recent_changes) == 0


def test_get_project_risks_canonical_risk_and_separation(temp_db):
    db = temp_db
    now = datetime.now(timezone.utc)

    proj_id = "project:security_test"
    db.save_project(Project(
        id=proj_id,
        name="Security Test",
        path="/local/sec",
        is_active=True,
    ))

    # Cluster 1: Vulnerability match type, no tech state -> not_assessed
    cl1 = StoryCluster(id="cl_sec_1", canonical_title="OpenSSL Vulnerability", event_ids=[], sources=[], cluster_score=0.8, created_at=now, updated_at=now)
    db.save_cluster(cl1)
    db.save_project_match(ProjectMatch(
        id="pm_sec_1",
        project_id=proj_id,
        entity_id="cl_sec_1",
        match_type="vulnerability",
        relevance_score=0.9,
        impact_score=0.8,
        reason_codes=["security_vulnerability"],
    ))

    # Cluster 2: High impact score (>= 0.70) with tech state but no claims/events -> insufficient_data, high_project_impact concern
    cl2 = StoryCluster(id="cl_sec_2", canonical_title="CUDA 13 High Impact Release", event_ids=[], sources=[], cluster_score=0.75, created_at=now, updated_at=now)
    db.save_cluster(cl2)
    db.save_technology_state(TechnologyState(
        cluster_id="cl_sec_2",
        current_status="evolving",
        risk_score=0.65,
        updated_at=now,
    ))
    db.save_project_match(ProjectMatch(
        id="pm_sec_2",
        project_id=proj_id,
        entity_id="cl_sec_2",
        match_type="technology_overlap",
        relevance_score=0.8,
        impact_score=0.75,
        reason_codes=["technology_overlap"],
    ))

    # Cluster 3: Technology state with supporting event -> assessed, assessed_risk concern
    ev3 = Event(id="ev_sec_3", source="nvd", source_type="security_advisory", title="Crit Vulnerability Event", url="http://nvd.nist.gov/3", text_content="Advisory details", created_at=now)
    db.save_event(ev3)
    cl3 = StoryCluster(id="cl_sec_3", canonical_title="Critical Kernel Vulnerability", event_ids=["ev_sec_3"], sources=["nvd"], cluster_score=0.9, created_at=now, updated_at=now)
    db.save_cluster(cl3)
    db.add_event_to_cluster("cl_sec_3", "ev_sec_3")
    db.save_technology_state(TechnologyState(
        cluster_id="cl_sec_3",
        current_status="declining",
        risk_score=0.75,
        updated_at=now,
    ))
    db.save_project_match(ProjectMatch(
        id="pm_sec_3",
        project_id=proj_id,
        entity_id="cl_sec_3",
        match_type="general_related",
        relevance_score=0.7,
        impact_score=0.4,
        reason_codes=["topic_match"],
    ))

    risks = projects_service.get_project_risks(proj_id, db=db)
    assert len(risks) == 3

    by_cid = {r["cluster_id"]: r for r in risks}

    # Cluster 1: Concern type vulnerability, canonical risk not_assessed
    r1 = by_cid["cl_sec_1"]
    assert r1["concern_type"] == "vulnerability"
    assert r1["risk_status"] == "not_assessed"
    assert r1["risk_level"] is None
    assert r1["risk_score"] is None

    # Cluster 2: High project impact (>= 0.70) does NOT become assessed risk; stays insufficient_data
    r2 = by_cid["cl_sec_2"]
    assert r2["concern_type"] == "high_project_impact"
    assert r2["risk_status"] == "insufficient_data"
    assert r2["risk_level"] is None
    assert r2["risk_score"] == 0.65  # Raw score preserved under insufficient_data

    # Cluster 3: Assessed canonical risk
    r3 = by_cid["cl_sec_3"]
    assert r3["concern_type"] == "assessed_risk"
    assert r3["risk_status"] == "assessed"
    assert r3["risk_level"] == "critical"
    assert r3["risk_score"] == 0.75
