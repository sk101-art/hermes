import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.evidence.maturity import assess_technology_maturity
from app.evidence.risk import calculate_technology_risk
from app.evidence.staleness import calculate_claim_staleness
from app.evidence.verification import compute_verification
from app.models.schemas import (
    Claim,
    ClaimRevision,
    Event,
    Evidence,
    IntelligenceChange,
    Relationship,
    StoryCluster,
    TechnologyAssessment,
    TechnologyAssessmentRevision,
    TechnologyState,
)
from app.storage.db import Database

MEANINGFUL_SCORE_DELTA = 0.02


def generate_change_id(entity_id: str, change_type: str, new_val: str) -> str:
    norm = f"{entity_id}|{change_type}|{new_val}"
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"change:{digest}"


def generate_revision_id(claim_id: str, new_status: str, new_score: float) -> str:
    norm = f"{claim_id}|{new_status}|{new_score:.4f}"
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"rev:{digest}"


def generate_tech_rev_id(cluster_id: str, new_stage: str, new_score: float) -> str:
    norm = f"{cluster_id}|{new_stage}|{new_score:.4f}"
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"techrev:{digest}"


def reevaluate_claim(
    claim: Claim,
    evidence_list: List[Evidence],
    db: Database,
    trigger_event: Optional[Event] = None,
    trigger_evidence: Optional[Evidence] = None,
    dry_run: bool = False,
) -> Tuple[Claim, Optional[ClaimRevision], Optional[IntelligenceChange]]:
    """
    Re-evaluates a single claim against all associated evidence.
    Detects status transitions, computes score deltas, and records revisions and changes.
    """
    prev_status = claim.status
    prev_score = claim.verification_score

    # Compute new verification score and status
    new_score, new_status = compute_verification(
        claim=claim,
        evidence_list=evidence_list,
        previous_status=prev_status,
    )

    now = datetime.now(timezone.utc)
    staleness = calculate_claim_staleness(claim, now)

    # Check for meaningful change
    score_delta = abs(new_score - prev_score)
    status_changed = prev_status != new_status
    meaningful_change = status_changed or (score_delta >= MEANINGFUL_SCORE_DELTA)

    revision = None
    change = None

    if meaningful_change and not dry_run:
        # Determine reason
        if status_changed:
            reason = f"Status transition from {prev_status} to {new_status} (Score: {prev_score:.4f} -> {new_score:.4f})"
        else:
            direction = "increased" if new_score > prev_score else "decreased"
            reason = f"Verification score {direction} by {score_delta:.4f} (Score: {prev_score:.4f} -> {new_score:.4f})"

        rev_id = generate_revision_id(claim.id, new_status, new_score)
        revision = ClaimRevision(
            id=rev_id,
            claim_id=claim.id,
            previous_status=prev_status,
            new_status=new_status,
            previous_verification_score=prev_score,
            new_verification_score=new_score,
            reason=reason,
            trigger_event_id=trigger_event.id if trigger_event else None,
            trigger_evidence_id=trigger_evidence.id if trigger_evidence else None,
            created_at=now,
        )

        # Classify intelligence change
        if new_status == "contradicted":
            ch_type = "contradiction_detected"
            imp = 0.85
        elif new_status == "mixed" and prev_status not in ("mixed", "contradicted"):
            ch_type = "contradiction_detected"
            imp = 0.80
        elif new_status == "retracted":
            ch_type = "claim_retracted"
            imp = 0.95
        elif new_status == "superseded":
            ch_type = "claim_superseded"
            imp = 0.50
        elif new_score > prev_score:
            ch_type = "verification_strengthened"
            imp = 0.65 if status_changed else 0.40
        else:
            ch_type = "verification_weakened"
            imp = 0.70 if status_changed else 0.45

        ch_id = generate_change_id(claim.id, ch_type, f"{new_status}:{new_score:.4f}")
        change = IntelligenceChange(
            id=ch_id,
            entity_type="claim",
            entity_id=claim.id,
            change_type=ch_type,
            old_value=f"{prev_status} ({prev_score:.4f})",
            new_value=f"{new_status} ({new_score:.4f})",
            importance=imp,
            reason=reason,
            created_at=now,
        )

    updated_claim = claim.model_copy(
        update={
            "status": new_status,
            "verification_score": new_score,
            "last_verified_at": now,
            "staleness_score": staleness,
            "updated_at": now,
        }
    )

    if not dry_run:
        db.save_claim(updated_claim)
        if revision:
            db.insert_claim_revision(revision)
        if change:
            db.insert_intelligence_change(change)

    return updated_claim, revision, change


def sequence_cluster_releases(
    cluster_id: str,
    events: List[Event],
    db: Database,
    dry_run: bool = False,
) -> List[Relationship]:
    """
    Orders releases by published_at and establishes 'supersedes' relationships
    in chronological lineage.
    """
    releases = [e for e in events if e.source == "github" and e.event_type == "release" and e.published_at]
    if len(releases) < 2:
        return []

    # Sort chronologically ascending
    releases.sort(key=lambda r: r.published_at)

    new_relationships = []
    now = datetime.now(timezone.utc)

    for i in range(len(releases) - 1):
        older_rel = releases[i]
        newer_rel = releases[i + 1]

        rel_id = f"rel:supersedes:{newer_rel.id}:{older_rel.id}"
        rel = Relationship(
            id=rel_id,
            source_event_id=newer_rel.id,
            target_event_id=older_rel.id,
            relationship_type="supersedes",
            confidence=1.0,
            metadata={
                "older_tag": older_rel.metadata.get("tag_name"),
                "newer_tag": newer_rel.metadata.get("tag_name"),
            },
            created_at=now,
        )
        new_relationships.append(rel)
        if not dry_run:
            db.save_relationship(rel)

    return new_relationships


def reevaluate_cluster_maturity(
    cluster: StoryCluster,
    events: List[Event],
    db: Database,
    dry_run: bool = False,
) -> Tuple[TechnologyAssessment, Optional[TechnologyAssessmentRevision], Optional[IntelligenceChange]]:
    """
    Re-evaluates technology maturity, records stage progressions and regressions.
    """
    prev_assessment = db.get_technology_assessment(cluster.id)
    prev_stage = prev_assessment.maturity_stage if prev_assessment else "concept"
    prev_score = prev_assessment.assessment_score if prev_assessment else 0.0

    new_assessment = assess_technology_maturity(cluster, events)
    now = datetime.now(timezone.utc)

    stage_changed = prev_stage != new_assessment.maturity_stage
    score_delta = abs(new_assessment.assessment_score - prev_score)

    revision = None
    change = None

    if (stage_changed or score_delta >= 0.05) and not dry_run:
        # Determine whether maturity increased or decreased
        STAGES = ["concept", "research", "prototype", "experimental", "early_adoption", "production_candidate", "established"]
        prev_idx = STAGES.index(prev_stage) if prev_stage in STAGES else 0
        new_idx = STAGES.index(new_assessment.maturity_stage) if new_assessment.maturity_stage in STAGES else 0

        if new_idx >= prev_idx:
            ch_type = "maturity_increased"
            reason = f"Technology maturity advanced from {prev_stage} to {new_assessment.maturity_stage} (Score: {new_assessment.assessment_score:.4f})"
            imp = 0.75
        else:
            ch_type = "maturity_decreased"
            reason = f"Technology maturity regressed from {prev_stage} to {new_assessment.maturity_stage} (Score: {new_assessment.assessment_score:.4f})"
            imp = 0.90

        rev_id = generate_tech_rev_id(cluster.id, new_assessment.maturity_stage, new_assessment.assessment_score)
        revision = TechnologyAssessmentRevision(
            id=rev_id,
            cluster_id=cluster.id,
            previous_stage=prev_stage,
            new_stage=new_assessment.maturity_stage,
            previous_score=prev_score,
            new_score=new_assessment.assessment_score,
            reason=reason,
            created_at=now,
        )

        ch_id = generate_change_id(cluster.id, ch_type, new_assessment.maturity_stage)
        change = IntelligenceChange(
            id=ch_id,
            entity_type="cluster",
            entity_id=cluster.id,
            change_type=ch_type,
            old_value=f"{prev_stage} ({prev_score:.4f})",
            new_value=f"{new_assessment.maturity_stage} ({new_assessment.assessment_score:.4f})",
            importance=imp,
            reason=reason,
            created_at=now,
        )

        db.insert_technology_assessment_revision(revision)
        db.insert_intelligence_change(change)

    if not dry_run:
        db.save_technology_assessment(new_assessment)

    return new_assessment, revision, change


def update_technology_state(
    cluster: StoryCluster,
    events: List[Event],
    claims: List[Claim],
    db: Database,
    dry_run: bool = False,
) -> TechnologyState:
    """
    Computes a comprehensive TechnologyState snapshot for the cluster.
    """
    now = datetime.now(timezone.utc)

    # Activity signal and latest release
    latest_event_at = None
    latest_release_tag = None

    for e in events:
        t = e.published_at or e.discovered_at
        if t:
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if latest_event_at is None or t > latest_event_at:
                latest_event_at = t

        if e.source == "github" and e.event_type == "release":
            tag = e.metadata.get("tag_name") or e.title
            if not latest_release_tag:
                latest_release_tag = tag

    # Current status
    if latest_event_at:
        days_idle = (now - latest_event_at).total_seconds() / 86400.0
        if days_idle <= 30:
            current_status = "active"
        elif days_idle <= 90:
            current_status = "slowing"
        else:
            current_status = "inactive"
    else:
        current_status = "unknown"

    active_count = sum(1 for c in claims if c.is_current)
    sup_count = sum(1 for c in claims if c.status in ("supported", "strongly_supported"))
    contra_count = sum(1 for c in claims if c.status in ("contradicted", "mixed"))
    super_count = sum(1 for c in claims if c.status == "superseded")

    risk = calculate_technology_risk(cluster, events, claims)

    # Determine trend
    if any(c.status == "retracted" for c in claims):
        trend = "retracted"
    elif contra_count > 0:
        trend = "mixed" if sup_count > 0 else "weakening"
    elif any(c.status == "strongly_supported" for c in claims):
        trend = "strengthening"
    elif super_count > 0 and active_count == 0:
        trend = "superseded"
    else:
        trend = "stable"

    state = TechnologyState(
        cluster_id=cluster.id,
        current_status=current_status,
        latest_event_at=latest_event_at,
        latest_release=latest_release_tag,
        latest_claim_revision_at=now,
        active_claim_count=active_count,
        supported_claim_count=sup_count,
        contradicted_claim_count=contra_count,
        superseded_claim_count=super_count,
        risk_score=risk,
        trend=trend,
        updated_at=now,
    )

    if not dry_run:
        db.save_technology_state(state)

    return state
