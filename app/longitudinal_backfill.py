import argparse
import sys
import time
from datetime import datetime, timezone

from app.evidence.claims import extract_claims_for_cluster
from app.evidence.recheck import populate_recheck_queue
from app.evidence.reevaluate import reevaluate_claim, reevaluate_cluster_maturity, sequence_cluster_releases, update_technology_state
from app.storage.db import Database


def run_longitudinal_backfill(rebuild: bool = False) -> None:
    start_time = time.time()
    db = Database()

    print("=" * 60)
    print("HERMES — LONGITUDINAL VERIFICATION & STATE BACKFILL")
    print("=" * 60)

    if rebuild:
        print("Clearing longitudinal state (revisions, technology states, queue, changes)...")
        db.conn.execute("DELETE FROM claim_revisions")
        db.conn.execute("DELETE FROM technology_assessment_revisions")
        db.conn.execute("DELETE FROM technology_states")
        db.conn.execute("DELETE FROM recheck_queue")
        db.conn.execute("DELETE FROM intelligence_changes")
        db.conn.commit()

    clusters = db.get_all_clusters()
    print(f"Processing {len(clusters)} StoryClusters for longitudinal state...")

    claims_initialized = 0
    states_initialized = 0
    release_rels_created = 0

    now = datetime.now(timezone.utc)

    for cluster in clusters:
        events = db.get_cluster_events(cluster.id)
        claims = db.get_claims_by_cluster(cluster.id)

        # 1. Sequence releases if applicable
        rels = sequence_cluster_releases(cluster.id, events, db)
        release_rels_created += len(rels)

        # 2. Re-evaluate claims with assertion policies and staleness
        for claim in claims:
            evs = db.get_evidence_by_claim(claim.id)
            updated_claim, rev, change = reevaluate_claim(claim, evs, db)
            claims_initialized += 1

        # 3. Assess maturity and revisions
        reevaluate_cluster_maturity(cluster, events, db)

        # 4. Update TechnologyState snapshot
        update_technology_state(cluster, events, claims, db)
        states_initialized += 1

    # 5. Populate Recheck Queue
    print("Populating Recheck Queue...")
    queue_items = populate_recheck_queue(db)

    duration = time.time() - start_time
    print("\n" + "=" * 60)
    print("LONGITUDINAL BACKFILL SUMMARY")
    print("=" * 60)
    print(f"  StoryClusters Processed:         {len(clusters):>6}")
    print(f"  Claims Initialized/Verified:     {claims_initialized:>6}")
    print(f"  Technology States Initialized:   {states_initialized:>6}")
    print(f"  Release Sequence Relationships:  {release_rels_created:>6}")
    print(f"  Recheck Queue Entries Created:   {len(queue_items):>6}")
    print(f"  Duration:                      {duration:>6.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Longitudinal State Backfill")
    parser.add_argument("--rebuild", action="store_true", help="Clear previous revisions and queue before backfilling")
    args = parser.parse_args()
    run_longitudinal_backfill(rebuild=args.rebuild)
