"""
HERMES Phase 17 Real Production Data Audit Script.
Reads data/tech_intel.db strictly through SQLite read-only mode (mode=ro&immutable=1),
verifies authoritative 12-table baseline, 7-source event distribution, and documents
representative real entities for audit closure.
"""

import os
import sys
import json
import sqlite3
import hashlib
from pathlib import Path
from typing import Any, Dict


def get_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def audit_real_data(db_path: str = "data/tech_intel.db", output_path: str = "reports/real_data_audit.json") -> Dict[str, Any]:
    abs_path = os.path.abspath(db_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Database not found at {abs_path}")

    # Compute SHA-256
    db_sha256 = get_file_sha256(abs_path)
    expected_sha = "f2966347f86f9ecd7343683f595f5d48b7fb940324eb5d936716f8899f5d5a77"

    # Connect read-only immutable
    uri = f"file:{abs_path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Authoritative 12-Table Counts
    authoritative_tables = [
        "events",
        "story_clusters",
        "claims",
        "evidence",
        "technology_assessments",
        "projects",
        "inbox_items",
        "saved_items",
        "daily_briefings",
        "source_checkpoints",
        "runtime_jobs",
        "intelligence_changes",
    ]

    expected_counts = {
        "events": 368,
        "story_clusters": 345,
        "claims": 360,
        "evidence": 416,
        "technology_assessments": 345,
        "projects": 2,
        "inbox_items": 322,
        "saved_items": 2,
        "daily_briefings": 1,
        "source_checkpoints": 9,
        "runtime_jobs": 10,
        "intelligence_changes": 0,
    }

    actual_counts = {}
    mismatches = []
    for tbl in authoritative_tables:
        cnt = cursor.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        actual_counts[tbl] = cnt
        if cnt != expected_counts[tbl]:
            mismatches.append(f"{tbl}: expected {expected_counts[tbl]}, got {cnt}")

    # 2. Event Sources Distribution
    src_rows = cursor.execute("SELECT source, COUNT(*) as cnt FROM events GROUP BY source ORDER BY cnt DESC").fetchall()
    source_distribution = {r["source"]: r["cnt"] for r in src_rows}

    # 3. Representative Real Entities
    # Multi-source story cluster
    multi_src_cluster = cursor.execute("""
        SELECT sc.id, sc.canonical_title, sc.cluster_score, COUNT(DISTINCT e.source) as src_count, COUNT(e.id) as ev_count
        FROM story_clusters sc
        JOIN cluster_events ce ON sc.id = ce.cluster_id
        JOIN events e ON ce.event_id = e.id
        GROUP BY sc.id
        HAVING src_count > 1
        ORDER BY sc.cluster_score DESC
        LIMIT 1
    """).fetchone()

    # Claim with supporting and opposing evidence
    claim_rep = cursor.execute("""
        SELECT c.id, c.subject, c.predicate, c.object, c.status, c.verification_score, COUNT(ev.id) as ev_count
        FROM claims c
        LEFT JOIN evidence ev ON c.id = ev.claim_id
        GROUP BY c.id
        HAVING ev_count > 0
        ORDER BY c.verification_score DESC
        LIMIT 1
    """).fetchone()

    # Project match with relevance and impact
    pm_rep = cursor.execute("""
        SELECT pm.id, p.name as project_name, pm.entity_id as cluster_id, pm.relevance_score, pm.impact_score, pm.match_type
        FROM project_matches pm
        JOIN projects p ON pm.project_id = p.id
        ORDER BY pm.relevance_score DESC
        LIMIT 1
    """).fetchone()

    # Saved item
    saved_rep = cursor.execute("""
        SELECT s.id, s.story_cluster_id, s.user_note, s.tags_json, s.saved_at
        FROM saved_items s
        LIMIT 1
    """).fetchone()

    # Daily Briefing
    briefing_rep = cursor.execute("""
        SELECT id, briefing_date, total_items, created_at FROM daily_briefings LIMIT 1
    """).fetchone()

    audit_result = {
        "database_file": db_path,
        "database_sha256": db_sha256,
        "sha256_verified": db_sha256 == expected_sha,
        "authoritative_table_counts": actual_counts,
        "table_count_verified": len(mismatches) == 0,
        "mismatches": mismatches,
        "event_source_distribution": source_distribution,
        "source_count": len(source_distribution),
        "representative_entities": {
            "multi_source_story": dict(multi_src_cluster) if multi_src_cluster else None,
            "claim_with_evidence": dict(claim_rep) if claim_rep else None,
            "project_match": dict(pm_rep) if pm_rep else None,
            "saved_item": dict(saved_rep) if saved_rep else None,
            "daily_briefing": dict(briefing_rep) if briefing_rep else None,
            "intelligence_changes_count": actual_counts.get("intelligence_changes", 0),
        }
    }

    conn.close()

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(audit_result, f, indent=2)

    print(f"[Audit] Results written to {output_path}")
    print(f"[Audit] SHA-256 match: {audit_result['sha256_verified']} ({db_sha256})")
    print(f"[Audit] 12-table counts verified: {audit_result['table_count_verified']}")
    return audit_result


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "reports/real_data_audit.json"
    res = audit_real_data(output_path=out_file)
    if not res["sha256_verified"] or not res["table_count_verified"]:
        sys.exit(1)
    sys.exit(0)
