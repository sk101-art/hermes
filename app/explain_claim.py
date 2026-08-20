import sys

# Safe UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.storage.db import Database


def explain(claim_id: str, db_path: str = "data/tech_intel.db"):
    db = Database(db_path=db_path)

    claim = db.get_claim(claim_id)
    if not claim:
        print(f"Error: Claim '{claim_id}' not found in database.")
        db.close()
        return

    cluster = db.get_cluster(claim.cluster_id)
    assessment = db.get_technology_assessment(claim.cluster_id)
    evidence_list = db.get_evidence_by_claim(claim_id)

    print("=" * 65)
    print("HERMES — CLAIM EXPLANATION & EVIDENCE PROVENANCE")
    print("=" * 65)

    print("\nCLAIM DETAILS")
    print(f"  ID:                 {claim.id}")
    print(f"  Type:               {claim.claim_type}")
    print(f"  Subject:            {claim.subject}")
    print(f"  Predicate:          {claim.predicate}")
    print(f"  Object:             {claim.object}")
    print(f"  Self-Reported:      {'YES' if claim.self_reported else 'NO'}")
    print(f"\nSTATEMENT:\n  \"{claim.claim_text}\"")

    print("\nSTATUS & VERIFICATION")
    print(f"  Status:             {claim.status.upper()}")
    print(f"  Verification Score: {claim.verification_score:.4f}")
    print(f"  Confidence:         {claim.confidence:.2f}")

    if assessment:
        print("\nTECHNOLOGY MATURITY")
        print(f"  Stage:              {assessment.maturity_stage.upper()}")
        print(f"  Assessment Score:   {assessment.assessment_score:.4f}")
        print(f"    - Implementation: {assessment.implementation_score:.2f}")
        print(f"    - Adoption:       {assessment.adoption_score:.2f}")
        print(f"    - Research:       {assessment.research_score:.2f}")
        print(f"    - Reproducibility:{assessment.reproducibility_score:.2f}")
        print(f"    - Community:      {assessment.community_score:.2f}")

    print(f"\nEVIDENCE PROVENANCE ({len(evidence_list)} records):")
    print("-" * 65)

    for idx, ev in enumerate(evidence_list, 1):
        print(f"[{idx:02d}] {ev.id} | [{ev.source.upper()}] {ev.evidence_type}")
        print(f"     Stance:          {ev.stance.upper()}")
        print(f"     Class:           {ev.evidence_class}")
        print(f"     Quality:         {ev.quality_score:.2f}")
        print(f"     Independence:    {ev.independence_score:.2f}")
        print(f"     Reproducibility: {ev.reproducibility_score:.2f}")
        if ev.url:
            print(f"     URL:             {ev.url}")
        if ev.excerpt:
            short_exc = ev.excerpt.replace("\n", " ")[:200]
            print(f"     Excerpt:         \"{short_exc}...\"")
        print("-" * 65)

    print("=" * 65)
    db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.explain_claim <claim_id>")
        sys.exit(1)
    explain(sys.argv[1])
