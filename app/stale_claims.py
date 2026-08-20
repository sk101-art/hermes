from datetime import datetime, timezone
from app.evidence.staleness import calculate_claim_staleness, classify_staleness_tier
from app.storage.db import Database


def run_stale_claims_audit() -> None:
    db = Database()
    claims = db.get_all_claims()
    now = datetime.now(timezone.utc)

    fresh = []
    aging = []
    stale = []

    for c in claims:
        staleness = calculate_claim_staleness(c, now)
        tier = classify_staleness_tier(staleness)
        if tier == "fresh":
            fresh.append((c, staleness))
        elif tier == "aging":
            aging.append((c, staleness))
        else:
            stale.append((c, staleness))

    total = len(claims) if claims else 1

    print("=" * 70)
    print("HERMES — CLAIM STALENESS AUDIT")
    print("=" * 70)

    print(f"\nTOTAL CLAIMS AUDITED: {len(claims)}")
    print(f"  - Fresh Claims (< 0.30):    {len(fresh):>4} ({len(fresh)/total*100:>5.1f}%)")
    print(f"  - Aging Claims (0.30-0.70): {len(aging):>4} ({len(aging)/total*100:>5.1f}%)")
    print(f"  - Stale Claims (> 0.70):    {len(stale):>4} ({len(stale)/total*100:>5.1f}%)")

    print("\nSAMPLE AGING & STALE CLAIMS:")
    print("-" * 70)

    sample = (stale + aging)[:20]
    if not sample:
        sample = fresh[:10]

    for idx, (c, st_score) in enumerate(sample, 1):
        tier = classify_staleness_tier(st_score)
        last_ver = c.last_verified_at.strftime("%Y-%m-%d") if c.last_verified_at else c.created_at.strftime("%Y-%m-%d")
        print(f"[{idx:02d}] {c.id} | [{c.claim_type.upper()}] Tier: {tier.upper()} (Staleness: {st_score:.4f})")
        print(f"     \"{c.claim_text[:65]}...\"")
        print(f"     Status: {c.status} (V: {c.verification_score:.4f}) | Last Verified: {last_ver}")
        print("-" * 70)

    print("=" * 70)


if __name__ == "__main__":
    run_stale_claims_audit()
