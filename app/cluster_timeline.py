import sys
from datetime import datetime, timezone
from app.storage.db import Database


def show_cluster_timeline(cluster_id: str) -> None:
    db = Database()
    cluster = db.get_cluster(cluster_id)
    if not cluster:
        print(f"Error: Cluster with ID '{cluster_id}' not found.")
        sys.exit(1)

    events = db.get_cluster_events(cluster_id)
    claims = db.get_claims_by_cluster(cluster_id)
    assessment = db.get_technology_assessment(cluster_id)
    assessment_revs = db.get_technology_assessment_revisions(cluster_id)
    tech_state = db.get_technology_state(cluster_id)

    print("=" * 75)
    print("HERMES — STORY CLUSTER & TECHNOLOGY TIMELINE")
    print("=" * 75)

    print(f"\nCLUSTER ID: {cluster.id}")
    print(f"Canonical Title: {cluster.canonical_title}")
    print(f"Sources: {', '.join(cluster.sources)} | Events: {len(events)} | Claims: {len(claims)}")

    if tech_state:
        print("\nTECHNOLOGY STATE SNAPSHOT:")
        print(f"  Current Status:    {tech_state.current_status.upper()}")
        print(f"  Trend:             {tech_state.trend.upper()}")
        print(f"  Risk Score:        {tech_state.risk_score:.4f}")
        print(f"  Latest Release:    {tech_state.latest_release or 'None'}")
        print(f"  Active Claims:     {tech_state.active_claim_count} (Supported: {tech_state.supported_claim_count}, Contradicted: {tech_state.contradicted_claim_count}, Superseded: {tech_state.superseded_claim_count})")

    if assessment:
        print(f"  Maturity Stage:    {assessment.maturity_stage.upper()} (Score: {assessment.assessment_score:.4f})")

    print("\nCHRONOLOGICAL CLUSTER HISTORY:")
    print("-" * 75)

    timeline_items = []

    # 1. Events
    for ev in events:
        dt = ev.published_at or ev.discovered_at or cluster.created_at
        timeline_items.append((
            dt,
            f"EVENT [{ev.source.upper()}] {ev.event_type}",
            f"Title: {ev.title}\n  URL: {ev.url}"
        ))

    # 2. Claims & Revisions
    for c in claims:
        dt = c.created_at
        timeline_items.append((
            dt,
            f"CLAIM EXTRACTED [{c.claim_type.upper()}]",
            f"\"{c.claim_text}\"\n  Status: {c.status} | Score: {c.verification_score:.4f} | Staleness: {c.staleness_score:.2f}"
        ))
        for rev in db.get_claim_revisions(c.id):
            timeline_items.append((
                rev.created_at,
                f"CLAIM REVISION [{c.id[:12]}]",
                f"Status: {rev.previous_status} -> {rev.new_status} | Reason: {rev.reason}"
            ))

    # 3. Maturity revisions
    for mrev in assessment_revs:
        timeline_items.append((
            mrev.created_at,
            "MATURITY STAGE REVISION",
            f"Stage: {mrev.previous_stage} -> {mrev.new_stage} (Score: {mrev.previous_score:.4f} -> {mrev.new_score:.4f})\n  Reason: {mrev.reason}"
        ))

    timeline_items.sort(key=lambda x: x[0])

    for dt, header, detail in timeline_items:
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt, datetime) else str(dt)
        print(f"[{date_str}] {header}")
        print(f"  {detail}")
        print("-" * 75)

    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.cluster_timeline <cluster_id>")
        sys.exit(1)
    show_cluster_timeline(sys.argv[1])
