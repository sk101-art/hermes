import statistics
import sys
from collections import Counter

# Safe UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.storage.db import Database


def run_audit(db_path: str = "data/tech_intel.db"):
    db = Database(db_path=db_path)

    claims = db.get_all_claims()
    evidence_list = db.get_all_evidence()
    assessments = db.get_all_technology_assessments()

    print("=" * 65)
    print("HERMES — CLAIMS, EVIDENCE & VERIFICATION AUDIT")
    print("=" * 65)

    total_claims = len(claims)
    print(f"\nTOTAL CLAIMS: {total_claims}")

    if total_claims == 0:
        print("No claims found in database. Run 'python -m app.claims_backfill' first.")
        db.close()
        return

    # 1. Claims by Type
    type_counts = Counter(c.claim_type for c in claims)
    print("\nCLAIMS BY TYPE:")
    for ctype, count in type_counts.most_common():
        print(f"  - {ctype:<25} {count:>5} ({count/total_claims*100:>5.1f}%)")

    # 2. Claims by Status
    status_counts = Counter(c.status for c in claims)
    print("\nCLAIMS BY STATUS:")
    for st in ["unverified", "weakly_supported", "supported", "strongly_supported", "mixed", "contradicted", "superseded", "retracted"]:
        count = status_counts.get(st, 0)
        if count > 0 or st in ("unverified", "weakly_supported", "supported", "strongly_supported", "mixed", "contradicted"):
            print(f"  - {st:<25} {count:>5} ({count/total_claims*100:>5.1f}%)")

    # 3. Evidence Coverage per Claim
    single_ev = 0
    multi_ev = 0
    single_src = 0
    multi_src = 0
    contra_claims = 0

    for c in claims:
        evs = db.get_evidence_by_claim(c.id)
        if len(evs) == 1:
            single_ev += 1
        elif len(evs) > 1:
            multi_ev += 1

        sources = {e.source for e in evs}
        if len(sources) == 1:
            single_src += 1
        elif len(sources) > 1:
            multi_src += 1

        if any(e.stance == "contradicts" for e in evs):
            contra_claims += 1

    print("\nEVIDENCE DEPTH & SOURCE DIVERSITY:")
    print(f"  - Claims with 1 evidence item:         {single_ev:>5} ({single_ev/total_claims*100:>5.1f}%)")
    print(f"  - Claims with multiple evidence items: {multi_ev:>5} ({multi_ev/total_claims*100:>5.1f}%)")
    print(f"  - Claims with 1 source:                {single_src:>5} ({single_src/total_claims*100:>5.1f}%)")
    print(f"  - Claims with multi-source evidence:   {multi_src:>5} ({multi_src/total_claims*100:>5.1f}%)")
    print(f"  - Claims with contradictory evidence:  {contra_claims:>5} ({contra_claims/total_claims*100:>5.1f}%)")

    # 4. Verification Score Statistics
    v_scores = [c.verification_score for c in claims]
    avg_v = sum(v_scores) / len(v_scores) if v_scores else 0.0
    med_v = statistics.median(v_scores) if v_scores else 0.0
    min_v = min(v_scores) if v_scores else 0.0
    max_v = max(v_scores) if v_scores else 0.0

    print("\nVERIFICATION SCORE METRICS:")
    print(f"  - Average Verification Score:          {avg_v:>5.4f}")
    print(f"  - Median Verification Score:           {med_v:>5.4f}")
    print(f"  - Lowest Verification Score:           {min_v:>5.4f}")
    print(f"  - Highest Verification Score:          {max_v:>5.4f}")

    # 5. Evidence by Type
    total_ev = len(evidence_list)
    print(f"\nTOTAL EVIDENCE RECORDS: {total_ev}")
    ev_type_counts = Counter(e.evidence_type for e in evidence_list)
    print("EVIDENCE BY TYPE:")
    for etype, count in ev_type_counts.most_common():
        print(f"  - {etype:<25} {count:>5} ({count/total_ev*100:>5.1f}%)")

    # 6. Technology Maturity Distribution
    total_assessments = len(assessments)
    print(f"\nTECHNOLOGY ASSESSMENTS: {total_assessments}")
    mat_counts = Counter(a.maturity_stage for a in assessments)
    print("MATURITY STAGE DISTRIBUTION:")
    for stage in ["concept", "research", "prototype", "experimental", "early_adoption", "production_candidate", "established"]:
        cnt = mat_counts.get(stage, 0)
        print(f"  - {stage:<25} {cnt:>5} ({cnt/max(1, total_assessments)*100:>5.1f}%)")

    print("=" * 65)
    db.close()


if __name__ == "__main__":
    run_audit()
