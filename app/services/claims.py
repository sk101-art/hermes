from typing import Any, Dict, List, Optional

from app.evidence.verification import is_independent_evidence
from app.models.schemas import Claim, Evidence
from app.services.schemas import ClaimDetail, ClaimRevisionDetail, EvidenceDetail
from app.storage.db import Database


def get_claim(claim_id: str, db: Optional[Database] = None) -> Optional[ClaimDetail]:
    """Retrieves full claim details, progressive evidence provenance, and revision history."""
    if db is None:
        db = Database()

    if not claim_id or not isinstance(claim_id, str) or not claim_id.strip():
        return None

    c = db.get_claim(claim_id.strip())
    if not c:
        return None

    evidence_records = db.get_evidence_by_claim(c.id)
    revisions = db.get_claim_revisions(c.id)

    ev_list: List[EvidenceDetail] = []
    for ev in evidence_records:
        is_ind = is_independent_evidence(ev)
        ev_list.append(
            EvidenceDetail(
                evidence_id=ev.id,
                claim_id=ev.claim_id,
                event_id=ev.event_id,
                source=ev.source,
                evidence_type=ev.evidence_type,
                evidence_class=ev.evidence_class,
                stance=ev.stance,
                quality_score=round(ev.quality_score, 4),
                independence_score=round(ev.independence_score, 4),
                reproducibility_score=round(ev.reproducibility_score, 4),
                is_independent=is_ind,
                url=ev.url,
                excerpt=ev.excerpt or getattr(ev, "text", "") or None,
                observed_at=ev.observed_at.isoformat() if getattr(ev, "observed_at", None) else None,
                created_at=ev.created_at.isoformat() if getattr(ev, "created_at", None) else None,
                id=ev.id,
                type=ev.evidence_type,
            )
        )

    rev_list: List[ClaimRevisionDetail] = []
    for r in revisions:
        rev_list.append(
            ClaimRevisionDetail(
                revision_id=r.id,
                id=r.id,
                claim_id=r.claim_id,
                previous_status=r.previous_status,
                new_status=r.new_status,
                previous_verification_score=round(r.previous_verification_score, 4) if r.previous_verification_score is not None else None,
                new_verification_score=round(r.new_verification_score, 4) if r.new_verification_score is not None else 0.0,
                reason=r.reason or "",
                trigger_event_id=getattr(r, "trigger_event_id", None),
                trigger_evidence_id=getattr(r, "trigger_evidence_id", None),
                revised_at=r.created_at.isoformat() if hasattr(r, "created_at") and r.created_at else "",
                old_status=r.previous_status,
                old_verification_score=round(r.previous_verification_score, 4) if r.previous_verification_score is not None else None,
            )
        )

    return ClaimDetail(
        claim_id=c.id,
        claim_text=c.claim_text,
        claim_type=c.claim_type,
        assertion_level=c.assertion_level,
        status=c.status,
        verification_score=round(c.verification_score, 4) if c.verification_score is not None else None,
        staleness_score=round(c.staleness_score, 4) if c.staleness_score is not None else 0.0,
        is_self_reported=bool(c.self_reported),
        cluster_id=c.cluster_id,
        evidence_count=len(evidence_records),
        evidence=ev_list,
        revisions=rev_list,
        id=c.id,
        text=c.claim_text,
        type=c.claim_type,
    )


def get_cluster_claims(
    cluster_id: str,
    current_only: bool = False,
    db: Optional[Database] = None,
) -> List[ClaimDetail]:
    """Retrieves all claims for a cluster with full evidence provenance."""
    if db is None:
        db = Database()

    if not cluster_id or not isinstance(cluster_id, str) or not cluster_id.strip():
        return []

    claims = db.get_claims_by_cluster(cluster_id.strip(), current_only=current_only)
    details: List[ClaimDetail] = []
    for c in claims:
        cd = get_claim(c.id, db=db)
        if cd:
            details.append(cd)
    return details
