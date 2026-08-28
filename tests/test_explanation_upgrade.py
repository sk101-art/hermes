"""Verification gates for the Project Intelligence Explanation Upgrade.

These 18 tests encode the spec's acceptance criteria:

 1. Narrative extraction from README/docs (skip badges/TOC/install, file:line refs)
 2. Narrative extraction_status (extracted / partial / unavailable)
 3. Narrative persists independently from technology tags
 4. Every match carries a versioned explanation
 5. Explanations never reduce to a bare similarity number
 6. Cap: semantic-only matches <= 0.39
 7. Cap: broad-topic matches <= 0.44
 8. Cap: specific-tech matches <= 0.64
 9. Cap: verified architectural matches <= 0.79
10. Direct dependency matches may reach up to 1.0
11. Language-only overlap is never a match
12. High impact score alone is NEVER an engineering concern
13. Each of the 8 concrete concern criteria produces a risk
14. Concern reason-code detection (CVE, breaking, deprecation, ...)
15. Legacy rows without explanation are labeled legacy_unexplained / not actionable
16. DB migration is idempotent and preserves existing rows
17. GET /projects/{project_id}/matches/{cluster_id} canonical payload + 404s
18. Explanation round-trips through the database intact
"""

import re
from datetime import datetime, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_db
from app.api.server import app
from app.context.embeddings import get_embedder
from app.context.explanation import EXPLANATION_VERSION, detect_concern_reason_codes
from app.context.matcher import (
    CAP_BROAD_TOPIC,
    CAP_SEMANTIC_ONLY,
    CAP_SPECIFIC_TECH,
    CAP_VERIFIED_ARCHITECTURAL,
    match_project_with_cluster,
)
from app.context.narrative import extract_narrative_from_docs
from app.models.schemas import (
    Claim,
    ComparisonRow,
    Event,
    EvidenceReference,
    MatchDimension,
    PotentialEffect,
    Project,
    ProjectFile,
    ProjectMatch,
    ProjectMatchExplanation,
    ProjectTechnologyProfile,
    RecommendedAction,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.services import projects as projects_service
from app.storage.db import Database


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    d = Database(db_path=str(tmp_path / "explanation_upgrade.db"))
    yield d
    d.close()


def _now():
    return datetime.now(timezone.utc)


def _project(pid="project:gate", name="Gate Project", **kwargs):
    now = _now()
    return Project(
        id=pid,
        name=name,
        path=f"reference/{pid.replace(':', '_')}",
        context_hash="hash-gate",
        created_at=now,
        updated_at=now,
        **kwargs,
    )


def _profile(project_id, languages=None, frameworks=None, dependencies=None, topics=None):
    return ProjectTechnologyProfile(
        project_id=project_id,
        languages=languages or [],
        frameworks=frameworks or [],
        dependencies=dependencies or {},
        topics=topics or [],
        profile_text=f"Project: {project_id}",
        profile_hash=f"phash-{project_id}",
        updated_at=_now(),
    )


def _event(eid, title, text="", source="github", event_type="repository", url=None):
    return Event(
        id=eid,
        source=source,
        event_type=event_type,
        source_type="code_repository" if source == "github" else "discussion",
        title=title,
        text=text,
        url=url,
    )


def _cluster(cid, title, event_ids=None, sources=None):
    now = _now()
    return StoryCluster(
        id=cid,
        canonical_title=title,
        event_ids=event_ids or [],
        sources=sources or [],
        cluster_score=0.5,
        created_at=now,
        updated_at=now,
    )


def _store_event_embedding(db_conn, event):
    """Store an event embedding and return an identical vector as the project
    embedding, guaranteeing cosine similarity of exactly 1.0 (offline mode is
    deterministic)."""
    embedder = get_embedder()
    vec = embedder.embed(event.title)
    db_conn.save_embedding(event.id, embedder.model_name, vec)
    return vec


def _pfile(rel_path, text, project_id="project:narr"):
    return ProjectFile(
        id=f"file:{project_id}:{rel_path}",
        project_id=project_id,
        relative_path=rel_path,
        file_type="docs",
        size_bytes=len(text.encode("utf-8")),
        content_hash=f"hash-{rel_path}",
        extracted_text=text,
    )


README_LINES = [
    "[![Build Status](https://ci.example.com/build.svg)](https://ci.example.com)",
    "![Logo](logo.png)",
    "",
    "# Vector Forge",
    "",
    "- [Installation](#installation)",
    "- [Usage](#usage)",
    "",
    "Vector Forge is a high-throughput vector indexing engine for retrieval pipelines.",
    "",
    "## Features",
    "",
    "- Builds disk-backed vector indexes with millisecond query latency",
    "- Supports incremental updates without full rebuilds",
    "- Provides a Python API and a REST gateway",
    "",
    "## Architecture",
    "",
    "The engine is organized as a storage core with pluggable index backends and a query planner layer.",
    "",
    "## Components",
    "",
    "- `core/` — storage engine and segment manager",
    "- `planner/` — query planning and routing",
    "- `gateway/` — REST API surface",
    "",
    "## Installation",
    "",
    "pip install vector-forge",
]
README_TEXT = "\n".join(README_LINES)


# ---------------------------------------------------------------------------
# Gate 1-3: Narrative extraction and persistence
# ---------------------------------------------------------------------------


def test_gate1_narrative_full_readme_extraction():
    """Badges, images, TOC links, headings, and install commands are skipped;
    purpose/capabilities/architecture/components are extracted with file:line
    evidence references."""
    files = [_pfile("README.md", README_TEXT)]
    narrative = extract_narrative_from_docs(files, user_description="user note")

    assert narrative.user_description == "user note"
    assert narrative.extraction_status == "extracted"
    assert narrative.narrative_version == "1"

    # Purpose: first substantive prose paragraph (line 9), badges/TOC skipped.
    assert narrative.purpose_summary is not None
    assert "high-throughput vector indexing engine" in narrative.purpose_summary

    # Capabilities from the Features section bullets.
    assert len(narrative.capability_summaries) == 3
    assert any("disk-backed vector indexes" in c for c in narrative.capability_summaries)

    # Architecture prose from the Architecture section.
    assert narrative.architecture_summary is not None
    assert "storage core" in narrative.architecture_summary

    # Components from the Components section bullets (inline markdown stripped).
    assert len(narrative.primary_components) == 3
    assert any("storage engine and segment manager" in c for c in narrative.primary_components)

    # Evidence references point at file:line and cover purpose/features/arch/components.
    labels = [r.label for r in narrative.evidence_references]
    assert labels, "narrative must carry evidence references"
    assert all(re.match(r"^README\.md:\d+$", lbl) for lbl in labels)
    assert "README.md:9" in labels  # purpose line
    assert all(r.kind == "file" for r in narrative.evidence_references)

    # Nothing synthesized from skipped content.
    blob = " ".join(
        [narrative.purpose_summary or ""]
        + narrative.capability_summaries
        + [narrative.architecture_summary or ""]
        + narrative.primary_components
    ).lower()
    assert "pip install" not in blob
    assert "build status" not in blob
    assert "installation](#" not in blob


def test_gate2_narrative_status_partial_and_unavailable():
    # Partial: capabilities exist but no purpose prose could be extracted.
    partial_doc = "\n".join([
        "# Mini Tool",
        "",
        "## Features",
        "",
        "- Parses config files quickly",
    ])
    narrative = extract_narrative_from_docs([_pfile("README.md", partial_doc)])
    assert narrative.purpose_summary is None
    assert narrative.capability_summaries, "feature bullets should still be captured"
    assert narrative.extraction_status == "partial"

    # Unavailable: no documentation files at all.
    narrative_none = extract_narrative_from_docs(
        [_pfile("src/main.py", "import os")], user_description="only code"
    )
    assert narrative_none.extraction_status == "unavailable"
    assert narrative_none.purpose_summary is None
    assert narrative_none.capability_summaries == []
    assert narrative_none.user_description == "only code"


def test_gate3_narrative_persists_independently_from_tags(db):
    files = [_pfile("README.md", README_TEXT, project_id="project:narr")]
    narrative = extract_narrative_from_docs(files)

    proj = _project("project:narr", "Narrative Lab")
    proj.narrative = narrative
    db.save_project(proj)

    got = db.get_project("project:narr")
    assert got is not None
    assert got.narrative is not None
    assert got.narrative.purpose_summary == narrative.purpose_summary
    assert got.narrative.extraction_status == "extracted"

    # Changing technology tags must not disturb the persisted narrative.
    proj.topics = ["vectors", "search"]
    proj.frameworks = ["FastAPI"]
    db.save_project(proj)
    got2 = db.get_project("project:narr")
    assert got2.narrative is not None
    assert got2.narrative.purpose_summary == narrative.purpose_summary
    assert got2.topics == ["vectors", "search"]

    # The aggregated intelligence payload surfaces the narrative.
    intel = projects_service.get_project_intelligence("project:narr", db=db)
    assert intel is not None
    assert intel.narrative is not None
    assert intel.narrative["purpose_summary"] == narrative.purpose_summary


# ---------------------------------------------------------------------------
# Gate 4-5: Every match is explained; never with a bare similarity number
# ---------------------------------------------------------------------------


def _direct_dependency_scenario(db_conn):
    """Project directly depends on vllm; cluster is its new release."""
    project = _project("project:vllm-app", "VLLM App")
    profile = _profile(project.id, dependencies={"vllm": "==0.6.0"})
    ev = _event(
        "github:release:vllm-project/vllm:v0.7.0",
        "Release v0.7.0 for vllm-project/vllm",
        text="Official release of vLLM 0.7.0 with improved batching.",
        source="github",
        event_type="release",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.7.0",
    )
    cluster = _cluster(
        "cluster:vllm_rel", "vLLM 0.7.0 Released", event_ids=[ev.id], sources=["github"]
    )
    claim = Claim(
        id="claim:vllm_rel",
        cluster_id=cluster.id,
        claim_type="release",
        subject="vllm-project/vllm",
        predicate="released",
        object="version v0.7.0",
        claim_text="Repository vllm-project/vllm released version v0.7.0.",
        status="strongly_supported",
        verification_score=0.90,
        self_reported=False,
    )
    assessment = TechnologyAssessment(
        cluster_id=cluster.id, maturity_stage="established", assessment_score=0.90
    )
    tech_state = TechnologyState(cluster_id=cluster.id, risk_score=0.10)
    vec = _store_event_embedding(db_conn, ev)
    return project, profile, vec, cluster, ev, claim, assessment, tech_state


def test_gate4_every_match_carries_versioned_explanation(db):
    project, profile, vec, cluster, ev, claim, assessment, tech_state = (
        _direct_dependency_scenario(db)
    )

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=vec,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[claim],
        assessment=assessment,
        tech_state=tech_state,
        db=db,
    )

    assert match is not None
    assert match.explanation is not None, "every surfaced match must carry an explanation"
    assert match.explanation_version == EXPLANATION_VERSION == "1"
    assert match.evaluated_at is not None

    expl = match.explanation
    assert expl.subject_kind == "release"
    assert expl.subject_name == cluster.canonical_title
    assert expl.what_happened == claim.claim_text[:240]
    assert expl.relevance_summary

    dims = expl.matched_dimensions
    assert any(d.dimension == "direct dependency" for d in dims)
    dep_dim = next(d for d in dims if d.dimension == "direct dependency")
    assert dep_dim.evidence_strength == "strong"
    assert dep_dim.evidence_references, "dimensions must cite evidence"

    assert expl.evidence_references, "explanation must cite evidence"
    assert len(expl.comparison_rows) == len(dims)
    assert expl.recommended_action is not None
    assert expl.recommended_action.urgency in ("high", "medium", "low")
    assert expl.recommended_action.rationale
    assert expl.relationship_label == "direct_match"


def test_gate5_explanation_never_just_similarity_number(db):
    """A semantic-only match must explain itself as weak, not print a score."""
    project = _project("project:sem", "Semantic Only Project")
    profile = _profile(project.id, languages=["cobol"])  # no overlap with cluster
    ev = _event("ev_garden", "New approach to gardening automation", text="Garden robots everywhere.")
    cluster = _cluster("cluster:garden", "Gardening Automation", event_ids=[ev.id], sources=["github"])
    vec = _store_event_embedding(db, ev)

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=vec,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[],
        assessment=None,
        tech_state=None,
        db=db,
    )

    assert match is not None
    expl = match.explanation
    assert expl.relevance_summary is not None
    # Never a bare similarity figure as the explanation.
    assert not re.search(r"semantic similarity:\s*[\d.]+\s*$", expl.relevance_summary, re.IGNORECASE)
    # Weak relationships must be stated as weak.
    assert "weak" in expl.relevance_summary.lower()
    assert any("semantic similarity only" in lim.lower() for lim in expl.limitations)


# ---------------------------------------------------------------------------
# Gate 6-10: Relevance score caps
# ---------------------------------------------------------------------------


def test_gate6_cap_semantic_only(db):
    """Semantic similarity alone can never exceed 39% relevance."""
    project = _project("project:sem", "Semantic Only Project")
    profile = _profile(project.id, languages=["cobol"])
    ev = _event("ev_garden", "New approach to gardening automation", text="Garden robots everywhere.")
    cluster = _cluster("cluster:garden", "Gardening Automation", event_ids=[ev.id], sources=["github"])
    vec = _store_event_embedding(db, ev)  # cosine similarity = 1.0

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=vec,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[],
        assessment=None,
        tech_state=None,
        db=db,
    )

    assert match is not None
    assert match.relevance_score <= CAP_SEMANTIC_ONLY
    assert match.relevance_score == pytest.approx(0.39)
    assert match.explanation.relationship_label in ("weak_contextual", "insufficient_evidence")


def test_gate7_cap_broad_topic(db):
    """Broad topic overlap alone can never exceed 44% relevance."""
    project = _project("project:quantum", "Quantum Interests")
    profile = _profile(project.id, topics=["quantum computing"])
    ev = _event(
        "ev_quantum",
        "quantum computing breakthroughs in error correction",
        text="Researchers report progress on quantum computing error correction.",
        source="hackernews",
        event_type="story",
    )
    cluster = _cluster("cluster:quantum", "Quantum Computing Progress", event_ids=[ev.id], sources=["hackernews"])

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=None,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[],
        assessment=None,
        tech_state=None,
        db=db,
    )

    assert match is not None
    assert match.relevance_score <= CAP_BROAD_TOPIC
    assert match.match_type == "compatible_tool"
    assert "not a direct dependency" in (match.explanation.relevance_summary or "")


def test_gate8_cap_specific_tech(db):
    """Specific technology overlap can never exceed 64% relevance."""
    project = _project("project:web", "Web Service")
    profile = _profile(project.id, languages=["python"], frameworks=["FastAPI", "Starlette"])
    ev = _event("ev_web", "FastAPI and Starlette python async improvements", text="Framework updates.")
    cluster = _cluster("cluster:web", "FastAPI Starlette Updates", event_ids=[ev.id], sources=["github"])
    vec = _store_event_embedding(db, ev)  # pushes raw relevance to 0.70 pre-cap

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=vec,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[],
        assessment=None,
        tech_state=None,
        db=db,
    )

    assert match is not None
    assert match.relevance_score <= CAP_SPECIFIC_TECH
    assert match.relevance_score == pytest.approx(0.64)
    assert match.match_type == "technology_overlap"


def test_gate9_cap_verified_architectural(db):
    """Verified architectural relevance can never exceed 79%."""
    project = _project("project:compiler", "Compiler Lab")
    profile = _profile(
        project.id,
        languages=["rust"],
        frameworks=["LLVM", "Cranelift"],
        topics=["compiler", "kernel"],
    )
    ev = _event("ev_comp", "LLVM Cranelift compiler kernel advances in rust", text="Backend work.")
    cluster = _cluster("cluster:comp", "Compiler Backend Advances", event_ids=[ev.id], sources=["github"])
    claim = Claim(
        id="claim:comp",
        cluster_id=cluster.id,
        claim_type="architecture",
        subject="LLVM",
        predicate="restructures",
        object="pass pipeline",
        claim_text="LLVM restructures its pass pipeline for better codegen.",
        status="supported",
        verification_score=0.85,
        self_reported=False,
    )
    vec = _store_event_embedding(db, ev)  # raw relevance 0.80 pre-cap

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=vec,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[claim],
        assessment=None,
        tech_state=None,
        db=db,
    )

    assert match is not None
    assert match.match_type == "architecture_relevant"
    assert match.relevance_score <= CAP_VERIFIED_ARCHITECTURAL
    assert match.relevance_score == pytest.approx(0.79)
    assert match.explanation.relationship_label == "architectural_similarity"


def test_gate10_direct_dependency_up_to_full_relevance(db):
    """Direct dependency matches are the only ones allowed to reach up to 1.0."""
    project, profile, vec, cluster, ev, claim, assessment, tech_state = (
        _direct_dependency_scenario(db)
    )

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=vec,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[claim],
        assessment=assessment,
        tech_state=tech_state,
        db=db,
    )

    assert match is not None
    assert match.match_type == "direct_dependency"
    assert match.relevance_score >= 0.75
    assert match.relevance_score <= 1.0
    assert match.recommendation == "upgrade_candidate"
    assert match.explanation.relationship_label == "direct_match"
    # Structured advisory replaces the old frontend lookup table.
    action = match.explanation.recommended_action
    assert action is not None
    assert action.action == "Plan an upgrade to the new release."
    assert action.validation_steps


# ---------------------------------------------------------------------------
# Gate 11: Language-only overlap
# ---------------------------------------------------------------------------


def test_gate11_language_only_overlap_is_not_a_match(db):
    project = _project("project:py", "Python Tools")
    profile = _profile(project.id, languages=["python"])
    ev = _event("ev_py", "Python 3.14 packaging improvements", text="Packaging news.")
    cluster = _cluster("cluster:py", "Python Packaging", event_ids=[ev.id], sources=["github"])

    match = match_project_with_cluster(
        project=project,
        profile=profile,
        project_embedding=None,
        cluster=cluster,
        cluster_events=[ev],
        cluster_claims=[],
        assessment=None,
        tech_state=None,
        db=db,
    )

    assert match is None, "language-only overlap must never be presented as a match"


# ---------------------------------------------------------------------------
# Gate 12-13: Engineering concern criteria
# ---------------------------------------------------------------------------


def test_gate12_high_impact_alone_is_never_a_concern(db):
    db.save_project(_project("project:concern", "Concern Lab"))
    db.save_cluster(_cluster("cl_hi", "High Impact Story"))
    db.save_project_match(ProjectMatch(
        id="pm_hi",
        project_id="project:concern",
        entity_id="cl_hi",
        match_type="technology_overlap",
        relevance_score=0.90,
        impact_score=0.95,  # very high impact, but no concrete concern signal
        recommendation="watch",
        reason_codes=["technology_match:fastapi"],
    ))

    risks = projects_service.get_project_risks("project:concern", db=db)
    assert risks == [], "a high impact score alone must never become an engineering concern"


def test_gate13_eight_concern_criteria_each_produce_risk(db):
    pid = "project:concern-lab"
    db.save_project(_project(pid, "Concern Criteria Lab"))
    now = _now()

    criteria = [
        ("cl_cve", ["cve:cve-2024-9876"], "vulnerability"),
        ("cl_break", ["breaking_change"], "breaking_change"),
        ("cl_deprec", ["deprecation"], "deprecation"),
        ("cl_incompat", ["incompatible_dependency"], "incompatible_dependency"),
        ("cl_removed", ["removed_feature"], "removed_feature"),
        ("cl_oper", ["operational_incompat"], "operational_incompat"),
        ("cl_regress", ["evidence_regression"], "evidence_regression"),
    ]
    for i, (cid, codes, _expected) in enumerate(criteria):
        db.save_cluster(_cluster(cid, f"Concern story {i}"))
        db.save_project_match(ProjectMatch(
            id=f"pm_{cid}",
            project_id=pid,
            entity_id=cid,
            match_type="technology_overlap",
            relevance_score=0.50,
            impact_score=0.40,
            recommendation="watch",
            reason_codes=codes,
        ))

    # 8th criterion: verified high/critical canonical risk (assessed state + event).
    ev = Event(
        id="ev_crit",
        source="nvd",
        source_type="security_advisory",
        event_type="advisory",
        title="Critical advisory",
        text="Advisory details.",
        url="https://nvd.nist.gov/crit",
    )
    db.save_event(ev)
    db.save_cluster(_cluster("cl_assessed", "Assessed Risk Story", event_ids=["ev_crit"], sources=["nvd"]))
    db.add_event_to_cluster("cl_assessed", "ev_crit")
    db.save_technology_state(TechnologyState(
        cluster_id="cl_assessed", current_status="declining", risk_score=0.75, updated_at=now
    ))
    db.save_project_match(ProjectMatch(
        id="pm_assessed",
        project_id=pid,
        entity_id="cl_assessed",
        match_type="general_related",
        relevance_score=0.50,
        impact_score=0.30,
        recommendation="watch",
        reason_codes=["topic_match"],
    ))

    risks = projects_service.get_project_risks(pid, limit=20, db=db)
    assert len(risks) == 8

    by_cid = {r["cluster_id"]: r for r in risks}
    for cid, _codes, expected_type in criteria:
        assert by_cid[cid]["concern_type"] == expected_type, f"{cid} should be {expected_type}"
    assert by_cid["cl_assessed"]["concern_type"] == "assessed_risk"
    assert by_cid["cl_assessed"]["risk_status"] == "assessed"
    assert by_cid["cl_assessed"]["risk_level"] == "critical"


# ---------------------------------------------------------------------------
# Gate 14: Concern reason-code detection
# ---------------------------------------------------------------------------


def test_gate14_concern_reason_code_detection():
    # CVE extraction takes precedence over the generic vulnerability marker.
    ev_cve = _event("e_cve", "CVE-2024-12345 disclosed", text="A vulnerability was found.", source="nvd")
    codes = detect_concern_reason_codes([ev_cve], [])
    assert "cve:cve-2024-12345" in codes
    assert "vulnerability" not in codes

    # Breaking change / deprecation markers.
    assert "breaking_change" in detect_concern_reason_codes(
        [_event("e_break", "Library announces breaking change in API")], []
    )
    assert "deprecation" in detect_concern_reason_codes(
        [_event("e_eol", "Project reaches end of life", text="No longer maintained.")], []
    )

    # Incompatible dependency requires a release claim plus incompatibility text.
    claim_rel = Claim(
        id="c_rel",
        cluster_id="cl_x",
        claim_type="release",
        subject="libx",
        predicate="released",
        object="2.0",
        claim_text="libx released 2.0, incompatible with 1.x",
        status="supported",
        verification_score=0.70,
    )
    assert "incompatible_dependency" in detect_concern_reason_codes([], [claim_rel])

    # Regression requires a supporting claim; without one it is not a concern.
    ev_reg = _event("e_reg", "Performance regression reported", text="Slower than before.")
    assert "evidence_regression" not in detect_concern_reason_codes([ev_reg], [])
    claim_sup = Claim(
        id="c_reg",
        cluster_id="cl_x",
        claim_type="performance",
        subject="libx",
        predicate="regressed",
        object="throughput",
        claim_text="Regression confirmed by independent benchmark.",
        status="supported",
        verification_score=0.80,
    )
    assert "evidence_regression" in detect_concern_reason_codes([ev_reg], [claim_sup])


# ---------------------------------------------------------------------------
# Gate 15: Legacy unexplained rows are not actionable
# ---------------------------------------------------------------------------


def test_gate15_legacy_unexplained_not_actionable(db):
    pid = "project:legacy"
    db.save_project(_project(pid, "Legacy Project"))
    db.save_cluster(_cluster("cl_legacy", "Legacy Story"))
    db.save_project_match(ProjectMatch(
        id="pm_legacy",
        project_id=pid,
        entity_id="cl_legacy",
        match_type="technology_overlap",
        relevance_score=0.60,
        impact_score=0.50,
        recommendation="watch",
        reason_codes=["technology_match:x"],
        # No explanation: pre-upgrade row.
    ))

    payload = projects_service.get_project_match_comparison(pid, "cl_legacy", db=db)
    assert payload is not None
    assert payload["match"]["explanation"] is None
    assert payload["match"]["explanation_version"] == "legacy_unexplained"

    intel = projects_service.get_project_intelligence(pid, db=db)
    assert intel is not None
    ms = intel.top_matches[0]
    assert ms["explanation"] is None
    assert ms["explanation_version"] == "legacy_unexplained"


# ---------------------------------------------------------------------------
# Gate 16: Migration idempotence and row preservation
# ---------------------------------------------------------------------------


def test_gate16_migration_idempotent_preserves_rows(tmp_path):
    db_path = str(tmp_path / "migrate.db")

    db1 = Database(db_path=db_path)
    now = _now()
    db1.save_project(_project("project:mig", "Mig Project"))
    explained = ProjectMatchExplanation(
        subject_kind="release",
        subject_name="Mig Release",
        what_happened="A release happened.",
        relevance_summary="Matched because Mig Project depends on it.",
        relationship_label="direct_match",
        explanation_version=EXPLANATION_VERSION,
        generated_at=now,
    )
    db1.save_project_match(ProjectMatch(
        id="pm_mig",
        project_id="project:mig",
        entity_id="cl_mig",
        match_type="direct_dependency",
        relevance_score=0.90,
        impact_score=0.80,
        recommendation="upgrade_candidate",
        reason_codes=["dependency_match:mig"],
        explanation=explained,
        explanation_version=EXPLANATION_VERSION,
        evaluated_at=now,
    ))
    # Legacy-style row with no explanation.
    db1.save_project_match(ProjectMatch(
        id="pm_mig_legacy",
        project_id="project:mig",
        entity_id="cl_mig_old",
        match_type="technology_overlap",
        relevance_score=0.50,
        impact_score=0.40,
        recommendation="watch",
        reason_codes=["technology_match:y"],
    ))
    db1.close()

    # Re-open: migrations run again and must be idempotent + non-destructive.
    db2 = Database(db_path=db_path)
    pm_cols = {r["name"] for r in db2.conn.execute("PRAGMA table_info(project_matches)").fetchall()}
    assert {"explanation_json", "explanation_version", "evaluated_at"} <= pm_cols
    p_cols = {r["name"] for r in db2.conn.execute("PRAGMA table_info(projects)").fetchall()}
    assert "narrative_json" in p_cols

    kept = db2.get_project_match("project:mig", "cl_mig")
    assert kept is not None, "existing match rows must survive migration"
    assert kept.explanation is not None
    assert kept.explanation.subject_name == "Mig Release"
    assert kept.relevance_score == pytest.approx(0.90)

    legacy = db2.get_project_match("project:mig", "cl_mig_old")
    assert legacy is not None
    assert legacy.explanation is None

    assert db2.get_project("project:mig") is not None
    db2.close()


# ---------------------------------------------------------------------------
# Gate 17: Canonical match-comparison API payload
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path):
    db_path = str(tmp_path / "api_expl.db")
    setup_db = Database(db_path=db_path)
    now = _now()

    setup_db.save_project(_project("project:api-expl", "API Explained", languages=["python"]))
    ev = _event(
        "ev_api_x",
        "Release v1.0 of example/libx",
        text="A new release.",
        event_type="release",
        url="https://github.com/example/libx/releases/tag/v1.0",
    )
    setup_db.save_event(ev)
    setup_db.save_cluster(_cluster("cl_api", "libx 1.0 Released", event_ids=["ev_api_x"], sources=["github"]))
    setup_db.add_event_to_cluster("cl_api", "ev_api_x")
    setup_db.save_claim(Claim(
        id="claim_api_x",
        cluster_id="cl_api",
        claim_type="release",
        subject="example/libx",
        predicate="released",
        object="v1.0",
        claim_text="example/libx released v1.0.",
        status="supported",
        verification_score=0.80,
    ))
    expl = ProjectMatchExplanation(
        subject_kind="release",
        subject_name="libx 1.0 Released",
        what_happened="example/libx released v1.0.",
        relevance_summary="Matched because API Explained directly depends on libx.",
        matched_dimensions=[MatchDimension(
            dimension="direct dependency",
            project_value="libx",
            intelligence_value="libx 1.0 Released",
            connection="The project directly depends on libx.",
            evidence_strength="strong",
        )],
        comparison_rows=[ComparisonRow(
            dimension="direct dependency",
            project_value="libx",
            intelligence_value="libx 1.0 Released",
            why_relevant="The project directly depends on libx.",
        )],
        relationship_label="direct_match",
        explanation_version=EXPLANATION_VERSION,
        generated_at=now,
    )
    setup_db.save_project_match(ProjectMatch(
        id="pm_api",
        project_id="project:api-expl",
        entity_id="cl_api",
        match_type="direct_dependency",
        relevance_score=0.90,
        impact_score=0.85,
        recommendation="upgrade_candidate",
        reason_codes=["dependency_match:libx"],
        explanation=expl,
        explanation_version=EXPLANATION_VERSION,
        evaluated_at=now,
    ))

    def override_get_db():
        request_db = Database(db_path=db_path)
        try:
            yield request_db
        finally:
            request_db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    setup_db.close()


def test_gate17_match_comparison_endpoint(api_client):
    resp = api_client.get("/projects/project:api-expl/matches/cl_api")
    assert resp.status_code == 200
    body = resp.json()

    # Canonical three-part payload.
    assert set(body.keys()) == {"project", "subject", "match"}

    assert body["project"]["project_id"] == "project:api-expl"
    assert body["project"]["name"] == "API Explained"
    assert "narrative" in body["project"]

    assert body["subject"]["cluster_id"] == "cl_api"
    assert body["subject"]["title"] == "libx 1.0 Released"
    assert body["subject"]["story_available"] is True
    assert body["subject"]["event_count"] >= 1
    assert body["subject"]["claim_count"] >= 1

    m = body["match"]
    assert m["cluster_id"] == "cl_api"
    assert m["match_type"] == "direct_dependency"
    assert m["explanation"] is not None
    assert m["explanation"]["relationship_label"] == "direct_match"
    assert m["explanation_version"] == "1"
    assert m["evaluated_at"]

    # Missing match and missing project both 404.
    assert api_client.get("/projects/project:api-expl/matches/cl_missing").status_code == 404
    assert api_client.get("/projects/project:nope/matches/cl_api").status_code == 404


# ---------------------------------------------------------------------------
# Gate 18: Explanation round-trips through storage
# ---------------------------------------------------------------------------


def test_gate18_explanation_db_roundtrip(db):
    now = _now()
    pid = "project:roundtrip"
    db.save_project(_project(pid, "Roundtrip"))

    expl = ProjectMatchExplanation(
        subject_kind="release",
        subject_name="Test Release",
        subject_description="A release description.",
        what_happened="Test Release shipped.",
        relevance_summary="Matched because Roundtrip directly depends on testlib.",
        matched_dimensions=[MatchDimension(
            dimension="direct dependency",
            project_value="testlib",
            intelligence_value="Test Release",
            connection="Direct dependency.",
            evidence_strength="strong",
            evidence_references=[EvidenceReference(label="GitHub release", kind="url", url="https://example.com")],
        )],
        potential_effects=[PotentialEffect(effect="New version may fix bugs.", likelihood="likely", severity="medium")],
        recommended_action=RecommendedAction(
            action="Plan an upgrade to the new release.",
            rationale="A new release is available for a direct dependency.",
            urgency="medium",
            conditions=["Check changelog"],
            validation_steps=["Run tests"],
            caveats=["May regress"],
        ),
        limitations=["Early stage."],
        comparison_rows=[ComparisonRow(
            dimension="direct dependency",
            project_value="testlib",
            intelligence_value="Test Release",
            why_relevant="Direct dependency.",
        )],
        evidence_references=[EvidenceReference(label="Test Release", kind="event", detail="github event (release)")],
        relationship_label="direct_match",
        explanation_version=EXPLANATION_VERSION,
        generated_at=now,
    )
    db.save_project_match(ProjectMatch(
        id="pm_rt",
        project_id=pid,
        entity_id="cl_rt",
        match_type="direct_dependency",
        relevance_score=0.88,
        impact_score=0.77,
        recommendation="upgrade_candidate",
        reason_codes=["dependency_match:testlib"],
        explanation=expl,
        explanation_version=EXPLANATION_VERSION,
        evaluated_at=now,
    ))

    got = db.get_project_match(pid, "cl_rt")
    assert got is not None
    assert got.explanation is not None
    assert got.explanation.subject_kind == "release"
    assert got.explanation.what_happened == "Test Release shipped."
    assert got.explanation.matched_dimensions[0].dimension == "direct dependency"
    assert got.explanation.matched_dimensions[0].evidence_references[0].url == "https://example.com"
    assert got.explanation.potential_effects[0].likelihood == "likely"
    assert got.explanation.recommended_action.urgency == "medium"
    assert got.explanation.recommended_action.validation_steps == ["Run tests"]
    assert got.explanation.comparison_rows[0].why_relevant == "Direct dependency."
    assert got.explanation.relationship_label == "direct_match"
    assert got.explanation_version == "1"
    assert got.evaluated_at is not None

    # Also visible through the list query.
    matches = db.get_project_matches(pid)
    assert len(matches) == 1
    assert matches[0].explanation.subject_name == "Test Release"
