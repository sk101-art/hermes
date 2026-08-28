"""Full rescan of the Ascel project: narrative + all matches with explanations."""
from app.storage.db import Database
from app.services.projects import scan_single_project

db = Database()
result = scan_single_project("project:ascel_-_copy", db)
print("SCAN RESULT:", result)

proj = db.get_project("project:ascel_-_copy")
print("NARRATIVE STATUS:", proj.narrative.extraction_status if proj.narrative else None)
if proj.narrative:
    print("PURPOSE:", proj.narrative.purpose_summary)
    print("CAPABILITIES:", proj.narrative.capability_summaries)
    print("ARCHITECTURE:", proj.narrative.architecture_summary)
    print("COMPONENTS:", proj.narrative.primary_components)
    print("EVIDENCE REFS:", [r.label for r in proj.narrative.evidence_references])

matches = db.get_project_matches("project:ascel_-_copy")
print(f"\nTOTAL MATCHES: {len(matches)}")
explained = [m for m in matches if m.explanation]
legacy = [m for m in matches if not m.explanation]
print(f"EXPLAINED: {len(explained)}, LEGACY: {len(legacy)}")
for i, m in enumerate(matches[:25], 1):
    tag = "EXPL" if m.explanation else "LEGACY"
    print(f"[{i}] {tag} cluster={m.entity_id} type={m.match_type} rel={m.relevance_score:.4f} rec={m.recommendation}")
