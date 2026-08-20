from datetime import datetime, timezone
from app.storage.db import Database


def run_changes_audit() -> None:
    db = Database()
    all_changes = db.get_all_intelligence_changes()
    changes_1d = db.get_recent_intelligence_changes(days=1)
    changes_7d = db.get_recent_intelligence_changes(days=7)

    print("=" * 70)
    print("HERMES — INTELLIGENCE CHANGES & TRANSITIONS AUDIT")
    print("=" * 70)

    print(f"\nCHANGE VOLUME:")
    print(f"  - Last 24 Hours:  {len(changes_1d):>4}")
    print(f"  - Last 7 Days:    {len(changes_7d):>4}")
    print(f"  - All Time:       {len(all_changes):>4}")

    # Breakdown by change type
    type_counts = {}
    for ch in all_changes:
        type_counts[ch.change_type] = type_counts.get(ch.change_type, 0) + 1

    print("\nCHANGES BY TYPE (ALL TIME):")
    for ctype in (
        "verification_strengthened",
        "verification_weakened",
        "contradiction_detected",
        "claim_superseded",
        "claim_retracted",
        "maturity_increased",
        "maturity_decreased",
        "new_release",
    ):
        cnt = type_counts.get(ctype, 0)
        pct = (cnt / len(all_changes) * 100) if all_changes else 0.0
        print(f"  - {ctype:<28} {cnt:>4} ({pct:>5.1f}%)")

    print("\nNOTABLE RECENT CHANGES:")
    print("-" * 70)

    for idx, ch in enumerate(all_changes[:20], 1):
        dt_str = ch.created_at.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{idx:02d}] {dt_str} | [{ch.change_type.upper()}] (Imp: {ch.importance:.2f})")
        print(f"     Target: {ch.entity_type} {ch.entity_id}")
        print(f"     Transition: {ch.old_value or 'None'} -> {ch.new_value or 'None'}")
        print(f"     Reason: {ch.reason}")
        print("-" * 70)

    if not all_changes:
        print("  No intelligence changes recorded yet.")

    print("=" * 70)


if __name__ == "__main__":
    run_changes_audit()
