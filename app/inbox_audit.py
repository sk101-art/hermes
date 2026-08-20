import sys
from collections import Counter
from datetime import datetime, timezone

from app.inbox.generator import generate_daily_inbox
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_inbox_audit() -> None:
    db = Database()

    print("=" * 65)
    print("HERMES — DAILY INBOX AUDIT REPORT")
    print("=" * 65)

    all_inbox = db.get_all_inbox_items(limit=1000)
    state_counts = Counter(it.state for it in all_inbox)
    starred_count = sum(1 for it in all_inbox if it.is_starred)

    # Run preview evaluation to get rejection reasons
    preview_records = generate_daily_inbox(db=db, preview=True)
    total_candidates = len(preview_records)
    rejection_counter = Counter()

    for c in preview_records:
        if c.get("rejection_reason"):
            rejection_counter[c["rejection_reason"]] += 1
        elif not c.get("selected"):
            rejection_counter["suppressed_by_cap"] += 1

    print(f"\nINBOX STATE SUMMARY:")
    print(f"  - Total Candidates Evaluated:  {total_candidates:>5}")
    print(f"  - Active (Unseen):             {state_counts.get('unseen', 0):>5}")
    print(f"  - Active (Seen):               {state_counts.get('seen', 0):>5}")
    print(f"  - Active (Opened):             {state_counts.get('opened', 0):>5}")
    print(f"  - Active (Starred):            {starred_count:>5}")
    print(f"  - Suppressed:                  {state_counts.get('suppressed', 0):>5}")
    print(f"  - Expired:                     {state_counts.get('expired', 0):>5}")
    print(f"  - Archived / Dismissed:        {state_counts.get('archived', 0):>5}")

    print(f"\nCANDIDATE REJECTION BREAKDOWN:")
    for reason, count in rejection_counter.most_common():
        print(f"  - {reason:<25}: {count:>5}")

    active_items = db.get_active_inbox_items(limit=20)
    print(f"\nTOP ACTIVE INBOX ITEMS ({len(active_items)}):")
    print("-" * 65)
    for idx, it in enumerate(active_items, 1):
        print(f"{idx:02d}. [{it.inbox_score:.2f}] [{it.state.upper()}] \"{it.title[:65]}\"")
        print(f"    Section: {it.section} | Type: {it.item_type}")
        if it.reason_codes:
            print(f"    Why: {', '.join(it.reason_codes[:4])}")
        print()

    print("=" * 65)


if __name__ == "__main__":
    run_inbox_audit()
