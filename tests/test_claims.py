import os
import tempfile
import pytest
from datetime import datetime, timezone

from app.evidence.classifier import classify_evidence, EVIDENCE_PRIORS
from app.evidence.claims import (
    compute_claim_fingerprint,
    compute_evidence_fingerprint,
    build_release_claim,
    build_repository_claim,
    build_model_claim,
    build_scholarly_identity_claim,
    build_performance_claim,
    extract_claims_for_cluster,
)
from app.models.schemas import Claim, Evidence, Event, StoryCluster
from app.storage.db import Database


def test_claim_model_instantiation_and_serialization():
    claim = Claim(
        id="claim:1234567890abcdef",
        cluster_id="cluster:test-1",
        claim_type="release",
        subject="vllm-project/vllm",
        predicate="released",
        object="version v0.6.0",
        claim_text="Repository vllm-project/vllm released version v0.6.0.",
        status="supported",
        confidence=1.0,
        verification_score=0.82,
        self_reported=True,
    )
    assert claim.id.startswith("claim:")
    assert claim.claim_type == "release"
    assert claim.self_reported is True

    claim_dict = claim.model_dump()
    assert claim_dict["subject"] == "vllm-project/vllm"
    assert claim_dict["verification_score"] == 0.82


def test_evidence_model_instantiation_and_serialization():
    ev = Evidence(
        id="evidence:abcdef1234567890",
        claim_id="claim:1234567890abcdef",
        event_id="github:release:12345",
        source="github",
        evidence_type="official_release",
        evidence_class="primary",
        stance="supports",
        excerpt="Release v0.6.0 notes.",
        quality_score=0.88,
        independence_score=0.50,
        reproducibility_score=0.85,
    )
    assert ev.id.startswith("evidence:")
    assert ev.evidence_type == "official_release"
    assert ev.stance == "supports"
    assert ev.quality_score == 0.88


def test_claim_fingerprint_stability():
    fp1 = compute_claim_fingerprint("cluster:1", "release", "vllm-project/vllm", "released", "version v0.6.0")
    fp2 = compute_claim_fingerprint("cluster:1", "RELEASE", " vllm-project/vllm ", "released", "version v0.6.0")
    fp3 = compute_claim_fingerprint("cluster:2", "release", "vllm-project/vllm", "released", "version v0.6.0")

    assert fp1 == fp2
    assert fp1 != fp3
    assert fp1.startswith("claim:")


def test_evidence_fingerprint_stability():
    fp1 = compute_evidence_fingerprint("claim:1", "github:101", "supports")
    fp2 = compute_evidence_fingerprint("claim:1", " github:101 ", "SUPPORTS")
    fp3 = compute_evidence_fingerprint("claim:1", "github:101", "contradicts")

    assert fp1 == fp2
    assert fp1 != fp3
    assert fp1.startswith("evidence:")


def test_evidence_classification_by_source_and_type():
    # GitHub release
    ev_gh_rel = Event(id="gh:rel:1", source="github", event_type="release", title="Release v1", url="https://gh.com")
    etype, eclass, q = classify_evidence(ev_gh_rel)
    assert etype == "official_release"
    assert eclass == "primary"
    assert q == EVIDENCE_PRIORS["official_release"]

    # GitHub repository
    ev_gh_repo = Event(id="gh:repo:1", source="github", event_type="repository", title="Repo", url="https://gh.com")
    etype, eclass, q = classify_evidence(ev_gh_repo)
    assert etype == "source_code"
    assert eclass == "primary"

    # arXiv preprint
    ev_ax = Event(id="arxiv:1", source="arxiv", event_type="research_paper", title="Paper", url="https://arxiv.org")
    etype, eclass, q = classify_evidence(ev_ax)
    assert etype == "preprint"
    assert eclass == "primary"

    # OpenAlex / Crossref
    ev_oa = Event(id="openalex:1", source="openalex", event_type="scholarly_work", title="Work", url="https://oa.org")
    etype, eclass, q = classify_evidence(ev_oa)
    assert etype == "registry_metadata"
    assert eclass == "metadata"

    # Hacker News
    ev_hn = Event(id="hn:1", source="hackernews", event_type="discussion", title="HN", url="https://hn.com")
    etype, eclass, q = classify_evidence(ev_hn)
    assert etype == "community_discussion"
    assert eclass == "community"

    # Stack Exchange
    ev_se = Event(id="se:1", source="stackexchange", event_type="question", title="Q", url="https://so.com")
    etype, eclass, q = classify_evidence(ev_se)
    assert etype == "developer_experience"
    assert eclass == "community"

    # RSS
    ev_rss = Event(id="rss:1", source="rss", event_type="article", title="Blog", url="https://blog.com")
    etype, eclass, q = classify_evidence(ev_rss)
    assert etype == "technical_blog"
    assert eclass == "secondary"


def test_deterministic_claim_builders():
    # Release claim
    ev_rel = Event(
        id="github:release:100",
        source="github",
        event_type="release",
        title="Release v0.6.0 for vllm-project/vllm",
        metadata={"repository": "vllm-project/vllm", "tag_name": "v0.6.0"},
        url="https://github.com/vllm-project/vllm/releases/tag/v0.6.0",
    )
    res_rel = build_release_claim(ev_rel, "cluster:1")
    assert res_rel is not None
    claim_rel, ev_rel_record = res_rel
    assert claim_rel.subject == "vllm-project/vllm"
    assert claim_rel.object == "version v0.6.0"
    assert claim_rel.claim_type == "release"
    assert ev_rel_record.evidence_type == "official_release"

    # Hugging Face Model claim
    ev_hf = Event(
        id="huggingface:model:meta-llama/Llama-3-8B",
        source="huggingface",
        event_type="model",
        title="Llama-3-8B",
        metadata={"repo_id": "meta-llama/Llama-3-8B"},
        url="https://huggingface.co/meta-llama/Llama-3-8B",
    )
    res_hf = build_model_claim(ev_hf, "cluster:2")
    assert res_hf is not None
    claim_hf, ev_hf_record = res_hf
    assert claim_hf.subject == "meta-llama/Llama-3-8B"
    assert claim_hf.claim_type == "availability"

    # Scholarly identity claim
    ev_cr = Event(
        id="crossref:10.1145/123",
        source="crossref",
        event_type="scholarly_work",
        title="FlashAttention-2 Paper",
        doi="10.1145/123",
        url="https://doi.org/10.1145/123",
    )
    res_cr = build_scholarly_identity_claim(ev_cr, "cluster:3")
    assert res_cr is not None
    claim_cr, ev_cr_record = res_cr
    assert claim_cr.claim_type == "scholarly_identity"
    assert "10.1145/123" in claim_cr.object

    # Performance claim (conservative attribution)
    ev_perf = Event(
        id="github:fast-rag",
        source="github",
        event_type="repository",
        title="Fast RAG",
        text="A framework achieving 4x faster throughput on GPUs.",
        url="https://github.com/example/fast-rag",
    )
    res_perf = build_performance_claim(ev_perf, "cluster:4")
    assert res_perf is not None
    claim_perf, ev_perf_record = res_perf
    assert claim_perf.claim_type == "performance"
    assert "Project reports" in claim_perf.claim_text


def test_no_evidence_no_saved_claim_rule():
    cluster = StoryCluster(id="cluster:empty", canonical_title="Empty")
    # Empty events list
    extracted = extract_claims_for_cluster(cluster, [])
    assert len(extracted) == 0


def test_claim_and_evidence_database_persistence():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    db2 = None
    try:
        db = Database(db_path=db_path)
        claim = Claim(
            id="claim:persisted-1",
            cluster_id="cluster:p1",
            claim_type="release",
            subject="llvm/llvm-project",
            predicate="released",
            object="version 22.1.0",
            claim_text="llvm/llvm-project released version 22.1.0.",
            status="supported",
            verification_score=0.85,
        )
        evidence = Evidence(
            id="evidence:persisted-1",
            claim_id=claim.id,
            event_id="github:release:22",
            source="github",
            evidence_type="official_release",
            stance="supports",
            quality_score=0.88,
        )

        db.save_claim(claim)
        db.save_evidence(evidence)
        db.close()
        db = None

        db2 = Database(db_path=db_path)
        fetched_claim = db2.get_claim("claim:persisted-1")
        assert fetched_claim is not None
        assert fetched_claim.subject == "llvm/llvm-project"
        assert fetched_claim.verification_score == 0.85

        fetched_ev = db2.get_evidence_by_claim("claim:persisted-1")
        assert len(fetched_ev) == 1
        assert fetched_ev[0].evidence_type == "official_release"
    finally:
        if db:
            db.close()
        if db2:
            db2.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass
