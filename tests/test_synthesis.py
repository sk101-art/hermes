"""
Tests for HERMES Grounded Intelligence Synthesis Layer (Phase 3).
Verifies deterministic, structured, provenance-carrying synthesis without epistemic fabrication or semantic inflation.
"""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    Claim,
    Evidence,
    Event,
    ProjectMatch,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.services.schemas import (
    GroundingRef,
    KeyClaimRef,
    StatementWithProvenance,
    StorySynthesis,
    StoryDetail,
)
from app.services.synthesis import (
    synthesize_story,
    validate_synthesis_grounding,
    _check_forbidden_phrases,
)
from app.services.intelligence import search_intelligence, MATURITY_ORDER


@pytest.fixture
def base_cluster():
    now = datetime.now(timezone.utc)
    return StoryCluster(
        id="cluster_test_1",
        canonical_title="FlashAttention-3 Fast JIT Kernel",
        event_ids=["ev_1"],
        sources=["github"],
        cluster_score=0.88,
        source_diversity_score=0.5,
        max_event_score=0.88,
        created_at=now,
        updated_at=now,
    )


def test_release_story_with_claim_and_event(base_cluster):
    """Release story with claim + event produces grounded what_happened."""
    ev = Event(
        id="ev_rel_1",
        source="github",
        source_type="code_repository",
        event_type="release",
        title="FlashAttention v3.0.0 Release",
        text="Official release of FlashAttention-3 with FP8 kernel support.",
        url="https://github.com/dao-ai-lab/flash-attention/releases/tag/v3.0.0",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.90,
    )
    cl = Claim(
        id="claim_rel_1",
        cluster_id=base_cluster.id,
        subject="FlashAttention-3",
        predicate="delivers",
        object="1.5x-2.0x speedup on Hopper GPUs with FP8",
        claim_text="FlashAttention-3 delivers 1.5x-2.0x speedup on Hopper GPUs with FP8",
        claim_type="release",
        assertion_level="author_fact",
        status="supported",
        verification_score=0.85,
        self_reported=True,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[cl],
        validate_references=True,
    )

    assert synth.is_synthesized is True
    assert synth.what_happened is not None
    assert "FlashAttention v3.0.0 Release" in synth.what_happened.statement
    assert any(ref.entity_id == "ev_rel_1" and ref.entity_type == "event" for ref in synth.what_happened.grounding_references)
    assert any(ref.entity_id == "claim_rel_1" and ref.entity_type == "claim" for ref in synth.what_happened.grounding_references)


def test_research_story_grounded_summary(base_cluster):
    """Research story produces grounded summary without overstating research result."""
    ev = Event(
        id="ev_arxiv_1",
        source="arxiv",
        source_type="academic_paper",
        event_type="paper",
        title="Sparse Attention Mechanisms for Long Context",
        text="We propose an attention pruning algorithm with O(N) complexity.",
        url="https://arxiv.org/abs/2608.99999",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.82,
    )
    cl = Claim(
        id="claim_res_1",
        cluster_id=base_cluster.id,
        subject="Sparse attention",
        predicate="achieves",
        object="4x memory reduction on 128k context benchmarks",
        claim_text="Sparse attention achieves 4x memory reduction on 128k context benchmarks",
        claim_type="benchmark",
        assertion_level="author_measurement",
        status="weakly_supported",
        verification_score=0.55,
        self_reported=True,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[cl],
        validate_references=True,
    )

    assert synth.is_synthesized is True
    assert synth.what_happened is not None
    assert "Research publication" in synth.what_happened.statement
    assert "Sparse Attention Mechanisms for Long Context" in synth.what_happened.statement
    assert synth.what_happened.grounding_references[0].entity_id == "ev_arxiv_1"


def test_self_reported_only_evidence_position(base_cluster):
    """Self-reported-only evidence produces clear self-reported statement, not verified/corroborated."""
    cl = Claim(
        id="claim_self_1",
        cluster_id=base_cluster.id,
        subject="FastKV",
        predicate="reduces",
        object="latency by 70%",
        claim_text="FastKV cache reduces latency by 70%",
        claim_type="performance",
        status="weakly_supported",
        verification_score=0.50,
        self_reported=True,
    )
    ev_item = Evidence(
        id="evi_self_1",
        claim_id=cl.id,
        event_id="ev_dummy_1",
        source="github",
        source_type="code_repository",
        title="Maintainer Announcement",
        url="https://github.com/example/kv/blog",
        stance="supports",
        evidence_class="self_disclosure",
        independence_score=0.30,
        reproducibility_score=0.40,
        quality_score=0.60,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_item]},
        validate_references=True,
    )

    assert synth.evidence_position is not None
    stmt = synth.evidence_position.statement.lower()
    assert "self-reported" in stmt
    assert "independent" not in stmt or "without independent" in stmt
    assert "corroborated" not in stmt
    assert any(r.entity_id == "evi_self_1" for r in synth.evidence_position.grounding_references)


def test_self_reported_claim_with_independent_reproduction(base_cluster):
    """Self-reported claim plus independent reproduction correctly describes independent reproduction."""
    cl = Claim(
        id="claim_indep_1",
        cluster_id=base_cluster.id,
        subject="vLLM",
        predicate="improves",
        object="throughput",
        claim_text="vLLM chunked prefill improves concurrency throughput",
        claim_type="performance",
        status="supported",
        verification_score=0.82,
        self_reported=False,
    )
    ev_self = Evidence(
        id="evi_s1",
        claim_id=cl.id,
        event_id="ev_d1",
        source="github",
        source_type="code_repository",
        evidence_class="primary",
        title="vLLM blog post",
        stance="supports",
        independence_score=0.30,
    )
    ev_indep = Evidence(
        id="evi_indep_1",
        claim_id=cl.id,
        event_id="ev_d2",
        source="anyscale",
        source_type="independent_benchmark",
        evidence_type="independent_reproduction",
        evidence_class="secondary",
        title="Independent LLM Inference Benchmark Suite",
        stance="supports",
        independence_score=0.90,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_self, ev_indep]},
        validate_references=True,
    )

    assert synth.evidence_position is not None
    assert "independent reproduction evidence" in synth.evidence_position.statement
    assert any(r.entity_id == "evi_indep_1" for r in synth.evidence_position.grounding_references)


def test_contextual_evidence_does_not_become_corroboration(base_cluster):
    """Contextual evidence alone does not produce a corroboration claim."""
    cl = Claim(
        id="claim_ctx_1",
        cluster_id=base_cluster.id,
        subject="Custom allocator",
        predicate="prevents",
        object="memory fragmentation",
        claim_text="Custom allocator prevents memory fragmentation",
        claim_type="architecture",
        status="weakly_supported",
        verification_score=0.45,
        self_reported=False,
    )
    ev_ctx = Evidence(
        id="evi_ctx_1",
        claim_id=cl.id,
        event_id="ev_d3",
        source="hacker_news",
        source_type="discussion",
        title="HN Discussion Thread",
        stance="context",
        evidence_class="community",
        independence_score=0.70,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_ctx]},
        validate_references=True,
    )

    assert synth.evidence_position is not None
    assert "corroborated" not in synth.evidence_position.statement
    assert "context" in synth.evidence_position.statement.lower()


def test_contradictory_evidence_reflected(base_cluster):
    """Contradictory evidence is explicitly captured in evidence_position and why_it_matters."""
    cl = Claim(
        id="claim_contra_1",
        cluster_id=base_cluster.id,
        subject="Quantized 4-bit model",
        predicate="matches",
        object="FP16 precision",
        claim_text="Quantized 4-bit model matches FP16 precision",
        claim_type="performance",
        status="contradicted",
        verification_score=0.25,
        self_reported=False,
    )
    ev_contra = Evidence(
        id="evi_contra_1",
        claim_id=cl.id,
        event_id="ev_d4",
        source="arxiv",
        source_type="academic_paper",
        title="Replication failure in 4-bit quantization benchmarks",
        stance="contradiction",
        evidence_class="secondary",
        independence_score=0.95,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_contra]},
        validate_references=True,
    )

    assert synth.evidence_position is not None
    assert "contradictory" in synth.evidence_position.statement.lower() or "disputed" in synth.evidence_position.statement.lower()
    assert any(r.entity_id == "evi_contra_1" for r in synth.evidence_position.grounding_references)
    assert synth.why_it_matters is not None
    assert "contradictory" in synth.why_it_matters.statement.lower()


def test_no_claims_usable_event_conservative_synthesis(base_cluster):
    """Event exists without claims: conservative event-grounded synthesis with no invented claim veracity."""
    ev = Event(
        id="ev_simple_1",
        source="github",
        source_type="code_repository",
        event_type="repository",
        title="Triton GPU Kernel Library",
        text="A language and compiler for custom deep learning operations.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.75,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[],
        validate_references=True,
    )

    assert synth.is_synthesized is True
    assert synth.what_happened is not None
    assert "Triton GPU Kernel Library" in synth.what_happened.statement
    assert synth.evidence_position is None
    assert len(synth.key_claims) == 0


def test_no_events_no_invented_what_happened(base_cluster):
    """When zero events and zero claims exist, what_happened is None and is_synthesized is False."""
    synth = synthesize_story(
        cluster=base_cluster,
        events=[],
        claims=[],
        validate_references=True,
    )

    assert synth.is_synthesized is False
    assert synth.what_happened is None
    assert synth.why_it_matters is None
    assert synth.fallback_excerpt is None


def test_insufficient_support_why_it_matters_remains_none(base_cluster):
    """When no verified performance, contradiction, project match, or maturity recommendation exists, why_it_matters is None."""
    ev = Event(
        id="ev_misc_1",
        source="github",
        title="Utility Helper Scripts",
        text="Miscellaneous helper scripts for developer workflows.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.40,
    )
    cl = Claim(
        id="claim_misc_1",
        cluster_id=base_cluster.id,
        subject="Scripts",
        predicate="support",
        object="Linux and macOS",
        claim_text="Scripts support Linux and macOS",
        claim_type="compatibility",
        status="unverified",
        verification_score=0.0,
        self_reported=True,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[cl],
        project_matches=[],
        changes=[],
        validate_references=True,
    )

    assert synth.why_it_matters is None


def test_established_maturity_does_not_infer_deployment_suitability(base_cluster):
    """Established maturity alone states the factual classification and NEVER produces deployment suitability advice."""
    now = datetime.now(timezone.utc)
    ass = TechnologyAssessment(
        id="ass_est_1",
        cluster_id=base_cluster.id,
        assessment_score=0.85,
        maturity_stage="established",
        assessed_at=now,
        created_at=now,
    )
    ev = Event(
        id="ev_est_1",
        source="github",
        title="vLLM Inference Core",
        text="Inference library.",
        discovered_at=now,
        final_score=0.8,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[],
        assessment=ass,
        validate_references=True,
    )

    assert synth.why_it_matters is not None
    stmt = synth.why_it_matters.statement
    assert "established" in stmt
    assert "suitable for stable deployment" not in stmt
    assert "suitable for deployment" not in stmt
    assert "production ready" not in stmt
    assert "safe to deploy" not in stmt


def test_weak_or_unverified_claim_never_linguistically_upgraded(base_cluster):
    """Weakly supported or unverified claims are never described as confirmed, verified, or proven."""
    cl = Claim(
        id="claim_weak_1",
        cluster_id=base_cluster.id,
        subject="New algorithm",
        predicate="delivers",
        object="100x speedup",
        claim_text="New algorithm delivers 100x speedup",
        claim_type="performance",
        status="unverified",
        verification_score=0.10,
        self_reported=True,
    )
    ev = Event(
        id="ev_wk_1",
        source="github",
        title="Prototype Release",
        text="Initial experimental commit.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.6,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[cl],
        validate_references=True,
    )

    # why_it_matters should be None because claim is unverified with score < 0.70
    assert synth.why_it_matters is None
    # evidence_position should not contain 'confirmed' or 'proven' or 'verified'
    if synth.evidence_position:
        stmt_lower = synth.evidence_position.statement.lower()
        assert "confirmed" not in stmt_lower
        assert "proven" not in stmt_lower
        assert "independently verified" not in stmt_lower


def test_no_project_match_yields_none_project_implications(base_cluster):
    """When ProjectMatch is absent, project_implications is strictly None."""
    ev = Event(
        id="ev_pm_1",
        source="github",
        title="General Tool",
        text="A tool.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.5,
    )
    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        project_matches=[],
        validate_references=True,
    )
    assert synth.project_implications is None


def test_project_match_grounded_implications(base_cluster):
    """Project match produces grounded project_implications."""
    pm = ProjectMatch(
        id="pm_hermes_1",
        project_id="project:cuda-compiler-lab",
        entity_type="cluster",
        entity_id=base_cluster.id,
        match_type="direct_dependency",
        relevance_score=0.91,
        impact_score=0.85,
        recommendation="evaluate",
        reason_codes=["direct_dependency"],
    )

    synth_with_proj = synthesize_story(
        cluster=base_cluster,
        events=[Event(id="ev_p1", source="github", title="Kernel", text="x", discovered_at=datetime.now(timezone.utc), final_score=0.8)],
        project_matches=[pm],
        validate_references=True,
    )
    assert synth_with_proj.project_implications is not None
    assert "cuda-compiler-lab" in synth_with_proj.project_implications.statement
    assert any(r.entity_id == "pm_hermes_1" and r.entity_type == "project_match" for r in synth_with_proj.project_implications.grounding_references)


def test_no_change_record_yields_none_change_summary(base_cluster):
    """When Change records are absent, change_summary is strictly None."""
    ev = Event(
        id="ev_ch_1",
        source="github",
        title="Stable Lib",
        text="A library.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.5,
    )
    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        changes=[],
        validate_references=True,
    )
    assert synth.change_summary is None


def test_change_summary_grounded(base_cluster):
    """Change summary is produced only when real change record exists."""
    class FakeChange:
        id = "ch_rev_1"
        cluster_id = base_cluster.id
        change_type = "maturity_upgrade"
        importance = "high"
        description = "Maturity upgraded from experimental to production_candidate"
        old_value = "experimental"
        new_value = "production_candidate"

    synth_with_change = synthesize_story(
        cluster=base_cluster,
        events=[Event(id="ev_c1", source="github", title="Kernel", text="x", discovered_at=datetime.now(timezone.utc), final_score=0.8)],
        changes=[FakeChange()],
        validate_references=True,
    )
    assert synth_with_change.change_summary is not None
    assert "transitioned from 'experimental' to 'production_candidate'" in synth_with_change.change_summary.statement
    assert synth_with_change.change_summary.grounding_references[0].entity_id == "ch_rev_1"


def test_story_detail_strictly_validates_synthesis_schema():
    """StoryDetail accepts a valid StorySynthesis and rejects malformed objects."""
    stmt = StatementWithProvenance(
        statement="Release published on GitHub.",
        grounding_references=[GroundingRef(entity_type="event", entity_id="ev_1", label="Release")],
    )
    synth = StorySynthesis(what_happened=stmt, is_synthesized=True)

    detail = StoryDetail(
        cluster_id="cl_1",
        canonical_title="Valid Story",
        cluster_score=0.8,
        synthesis=synth,
    )
    assert detail.synthesis is not None
    assert detail.synthesis.what_happened.statement == "Release published on GitHub."

    # Verify invalid grounding reference inside StoryDetail fails Pydantic validation
    with pytest.raises(ValidationError):
        StoryDetail(
            cluster_id="cl_1",
            canonical_title="Invalid Story",
            cluster_score=0.8,
            synthesis={"what_happened": {"statement": "test", "grounding_references": [{"entity_type": "event"}]}},  # missing entity_id
        )


def test_canonical_maturity_order_taxonomy_in_search_filtering(base_cluster):
    """Canonical 7-stage maturity taxonomy is strictly ordered for search filtering."""
    canonical_stages = [
        "concept",
        "research",
        "prototype",
        "experimental",
        "early_adoption",
        "production_candidate",
        "established",
    ]
    for stage in canonical_stages:
        assert stage in MATURITY_ORDER, f"Stage '{stage}' missing from MATURITY_ORDER"

    # Verify monotonic ranking order
    for i in range(len(canonical_stages) - 1):
        s1 = canonical_stages[i]
        s2 = canonical_stages[i + 1]
        assert MATURITY_ORDER[s1] < MATURITY_ORDER[s2], f"Maturity order violation: {s1} ({MATURITY_ORDER[s1]}) >= {s2} ({MATURITY_ORDER[s2]})"


def test_invalid_or_nonexistent_grounding_id_rejected(base_cluster):
    """Validation rejects any grounding reference citing a nonexistent or unsupplied entity ID."""
    stmt = StatementWithProvenance(
        statement="A synthesized fact.",
        grounding_references=[GroundingRef(entity_type="event", entity_id="nonexistent_event_id")],
    )
    synth = StorySynthesis(
        what_happened=stmt,
        is_synthesized=True,
    )

    valid_entities = {
        "event": {"ev_valid_1"},
        "claim": set(),
        "evidence": set(),
        "assessment": set(),
        "project_match": set(),
        "change": set(),
    }

    with pytest.raises(ValueError, match="nonexistent or unsupplied event ID"):
        validate_synthesis_grounding(synth, valid_entities)


def test_invalid_entity_type_rejected():
    """Validation rejects invalid entity types."""
    stmt = StatementWithProvenance(
        statement="A synthesized fact.",
        grounding_references=[GroundingRef(entity_type="unknown_type", entity_id="id_1")],
    )
    synth = StorySynthesis(what_happened=stmt, is_synthesized=True)
    with pytest.raises(ValueError, match="Invalid grounding entity_type"):
        validate_synthesis_grounding(synth, {"unknown_type": {"id_1"}})


def test_raw_excerpt_never_returned_as_synthesized_intelligence(base_cluster):
    """When what_happened is not formed, raw text is isolated in fallback_excerpt and is_synthesized is False."""
    ev = Event(
        id="ev_raw_1",
        source="reddit",
        title="",  # No clean title
        text="Raw unprocessed user forum text snippet.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.30,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[],
        validate_references=True,
    )

    assert synth.is_synthesized is False
    assert synth.what_happened is None
    assert synth.fallback_excerpt == "Raw unprocessed user forum text snippet."


def test_high_ranking_score_does_not_influence_synthesis(base_cluster):
    """A story with 0.99 ranking score but unverified claims does not claim verified status."""
    base_cluster.cluster_score = 0.99
    cl = Claim(
        id="claim_unver_1",
        cluster_id=base_cluster.id,
        subject="Architecture",
        predicate="surpasses",
        object="all existing models",
        claim_text="Revolutionary architecture surpasses all existing models",
        claim_type="performance",
        status="unverified",
        verification_score=0.0,
        self_reported=True,
    )
    ev = Event(
        id="ev_pop_1",
        source="hacker_news",
        title="Viral Hacker News Story",
        text="Huge discussion on social media.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.99,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[cl],
        validate_references=True,
    )

    assert synth.evidence_position is not None
    assert "corroborated" not in synth.evidence_position.statement
    assert "lack recorded corroborating evidence" in synth.evidence_position.statement


def test_partial_synthesis_serialization(base_cluster):
    """Partial synthesis with only what_happened serializes cleanly to dict/JSON."""
    ev = Event(
        id="ev_part_1",
        source="github",
        title="Small Tool",
        text="CLI tool for diffs.",
        discovered_at=datetime.now(timezone.utc),
        final_score=0.5,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        events=[ev],
        claims=[],
        validate_references=True,
    )

    d = synth.model_dump()
    assert d["is_synthesized"] is True
    assert d["what_happened"] is not None
    assert d["why_it_matters"] is None
    assert d["evidence_position"] is None
    assert d["project_implications"] is None
    assert d["change_summary"] is None


def test_synthesis_does_not_mutate_inputs(base_cluster):
    """Synthesis is strictly read-only and does not modify claim verification score, status, or cluster values."""
    cl = Claim(
        id="claim_pure_1",
        cluster_id=base_cluster.id,
        subject="Kernel",
        predicate="delivers",
        object="latency reduction",
        claim_text="Kernel latency benchmark",
        claim_type="performance",
        status="supported",
        verification_score=0.77,
        self_reported=False,
    )
    orig_score = cl.verification_score
    orig_status = cl.status

    _ = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        validate_references=True,
    )

    assert cl.verification_score == orig_score
    assert cl.status == orig_status


def test_forbidden_phrases_checker():
    """Forbidden generic phrases are caught by the phrase checker."""
    with pytest.raises(ValueError, match="forbidden generic phrase"):
        _check_forbidden_phrases("This is an important development for the industry.")

    # Safe text passes
    _check_forbidden_phrases("Release v2.0 published on GitHub.")


def test_independence_score_threshold_084_vs_085(base_cluster):
    """0.84 independence score does not qualify as independent; 0.85 does."""
    cl = Claim(
        id="claim_thresh_1",
        cluster_id=base_cluster.id,
        subject="Model",
        predicate="achieves",
        object="low latency",
        claim_text="Model achieves low latency",
        claim_type="performance",
        status="supported",
        verification_score=0.70,
        self_reported=False,
    )

    # 0.84 test: Not independent
    ev_084 = Evidence(
        id="ev_084",
        claim_id=cl.id,
        event_id="ev_1",
        source="tech_blog",
        source_type="discussion",
        evidence_class="community",
        title="Blog review",
        stance="supports",
        independence_score=0.84,
    )
    synth_084 = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_084]},
        validate_references=True,
    )
    assert synth_084.evidence_position is not None
    assert "without independent third-party verification" in synth_084.evidence_position.statement
    assert "Independent evidence is attached" not in synth_084.evidence_position.statement

    # 0.85 test: Qualifies as independent
    ev_085 = Evidence(
        id="ev_085",
        claim_id=cl.id,
        event_id="ev_1",
        source="benchmark_lab",
        source_type="academic_paper",
        evidence_class="secondary",
        title="Lab benchmark",
        stance="supports",
        independence_score=0.85,
    )
    synth_085 = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_085]},
        validate_references=True,
    )
    assert synth_085.evidence_position is not None
    assert "Independent evidence is attached from 1 source(s)." in synth_085.evidence_position.statement
    assert "reproduction" not in synth_085.evidence_position.statement.lower()


def test_evidence_type_independent_reproduction_counts_independent(base_cluster):
    """evidence_type='independent_reproduction' counts as independent reproduction regardless of class."""
    cl = Claim(
        id="claim_repro_1",
        cluster_id=base_cluster.id,
        subject="Algorithm",
        predicate="scales",
        object="linearly",
        claim_text="Algorithm scales linearly",
        claim_type="performance",
        status="supported",
        verification_score=0.90,
        self_reported=False,
    )
    ev_repro = Evidence(
        id="ev_repro_1",
        claim_id=cl.id,
        event_id="ev_1",
        source="independent_lab",
        source_type="independent_benchmark",
        evidence_type="independent_reproduction",
        evidence_class="community",
        title="Reproduction Run",
        stance="supports",
        independence_score=0.50,  # Low independence score overridden by explicit evidence_type
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_repro]},
        validate_references=True,
    )
    assert synth.evidence_position is not None
    assert "Claims have independent reproduction evidence from 1 source(s)." in synth.evidence_position.statement


def test_primary_evidence_class_low_independence_not_independent(base_cluster):
    """evidence_class='primary' with low independence correctly states self-reported primary release material."""
    cl = Claim(
        id="claim_prim_1",
        cluster_id=base_cluster.id,
        subject="Project",
        predicate="releases",
        object="v1",
        claim_text="Project releases v1",
        claim_type="release",
        status="unverified",
        verification_score=0.30,
        self_reported=True,
    )
    ev_prim = Evidence(
        id="ev_prim_1",
        claim_id=cl.id,
        event_id="ev_1",
        source="github",
        source_type="code_repository",
        evidence_class="primary",
        title="Author Release",
        stance="supports",
        independence_score=0.30,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_prim]},
        validate_references=True,
    )
    assert synth.evidence_position is not None
    assert "self-reported primary release material without independent third-party verification" in synth.evidence_position.statement


def test_independent_registry_metadata_not_described_as_reproduction(base_cluster):
    """Independent registry/metadata evidence is described as metadata, not independent reproduction."""
    cl = Claim(
        id="claim_meta_1",
        cluster_id=base_cluster.id,
        subject="Paper",
        predicate="registered_with_doi",
        object="10.1234/test.doi",
        claim_text="Paper registered with DOI 10.1234/test.doi",
        claim_type="scholarly_identity",
        status="supported",
        verification_score=0.50,
        self_reported=False,
    )
    ev_meta = Evidence(
        id="ev_meta_1",
        claim_id=cl.id,
        event_id="ev_1",
        source="openalex",
        source_type="scholarly_index",
        evidence_type="registry_metadata",
        evidence_class="metadata",
        title="Registry record",
        stance="supports",
        independence_score=0.90,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_meta]},
        validate_references=True,
    )
    assert synth.evidence_position is not None
    assert "Independent metadata records are attached from 1 source(s)." in synth.evidence_position.statement
    assert "reproduction" not in synth.evidence_position.statement.lower()
    assert "corroborated" not in synth.evidence_position.statement.lower()


def test_contextual_evidence_high_score_not_corroboration_unless_stance_permits(base_cluster):
    """Contextual evidence with high score does not produce a corroboration or reproduction claim."""
    cl = Claim(
        id="claim_ctx_hi",
        cluster_id=base_cluster.id,
        subject="Library",
        predicate="used_by",
        object="framework",
        claim_text="Library is used by framework",
        claim_type="ecosystem",
        status="supported",
        verification_score=0.60,
        self_reported=False,
    )
    ev_ctx = Evidence(
        id="ev_ctx_hi",
        claim_id=cl.id,
        event_id="ev_1",
        source="arxiv",
        source_type="academic_paper",
        evidence_class="secondary",
        title="Related Work Citation",
        stance="context",
        independence_score=0.95,
    )

    synth = synthesize_story(
        cluster=base_cluster,
        claims=[cl],
        evidence_by_claim={cl.id: [ev_ctx]},
        validate_references=True,
    )
    assert synth.evidence_position is not None
    assert "Evidence provides contextual background without direct independent replication." in synth.evidence_position.statement
    assert "corroborated" not in synth.evidence_position.statement.lower()
    assert "reproduction" not in synth.evidence_position.statement.lower()
