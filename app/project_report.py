import sys
from app.storage.db import Database

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def show_project_report(project_name: str) -> None:
    db = Database()
    project = db.get_project_by_name(project_name)
    if not project:
        print(f"Error: Project '{project_name}' not found.")
        sys.exit(1)

    profile = db.get_project_profile(project.id)
    matches = db.get_project_matches(project.id)

    print("=" * 75)
    print("HERMES — PROJECT INTELLIGENCE REPORT")
    print("=" * 75)

    print(f"\nPROJECT: {project.name}")
    print(f"Path: {project.path}")
    if project.description:
        print(f"Description: {project.description}")

    if profile:
        print("\nTECHNOLOGY PROFILE:")
        print(f"  Languages:     {', '.join(profile.languages) if profile.languages else 'None'}")
        print(f"  Frameworks:    {', '.join(profile.frameworks) if profile.frameworks else 'None'}")
        print(f"  ML & AI Stack: {', '.join(profile.ml_stack) if profile.ml_stack else 'None'}")
        print(f"  Storage & DB:  {', '.join(profile.databases) if profile.databases else 'None'}")
        print(f"  Dependencies:  {', '.join(list(profile.dependencies.keys())[:15]) if profile.dependencies else 'None'}")
        print(f"  Topics:        {', '.join(profile.topics) if profile.topics else 'None'}")

    print(f"\nTOP RELEVANT DEVELOPMENTS ({len(matches)} matches found):")
    print("-" * 75)

    if not matches:
        print("  No developments matched yet. Run 'python -m app.context_match' to evaluate intelligence.")

    for idx, m in enumerate(matches[:10], 1):
        cluster = db.get_cluster(m.entity_id)
        title = cluster.canonical_title if cluster else m.entity_id
        claims = db.get_claims_by_cluster(m.entity_id)
        events = db.get_cluster_events(m.entity_id)
        assessment = db.get_technology_assessment(m.entity_id)
        mat_str = assessment.maturity_stage.upper() if assessment else "UNKNOWN"

        print(f"{idx:02d}. [{m.recommendation.upper()}] Impact: {m.impact_score:.2f} | Relevance: {m.relevance_score:.2f} | Maturity: {mat_str}")
        print(f"    Story: \"{title}\"")
        print(f"    Match Type: {m.match_type.replace('_', ' ').title()}")
        print("    Why:")
        for r in m.reason_codes:
            print(f"      - {r}")

        if claims:
            strongest = claims[0]
            print(f"    Claim: \"{strongest.claim_text}\" (Status: {strongest.status.upper()} | Verification: {strongest.verification_score:.2f})")

        if events:
            top_ev = events[0]
            print(f"    Source: [{top_ev.source.upper()}] {top_ev.url}")

        print("-" * 75)

    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.project_report <project_name>")
        sys.exit(1)
    show_project_report(sys.argv[1])
