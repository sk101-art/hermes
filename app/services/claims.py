from typing import Any, Dict, List, Optional

from app.models.schemas import Claim, Evidence
from app.services.schemas import ClaimDetail
from app.storage.db import Database


def get_claim(claim_id: str, db: Optional[Database] = None) -> Optional[ClaimDetail]:
    """Retrieves full claim details, evidence provenance, and revision history."""
    if db is None:
        db = Database()

    if not claim_id:
        return None

    c = db.get_claim(claim_id.strip())
    if not c:
        return None

    evidence_records = db.get_evidence_by_claim(c.id)
    revisions = db.get_claim_revisions(c.id)

    ev_list = []
    for ev in evidence_records:
        ev_list.append({
            "id": ev.id,
            "source": ev.source,
            "type": ev.evidence_type,
            "evidence_class": ev.evidence_class,
            "stance": ev.stance,
            "quality_score": round(ev.quality_score, 4),
            "independence_score": round(ev.independence_score, 4),
            "reproducibility_score": round(ev.reproducibility_score, 4),
            "is_independent": ev.independence_score >= 0.60 or ev.evidence_class == "independent",
            "url": ev.url,
            "excerpt": ev.excerpt,
        })

    rev_list = []
    for r in revisions:
        rev_list.append({
            "id": r.id,
            "revised_at": r.revised_at.isoformat(),
            "reason": r.reason,
            "old_verification_score": round(r.old_verification_score, 4),
            "new_verification_score": round(r.new_verification_score, 4),
            "old_status": r.old_status,
            "new_status": r.new_status,
            "old_staleness_score": round(r.old_staleness_score, 4),
            "new_staleness_score": round(r.new_staleness_score, 4),
        })

    return ClaimDetail(
        claim_id=c.id,
        claim_text=c.claim_text,
        claim_type=c.claim_type,
        assertion_level=c.assertion_level,
        status=c.status,
        verification_score=round(c.verification_score, 4),
        staleness_score=round(c.staleness_score, 4),
        is_self_reported=bool(c.self_reported),
        cluster_id=c.cluster_id,
        evidence_count=len(evidence_records),
        evidence=ev_list,
        revisions=rev_list,
    )


def get_cluster_claims(
    cluster_id: str,
    current_only: bool = False,
    db: Optional[Database] = None,
) -> List[ClaimDetail]:
    """Retrieves all claims for a cluster with full evidence provenance."""
    if db is None:
        db = Database()

    claims = db.get_claims_by_cluster(cluster_id, current_only=current_only)
    details = []
    for c in claims:
        cd = get_claim(c.id, db=db)
        if cd:
            details.append(cd)
    return details
