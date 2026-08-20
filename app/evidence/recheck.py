import hashlib
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.evidence.reevaluate import reevaluate_claim
from app.evidence.staleness import calculate_claim_staleness
from app.models.schemas import Claim, RecheckQueueItem, StoryCluster
from app.storage.db import Database


def calculate_recheck_priority(
    claim: Claim,
    cluster: Optional[StoryCluster] = None,
    now: Optional[datetime] = None,
) -> Tuple[float, str]:
    """
    Computes a deterministic recheck priority score [0.0 - 1.0] and reason.
    High priority: performance claims, mixed/contradicted claims, stale claims, weakly supported claims.
    Low priority: stable permanent metadata / DOI facts.
    """
    if not now:
        now = datetime.now(timezone.utc)

    # 1. Contradictions or mixed stances
    if claim.status in ("contradicted", "mixed"):
        return 0.92, "Contradicted or mixed claim requiring re-verification"

    # 2. Performance claims
    if claim.claim_type == "performance" or getattr(claim, "assertion_level", "") == "performance_claim":
        staleness = calculate_claim_staleness(claim, now)
        if staleness > 0.50:
            return 0.88, "Stale self-reported performance claim awaiting validation"
        return 0.82, "Self-reported performance claim awaiting independent benchmarks"

    # 3. High staleness claims
    staleness = calculate_claim_staleness(claim, now)
    if staleness >= 0.70:
        return 0.76, f"Stale {claim.claim_type} claim (staleness: {staleness:.2f})"

    # 4. Weakly supported or unverified claims
    if claim.status in ("weakly_supported", "unverified"):
        return 0.65, f"Weakly supported {claim.claim_type} claim awaiting corroboration"

    # 5. Research claims awaiting replication
    if claim.claim_type == "research_result" or getattr(claim, "assertion_level", "") == "research_claim":
        return 0.48, "Research claim awaiting peer review / reproduction"

    # 6. Aging claims
    if staleness >= 0.30:
        return 0.40, f"Aging {claim.claim_type} claim (staleness: {staleness:.2f})"

    # 7. Stable facts (DOI, releases, repo metadata)
    if claim.claim_type == "scholarly_identity" or "doi" in claim.metadata:
        return 0.10, "Stable scholarly identity fact"

    return 0.30, f"Routine {claim.claim_type} claim check"


def populate_recheck_queue(db: Database, dry_run: bool = False) -> List[RecheckQueueItem]:
    """
    Scans all claims and generates prioritized recheck queue items.
    """
    claims = db.get_all_claims()
    now = datetime.now(timezone.utc)
    items = []

    for c in claims:
        prio, reason = calculate_recheck_priority(c, now=now)
        item_id = f"recheck:{c.id}"
        item = RecheckQueueItem(
            id=item_id,
            entity_type="claim",
            entity_id=c.id,
            reason=reason,
            priority=prio,
            status="pending",
            created_at=now,
        )
        items.append(item)
        if not dry_run:
            db.insert_recheck_queue_item(item)

    return items


def process_recheck_queue(
    db: Database,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> List[Tuple[RecheckQueueItem, Optional[Claim], Optional[str]]]:
    """
    Processes pending items from the recheck queue using stored Evidence.
    """
    pending = db.get_pending_recheck_items(limit=limit)
    now = datetime.now(timezone.utc)
    results = []

    for item in pending:
        if item.entity_type == "claim":
            claim = db.get_claim(item.entity_id)
            if not claim:
                if not dry_run:
                    db.update_recheck_item_status(item.id, "skipped", last_checked_at=now)
                results.append((item, None, "Claim not found"))
                continue

            evidence_list = db.get_evidence_by_claim(claim.id)
            updated_claim, rev, ch = reevaluate_claim(
                claim=claim,
                evidence_list=evidence_list,
                db=db,
                dry_run=dry_run,
            )

            outcome = "Re-evaluated (no change)"
            if rev:
                outcome = f"Revision created: {rev.reason}"

            if not dry_run:
                db.update_recheck_item_status(item.id, "completed", last_checked_at=now)

            results.append((item, updated_claim, outcome))

    return results
