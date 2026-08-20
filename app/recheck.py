import argparse
import sys
import time

from app.evidence.recheck import populate_recheck_queue, process_recheck_queue
from app.storage.db import Database


def run_recheck(dry_run: bool = False, refresh_sources: bool = False, limit: int = None) -> None:
    db = Database()
    print("=" * 65)
    print("HERMES — RECHECK QUEUE & RE-EVALUATION RUNNER" + (" [DRY RUN]" if dry_run else ""))
    print("=" * 65)

    if refresh_sources:
        print("Refreshing sources before recheck...")
        from app.main import run_pipeline
        run_pipeline()

    # Ensure queue has pending items
    pending = db.get_pending_recheck_items(limit=limit)
    if not pending:
        print("Recheck queue is empty. Populating from current claims...")
        populate_recheck_queue(db, dry_run=dry_run)
        pending = db.get_pending_recheck_items(limit=limit)

    print(f"Processing {len(pending)} pending items in recheck queue...\n")

    results = process_recheck_queue(db, dry_run=dry_run, limit=limit)

    for idx, (item, claim, outcome) in enumerate(results[:25], 1):
        claim_text = f"\"{claim.claim_text[:55]}...\"" if claim else "[Entity: " + item.entity_id + "]"
        print(f"[{idx:02d}] Priority: {item.priority:.2f} | {item.reason}")
        print(f"     Target: {item.entity_type} {item.entity_id}")
        if claim:
            print(f"     Claim:  {claim_text}")
            print(f"     Status: {claim.status} (Score: {claim.verification_score:.4f})")
        print(f"     Result: {outcome}")
        print("-" * 65)

    if len(results) > 25:
        print(f"... and {len(results) - 25} more items processed.")

    print("\n" + "=" * 65)
    print("RECHECK SUMMARY")
    print("=" * 65)
    print(f"  Items Processed:   {len(results):>5}")
    print(f"  Dry Run:           {str(dry_run):>5}")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Longitudinal Recheck Runner")
    parser.add_argument("--dry-run", action="store_true", help="Preview recheck candidates without mutating database")
    parser.add_argument("--refresh-sources", action="store_true", help="Run ingestion adapters before re-evaluating")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of items to recheck")
    args = parser.parse_args()
    run_recheck(dry_run=args.dry_run, refresh_sources=args.refresh_sources, limit=args.limit)
