import json
from pathlib import Path

data = json.loads(Path("reports/ascel_intel.json").read_text(encoding="utf-8-sig"))
print("KEYS:", list(data.keys()))
print("narrative:", data.get("narrative"))
matches = data.get("top_matches") or data.get("matches_summary") or data.get("matches") or []
print("MATCH COUNT:", len(matches))
for i, m in enumerate(matches[:20], 1):
    print(
        f"[{i}] cluster={m.get('cluster_id')} type={m.get('match_type')} "
        f"rel={m.get('relevance_score')} impact={m.get('impact_score')} "
        f"expl={'YES' if m.get('explanation') else 'NO'} "
        f"ver={m.get('explanation_version')} rec={m.get('recommendation')}"
    )
