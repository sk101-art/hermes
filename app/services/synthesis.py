"""
HERMES Grounded Intelligence Synthesis Layer (Phase 3)
Deterministic, structured, provenance-carrying synthesis without epistemic fabrication or truncation-as-intelligence.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from app.evidence.verification import is_independent_evidence
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
)
from app.storage.db import Database


ALLOWED_ENTITY_TYPES = {
    "event",
    "claim",
    "evidence",
    "assessment",
    "project_match",
    "change",
}

FORBIDDEN_GENERIC_PATTERNS = [
    r"\bthis is an important development\b",
    r"\bdevelopers should monitor this\b",
    r"\bthis could have significant implications\b",
    r"\bthis signals growing adoption\b",
    r"\bsuitable for stable deployment\b",
    r"\bsuitable for deployment\b",
    r"\bproduction ready\b",
    r"\bsafe to deploy\b",
]


def validate_synthesis_grounding(
    synthesis: StorySynthesis,
    valid_entities: Dict[str, Set[str]],
) -> None:
    """
    Validates that every GroundingRef cited in the synthesis belongs to an entity
    actually supplied to this synthesis operation. Raises ValueError if ungrounded.
    """
    fields_to_check = [
        ("what_happened", synthesis.what_happened),
        ("why_it_matters", synthesis.why_it_matters),
        ("evidence_position", synthesis.evidence_position),
        ("project_implications", synthesis.project_implications),
        ("change_summary", synthesis.change_summary),
    ]

    for field_name, stmt_obj in fields_to_check:
        if stmt_obj is None:
            continue
        for ref in stmt_obj.grounding_references:
            if ref.entity_type not in ALLOWED_ENTITY_TYPES:
                raise ValueError(
                    f"Invalid grounding entity_type '{ref.entity_type}' in {field_name}. "
                    f"Allowed: {ALLOWED_ENTITY_TYPES}"
                )
            allowed_ids = valid_entities.get(ref.entity_type, set())
            if ref.entity_id not in allowed_ids:
                raise ValueError(
                    f"Grounding violation in {field_name}: cites nonexistent or unsupplied {ref.entity_type} ID '{ref.entity_id}'."
                )


def _check_forbidden_phrases(text: str) -> None:
    """Verifies that synthesis does not use unsubstantiated filler phrases."""
    text_lower = text.lower()
    for pat in FORBIDDEN_GENERIC_PATTERNS:
        if re.search(pat, text_lower):
            raise ValueError(f"Synthesis generated forbidden generic phrase matching pattern: '{pat}'")


def synthesize_story(
    cluster: Optional[StoryCluster] = None,
    cluster_id: Optional[str] = None,
    events: Optional[List[Event]] = None,
    claims: Optional[List[Claim]] = None,
    evidence_by_claim: Optional[Dict[str, List[Evidence]]] = None,
    assessment: Optional[TechnologyAssessment] = None,
    tech_state: Optional[TechnologyState] = None,
    project_matches: Optional[List[ProjectMatch]] = None,
    changes: Optional[List[Any]] = None,
    db: Optional[Database] = None,
    validate_references: bool = True,
) -> StorySynthesis:
    """
    Deterministic factual synthesis deriving structured statements strictly from
    grounded events, claims, evidence, assessments, project matches, and change records.
    """
    cid = cluster.id if cluster else cluster_id
    if cid is None and events:
        cid = getattr(events[0], "cluster_id", None)

    # Resolve from DB if missing and DB is available
    if db is not None and cid is not None:
        if cluster is None:
            cluster = db.get_cluster(cid)
        if events is None:
            events = db.get_cluster_events(cid)
        if claims is None:
            claims = db.get_claims_by_cluster(cid, current_only=True)
        if assessment is None:
            assessment = db.get_technology_assessment(cid)
        if tech_state is None:
            tech_state = db.get_technology_state(cid)
        if evidence_by_claim is None and claims:
            evidence_by_claim = {}
            for c in claims:
                evidence_by_claim[c.id] = db.get_evidence_by_claim(c.id)
        if project_matches is None:
            project_matches = []
            for p in db.get_all_projects(active_only=True):
                for m in db.get_project_matches(p.id):
                    if m.entity_id == cid:
                        project_matches.append(m)
        if changes is None:
            changes = db.get_technology_assessment_revisions(cid) if hasattr(db, "get_technology_assessment_revisions") else []

    events = events or []
    claims = claims or []
    evidence_by_claim = evidence_by_claim or {}
    project_matches = project_matches or []
    changes = changes or []

    # Map of valid input entities for reference validation
    valid_entities: Dict[str, Set[str]] = {
        "event": {e.id for e in events if e.id},
        "claim": {c.id for c in claims if c.id},
        "evidence": {
            ev.id
            for ev_list in evidence_by_claim.values()
            for ev in ev_list
            if getattr(ev, "id", None)
        },
        "assessment": {getattr(assessment, "id", cid or "assessment_1")} if assessment else set(),
        "project_match": {pm.id for pm in project_matches if getattr(pm, "id", None)},
        "change": {getattr(ch, "id", "") for ch in changes if getattr(ch, "id", "")},
    }

    # 1. Key Claims Preservation (Identity, status, truthful score preserved)
    key_claims: List[KeyClaimRef] = []
    for c in claims:
        key_claims.append(
            KeyClaimRef(
                claim_id=c.id,
                claim_text=c.claim_text,
                claim_type=c.claim_type,
                status=c.status,
                verification_score=c.verification_score,
                is_self_reported=getattr(c, "self_reported", getattr(c, "is_self_reported", False)),
            )
        )

    # 2. What Happened Synthesis
    what_happened: Optional[StatementWithProvenance] = None
    fallback_excerpt: Optional[str] = None

    if events:
        rel_events = [e for e in events if e.event_type == "release" or "release" in (e.title or "").lower()]
        paper_events = [
            e for e in events
            if e.event_type in ("paper", "publication") or e.source in ("arxiv", "openalex", "crossref")
        ]

        if rel_events:
            ev = rel_events[0]
            stmt = f"Release published: {ev.title}."
            if ev.text and len(ev.text.strip()) > 0:
                stmt += f" ({ev.text.strip()[:140]})"
            refs = [GroundingRef(entity_type="event", entity_id=ev.id, label="Release Event")]
            matching_claims = [c for c in claims if c.claim_type == "release"]
            if matching_claims:
                refs.append(GroundingRef(entity_type="claim", entity_id=matching_claims[0].id, label=f"Claim ({matching_claims[0].claim_type})"))
            what_happened = StatementWithProvenance(statement=stmt, grounding_references=refs)
        elif paper_events:
            ev = paper_events[0]
            stmt = f"Research publication '{ev.title}' appeared on {ev.source}"
            if ev.text and len(ev.text.strip()) > 0:
                stmt += f": {ev.text.strip()[:140]}."
            else:
                stmt += "."
            refs = [GroundingRef(entity_type="event", entity_id=ev.id, label="Publication Event")]
            matching_claims = [c for c in claims if c.claim_type in ("benchmark", "performance")]
            if matching_claims:
                refs.append(GroundingRef(entity_type="claim", entity_id=matching_claims[0].id, label=f"Claim ({matching_claims[0].claim_type})"))
            what_happened = StatementWithProvenance(statement=stmt, grounding_references=refs)
        else:
            primary_ev = events[0]
            if primary_ev.title and primary_ev.title.strip():
                stmt = f"Technology development '{primary_ev.title}' reported on {primary_ev.source}"
                if primary_ev.text and primary_ev.text.strip():
                    stmt += f" regarding: {primary_ev.text.strip()[:140]}."
                else:
                    stmt += "."
                refs = [GroundingRef(entity_type="event", entity_id=primary_ev.id, label="Primary Event")]
                what_happened = StatementWithProvenance(statement=stmt, grounding_references=refs)
            elif claims:
                c = claims[0]
                stmt = f"Extracted technology claim: {c.claim_text}."
                refs = [GroundingRef(entity_type="claim", entity_id=c.id, label=f"Claim ({c.claim_type})")]
                what_happened = StatementWithProvenance(statement=stmt, grounding_references=refs)
    elif claims:
        c = claims[0]
        stmt = f"Extracted technology claim: {c.claim_text}."
        refs = [GroundingRef(entity_type="claim", entity_id=c.id, label=f"Claim ({c.claim_type})")]
        what_happened = StatementWithProvenance(statement=stmt, grounding_references=refs)

    # 3. Why It Matters Synthesis (Requires grounded stored signals - No operational overreach)
    why_it_matters: Optional[StatementWithProvenance] = None

    supported_perf_claims = [
        c for c in claims
        if c.status in ("supported", "strongly_supported")
        and (c.claim_type in ("performance", "benchmark", "capability") or (c.verification_score is not None and c.verification_score >= 0.70))
    ]
    contradicted_claims = [c for c in claims if c.status in ("contradicted", "mixed")]
    high_relevance_matches = [pm for pm in project_matches if getattr(pm, "relevance_score", 0.0) >= 0.50]

    if supported_perf_claims:
        c = supported_perf_claims[0]
        v_str = f"{c.verification_score:.2f}" if c.verification_score is not None else "supported"
        stmt = f"Supported claim with recorded verification score {v_str}: '{c.claim_text}'."
        refs = [GroundingRef(entity_type="claim", entity_id=c.id, label=f"Claim ({c.status})")]
        why_it_matters = StatementWithProvenance(statement=stmt, grounding_references=refs)
    elif contradicted_claims:
        c = contradicted_claims[0]
        stmt = f"Identified contradictory or mixed evidence challenging assertions in '{c.claim_text}'."
        refs = [GroundingRef(entity_type="claim", entity_id=c.id, label=f"Claim ({c.status})")]
        why_it_matters = StatementWithProvenance(statement=stmt, grounding_references=refs)
    elif high_relevance_matches:
        pm = high_relevance_matches[0]
        rec = pm.recommendation or pm.match_type
        stmt = f"Directly impacts project '{pm.project_id}' with relevance score {pm.relevance_score:.2f} ({rec})."
        refs = [GroundingRef(entity_type="project_match", entity_id=pm.id, label="Project Match")]
        why_it_matters = StatementWithProvenance(statement=stmt, grounding_references=refs)
    elif assessment and getattr(assessment, "recommendation", None) and str(getattr(assessment, "recommendation", "")).strip():
        rec_clean = str(getattr(assessment, "recommendation", "")).strip()
        mat = assessment.maturity_stage or "unassessed"
        stmt = f"Assessed at maturity stage '{mat}' with stored guidance: {rec_clean}."
        ass_id = getattr(assessment, "id", None) or (cid if cid else "assessment_rec")
        refs = [GroundingRef(entity_type="assessment", entity_id=ass_id, label="Technology Assessment Guidance")]
        why_it_matters = StatementWithProvenance(statement=stmt, grounding_references=refs)
    elif assessment and assessment.maturity_stage in ("established", "production_candidate"):
        stmt = f"Technology is classified at '{assessment.maturity_stage}' maturity stage in HERMES assessment."
        ass_id = getattr(assessment, "id", None) or (cid if cid else "assessment_mat")
        refs = [GroundingRef(entity_type="assessment", entity_id=ass_id, label="Maturity Classification")]
        why_it_matters = StatementWithProvenance(statement=stmt, grounding_references=refs)
    else:
        why_it_matters = None

    # 4. Evidence Position Synthesis
    evidence_position: Optional[StatementWithProvenance] = None

    if claims:
        all_evidence: List[Evidence] = []
        for c in claims:
            all_evidence.extend(evidence_by_claim.get(c.id, []))

        all_contra = [
            ev for ev in all_evidence
            if getattr(ev, "stance", "").lower() in ("contradiction", "contradicts")
        ]
        contextual_only = [
            ev for ev in all_evidence
            if getattr(ev, "stance", "").lower() in ("contextual", "context")
        ]
        independent_supporting = [
            ev for ev in all_evidence
            if getattr(ev, "stance", "").lower() in ("support", "supports")
            and is_independent_evidence(ev)
        ]

        primary_claim = claims[0]
        claim_label = f"Claim ({primary_claim.status or 'unverified'})"

        if all_contra:
            ev = all_contra[0]
            stmt = "Evidence contains contradictory or disputed claims regarding stated properties."
            refs = [
                GroundingRef(entity_type="claim", entity_id=primary_claim.id, label=claim_label),
                GroundingRef(entity_type="evidence", entity_id=ev.id, label="Contradicting Evidence"),
            ]
            evidence_position = StatementWithProvenance(statement=stmt, grounding_references=refs)
        elif all_evidence and len(contextual_only) == len(all_evidence):
            ev = contextual_only[0]
            stmt = "Evidence provides contextual background without direct independent replication."
            refs = [
                GroundingRef(entity_type="claim", entity_id=primary_claim.id, label=claim_label),
                GroundingRef(entity_type="evidence", entity_id=ev.id, label="Contextual Evidence"),
            ]
            evidence_position = StatementWithProvenance(statement=stmt, grounding_references=refs)
        elif independent_supporting:
            ev = independent_supporting[0]
            source_count = len({ev.source for ev in independent_supporting if ev.source})
            independent_reproductions = [
                e for e in independent_supporting
                if getattr(e, "evidence_type", "") == "independent_reproduction"
            ]
            is_all_metadata = all(
                getattr(e, "evidence_class", "") == "metadata"
                or getattr(e, "evidence_type", "") in ("registry_metadata", "package_metadata")
                for e in independent_supporting
            )

            if independent_reproductions:
                stmt = f"Claims have independent reproduction evidence from {source_count} source(s)."
                label = "Independent Reproduction"
            elif is_all_metadata:
                stmt = f"Independent metadata records are attached from {source_count} source(s)."
                label = "Independent Metadata"
            else:
                stmt = f"Independent evidence is attached from {source_count} source(s)."
                label = "Independent Evidence"

            refs = [
                GroundingRef(entity_type="claim", entity_id=primary_claim.id, label=claim_label),
                GroundingRef(entity_type="evidence", entity_id=ev.id, label=label),
            ]
            evidence_position = StatementWithProvenance(statement=stmt, grounding_references=refs)
        elif all_evidence:
            ev = all_evidence[0]
            is_self = any(
                getattr(c, "self_reported", getattr(c, "is_self_reported", False))
                for c in claims
            ) or any(
                getattr(e, "self_reported", getattr(e, "is_self_reported", False))
                or getattr(e, "evidence_class", "") in ("primary", "self_disclosure")
                for e in all_evidence
            )
            if is_self:
                stmt = "Claims originate from self-reported primary release material without independent third-party verification."
            else:
                stmt = f"Supported by {len(all_evidence)} recorded evidence item(s) without independent third-party verification."
            refs = [
                GroundingRef(entity_type="claim", entity_id=primary_claim.id, label=claim_label),
                GroundingRef(entity_type="evidence", entity_id=ev.id, label="Evidence Item"),
            ]
            evidence_position = StatementWithProvenance(statement=stmt, grounding_references=refs)
        else:
            stmt = "Claims have been extracted from source announcements but lack recorded corroborating evidence records."
            refs = [GroundingRef(entity_type="claim", entity_id=primary_claim.id, label="Uncorroborated Claim")]
            evidence_position = StatementWithProvenance(statement=stmt, grounding_references=refs)

    # 5. Project Implications Synthesis (Only when ProjectMatch exists)
    project_implications: Optional[StatementWithProvenance] = None
    if project_matches:
        pm = project_matches[0]
        rec = pm.recommendation or pm.match_type
        stmt = f"Project relevance detected for '{pm.project_id}' ({rec}, score {pm.relevance_score:.2f})."
        refs = [GroundingRef(entity_type="project_match", entity_id=pm.id, label="Project Match Record")]
        if events:
            refs.append(GroundingRef(entity_type="event", entity_id=events[0].id, label="Triggering Event"))
        project_implications = StatementWithProvenance(statement=stmt, grounding_references=refs)

    # 6. Change Summary Synthesis (Only when Change record exists)
    change_summary: Optional[StatementWithProvenance] = None
    if changes:
        ch = changes[0]
        ch_id = getattr(ch, "id", "")
        desc = getattr(ch, "description", "") or getattr(ch, "change_type", "Detected change")
        old_v = getattr(ch, "old_value", None)
        new_v = getattr(ch, "new_value", None)
        if old_v and new_v:
            stmt = f"Change recorded: {desc} (transitioned from '{old_v}' to '{new_v}')."
        else:
            stmt = f"Change recorded: {desc}."
        refs = [GroundingRef(entity_type="change", entity_id=ch_id, label="Intelligence Change Record")]
        change_summary = StatementWithProvenance(statement=stmt, grounding_references=refs)

    # 7. Overall Synthesis & Fallback Handling
    is_synthesized = what_happened is not None
    if not is_synthesized and events:
        for e in events:
            if e.text and e.text.strip():
                fallback_excerpt = e.text.strip()[:300]
                break

    synthesis = StorySynthesis(
        what_happened=what_happened,
        why_it_matters=why_it_matters,
        evidence_position=evidence_position,
        key_claims=key_claims,
        project_implications=project_implications,
        change_summary=change_summary,
        is_synthesized=is_synthesized,
        fallback_excerpt=fallback_excerpt,
    )

    # Safety checks
    if synthesis.what_happened:
        _check_forbidden_phrases(synthesis.what_happened.statement)
    if synthesis.why_it_matters:
        _check_forbidden_phrases(synthesis.why_it_matters.statement)
    if synthesis.evidence_position:
        _check_forbidden_phrases(synthesis.evidence_position.statement)
    if synthesis.project_implications:
        _check_forbidden_phrases(synthesis.project_implications.statement)
    if synthesis.change_summary:
        _check_forbidden_phrases(synthesis.change_summary.statement)

    if validate_references:
        validate_synthesis_grounding(synthesis, valid_entities)

    return synthesis
