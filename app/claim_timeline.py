import sys
from datetime import datetime, timezone
from app.storage.db import Database


def show_claim_timeline(claim_id: str) -> None:
    db = Database()
    claim = db.get_claim(claim_id)
    if not claim:
        print(f"Error: Claim with ID '{claim_id}' not found.")
        sys.exit(1)

    revisions = db.get_claim_revisions(claim_id)
    evidence_list = db.get_evidence_by_claim(claim_id)

    print("=" * 70)
    print("HERMES — CLAIM LONGITUDINAL TIMELINE")
    print("=" * 70)

    print(f"\nCLAIM ID: {claim.id}")
    print(f"Assertion Level: {claim.assertion_level.upper()} | Type: {claim.claim_type}")
    print(f"Statement: \"{claim.claim_text}\"")
    print(f"Self-Reported: {claim.self_reported} | Current: {claim.is_current}")

    print("\nCURRENT STATUS & VERIFICATION:")
    print(f"  Status:             {claim.status.upper()}")
    print(f"  Verification Score: {claim.verification_score:.4f}")
    print(f"  Staleness Score:    {claim.staleness_score:.4f}")
    if claim.last_verified_at:
        print(f"  Last Verified At:   {claim.last_verified_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    print("\nCHRONOLOGICAL TIMELINE:")
    print("-" * 70)

    timeline_items = []

    # 1. Initial creation
    created_dt = claim.created_at
    timeline_items.append((
        created_dt,
        "CLAIM CREATED",
        f"Initial status: {claim.status} (Score: {claim.verification_score:.4f})"
    ))

    # 2. Revisions
    for rev in revisions:
        timeline_items.append((
            rev.created_at,
            "CLAIM REVISION",
            f"{rev.previous_status} -> {rev.new_status} | Score: {rev.previous_verification_score:.4f} -> {rev.new_verification_score:.4f}\n     Reason: {rev.reason}"
        ))

    # 3. Evidence arrivals
    for ev in evidence_list:
        timeline_items.append((
            ev.created_at,
            f"EVIDENCE [{ev.source.upper()}] {ev.evidence_type}",
            f"Stance: {ev.stance.upper()} | Quality: {ev.quality_score:.2f} | Indep: {ev.independence_score:.2f}\n     Excerpt: \"{ev.excerpt[:90]}...\"\n     URL: {ev.url}"
        ))

    # Sort chronological
    timeline_items.sort(key=lambda x: x[0])

    for dt, header, detail in timeline_items:
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{date_str}] {header}")
        print(f"  {detail}")
        print("-" * 70)

    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.claim_timeline <claim_id>")
        sys.exit(1)
    show_claim_timeline(sys.argv[1])
