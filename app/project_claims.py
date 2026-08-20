import sys
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def show_project_claims(project_name: str) -> None:
    db = Database()
    project = db.get_project_by_name(project_name)
    if not project:
        print(f"Error: Project '{project_name}' not found.")
        sys.exit(1)

    matches = db.get_project_matches(project.id)

    print("=" * 75)
    print(f"HERMES — RELEVANT CLAIMS FOR PROJECT '{project.name}'")
    print("=" * 75)

    all_matched_claims = []
    for m in matches:
        claims = db.get_claims_by_cluster(m.entity_id)
        for c in claims:
            all_matched_claims.append((m, c))

    # Sort by impact score DESC, verification score DESC
    all_matched_claims.sort(key=lambda x: (x[0].impact_score, x[1].verification_score), reverse=True)

    print(f"\nTOTAL RELEVANT CLAIMS: {len(all_matched_claims)}\n")

    for idx, (m, c) in enumerate(all_matched_claims[:15], 1):
        print(f"[{idx:02d}] Claim ID: {c.id}")
        print(f"     Statement: \"{c.claim_text}\"")
        print(f"     Status:    {c.status.upper()} | Verification: {c.verification_score:.4f} | Staleness: {c.staleness_score:.2f}")
        print(f"     Assertion: {c.assertion_level.upper()} | Self-Reported: {c.self_reported}")
        print(f"     Project Match Impact: {m.impact_score:.2f} ({m.recommendation.upper()})")
        print("-" * 75)

    if not all_matched_claims:
        print("  No relevant claims found for this project.")

    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.project_claims <project_name>")
        sys.exit(1)
    show_project_claims(sys.argv[1])
