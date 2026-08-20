import argparse
import sys
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_saved_view(include_inactive: bool = False) -> None:
    db = Database()
    saved_items = db.get_all_saved_items(active_only=not include_inactive)

    print("=" * 75)
    print(f"HERMES — PERSISTENT SAVED LIBRARY ({len(saved_items)} items)")
    print("=" * 75)

    if not saved_items:
        print("\nNo saved items in library.")
        print("Star high-value items with 'python -m app.star <inbox_id>' to persist them.")
        print("=" * 75)
        return

    for idx, s in enumerate(saved_items, 1):
        # Fetch current live intelligence
        cluster = db.get_cluster(s.story_cluster_id)
        claims = db.get_claims_by_cluster(s.story_cluster_id)
        assessment = db.get_technology_assessment(s.story_cluster_id)
        tech_state = db.get_technology_state(s.story_cluster_id)

        curr_v = claims[0].verification_score if claims else s.verification_snapshot
        curr_mat = assessment.maturity_stage.upper() if assessment else s.maturity_snapshot.upper()
        curr_risk = tech_state.risk_score if tech_state else s.risk_snapshot

        active_tag = "" if s.is_active else " [INACTIVE]"
        save_date = s.saved_at.strftime("%Y-%m-%d")

        print(f"\n{idx:02d}. {active_tag}\"{s.title_snapshot}\"")
        print(f"    Saved ID:     {s.id}")
        print(f"    Saved Date:   {save_date}")
        print(f"    Verification: Current: {curr_v:.2f} | At Save: {s.verification_snapshot:.2f}")
        print(f"    Maturity:     Current: {curr_mat} | At Save: {s.maturity_snapshot.upper()}")
        print(f"    Risk:         Current: {curr_risk:.2f} | At Save: {s.risk_snapshot:.2f}")

        if s.project_ids:
            print(f"    Projects:     {', '.join(s.project_ids)}")
        if s.tags:
            print(f"    Tags:         {', '.join(s.tags)}")
        if s.user_note:
            print(f"    User Note:    \"{s.user_note}\"")

        print("-" * 75)

    print("=" * 75)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Saved Library")
    parser.add_argument("--all", action="store_true", help="Include deactivated/unstarred saved items")
    args = parser.parse_args()
    run_saved_view(include_inactive=args.all)
