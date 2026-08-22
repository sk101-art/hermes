import json
import os
import sqlite3
from datetime import datetime, timezone
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
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
    InboxItem,
    ProjectMatch,
    IntelligenceChange,
    ClaimRevision,
    TechnologyAssessmentRevision,
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
    # Canonical enum & string inputs (all 7 canonical stages)
    assert normalize_maturity_stage(MaturityStage.CONCEPT) == "concept"
    assert normalize_maturity_stage(MaturityStage.RESEARCH) == "research"
    assert normalize_maturity_stage(MaturityStage.PROTOTYPE) == "prototype"
    assert normalize_maturity_stage(MaturityStage.EXPERIMENTAL) == "experimental"
    assert normalize_maturity_stage(MaturityStage.EARLY_ADOPTION) == "early_adoption"
    assert normalize_maturity_stage(MaturityStage.PRODUCTION_CANDIDATE) == "production_candidate"
    assert normalize_maturity_stage(MaturityStage.ESTABLISHED) == "established"

    assert normalize_maturity_stage("concept") == "concept"
    assert normalize_maturity_stage("research") == "research"
    assert normalize_maturity_stage("prototype") == "prototype"
    assert normalize_maturity_stage("experimental") == "experimental"
    assert normalize_maturity_stage("early_adoption") == "early_adoption"
    assert normalize_maturity_stage("production_candidate") == "production_candidate"
    assert normalize_maturity_stage("established") == "established"
    assert normalize_maturity_stage("  EXPERIMENTAL  ") == "experimental"

    # Negative tests: Non-canonical legacy values MUST NOT be normalized or aliased
    assert normalize_maturity_stage("maturing") is None
    assert normalize_maturity_stage("production_ready") is None
    assert normalize_maturity_stage("stable") is None
    assert normalize_maturity_stage("growth") is None
    assert normalize_maturity_stage("growth (0.72)") is None
    assert normalize_maturity_stage("experimental (0.90)") is None
    assert normalize_maturity_stage("mature") is None
    assert normalize_maturity_stage("proposal") is None

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


# ---------------------------------------------------------------------------
# Phase 14 Semantic Grounding, Strict Maturity & Taxonomy Invariant Tests
# ---------------------------------------------------------------------------

def test_phase14_canonical_maturity_stages_complete_matrix():
    """All 7 canonical maturity stages must normalize to themselves."""
    canonical_stages = [
        ("concept", MaturityStage.CONCEPT),
        ("research", MaturityStage.RESEARCH),
        ("prototype", MaturityStage.PROTOTYPE),
        ("experimental", MaturityStage.EXPERIMENTAL),
        ("early_adoption", MaturityStage.EARLY_ADOPTION),
        ("production_candidate", MaturityStage.PRODUCTION_CANDIDATE),
        ("established", MaturityStage.ESTABLISHED),
    ]
    for raw_str, enum_val in canonical_stages:
        assert normalize_maturity_stage(raw_str) == raw_str
        assert normalize_maturity_stage(enum_val) == raw_str
        assert normalize_maturity_stage(f"  {raw_str.upper()}  ") == raw_str


def test_phase14_rejected_maturity_legacy_aliases_degrade_neutrally():
    """Rejected legacy aliases and non-canonical strings MUST NOT be normalized or aliased."""
    rejected_values = [
        "maturing",
        "production_ready",
        "stable",
        "growth",
        "growth (0.72)",
        "experimental (0.90)",
        "mature",
        "proposal",
        "beta",
        "alpha",
        "deprecated",
        "legacy",
        "1.0",
        "0.85",
    ]
    for val in rejected_values:
        assert normalize_maturity_stage(val) is None, f"Expected '{val}' to normalize to None"


def test_phase14_canonical_claim_statuses_complete_matrix():
    """All 8 canonical claim statuses must normalize cleanly."""
    canonical_statuses = [
        ("strongly_supported", ClaimStatus.STRONGLY_SUPPORTED),
        ("supported", ClaimStatus.SUPPORTED),
        ("weakly_supported", ClaimStatus.WEAKLY_SUPPORTED),
        ("mixed", ClaimStatus.MIXED),
        ("contradicted", ClaimStatus.CONTRADICTED),
        ("unverified", ClaimStatus.UNVERIFIED),
        ("superseded", ClaimStatus.SUPERSEDED),
        ("retracted", ClaimStatus.RETRACTED),
    ]
    for raw_str, enum_val in canonical_statuses:
        assert normalize_claim_status(raw_str) == raw_str
        assert normalize_claim_status(enum_val) == raw_str
        assert normalize_claim_status(f"  {raw_str.upper()}  ") == raw_str


def test_phase14_null_and_unsupported_claim_statuses_never_fabricated():
    """Null input returns None; unsupported aliases (like 'verified' or 'not_assessed') return None."""
    assert normalize_claim_status(None) is None
    assert normalize_claim_status("") is None
    assert normalize_claim_status("   ") is None
    # 'not_assessed' belongs to RiskStatus, not ClaimStatus
    assert normalize_claim_status("not_assessed") is None
    # 'verified' is NOT an officially supported ClaimStatus alias
    assert normalize_claim_status("verified") is None
    assert normalize_claim_status("unsupported_alias") is None


def test_phase14_unverified_remains_distinct_from_missing_data():
    """'unverified' is an explicit canonical evaluated state, distinct from None/null."""
    assert normalize_claim_status("unverified") == "unverified"
    assert normalize_claim_status(None) is None
    assert normalize_claim_status("unverified") != normalize_claim_status(None)


def test_phase14_score_domain_independence():
    """Different score fields across models maintain independent ranges, nullability, and semantics."""
    now = datetime.now(timezone.utc)

    # 1. Event scores
    ev = Event(
        id="github:test/repo",
        title="Test Event",
        relevance_score=0.75,
        trust_score=0.80,
        novelty_score=0.60,
        final_score=0.72,
    )
    assert ev.relevance_score == 0.75
    assert ev.final_score == 0.72

    # 2. Cluster scores
    cl = StoryCluster(
        id="cluster:1",
        canonical_title="Test Cluster",
        cluster_score=1.45,
        source_diversity_score=0.66,
    )
    assert cl.cluster_score == 1.45
    assert cl.source_diversity_score == 0.66

    # 3. Claim verification score
    claim = Claim(
        id="claim:1",
        cluster_id="cluster:1",
        subject="Subject",
        predicate="supports",
        object="Object",
        claim_text="Test claim text",
        status="supported",
        verification_score=0.88,
    )
    assert claim.verification_score == 0.88

    # 4. ProjectMatch scores (nullable)
    pm = ProjectMatch(
        id="pm:1",
        project_id="proj:1",
        entity_id="cluster:1",
        relevance_score=0.92,
        impact_score=0.85,
    )
    assert pm.relevance_score == 0.92
    assert pm.impact_score == 0.85

    # 5. InboxItem scores (nullable)
    inbox = InboxItem(
        id="inbox:1",
        entity_id="cluster:1",
        story_cluster_id="cluster:1",
        title="Inbox Title",
        inbox_score=0.79,
        rank_score=0.91,
        project_impact_score=None,
    )
    assert inbox.inbox_score == 0.79
    assert inbox.rank_score == 0.91
    assert inbox.project_impact_score is None

    # 6. IntelligenceChange importance
    chg = IntelligenceChange(
        id="chg:1",
        entity_id="claim:1",
        change_type="status_change",
        importance=0.65,
        reason="Updated evidence",
    )
    assert chg.importance == 0.65

    # 7. TechnologyState risk score (nullable)
    tstate = TechnologyState(
        cluster_id="cluster:1",
        risk_score=None,
    )
    assert tstate.risk_score is None


def test_phase14_genuine_zero_preserved_and_not_dropped():
    """A genuine zero score (0.0) is preserved and never falsified to None."""
    ev = Event(id="arxiv:1", title="Paper", relevance_score=0.0, final_score=0.0)
    assert ev.relevance_score == 0.0
    assert ev.final_score == 0.0

    claim = Claim(
        id="claim:2",
        cluster_id="c:1",
        subject="S",
        predicate="P",
        object="O",
        claim_text="Text",
        verification_score=0.0,
    )
    assert claim.verification_score == 0.0

    inbox = InboxItem(
        id="inbox:2",
        entity_id="c:1",
        story_cluster_id="c:1",
        title="Inbox 2",
        inbox_score=0.0,
        rank_score=0.0,
        project_impact_score=0.0,
    )
    assert inbox.inbox_score == 0.0
    assert inbox.rank_score == 0.0
    assert inbox.project_impact_score == 0.0


def test_phase14_historical_revisions_preserve_null_previous_states():
    """Historical revision records preserve previous_status=None without backfilling current state."""
    crev = ClaimRevision(
        id="rev:1",
        claim_id="claim:1",
        previous_status=None,
        new_status="supported",
        reason="Initial baseline assessment",
    )
    assert crev.previous_status is None
    assert crev.new_status == "supported"

    trev = TechnologyAssessmentRevision(
        id="trev:1",
        cluster_id="cluster:1",
        previous_stage=None,
        new_stage="prototype",
        previous_score=None,
        new_score=0.45,
        reason="Initial maturity stage determination",
    )
    assert trev.previous_stage is None
    assert trev.new_stage == "prototype"
    assert trev.previous_score is None


def test_phase14_source_identities_exact_canonical():
    """Exact source identities like 'hackernews' (not 'hacker_news') must be preserved."""
    ev = Event(id="hackernews:9999", title="HN Discussion")
    assert ev.source == "hackernews"
    assert ev.source_type == "discussion"

    ev_gh = Event(id="github:org/repo", title="Repo")
    assert ev_gh.source == "github"

    ev_arxiv = Event(id="arxiv:2608.12345", title="Paper")
    assert ev_arxiv.source == "arxiv"


def test_phase14_evidence_stance_aliases_boundary_and_idempotency():
    """Retained stance aliases ('refutes', 'opposes' -> 'contradicts', 'neutral', 'background' -> 'context') test."""
    # Positive compatibility
    assert normalize_evidence_stance("refutes") == "contradicts"
    assert normalize_evidence_stance("opposes") == "contradicts"
    assert normalize_evidence_stance("neutral") == "context"
    assert normalize_evidence_stance("background") == "context"

    # Idempotent normalization (single-normalization)
    assert normalize_evidence_stance("contradicts") == "contradicts"
    assert normalize_evidence_stance("context") == "context"
    assert normalize_evidence_stance("supports") == "supports"


def test_phase14_evidence_class_aliases_boundary_and_idempotency():
    """Retained evidence class aliases ('author' -> 'primary', 'discussion' -> 'community', etc.)."""
    assert normalize_evidence_class("author") == "primary"
    assert normalize_evidence_class("discussion") == "community"
    assert normalize_evidence_class("registry") == "metadata"
    assert normalize_evidence_class("benchmark") == "secondary"
    assert normalize_evidence_class("independent") == "primary"

    # Idempotency
    assert normalize_evidence_class("primary") == "primary"
    assert normalize_evidence_class("secondary") == "secondary"
    assert normalize_evidence_class("community") == "community"
    assert normalize_evidence_class("metadata") == "metadata"

