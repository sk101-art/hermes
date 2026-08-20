import os
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest

from app.evidence.recheck import calculate_recheck_priority, populate_recheck_queue, process_recheck_queue
from app.evidence.reevaluate import (
    reevaluate_claim,
    reevaluate_cluster_maturity,
    sequence_cluster_releases,
    update_technology_state,
)
from app.evidence.risk import calculate_technology_risk
from app.evidence.staleness import calculate_claim_staleness, classify_staleness_tier
from app.evidence.verification import compute_verification, derive_status_with_policy
from app.models.schemas import (
    Claim,
    ClaimRevision,
    Event,
    Evidence,
    StoryCluster,
    TechnologyAssessment,
    TechnologyAssessmentRevision,
    TechnologyState,
)
from app.storage.db import Database


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_longitudinal.db")
    db = Database(db_path=db_file)
    yield db
    db.close()


def test_claim_revisions_table_and_model(test_db):
    now = datetime.now(timezone.utc)
    claim = Claim(
        id="claim:test1",
        cluster_id="cluster:test",
        claim_type="release",
        assertion_level="artifact_fact",
        subject="test/repo",
        predicate="released",
        object="v1.0.0",
        claim_text="Released v1.0.0",
        status="supported",
        verification_score=0.65,
        created_at=now,
        updated_at=now,
    )
    test_db.save_claim(claim)

    rev = ClaimRevision(
        id="rev:test1",
        claim_id=claim.id,
        previous_status="supported",
        new_status="strongly_supported",
        previous_verification_score=0.65,
        new_verification_score=0.85,
        reason="Corroborated by independent reproduction",
        created_at=now,
    )
    test_db.insert_claim_revision(rev)

    revs = test_db.get_claim_revisions(claim.id)
    assert len(revs) == 1
    assert revs[0].previous_status == "supported"
    assert revs[0].new_status == "strongly_supported"
    assert revs[0].new_verification_score == 0.85


def test_meaningful_change_and_idempotence(test_db):
    now = datetime.now(timezone.utc)
    claim = Claim(
        id="claim:idem1",
        cluster_id="cluster:test",
        claim_type="release",
        assertion_level="artifact_fact",
        subject="test/repo",
        predicate="released",
        object="v1.0.0",
        claim_text="Released v1.0.0",
        status="weakly_supported",
        verification_score=0.40,
        created_at=now,
        updated_at=now,
    )
    test_db.save_claim(claim)

    ev1 = Evidence(
        id="ev:idem1",
        claim_id=claim.id,
        event_id="ev:e1",
        source="github",
        evidence_type="official_release",
        evidence_class="primary",
        stance="supports",
        excerpt="Release v1.0.0",
        quality_score=0.95,
        independence_score=0.50,
        reproducibility_score=0.85,
        created_at=now,
    )
    test_db.save_evidence(ev1)

    # 1. First re-evaluation: status upgrades weakly_supported -> strongly_supported
    updated_claim, rev1, ch1 = reevaluate_claim(claim, [ev1], test_db)
    assert rev1 is not None
    assert ch1 is not None
    assert updated_claim.status == "strongly_supported"

    # 2. Second re-evaluation with same evidence: IDEMPOTENT (no new revision)
    updated_again, rev2, ch2 = reevaluate_claim(updated_claim, [ev1], test_db)
    assert rev2 is None
    assert ch2 is None


def test_contradiction_weighting_and_mixed_status(test_db):
    now = datetime.now(timezone.utc)
    claim = Claim(
        id="claim:contra1",
        cluster_id="cluster:test",
        claim_type="performance",
        assertion_level="performance_claim",
        subject="test/repo",
        predicate="reports_performance",
        object="10x faster",
        claim_text="Reports 10x faster",
        status="supported",
        verification_score=0.60,
        created_at=now,
        updated_at=now,
    )
    test_db.save_claim(claim)

    # Supporting evidence
    ev_sup = Evidence(
        id="ev:sup1",
        claim_id=claim.id,
        event_id="ev:e1",
        source="github",
        evidence_type="benchmark_code",
        evidence_class="primary",
        stance="supports",
        quality_score=0.80,
        independence_score=0.40,
        reproducibility_score=0.60,
        created_at=now,
    )
    # Contradicting benchmark replication
    ev_contra = Evidence(
        id="ev:con1",
        claim_id=claim.id,
        event_id="ev:e2",
        source="hacker_news",
        evidence_type="independent_reproduction",
        evidence_class="external_evaluation",
        stance="contradicts",
        quality_score=0.90,
        independence_score=0.95,
        reproducibility_score=0.85,
        created_at=now,
    )

    score, status = compute_verification(claim, [ev_sup, ev_contra])
    assert status == "mixed"

    updated_claim, rev, ch = reevaluate_claim(claim, [ev_sup, ev_contra], test_db)
    assert updated_claim.status == "mixed"
    assert rev is not None
    assert ch.change_type == "contradiction_detected"


def test_independent_reproduction_and_assertion_policies():
    now = datetime.now(timezone.utc)
    # Research claim with preprint only -> capped at supported
    claim_paper = Claim(
        id="claim:paper1",
        cluster_id="cluster:test",
        claim_type="research_result",
        assertion_level="research_claim",
        subject="Paper Title",
        predicate="proposes",
        object="Method X",
        claim_text="Paper proposes Method X",
        status="unverified",
        verification_score=0.0,
        created_at=now,
        updated_at=now,
    )
    ev_arxiv = Evidence(
        id="ev:arx1",
        claim_id=claim_paper.id,
        event_id="ev:p1",
        source="arxiv",
        evidence_type="preprint_paper",
        evidence_class="primary",
        stance="supports",
        quality_score=0.85,
        independence_score=0.80,
        reproducibility_score=0.70,
        created_at=now,
    )

    score1, status1 = compute_verification(claim_paper, [ev_arxiv])
    assert status1 == "supported"  # Capped at supported for single preprint

    # Add independent reproduction from another source
    ev_repro = Evidence(
        id="ev:rep1",
        claim_id=claim_paper.id,
        event_id="ev:p2",
        source="github",
        evidence_type="independent_reproduction",
        evidence_class="external_evaluation",
        stance="supports",
        quality_score=0.90,
        independence_score=0.90,
        reproducibility_score=0.85,
        created_at=now,
    )

    score2, status2 = compute_verification(claim_paper, [ev_arxiv, ev_repro])
    assert status2 == "strongly_supported"


def test_claim_supersession_and_release_lineage(test_db):
    dt1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    dt2 = datetime(2025, 2, 1, tzinfo=timezone.utc)

    e1 = Event(
        id="github:release:test/repo:v1.0",
        source="github",
        event_type="release",
        source_type="release",
        title="v1.0",
        published_at=dt1,
        discovered_at=dt1,
        metadata={"tag_name": "v1.0"},
    )
    e2 = Event(
        id="github:release:test/repo:v2.0",
        source="github",
        event_type="release",
        source_type="release",
        title="v2.0",
        published_at=dt2,
        discovered_at=dt2,
        metadata={"tag_name": "v2.0"},
    )

    rels = sequence_cluster_releases("cluster:test", [e1, e2], test_db)
    assert len(rels) == 1
    assert rels[0].relationship_type == "supersedes"
    assert rels[0].source_event_id == e2.id
    assert rels[0].target_event_id == e1.id


def test_technology_maturity_regression(test_db):
    cluster = StoryCluster(
        id="cluster:regress",
        canonical_title="Regressing Technology",
        sources=["github"],
        event_ids=["e1"],
    )
    test_db.save_cluster(cluster)

    # Initial high assessment
    initial_assess = TechnologyAssessment(
        cluster_id=cluster.id,
        maturity_stage="production_candidate",
        assessment_score=0.80,
    )
    test_db.save_technology_assessment(initial_assess)

    # Cluster now only has 1 event with no releases/reproductions
    ev = Event(
        id="e1",
        source="github",
        event_type="repository",
        source_type="repository",
        title="Repo",
    )
    new_assess, rev, change = reevaluate_cluster_maturity(cluster, [ev], test_db)

    assert rev is not None
    assert rev.previous_stage == "production_candidate"
    assert rev.new_stage in ("concept", "experimental", "prototype")
    assert change.change_type == "maturity_decreased"


def test_staleness_calculation_per_type():
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=120)

    # 1. Release claim older than half-life (45 days)
    c_release = Claim(
        id="c1",
        cluster_id="cl1",
        claim_type="release",
        assertion_level="artifact_fact",
        subject="s",
        predicate="p",
        object="o",
        claim_text="t",
        created_at=old_time,
        last_verified_at=old_time,
    )
    st_rel = calculate_claim_staleness(c_release, now)
    assert st_rel > 0.70
    assert classify_staleness_tier(st_rel) == "stale"

    # 2. Scholarly DOI claim (permanent)
    c_doi = Claim(
        id="c2",
        cluster_id="cl1",
        claim_type="scholarly_identity",
        assertion_level="artifact_fact",
        subject="s",
        predicate="p",
        object="10.1234/test",
        claim_text="t",
        metadata={"doi": "10.1234/test"},
        created_at=old_time,
        last_verified_at=old_time,
    )
    st_doi = calculate_claim_staleness(c_doi, now)
    assert st_doi == 0.0
    assert classify_staleness_tier(st_doi) == "fresh"


def test_recheck_queue_prioritization(test_db):
    now = datetime.now(timezone.utc)
    c_contra = Claim(
        id="c:contra",
        cluster_id="cl1",
        claim_type="performance",
        assertion_level="performance_claim",
        subject="s",
        predicate="p",
        object="o",
        claim_text="t",
        status="contradicted",
        verification_score=0.20,
        created_at=now,
    )
    c_doi = Claim(
        id="c:doi",
        cluster_id="cl1",
        claim_type="scholarly_identity",
        assertion_level="artifact_fact",
        subject="s",
        predicate="p",
        object="o",
        claim_text="t",
        status="supported",
        verification_score=0.75,
        metadata={"doi": "10.1000/182"},
        created_at=now,
    )

    prio_contra, _ = calculate_recheck_priority(c_contra, now=now)
    prio_doi, _ = calculate_recheck_priority(c_doi, now=now)

    assert prio_contra >= 0.90
    assert prio_doi <= 0.20
    assert prio_contra > prio_doi


def test_recheck_dry_run(test_db):
    now = datetime.now(timezone.utc)
    claim = Claim(
        id="claim:dry",
        cluster_id="cluster:test",
        claim_type="release",
        assertion_level="artifact_fact",
        subject="test/repo",
        predicate="released",
        object="v1.0.0",
        claim_text="Released v1.0.0",
        status="weakly_supported",
        verification_score=0.30,
        created_at=now,
        updated_at=now,
    )
    test_db.save_claim(claim)

    ev = Evidence(
        id="ev:dry1",
        claim_id=claim.id,
        event_id="ev:e1",
        source="github",
        evidence_type="official_release",
        evidence_class="primary",
        stance="supports",
        quality_score=0.95,
        independence_score=0.50,
        reproducibility_score=0.85,
        created_at=now,
    )
    test_db.save_evidence(ev)

    # Populate queue and run dry-run
    populate_recheck_queue(test_db, dry_run=False)
    results = process_recheck_queue(test_db, dry_run=True)

    assert len(results) == 1
    # Check that database claim was NOT mutated
    db_claim = test_db.get_claim("claim:dry")
    assert db_claim.status == "weakly_supported"
    assert db_claim.verification_score == 0.30


def test_status_boundary_hysteresis():
    now = datetime.now(timezone.utc)
    claim = Claim(
        id="c:hyst",
        cluster_id="cl1",
        claim_type="architecture",
        assertion_level="artifact_fact",
        subject="s",
        predicate="p",
        object="o",
        claim_text="t",
        status="supported",
        verification_score=0.69,
        created_at=now,
    )

    ev = Evidence(
        id="ev:h1",
        claim_id=claim.id,
        event_id="e1",
        source="github",
        evidence_type="repository_metadata",
        evidence_class="primary",
        stance="supports",
        quality_score=0.71,
        independence_score=0.50,
        reproducibility_score=0.80,
        created_at=now,
    )

    # A score hovering at 0.695 (just below 0.70) with previous_status="supported"
    # remains "supported" due to hysteresis preventing oscillation
    status = derive_status_with_policy(
        claim=claim,
        final_score=0.695,
        supporting=[ev],
        contradicting=[],
        contra_weight=0.0,
        previous_status="supported",
    )
    assert status == "supported"
