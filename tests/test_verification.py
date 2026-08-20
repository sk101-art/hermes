import pytest
from app.evidence.verification import compute_verification, calculate_evidence_independence
from app.evidence.maturity import assess_technology_maturity
from app.models.schemas import Claim, Evidence, Event, StoryCluster


def test_single_announcement_vs_release_and_independent_reproduction():
    claim_announcement = Claim(
        id="claim:a1",
        cluster_id="cluster:1",
        claim_type="performance",
        subject="framework-x",
        predicate="reports",
        object="speedup",
        claim_text="Project reports 5x speedup.",
        self_reported=True,
    )
    ev_announcement = Evidence(
        id="ev:1",
        claim_id=claim_announcement.id,
        event_id="rss:1",
        source="rss",
        evidence_type="announcement",
        stance="supports",
        quality_score=0.40,
        independence_score=0.40,
        reproducibility_score=0.30,
    )
    score_announcement, status_announcement = compute_verification(claim_announcement, [ev_announcement])

    # Now compare with official release + independent reproduction
    claim_reproduced = Claim(
        id="claim:a2",
        cluster_id="cluster:2",
        claim_type="performance",
        subject="framework-x",
        predicate="reports",
        object="speedup",
        claim_text="Project reports 5x speedup.",
        self_reported=False,
    )
    ev_release = Evidence(
        id="ev:2",
        claim_id=claim_reproduced.id,
        event_id="github:release:1",
        source="github",
        evidence_type="official_release",
        stance="supports",
        quality_score=0.88,
        independence_score=0.60,
        reproducibility_score=0.85,
    )
    ev_repro = Evidence(
        id="ev:3",
        claim_id=claim_reproduced.id,
        event_id="arxiv:2",
        source="arxiv",
        evidence_type="independent_reproduction",
        stance="supports",
        quality_score=0.95,
        independence_score=0.95,
        reproducibility_score=0.90,
    )
    score_reproduced, status_reproduced = compute_verification(claim_reproduced, [ev_release, ev_repro])

    assert score_announcement < score_reproduced
    assert status_announcement in ("unverified", "weakly_supported")
    assert status_reproduced == "strongly_supported"


def test_echo_penalty_and_saturating_quantity():
    claim = Claim(
        id="claim:echo",
        cluster_id="cluster:echo",
        claim_type="release",
        subject="project-y",
        predicate="released",
        object="v1.0",
        claim_text="Project released v1.0",
    )

    # 10 duplicate announcements copying the same URL / source
    duplicate_ev = [
        Evidence(
            id=f"ev:echo:{i}",
            claim_id=claim.id,
            event_id=f"rss:{i}",
            source="rss",
            evidence_type="technical_blog",
            stance="supports",
            url="https://copied-blog.com/post",
            quality_score=0.58,
            independence_score=0.50,
            reproducibility_score=0.50,
        )
        for i in range(10)
    ]

    score_echo, status_echo = compute_verification(claim, duplicate_ev)
    # The echo penalty and quantity saturation should prevent the score from reaching a naive runaway value (> 0.85)
    assert score_echo < 0.70


def test_contradiction_handling_and_status_derivation():
    claim = Claim(
        id="claim:contra",
        cluster_id="cluster:contra",
        claim_type="reliability",
        subject="db-engine",
        predicate="provides",
        object="zero-crash guarantees",
        claim_text="Database provides zero-crash guarantees.",
    )

    ev_support = Evidence(
        id="ev:sup:1",
        claim_id=claim.id,
        event_id="github:release:1",
        source="github",
        evidence_type="official_release",
        stance="supports",
        quality_score=0.88,
        independence_score=0.50,
        reproducibility_score=0.80,
    )

    ev_contra = Evidence(
        id="ev:contra:1",
        claim_id=claim.id,
        event_id="github:issue:100",
        source="github",
        evidence_type="issue_report",
        stance="contradicts",
        quality_score=0.80,
        independence_score=0.80,
        reproducibility_score=0.80,
    )

    score_contra, status_contra = compute_verification(claim, [ev_support, ev_contra])
    assert status_contra in ("mixed", "contradicted")
    assert score_contra < 0.50


def test_technology_maturity_stages():
    cluster = StoryCluster(id="cluster:mat", canonical_title="Maturity Test")

    # 1. Paper only -> research
    ev_paper = Event(
        id="arxiv:100",
        source="arxiv",
        source_type="research_paper",
        event_type="preprint",
        title="Theoretical Paper",
    )
    mat_research = assess_technology_maturity(cluster, [ev_paper])
    assert mat_research.maturity_stage == "research"
    assert mat_research.research_score > 0
    assert mat_research.implementation_score == 0

    # 2. Paper + GitHub repo -> prototype / experimental
    ev_repo = Event(
        id="github:test-proto",
        source="github",
        source_type="code_repository",
        event_type="repository",
        title="test-proto",
    )
    mat_proto = assess_technology_maturity(cluster, [ev_paper, ev_repo])
    assert mat_proto.maturity_stage in ("prototype", "experimental")

    # 3. Mature Repo with multiple releases and high stars -> established / production_candidate
    ev_mature_repo = Event(
        id="github:vllm",
        source="github",
        event_type="repository",
        title="vLLM",
        metadata={"stars": 25000},
    )
    ev_rel1 = Event(
        id="github:release:1",
        source="github",
        event_type="release",
        title="v0.5.0",
    )
    ev_rel2 = Event(
        id="github:release:2",
        source="github",
        event_type="release",
        title="v0.6.0",
    )
    mat_established = assess_technology_maturity(cluster, [ev_mature_repo, ev_rel1, ev_rel2])
    assert mat_established.maturity_stage in ("established", "production_candidate")
    assert mat_established.implementation_score >= 0.70
