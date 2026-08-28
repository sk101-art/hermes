"""Deterministic match-explanation generation.

HERMES previously computed relevance scores but never explained them; the
frontend papered over this with a static formatAdvisory() lookup table. This
module generates a versioned, evidence-grounded ProjectMatchExplanation for
every match, answering:

- What is this intelligence item?
- What happened?
- Why was it matched to this project?
- What effect could it have?
- What should the user do next?
- What evidence supports each statement?

Hard rules (from the explanation-upgrade spec):
- Never synthesize descriptions that are not grounded in stored data.
- Never present "Semantic similarity: 0.79" as an explanation.
- Weak relationships must be stated as weak.
- If a question cannot be answered, the match must not be presented as
  actionable (relationship_label stays insufficient_evidence).
"""

from datetime import datetime, timezone
from typing import List, Optional
import re

from app.models.schemas import (
    Claim,
    ComparisonRow,
    Event,
    MatchDimension,
    PotentialEffect,
    Project,
    ProjectMatchExplanation,
    ProjectTechnologyProfile,
    RecommendedAction,
    EvidenceReference,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)

EXPLANATION_VERSION = "1"

_RESEARCH_SOURCES = {"arxiv", "openalex", "crossref"}
_DISCUSSION_SOURCES = {"hackernews", "stackexchange", "reddit"}

_VULN_MARKERS = ("cve-", "vulnerability", "vulnerabilities", "security advisory", "exploit", "remote code execution")
_BREAKING_MARKERS = ("breaking change", "breaking changes", "breaking api", "incompatible", "removed support", "abi break")
_DEPRECATION_MARKERS = ("deprecat", "end of life", "eol", "sunset", "no longer maintained")
_REMOVED_FEATURE_MARKERS = ("removed", "removal of", "no longer supports", "dropped support", "feature removed")
_OPERATIONAL_INCOMPAT_MARKERS = ("operational incompat", "requires migration", "data loss", "corrupt", "cannot start", "fails to start")
_REGRESSION_MARKERS = ("regression", "regressed", "performance regression", "slower than", "degraded performance")


def detect_concern_reason_codes(
    events: List[Event], claims: List[Claim]
) -> List[str]:
    """Detect audited concern signals and return structured reason codes.

    These codes feed get_project_risks(): a match only becomes an engineering
    concern when one of these concrete criteria is met — never from a high
    impact score alone.
    """
    codes: List[str] = []
    text_blob = " ".join(
        [(e.title or "") + " " + (e.text or "") for e in events]
        + [(c.claim_text or "") for c in claims]
    ).lower()

    # Vulnerability / CVE
    cve_ids = re.findall(r"cve-\d{4}-\d{4,}", text_blob)
    if cve_ids:
        codes.append(f"cve:{cve_ids[0]}")
    elif any(m in text_blob for m in _VULN_MARKERS):
        codes.append("vulnerability")

    # Breaking API/ABI change
    if any(m in text_blob for m in _BREAKING_MARKERS):
        codes.append("breaking_change")

    # Deprecation / EOL
    if any(m in text_blob for m in _DEPRECATION_MARKERS):
        codes.append("deprecation")

    # Incompatible dependency version (release claims mentioning incompatibility)
    has_release_claim = any(c.claim_type == "release" for c in claims)
    if has_release_claim and ("incompatible" in text_blob or "requires >=" in text_blob or "minimum version" in text_blob):
        codes.append("incompatible_dependency")

    # Removed / changed feature in use
    if any(m in text_blob for m in _REMOVED_FEATURE_MARKERS):
        codes.append("removed_feature")

    # Operational incompatibility
    if any(m in text_blob for m in _OPERATIONAL_INCOMPAT_MARKERS):
        codes.append("operational_incompat")

    # Evidence-backed regression (requires a supporting claim)
    if any(m in text_blob for m in _REGRESSION_MARKERS) and any(
        c.status in ("strongly_supported", "supported") for c in claims
    ):
        codes.append("evidence_regression")

    return codes


def _event_refs(events: List[Event], limit: int = 4) -> List[EvidenceReference]:
    refs: List[EvidenceReference] = []
    for e in events[:limit]:
        label = (e.title or e.id)[:80]
        refs.append(
            EvidenceReference(
                label=label,
                kind="url" if e.url else "event",
                url=e.url,
                detail=f"{e.source} event" + (f" ({e.event_type})" if e.event_type else ""),
            )
        )
    return refs


def _claim_refs(claims: List[Claim], limit: int = 3) -> List[EvidenceReference]:
    refs: List[EvidenceReference] = []
    for c in claims[:limit]:
        refs.append(
            EvidenceReference(
                label=(c.claim_text or c.id)[:80],
                kind="claim",
                detail=f"claim {c.id} — status: {c.status}, verification: {c.verification_score:.2f}"
                if c.verification_score is not None
                else f"claim {c.id} — status: {c.status}",
            )
        )
    return refs


def classify_subject_kind(events: List[Event], claims: List[Claim]) -> str:
    """Classify what kind of intelligence item this cluster represents."""
    text_blob = " ".join(
        [(e.title or "") + " " + (e.text or "") for e in events]
        + [(c.claim_text or "") for c in claims]
    ).lower()

    if any(m in text_blob for m in _VULN_MARKERS):
        return "vulnerability"
    if any(c.claim_type == "release" for c in claims) or any(
        e.event_type == "release" for e in events
    ):
        return "release"
    if any(e.source in _RESEARCH_SOURCES for e in events):
        return "research"
    if any(e.source in _DISCUSSION_SOURCES for e in events):
        return "discussion"
    if any(c.claim_type in ("performance", "benchmark", "architecture") for c in claims):
        return "change"
    return "story"


def describe_what_happened(
    cluster: StoryCluster, events: List[Event], claims: List[Claim], subject_kind: str
) -> Optional[str]:
    """Grounded description of what happened. Never invented."""
    # Prefer concrete release claims.
    for c in claims:
        if c.claim_type == "release" and c.claim_text:
            return c.claim_text[:240]
    # Then verified claim text.
    for c in claims:
        if c.status in ("strongly_supported", "supported") and c.claim_text:
            return c.claim_text[:240]
    # Then the lead event title.
    if events:
        lead = events[0]
        if lead.title:
            return lead.title[:240]
    # Fall back to the cluster title itself.
    if cluster.canonical_title:
        return cluster.canonical_title[:240]
    return None


def build_recommended_action(
    recommendation: Optional[str],
    subject_kind: str,
    matched_deps: List[str],
    strongest_claim: Optional[Claim],
    stage: str,
    risk_score: float,
) -> Optional[RecommendedAction]:
    """Structured advisory replacing the frontend formatAdvisory() lookup."""
    rec = (recommendation or "").strip().lower()
    claim_note = ""
    if strongest_claim and strongest_claim.claim_text:
        claim_note = f" Based on: {strongest_claim.claim_text[:120]}"

    if rec == "potential_risk":
        return RecommendedAction(
            action="Investigate impact on the current project implementation.",
            rationale="Signals in this story contradict expectations or raise risk for technology the project uses."
            + claim_note,
            urgency="high",
            conditions=["Confirm the affected component/version is actually in use."],
            validation_steps=[
                "Reproduce or check the reported issue against the project's pinned versions.",
                "Review the project's dependency lockfile for the affected range.",
            ],
            caveats=["Risk signals may be unverified; check claim status before acting."],
        )
    if rec == "upgrade_candidate":
        dep_note = f" Direct dependency: {', '.join(matched_deps)}." if matched_deps else ""
        return RecommendedAction(
            action="Plan an upgrade to the new release.",
            rationale="A new release is available for technology the project directly depends on." + dep_note + claim_note,
            urgency="medium",
            conditions=["Check the release notes for breaking changes before upgrading."],
            validation_steps=[
                "Read the changelog for breaking changes.",
                "Run the project's test suite in a branch with the upgraded version.",
            ],
            caveats=["New releases can regress performance or behavior; benchmark first."],
        )
    if rec == "optimization_candidate":
        return RecommendedAction(
            action="Benchmark the potential performance or efficiency gains.",
            rationale="Verified performance-related claims suggest possible gains for the project's stack." + claim_note,
            urgency="low",
            conditions=["Gains are claim-based until measured on the project's workload."],
            validation_steps=["Set up a representative benchmark before and after the change."],
            caveats=["Published benchmarks rarely match real workloads exactly."],
        )
    if rec == "consider":
        return RecommendedAction(
            action="Consider this tool or technique for evaluation.",
            rationale="Relevant to the project's stack with sufficient maturity and verification." + claim_note,
            urgency="low",
            conditions=["Maturity stage: " + stage + "."],
            validation_steps=["Prototype on a non-critical path first."],
            caveats=[],
        )
    if rec == "evaluate":
        return RecommendedAction(
            action="Assess compatibility with the project architecture.",
            rationale="Relevant but earlier-stage; compatibility with the project is not yet established." + claim_note,
            urgency="low",
            conditions=["Maturity stage: " + stage + ".", f"Risk score: {risk_score:.2f}."],
            validation_steps=["Check integration requirements and constraints."],
            caveats=["Early-stage technology may change APIs before stabilizing."],
        )
    if rec == "watch":
        return RecommendedAction(
            action="Monitor for maturity improvements.",
            rationale="Emerging or weakly verified technology in the project's ecosystem." + claim_note,
            urgency="low",
            conditions=[],
            validation_steps=[],
            caveats=["Not actionable yet; evidence or maturity is insufficient."],
        )
    if rec == "not_recommended_yet":
        return RecommendedAction(
            action="Defer adoption.",
            rationale="Early stage or unverified stability; insufficient evidence to act." + claim_note,
            urgency="low",
            conditions=[],
            validation_steps=[],
            caveats=["Re-evaluate when verification or maturity improves."],
        )
    return None


def generate_match_explanation(
    project: Project,
    profile: ProjectTechnologyProfile,
    cluster: StoryCluster,
    cluster_events: List[Event],
    cluster_claims: List[Claim],
    assessment: Optional[TechnologyAssessment],
    tech_state: Optional[TechnologyState],
    matched_deps: List[str],
    matched_techs: List[str],
    matched_langs: List[str],
    matched_topics: List[str],
    semantic_sim: float,
    match_type: str,
    relevance_score: float,
    recommendation: Optional[str],
) -> ProjectMatchExplanation:
    """Build the full explanation for a computed match."""
    now = datetime.now(timezone.utc)

    subject_kind = classify_subject_kind(cluster_events, cluster_claims)
    what_happened = describe_what_happened(cluster, cluster_events, cluster_claims, subject_kind)

    strongest_claim = cluster_claims[0] if cluster_claims else None
    stage = assessment.maturity_stage if assessment else "unknown"
    risk_score = tech_state.risk_score if tech_state else 0.25

    # --- Matched dimensions ---
    dimensions: List[MatchDimension] = []
    for dep in matched_deps:
        dimensions.append(
            MatchDimension(
                dimension="direct dependency",
                project_value=dep,
                intelligence_value=cluster.canonical_title,
                connection=f"The project directly depends on {dep}, and this story is about it.",
                evidence_strength="strong",
                evidence_references=_event_refs(cluster_events, 2),
            )
        )
    for tech in matched_techs:
        dimensions.append(
            MatchDimension(
                dimension="technology overlap",
                project_value=tech,
                intelligence_value=cluster.canonical_title,
                connection=f"The project uses {tech}, which this story references.",
                evidence_strength="moderate",
                evidence_references=_event_refs(cluster_events, 2),
            )
        )
    for top in matched_topics:
        dimensions.append(
            MatchDimension(
                dimension="topic overlap",
                project_value=top,
                intelligence_value=cluster.canonical_title,
                connection=f"The project works in the '{top}' area, which this story also touches.",
                evidence_strength="weak",
                evidence_references=_event_refs(cluster_events, 1),
            )
        )
    for lang in matched_langs:
        dimensions.append(
            MatchDimension(
                dimension="language",
                project_value=lang,
                intelligence_value=cluster.canonical_title,
                connection=f"Both involve {lang}. Language alone is a weak signal.",
                evidence_strength="weak",
                evidence_references=[],
            )
        )

    # --- Relevance summary (never just a similarity number) ---
    if matched_deps:
        relevance_summary = (
            f"Matched because {project.name} directly depends on {', '.join(matched_deps)}, "
            f"and this {subject_kind} is about that technology."
        )
    elif matched_techs:
        relevance_summary = (
            f"Matched because {project.name} uses {', '.join(matched_techs)}, "
            f"which this {subject_kind} references."
        )
    elif matched_topics:
        relevance_summary = (
            f"Matched on shared topic area ({', '.join(matched_topics)}). "
            f"This is a contextual relationship, not a direct dependency."
        )
    elif semantic_sim > 0:
        relevance_summary = (
            "Matched only on semantic similarity between the project profile and the story text. "
            "No concrete shared technology was identified, so this relationship is weak."
        )
    else:
        relevance_summary = "No concrete connection could be identified between this project and the story."

    # --- Potential effects ---
    effects: List[PotentialEffect] = []
    has_release = subject_kind == "release"
    has_perf = any(c.claim_type in ("performance", "benchmark") for c in cluster_claims)
    has_risk_signal = any(
        c.status in ("contradicted", "mixed") for c in cluster_claims
    ) or risk_score >= 0.60

    if matched_deps and has_release:
        effects.append(
            PotentialEffect(
                effect=f"A new version of {', '.join(matched_deps)} may bring fixes or features the project can use.",
                likelihood="likely",
                severity="medium",
                evidence_references=_claim_refs(cluster_claims, 2),
            )
        )
    if has_perf and (matched_deps or matched_techs):
        effects.append(
            PotentialEffect(
                effect="Reported performance changes could affect the project's workload if adopted.",
                likelihood="possible",
                severity="medium",
                evidence_references=_claim_refs(cluster_claims, 2),
            )
        )
    if has_risk_signal and (matched_deps or matched_techs):
        effects.append(
            PotentialEffect(
                effect="Risk signals in this story may affect technology the project relies on.",
                likelihood="possible",
                severity="high",
                evidence_references=_claim_refs(cluster_claims, 2),
            )
        )
    if subject_kind == "vulnerability" and (matched_deps or matched_techs):
        effects.append(
            PotentialEffect(
                effect="A reported vulnerability may apply to components in the project.",
                likelihood="possible",
                severity="high",
                evidence_references=_event_refs(cluster_events, 2),
            )
        )

    # --- Recommended action (structured advisory) ---
    action = build_recommended_action(
        recommendation, subject_kind, matched_deps, strongest_claim, stage, risk_score
    )

    # --- Limitations ---
    limitations: List[str] = []
    if not matched_deps and not matched_techs and semantic_sim > 0:
        limitations.append("This match is based on semantic similarity only; no shared technology was identified.")
    if not cluster_claims:
        limitations.append("No verified claims support this story yet.")
    elif strongest_claim and strongest_claim.status in ("unverified", "weakly_supported"):
        limitations.append(f"The strongest claim is {strongest_claim.status}; treat conclusions cautiously.")
    if matched_langs and not (matched_deps or matched_techs or matched_topics):
        limitations.append("The only overlap is programming language, which is a very weak signal.")
    if stage in ("concept", "prototype", "research"):
        limitations.append(f"The technology is at an early maturity stage ({stage}).")

    # --- Comparison rows ---
    comparison_rows: List[ComparisonRow] = []
    for dim in dimensions:
        comparison_rows.append(
            ComparisonRow(
                dimension=dim.dimension,
                project_value=dim.project_value,
                intelligence_value=dim.intelligence_value,
                why_relevant=dim.connection,
            )
        )

    # --- Relationship label ---
    if matched_deps:
        relationship_label = "direct_match"
    elif match_type == "architecture_relevant":
        relationship_label = "architectural_similarity"
    elif match_type in ("technology_overlap", "compatible_tool", "optimization_opportunity"):
        relationship_label = "potential_alternative"
    elif matched_techs or matched_topics:
        relationship_label = "weak_contextual"
    elif semantic_sim > 0:
        relationship_label = "weak_contextual" if semantic_sim >= 0.30 else "insufficient_evidence"
    else:
        relationship_label = "insufficient_evidence"

    # --- Evidence references ---
    evidence = _event_refs(cluster_events, 4) + _claim_refs(cluster_claims, 3)

    # --- Subject description (grounded only) ---
    subject_description = None
    if cluster_events and cluster_events[0].text:
        subject_description = cluster_events[0].text[:300]

    return ProjectMatchExplanation(
        subject_kind=subject_kind,
        subject_name=cluster.canonical_title,
        subject_description=subject_description,
        what_happened=what_happened,
        relevance_summary=relevance_summary,
        matched_dimensions=dimensions,
        potential_effects=effects,
        recommended_action=action,
        limitations=limitations,
        comparison_rows=comparison_rows,
        evidence_references=evidence,
        relationship_label=relationship_label,
        explanation_version=EXPLANATION_VERSION,
        generated_at=now,
    )
