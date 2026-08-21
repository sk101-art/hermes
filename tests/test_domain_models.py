import json
import os
import sqlite3
import pytest
from app.models.schemas import (
    MaturityStage,
    ClaimStatus,
    EvidenceStance,
    EvidenceClass,
    AssertionLevel,
    RiskLevel,
    RiskStatus,
    normalize_maturity_stage,
    normalize_claim_status,
    normalize_evidence_stance,
    normalize_evidence_class,
    normalize_assertion_level,
    Claim,
    Evidence,
    Event,
    TechnologyAssessment,
    TechnologyState,
)
from app.evidence.verification import (
    is_independent_evidence,
    compute_verification,
    derive_status_with_policy,
)


def test_canonical_maturity_stages_enumeration():
    """Verify all 7 canonical maturity stages are present and exact."""
    expected_stages = {
        "concept",
        "research",
        "prototype",
        "experimental",
        "early_adoption",
        "production_candidate",
        "established",
    }
    actual_stages = {s.value for s in MaturityStage}
    assert actual_stages == expected_stages
    assert len(MaturityStage) == 7
    # String enum equality check
    assert MaturityStage.PRODUCTION_CANDIDATE == "production_candidate"
    assert MaturityStage.ESTABLISHED == "established"


def test_canonical_claim_statuses_enumeration():
    """Verify all 8 canonical claim statuses are present and exact."""
    expected = {
        "strongly_supported",
        "supported",
        "weakly_supported",
        "mixed",
        "contradicted",
        "unverified",
        "superseded",
        "retracted",
    }
    actual = {s.value for s in ClaimStatus}
    assert actual == expected
    assert len(ClaimStatus) == 8
    # Test all individual variants
    assert ClaimStatus.STRONGLY_SUPPORTED == "strongly_supported"
    assert ClaimStatus.MIXED == "mixed"
    assert ClaimStatus.CONTRADICTED == "contradicted"
    assert ClaimStatus.UNVERIFIED == "unverified"
    assert ClaimStatus.SUPERSEDED == "superseded"
    assert ClaimStatus.RETRACTED == "retracted"


def test_canonical_evidence_stances_enumeration():
    """Verify all 3 canonical evidence stances are present."""
    expected = {"supports", "contradicts", "context"}
    actual = {s.value for s in EvidenceStance}
    assert actual == expected
    assert len(EvidenceStance) == 3
    assert EvidenceStance.CONTEXT == "context"
    assert EvidenceStance.CONTRADICTS == "contradicts"


def test_canonical_evidence_classes_enumeration():
    """Verify all 4 canonical evidence classes are present."""
    expected = {"primary", "secondary", "community", "metadata"}
    actual = {c.value for c in EvidenceClass}
    assert actual == expected
    assert len(EvidenceClass) == 4


def test_canonical_assertion_levels_enumeration():
    """Verify all 5 canonical assertion levels are present."""
    expected = {
        "artifact_fact",
        "performance_claim",
        "research_claim",
        "community_observation",
        "self_reported_claim",
    }
    actual = {a.value for a in AssertionLevel}
    assert actual == expected
    assert len(AssertionLevel) == 5


def test_canonical_risk_levels_and_statuses():
    """Verify risk levels and provenance statuses."""
    expected_levels = {"critical", "high", "medium", "low"}
    assert {r.value for r in RiskLevel} == expected_levels

    expected_statuses = {"not_assessed", "insufficient_data", "assessed"}
    assert {s.value for s in RiskStatus} == expected_statuses


def test_maturity_stage_normalizer_strictness():
    # Canonical enum & string inputs
    assert normalize_maturity_stage(MaturityStage.EARLY_ADOPTION) == "early_adoption"
    assert normalize_maturity_stage("prototype") == "prototype"
    assert normalize_maturity_stage("production_candidate") == "production_candidate"
    assert normalize_maturity_stage("  EXPERIMENTAL  ") == "experimental"

    # Supported compatibility aliases
    assert normalize_maturity_stage("maturing") == "early_adoption"
    assert normalize_maturity_stage("production_ready") == "established"
    assert normalize_maturity_stage("stable") == "established"

    # Empty, None, and unmapped invalid inputs -> None (never fabricated defaults)
    assert normalize_maturity_stage(None) is None
    assert normalize_maturity_stage("") is None
    assert normalize_maturity_stage("   ") is None
    assert normalize_maturity_stage("unrecognized_xyz") is None
    assert normalize_maturity_stage("unknown") is None


def test_claim_status_normalizer_strictness():
    assert normalize_claim_status(ClaimStatus.STRONGLY_SUPPORTED) == "strongly_supported"
    assert normalize_claim_status("supported") == "supported"
    assert normalize_claim_status("  WEAKLY_SUPPORTED  ") == "weakly_supported"
    assert normalize_claim_status("mixed") == "mixed"
    assert normalize_claim_status("contradicted") == "contradicted"
    assert normalize_claim_status("unverified") == "unverified"
    assert normalize_claim_status("superseded") == "superseded"
    assert normalize_claim_status("retracted") == "retracted"

    assert normalize_claim_status(None) is None
    assert normalize_claim_status("") is None
    assert normalize_claim_status("bogus_status") is None


def test_evidence_stance_normalizer_strictness():
    assert normalize_evidence_stance(EvidenceStance.SUPPORTS) == "supports"
    assert normalize_evidence_stance("contradicts") == "contradicts"
    assert normalize_evidence_stance("CONTEXT") == "context"
    # Supported compatibility aliases
    assert normalize_evidence_stance("refutes") == "contradicts"
    assert normalize_evidence_stance("opposes") == "contradicts"
    assert normalize_evidence_stance("neutral") == "context"
    assert normalize_evidence_stance("background") == "context"

    assert normalize_evidence_stance(None) is None
    assert normalize_evidence_stance("") is None
    assert normalize_evidence_stance("unrecognized_stance") is None


def test_evidence_class_normalizer_strictness():
    assert normalize_evidence_class(EvidenceClass.PRIMARY) == "primary"
    assert normalize_evidence_class("secondary") == "secondary"
    assert normalize_evidence_class("community") == "community"
    assert normalize_evidence_class("metadata") == "metadata"
    # Supported compatibility aliases
    assert normalize_evidence_class("author") == "primary"
    assert normalize_evidence_class("discussion") == "community"
    assert normalize_evidence_class("registry") == "metadata"
    assert normalize_evidence_class("benchmark") == "secondary"
    assert normalize_evidence_class("independent") == "primary"

    assert normalize_evidence_class(None) is None
    assert normalize_evidence_class("") is None
    assert normalize_evidence_class("unrecognized_class") is None


def test_assertion_level_normalizer_strictness():
    assert normalize_assertion_level(AssertionLevel.ARTIFACT_FACT) == "artifact_fact"
    assert normalize_assertion_level("performance_claim") == "performance_claim"
    assert normalize_assertion_level("research_claim") == "research_claim"
    assert normalize_assertion_level("community_observation") == "community_observation"
    assert normalize_assertion_level("self_reported_claim") == "self_reported_claim"
    # Supported compatibility aliases
    assert normalize_assertion_level("artifact") == "artifact_fact"
    assert normalize_assertion_level("performance") == "performance_claim"
    assert normalize_assertion_level("research") == "research_claim"
    assert normalize_assertion_level("community") == "community_observation"
    assert normalize_assertion_level("self_reported") == "self_reported_claim"

    assert normalize_assertion_level(None) is None
    assert normalize_assertion_level("") is None
    assert normalize_assertion_level("bogus_level") is None


def test_is_independent_evidence_helper():
    # 1. Independent reproduction
    ev_repro = Evidence(
        id="ev_1",
        claim_id="c_1",
        event_id="e_1",
        source="github",
        evidence_type="independent_reproduction",
        independence_score=0.50,
    )
    assert is_independent_evidence(ev_repro) is True

    # 2. High independence score
    ev_high_ind = Evidence(
        id="ev_2",
        claim_id="c_1",
        event_id="e_2",
        source="arxiv",
        evidence_type="preprint",
        independence_score=0.90,
    )
    assert is_independent_evidence(ev_high_ind) is True

    # 3. Standard self-reported or low independence evidence
    ev_low_ind = Evidence(
        id="ev_3",
        claim_id="c_1",
        event_id="e_3",
        source="github",
        evidence_type="source_code",
        independence_score=0.50,
    )
    assert is_independent_evidence(ev_low_ind) is False

    # 4. Independence evaluated independently of claim.self_reported
    claim_self_reported = Claim(
        id="c_1",
        cluster_id="cl_1",
        subject="ProjectX",
        predicate="claims",
        object="speedup",
        claim_text="ProjectX delivers 10x speedup.",
        self_reported=True,
    )
    assert claim_self_reported.self_reported is True
    assert is_independent_evidence(ev_high_ind) is True


def test_context_evidence_semantics_in_verification():
    """Verify that contextual evidence is purely informational and does not inflate support score."""
    claim = Claim(
        id="c_1",
        cluster_id="cl_1",
        subject="ModelY",
        predicate="supports",
        object="feature",
        claim_text="ModelY supports feature Z.",
        assertion_level="artifact_fact",
    )

    ev_context = Evidence(
        id="ev_ctx",
        claim_id="c_1",
        event_id="e_ctx",
        source="hackernews",
        evidence_type="community_discussion",
        stance="context",
        quality_score=0.80,
        independence_score=0.80,
    )

    # Context only -> unverified with baseline score
    score_ctx_only, status_ctx_only = compute_verification(claim, [ev_context])
    assert score_ctx_only == 0.20
    assert status_ctx_only == "unverified"

    # Supporting evidence baseline
    ev_sup = Evidence(
        id="ev_sup",
        claim_id="c_1",
        event_id="e_sup",
        source="github",
        evidence_type="source_code",
        stance="supports",
        quality_score=0.80,
        independence_score=0.60,
        reproducibility_score=0.70,
    )
    score_sup_only, status_sup_only = compute_verification(claim, [ev_sup])
    assert score_sup_only >= 0.50

    # Adding context evidence to supporting evidence does NOT alter supporting score components
    score_combined, _ = compute_verification(claim, [ev_sup, ev_context])
    assert score_combined == score_sup_only


def test_enum_serialization_and_pydantic_compatibility():
    """Verify that models with canonical enums serialize cleanly to JSON and dicts."""
    assessment = TechnologyAssessment(
        cluster_id="cl_100",
        maturity_stage=MaturityStage.EARLY_ADOPTION,
        assessment_score=0.75,
    )
    dumped = assessment.model_dump()
    assert dumped["maturity_stage"] == "early_adoption"
    assert isinstance(dumped["maturity_stage"], str)

    json_str = assessment.model_dump_json()
    parsed_json = json.loads(json_str)
    assert parsed_json["maturity_stage"] == "early_adoption"

    # Claim serialization
    claim = Claim(
        id="c_200",
        cluster_id="cl_100",
        subject="LibA",
        predicate="is",
        object="fast",
        claim_text="LibA is fast.",
        assertion_level=AssertionLevel.PERFORMANCE_CLAIM,
        status=ClaimStatus.STRONGLY_SUPPORTED,
    )
    claim_dict = claim.model_dump()
    assert claim_dict["assertion_level"] == "performance_claim"
    assert claim_dict["status"] == "strongly_supported"

    # Evidence serialization
    evidence = Evidence(
        id="e_300",
        claim_id="c_200",
        event_id="ev_1",
        source="github",
        evidence_class=EvidenceClass.PRIMARY,
        stance=EvidenceStance.SUPPORTS,
    )
    ev_dict = evidence.model_dump()
    assert ev_dict["evidence_class"] == "primary"
    assert ev_dict["stance"] == "supports"


def test_real_database_persisted_values_conform_to_canonical_ontology():
    """Verify 100% of live and historical database values map cleanly to canonical domain enums."""
    db_path = "data/tech_intel.db"
    if not os.path.exists(db_path):
        pytest.skip("Local SQLite database data/tech_intel.db not present in test environment.")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 1. technology_assessments maturity_stage
    c.execute("SELECT DISTINCT maturity_stage FROM technology_assessments WHERE maturity_stage IS NOT NULL")
    for row in c.fetchall():
        val = row[0]
        normalized = normalize_maturity_stage(val)
        assert normalized is not None, f"technology_assessments has unmapped maturity_stage: {val}"
        assert normalized in {stage.value for stage in MaturityStage}

    # 2. technology_assessment_revisions
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='technology_assessment_revisions'")
    if c.fetchone():
        c.execute("SELECT DISTINCT previous_stage FROM technology_assessment_revisions WHERE previous_stage IS NOT NULL")
        for row in c.fetchall():
            val = row[0]
            assert normalize_maturity_stage(val) is not None, f"Unmapped historical previous_stage: {val}"
        c.execute("SELECT DISTINCT new_stage FROM technology_assessment_revisions WHERE new_stage IS NOT NULL")
        for row in c.fetchall():
            val = row[0]
            assert normalize_maturity_stage(val) is not None, f"Unmapped historical new_stage: {val}"

    # 3. saved_items maturity_snapshot
    c.execute("SELECT DISTINCT maturity_snapshot FROM saved_items WHERE maturity_snapshot IS NOT NULL")
    for row in c.fetchall():
        val = row[0]
        assert normalize_maturity_stage(val) is not None, f"saved_items has unmapped maturity_snapshot: {val}"

    # 4. evidence stances
    c.execute("SELECT DISTINCT stance FROM evidence WHERE stance IS NOT NULL")
    for row in c.fetchall():
        val = row[0]
        normalized = normalize_evidence_stance(val)
        assert normalized is not None, f"evidence has unmapped stance: {val}"
        assert normalized in {stance.value for stance in EvidenceStance}

    # 5. evidence classes
    c.execute("SELECT DISTINCT evidence_class FROM evidence WHERE evidence_class IS NOT NULL")
    for row in c.fetchall():
        val = row[0]
        normalized = normalize_evidence_class(val)
        assert normalized is not None, f"evidence has unmapped evidence_class: {val}"
        assert normalized in {cls.value for cls in EvidenceClass}

    # 6. claims statuses
    c.execute("SELECT DISTINCT status FROM claims WHERE status IS NOT NULL")
    for row in c.fetchall():
        val = row[0]
        normalized = normalize_claim_status(val)
        assert normalized is not None, f"claims has unmapped status: {val}"
        assert normalized in {status.value for status in ClaimStatus}

    # 7. claims assertion levels
    c.execute("SELECT DISTINCT assertion_level FROM claims WHERE assertion_level IS NOT NULL")
    for row in c.fetchall():
        val = row[0]
        normalized = normalize_assertion_level(val)
        assert normalized is not None, f"claims has unmapped assertion_level: {val}"
        assert normalized in {lvl.value for lvl in AssertionLevel}

    # 8. claim_revisions
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='claim_revisions'")
    if c.fetchone():
        c.execute("SELECT DISTINCT previous_status FROM claim_revisions WHERE previous_status IS NOT NULL")
        for row in c.fetchall():
            val = row[0]
            assert normalize_claim_status(val) is not None, f"claim_revisions has unmapped previous_status: {val}"
        c.execute("SELECT DISTINCT new_status FROM claim_revisions WHERE new_status IS NOT NULL")
        for row in c.fetchall():
            val = row[0]
            assert normalize_claim_status(val) is not None, f"claim_revisions has unmapped new_status: {val}"

    conn.close()
