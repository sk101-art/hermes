import sys
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_saved_detail(saved_id: str) -> None:
    db = Database()
    saved = db.get_saved_item(saved_id)
    if not saved:
        print(f"Error: Saved item '{saved_id}' not found.")
        sys.exit(1)

    cluster = db.get_cluster(saved.story_cluster_id)
    claims = db.get_claims_by_cluster(saved.story_cluster_id)
    events = db.get_cluster_events(saved.story_cluster_id)
    assessment = db.get_technology_assessment(saved.story_cluster_id)
    tech_state = db.get_technology_state(saved.story_cluster_id)

    curr_v = claims[0].verification_score if claims else saved.verification_snapshot
    curr_mat = assessment.maturity_stage.upper() if assessment else saved.maturity_snapshot.upper()
    curr_risk = tech_state.risk_score if tech_state else saved.risk_snapshot

    # Revisions / Changes since save
    all_revisions = db.get_claim_revisions_by_cluster(saved.story_cluster_id)
    recent_revisions = [r for r in all_revisions if r.created_at >= saved.saved_at]

    print("=" * 75)
    print(f"HERMES — SAVED ITEM DETAIL")
    print("=" * 75)
    print(f"Title:        \"{saved.title_snapshot}\"")
    print(f"Saved ID:     {saved.id}")
    print(f"Cluster ID:   {saved.story_cluster_id}")
    print(f"Saved At:     {saved.saved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Link Status:  {saved.link_status.upper()}")
    print(f"Active:       {saved.is_active}")

    if saved.project_ids:
        print(f"Projects:     {', '.join(saved.project_ids)}")
    if saved.tags:
        print(f"Tags:         {', '.join(saved.tags)}")
    if saved.user_note:
        print(f"User Note:    \"{saved.user_note}\"")

    print("\n--- METRICS COMPARISON ---")
    print(f"  Verification: AT SAVE: {saved.verification_snapshot:.2f}  -->  CURRENT: {curr_v:.2f}")
    print(f"  Maturity:     AT SAVE: {saved.maturity_snapshot.upper():<12}  -->  CURRENT: {curr_mat}")
    print(f"  Risk Score:   AT SAVE: {saved.risk_snapshot:.2f}  -->  CURRENT: {curr_risk:.2f}")

    print("\n--- CHANGES SINCE SAVE ---")
    if not recent_revisions:
        print("  No claim revisions recorded since save.")
    for r in recent_revisions:
        print(f"  - [{r.created_at.strftime('%Y-%m-%d')}] [{r.revision_type.upper()}] {r.reason}")

    print("\n--- CURRENT CLAIMS ---")
    for c in claims:
        print(f"  - [{c.status.upper()}] \"{c.claim_text}\" (Score: {c.verification_score:.2f})")

    print("\n--- PROVENANCE / SOURCES ---")
    for ev in events:
        print(f"  - [{ev.source.upper()}] {ev.title}")
        print(f"    {ev.url}")

    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.saved_detail <saved_item_id>")
        sys.exit(1)
    run_saved_detail(sys.argv[1])
