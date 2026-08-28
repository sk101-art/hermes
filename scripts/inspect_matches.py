"""Inspect 5+ Ascel match explanations via the comparison service."""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.storage.db import Database
from app.services.projects import get_project_match_comparison

db = Database()
matches = db.get_project_matches("project:ascel_-_copy")
top5 = matches[:5]

for i, m in enumerate(top5, 1):
    payload = get_project_match_comparison("project:ascel_-_copy", m.entity_id, db)
    print("=" * 70)
    print(f"MATCH {i}: {m.entity_id}")
    print(f"  subject: {payload['subject']['title']}")
    print(f"  match_type={payload['match']['match_type']} rel={payload['match']['relevance_score']} rec={payload['match']['recommendation']}")
    expl = payload["match"]["explanation"]
    if not expl:
        print("  NO EXPLANATION")
        continue
    print(f"  subject_kind: {expl['subject_kind']}")
    print(f"  what_happened: {expl['what_happened']}")
    print(f"  relevance_summary: {expl['relevance_summary']}")
    print(f"  relationship_label: {expl['relationship_label']}")
    print(f"  version: {expl['explanation_version']}")
    for d in expl["matched_dimensions"]:
        print(f"    dim[{d['dimension']}] strength={d['evidence_strength']}: {d['connection']}")
        for ref in d["evidence_references"][:2]:
            print(f"      ref: {ref['label']}")
    for e in expl["potential_effects"][:2]:
        print(f"    effect({e['likelihood']}/{e['severity']}): {e['effect']}")
    ra = expl.get("recommended_action")
    if ra:
        print(f"    action({ra['urgency']}): {ra['action']}")
        print(f"      rationale: {ra['rationale']}")
    print(f"  limitations: {expl['limitations']}")
