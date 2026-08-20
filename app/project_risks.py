import sys
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def show_project_risks(project_name: str) -> None:
    db = Database()
    project = db.get_project_by_name(project_name)
    if not project:
        print(f"Error: Project '{project_name}' not found.")
        sys.exit(1)

    matches = db.get_project_matches(project.id)

    print("=" * 75)
    print(f"HERMES — PROJECT RISK & VULNERABILITY RADAR: '{project.name}'")
    print("=" * 75)

    risk_items = []
    for m in matches:
        claims = db.get_claims_by_cluster(m.entity_id)
        tech_state = db.get_technology_state(m.entity_id)
        cluster = db.get_cluster(m.entity_id)
        assessment = db.get_technology_assessment(m.entity_id)

        # 1. Contradicted or mixed claims
        contra_claims = [c for c in claims if c.status in ("contradicted", "mixed")]
        # 2. High risk score
        risk_score = tech_state.risk_score if tech_state else 0.25
        # 3. Weakly supported or regressions
        revisions = db.get_technology_assessment_revisions(m.entity_id)
        regressions = [r for r in revisions if "regressed" in r.reason.lower() or "decreased" in r.reason.lower()]

        if contra_claims or risk_score >= 0.50 or regressions or m.recommendation == "potential_risk":
            risk_items.append({
                "match": m,
                "cluster": cluster,
                "contra_claims": contra_claims,
                "risk_score": risk_score,
                "regressions": regressions,
                "stage": assessment.maturity_stage if assessment else "concept",
            })

    # Sort by risk score DESC
    risk_items.sort(key=lambda x: x["risk_score"], reverse=True)

    print(f"\nDETECTED RISK ITEMS: {len(risk_items)}\n")

    if not risk_items:
        print("  No active risks or contradictions detected for project dependencies / technologies.")

    for idx, item in enumerate(risk_items, 1):
        m = item["match"]
        c_title = item["cluster"].canonical_title if item["cluster"] else m.entity_id
        print(f"[{idx:02d}] Technology / Story: \"{c_title}\"")
        print(f"     Risk Score:    {item['risk_score']:.4f} | Stage: {item['stage'].upper()}")
        print(f"     Recommendation:{m.recommendation.upper()} (Impact: {m.impact_score:.2f})")

        if item["contra_claims"]:
            print("     Contradicted / Mixed Claims:")
            for cc in item["contra_claims"]:
                print(f"       - [{cc.status.upper()}] \"{cc.claim_text}\" (Score: {cc.verification_score:.4f})")

        if item["regressions"]:
            print("     Maturity Regressions:")
            for reg in item["regressions"]:
                print(f"       - {reg.reason}")

        print("-" * 75)

    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.project_risks <project_name>")
        sys.exit(1)
    show_project_risks(sys.argv[1])
