import argparse
import sys
from datetime import datetime, timezone
from typing import Dict

# Safe UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.evidence.claims import extract_claims_for_cluster
from app.evidence.maturity import assess_technology_maturity
from app.evidence.verification import compute_verification
from app.storage.db import Database


def run_claims_backfill(rebuild: bool = False, db_path: str = "data/tech_intel.db"):
    db = Database(db_path=db_path)

    if rebuild:
        print("Clearing existing claims, evidence, and technology assessments...", flush=True)
        db.clear_claims_and_evidence()

    clusters = db.get_all_clusters()
    total_clusters = len(clusters)

    print("=" * 60, flush=True)
    print("HERMES — CLAIM & EVIDENCE GRAPH BACKFILL", flush=True)
    print("=" * 60, flush=True)
    print(f"Processing {total_clusters} StoryClusters...", flush=True)

    start_time = datetime.now(timezone.utc)
    claims_created = 0
    evidence_created = 0
    dup_claims_prevented = 0
    dup_evidence_prevented = 0
    assessments_created = 0

    for cluster in clusters:
        events = db.get_cluster_events(cluster.id)
        if not events:
            continue

        # 1. Technology Maturity Assessment
        assessment = assess_technology_maturity(cluster, events)
        db.save_technology_assessment(assessment)
        assessments_created += 1

        # 2. Extract Claims & Associated Evidence
        claims_with_evidence = extract_claims_for_cluster(cluster, events)

        for claim, evidence_list in claims_with_evidence:
            # Score verification & status
            v_score, status = compute_verification(claim, evidence_list)
            claim.verification_score = v_score
            claim.status = status

            if db.claim_exists(claim.id):
                dup_claims_prevented += 1
                db.save_claim(claim)  # update status/score
            else:
                db.save_claim(claim)
                claims_created += 1

            for ev in evidence_list:
                if db.evidence_exists(ev.id):
                    dup_evidence_prevented += 1
                    db.save_evidence(ev)
                else:
                    db.save_evidence(ev)
                    evidence_created += 1

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()

    print("\n" + "=" * 60, flush=True)
    print("BACKFILL & EVIDENCE GRAPH SUMMARY", flush=True)
    print("=" * 60, flush=True)
    print(f"  StoryClusters Processed:        {total_clusters:>6}", flush=True)
    print(f"  Technology Assessments Created: {assessments_created:>6}", flush=True)
    print(f"  Claims Created:                 {claims_created:>6}", flush=True)
    print(f"  Evidence Records Created:       {evidence_created:>6}", flush=True)
    print(f"  Duplicate Claims Prevented:     {dup_claims_prevented:>6}", flush=True)
    print(f"  Duplicate Evidence Prevented:   {dup_evidence_prevented:>6}", flush=True)
    print(f"  Duration:                       {duration:>5.2f}s", flush=True)
    print("=" * 60, flush=True)

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Claim and Evidence Graph Backfill")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild claims and evidence from scratch")
    args = parser.parse_args()

    run_claims_backfill(rebuild=args.rebuild)
