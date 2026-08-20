import argparse
import sys
import time
from datetime import datetime, timezone

from app.inbox.generator import generate_daily_inbox
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_inbox_generate(lookback: int = 36, ttl: int = 24, rebuild_today: bool = False, preview: bool = False) -> None:
    start_time = time.time()
    db = Database()

    print("=" * 65)
    print("HERMES — DAILY INBOX GENERATOR")
    if preview:
        print("MODE: PREVIEW (No Database Mutations)")
    elif rebuild_today:
        print("MODE: REBUILD TODAY (Active/Suppressed Re-evaluation)")
    print("=" * 65)

    res = generate_daily_inbox(
        db=db,
        lookback_hours=lookback,
        ttl_hours=ttl,
        rebuild_today=rebuild_today,
        preview=preview,
    )

    duration = time.time() - start_time

    if preview:
        candidate_records = res
        print(f"\nEvaluated {len(candidate_records)} candidates:")
        eligible = [c for c in candidate_records if not c.get("rejection_reason")]
        rejected = [c for c in candidate_records if c.get("rejection_reason")]
        print(f"  - Eligible:     {len(eligible):>4}")
        print(f"  - Rejected:     {len(rejected):>4}")

        print("\nTOP CANDIDATE RANKING (PREVIEW):")
        print("-" * 65)
        for idx, c in enumerate(candidate_records[:40], 1):
            cl = c["cluster"]
            sel = "YES" if c.get("selected") else "NO"
            rej = f"({c.get('rejection_reason')})" if c.get("rejection_reason") else ""
            bd = c.get("breakdown", {})
            print(f"{idx:02d}. [{c['score']:.2f}] [Selected: {sel} {rej}] \"{cl.canonical_title[:60]}\"")
            print(f"    Section: {c['section']} | Match: {c['match_type']}")
            print(f"    Score: Cluster: {bd.get('cluster_score', 0):.2f} | Nov: {bd.get('novelty', 0):.2f} | Proj: {bd.get('project_impact', 0):.2f} | Ver: {bd.get('verification', 0):.2f} | Chg: {bd.get('change_importance', 0):.2f}")
            if c.get("reasons"):
                print(f"    Why: {', '.join(c['reasons'][:3])}")
            print()
    else:
        items = res
        unseen_count = sum(1 for it in items if it.state == "unseen")
        starred_count = sum(1 for it in items if it.state == "starred")
        must_know_count = sum(1 for it in items if it.section == "must_know")
        project_rel_count = sum(1 for it in items if it.section == "project_relevant")
        corrections_count = sum(1 for it in items if it.section == "corrections_updates")

        print(f"\nGenerated {len(items)} active inbox items for Today:")
        print(f"  - Must Know:             {must_know_count:>4}")
        print(f"  - Project Relevant:      {project_rel_count:>4}")
        print(f"  - Corrections/Updates:   {corrections_count:>4}")
        print(f"  - Unseen:                {unseen_count:>4}")
        print(f"  - Starred:               {starred_count:>4}")
        print(f"  - Generation Duration: {duration:>6.2f}s")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Daily Inbox Generator")
    parser.add_argument("--lookback", type=int, default=36, help="Lookback window in hours")
    parser.add_argument("--ttl", type=int, default=24, help="Inbox item TTL in hours")
    parser.add_argument("--rebuild-today", action="store_true", help="Rebuild today's active/suppressed items")
    parser.add_argument("--preview", action="store_true", help="Preview candidate ranking without saving")
    args = parser.parse_args()
    run_inbox_generate(lookback=args.lookback, ttl=args.ttl, rebuild_today=args.rebuild_today, preview=args.preview)
