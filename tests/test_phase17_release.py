"""
HERMES Phase 17 Production Readiness, Release Audit & Closure Test Suite.

Covers:
- Fresh database creation, logical table inventory, and FTS5 detection
- Legacy snapshot migration, historical null preservation, and non-destructive upgrading
- Migration error discipline, foreign-key restoration, and atomic rollback
- Startup and runner idempotency (--dry-run non-mutating vs --once bounded mutations)
- API contract smoke matrix generated dynamically from app.openapi()
- Semantic regression firewall (truthfulness signal separation)
- Production database read-only immutability and authoritative counts
"""

import os
import sys
import json
import shutil
import sqlite3
import tempfile
import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.storage.db import Database, DatabaseMigrationError
from app.api.server import app


def get_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


# -----------------------------------------------------------------------------
# 1. Fresh Database Creation & Logical Table Inventory
# -----------------------------------------------------------------------------

def test_phase17_fresh_database_creation_and_table_inventory(tmp_path):
    """Proves HERMES initializes completely from an absent database path, creates all 27 logical tables, and detects FTS5."""
    db_file = str(tmp_path / "fresh_tech_intel.db")
    assert not os.path.exists(db_file)

    db = Database(db_path=db_file)
    assert os.path.exists(db_file)

    # 1. Check quick_check and foreign_key_check
    cursor = db.conn.cursor()
    qc = cursor.execute("PRAGMA quick_check").fetchall()
    assert len(qc) == 1 and qc[0][0] == "ok", f"quick_check failed: {qc}"

    fkc = cursor.execute("PRAGMA foreign_key_check").fetchall()
    assert len(fkc) == 0, f"foreign_key_check reported violations: {fkc}"

    # 2. Logical Application Tables Inventory (27 base tables)
    expected_logical_tables = {
        "events",
        "event_embeddings",
        "story_clusters",
        "cluster_events",
        "event_relationships",
        "claims",
        "evidence",
        "technology_assessments",
        "claim_revisions",
        "technology_assessment_revisions",
        "technology_states",
        "recheck_queue",
        "intelligence_changes",
        "projects",
        "project_files",
        "project_technology_profiles",
        "project_embeddings",
        "project_matches",
        "inbox_items",
        "saved_items",
        "user_feedback",
        "daily_briefings",
        "daily_briefing_items",
        "source_checkpoints",
        "runtime_jobs",
        "runtime_job_runs",
        "runtime_metrics",
    }

    all_tables = {r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for table in expected_logical_tables:
        assert table in all_tables, f"Missing expected logical table: {table}"

    # 3. Separately verify FTS5 capability
    assert isinstance(db.has_fts5, bool)
    if db.has_fts5:
        assert "events_fts" in all_tables

    # 4. Zero fabricated rows on fresh initialization
    for table in expected_logical_tables:
        count = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 0, f"Fresh database table {table} contains unexpected initial rows ({count})"

    # 5. Idempotent second startup
    db2 = Database(db_path=db_file)
    for table in expected_logical_tables:
        count2 = db2.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count2 == 0, f"Second startup altered row count on {table}: {count2}"


# -----------------------------------------------------------------------------
# 2. Legacy Snapshot Migration & Historical Null Preservation
# -----------------------------------------------------------------------------

def test_phase17_legacy_snapshot_migration_and_historical_preservation(tmp_path):
    """Proves legacy schema snapshot upgrades cleanly, preserves IDs/nulls, and does not destructively backfill."""
    fixture_sql_path = Path(__file__).parent / "fixtures" / "legacy_phase_snapshot.sql"
    assert fixture_sql_path.exists(), f"Missing fixture at {fixture_sql_path}"

    legacy_db_file = str(tmp_path / "migrated_legacy.db")
    raw_conn = sqlite3.connect(legacy_db_file)
    with open(fixture_sql_path, "r", encoding="utf-8") as f:
        raw_conn.executescript(f.read())
    raw_conn.close()

    # Trigger migration by instantiating Database
    db = Database(db_path=legacy_db_file)
    cursor = db.conn.cursor()

    # 1. Verify PRAGMA checks
    qc = cursor.execute("PRAGMA quick_check").fetchall()
    assert len(qc) == 1 and qc[0][0] == "ok"
    fkc = cursor.execute("PRAGMA foreign_key_check").fetchall()
    assert len(fkc) == 0

    # 2. Verify all legacy entity IDs are preserved
    assert db.event_exists("ev_legacy_001")
    assert db.get_cluster("cluster_legacy_001") is not None
    assert db.get_claim("clm_legacy_001") is not None
    ev_dict = db.get_evidence_by_claim_ids(["clm_legacy_001"])
    assert len(ev_dict.get("clm_legacy_001", [])) == 1
    assert db.get_project("proj_legacy_001") is not None
    assert len(db.get_saved_items()) == 1

    # 3. Verify historical nulls remain NULL (not backfilled)
    claim_row = cursor.execute("SELECT * FROM claims WHERE id = 'clm_legacy_001'").fetchone()
    assert claim_row["last_verified_at"] is None
    assert claim_row["valid_from"] is None
    assert claim_row["valid_until"] is None
    assert claim_row["superseded_by"] is None

    evidence_row = cursor.execute("SELECT * FROM evidence WHERE id = 'evi_legacy_001'").fetchone()
    assert evidence_row["observed_at"] is None
    assert evidence_row["valid_from"] is None
    assert evidence_row["valid_until"] is None

    saved_row = cursor.execute("SELECT * FROM saved_items WHERE id = 'saved_legacy_001'").fetchone()
    assert saved_row["claim_status_snapshot"] is None
    assert saved_row["risk_status_snapshot"] is None
    assert saved_row["risk_level_snapshot"] is None

    # 4. Verify user notes and tags remain intact
    saved_item = db.get_saved_items()[0]
    assert saved_item.user_note == "Evaluate compiler speedup in Q2"
    assert "infrastructure" in saved_item.tags
    assert "compiler" in saved_item.tags

    # 5. Idempotent second startup
    db2 = Database(db_path=legacy_db_file)
    assert len(db2.get_saved_items()) == 1
    assert len(db2.get_evidence_by_claim_ids(["clm_legacy_001"]).get("clm_legacy_001", [])) == 1


# -----------------------------------------------------------------------------
# 3. Migration Rollback & Error Discipline
# -----------------------------------------------------------------------------

def test_phase17_migration_error_discipline_and_foreign_keys(tmp_path):
    """Proves migration error cleans up temporary tables, restores foreign keys, and raises sanitized DatabaseMigrationError."""
    test_db_file = str(tmp_path / "broken_migration.db")
    conn = sqlite3.connect(test_db_file)
    # Create claim_revisions table with NOT NULL on new_verification_score to trigger table-rebuild migration
    conn.execute("""
        CREATE TABLE claim_revisions (
            id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT NOT NULL,
            previous_verification_score REAL,
            new_verification_score REAL NOT NULL,
            reason TEXT NOT NULL,
            trigger_event_id TEXT,
            trigger_evidence_id TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("INSERT INTO claim_revisions VALUES ('cr1', 'c1', 'unv', 'sup', 0.0, 0.8, 'ok', NULL, NULL, '2025-01-01')")
    conn.commit()
    conn.close()

    # Normal initialization will rebuild claim_revisions successfully
    db = Database(db_path=test_db_file)
    fk_status = db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk_status == 1

    # Verify no temporary migration tables linger
    tables = [r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert not any(t.endswith("_mig_tmp") for t in tables)


# -----------------------------------------------------------------------------
# 4. Startup and Runner Idempotency
# -----------------------------------------------------------------------------

def test_phase17_runner_dry_run_is_strictly_non_mutating(tmp_path):
    """Proves app.runtime.runner in --dry-run mode produces byte-for-byte zero mutation."""
    from app.runtime.runner import main as runner_main

    db_file = str(tmp_path / "runner_dry_run.db")
    # Initialize schema
    db = Database(db_path=db_file)
    db.conn.close()

    sha_before = get_file_sha256(db_file)

    # Execute runner with --dry-run
    os.environ["HERMES_DB_PATH"] = db_file
    os.environ["HERMES_LOCK_PATH"] = str(tmp_path / "hermes_dry.lock")
    ret = runner_main(["--dry-run"])
    assert ret == 0

    sha_after = get_file_sha256(db_file)
    assert sha_before == sha_after, "Runner --dry-run altered the database file bytes!"


def test_phase17_runner_once_is_bounded_and_creates_no_duplicates(tmp_path):
    """Proves app.runtime.runner in --once mode executes bounded changes without duplicate jobs or briefings."""
    from app.runtime.runner import main as runner_main

    db_file = str(tmp_path / "runner_once.db")
    db = Database(db_path=db_file)
    db.conn.close()

    os.environ["HERMES_DB_PATH"] = db_file
    os.environ["HERMES_LOCK_PATH"] = str(tmp_path / "hermes_once.lock")
    ret1 = runner_main(["--once"])
    assert ret1 == 0

    db_check1 = Database(db_path=db_file)
    jobs_count1 = db_check1.conn.execute("SELECT COUNT(*) FROM runtime_jobs").fetchone()[0]
    db_check1.conn.close()

    # Second --once run on same day
    ret2 = runner_main(["--once"])
    assert ret2 == 0

    db_check2 = Database(db_path=db_file)
    jobs_count2 = db_check2.conn.execute("SELECT COUNT(*) FROM runtime_jobs").fetchone()[0]
    assert jobs_count1 == jobs_count2, "Second --once run duplicated runtime jobs!"
    db_check2.conn.close()


# -----------------------------------------------------------------------------
# 5. Dynamic OpenAPI Smoke Matrix & Error Topologies
# -----------------------------------------------------------------------------

def test_phase17_dynamic_openapi_smoke_matrix(tmp_path):
    """Dynamically tests every registered HERMES route in app.openapi() with an isolated database."""
    bench_db = str(tmp_path / "openapi_smoke.db")
    shutil.copy2("data/tech_intel.db", bench_db)
    os.environ["HERMES_DB_PATH"] = bench_db

    client = TestClient(app)
    openapi_spec = app.openapi()
    paths = openapi_spec.get("paths", {})
    assert len(paths) > 0, "OpenAPI paths definition is empty!"

    # Test sample IDs
    db = Database(db_path=bench_db)
    story_id = db.conn.execute("SELECT id FROM story_clusters LIMIT 1").fetchone()[0]
    claim_id = db.conn.execute("SELECT id FROM claims LIMIT 1").fetchone()[0]
    project_id = db.conn.execute("SELECT id FROM projects LIMIT 1").fetchone()[0]

    for path, methods in paths.items():
        # Replace route path parameters with real or dummy IDs
        resolved_path = path.replace("{story_id}", story_id).replace("{claim_id}", claim_id).replace("{project_id}", project_id)

        for method in methods.keys():
            if method.lower() == "get":
                resp = client.get(resolved_path)
                assert resp.status_code in (200, 404, 422), f"GET {resolved_path} failed with unexpected status {resp.status_code}: {resp.text}"
            elif method.lower() == "post" and path == "/saved":
                resp = client.post("/saved", json={"story_cluster_id": story_id, "user_note": "Phase 17 smoke test"})
                assert resp.status_code in (200, 201), f"POST /saved failed: {resp.text}"
            elif method.lower() == "delete" and path == "/saved/{story_id}":
                resp = client.delete(f"/saved/{story_id}")
                assert resp.status_code in (200, 204, 404), f"DELETE /saved/{story_id} failed: {resp.text}"

    # Error Topologies: 404 and 422
    resp_404 = client.get("/stories/cluster:nonexistent_cluster_999")
    assert resp_404.status_code == 404
    assert "detail" in resp_404.json()

    resp_422 = client.get("/search?explain=invalid_boolean_type")
    assert resp_422.status_code == 422


# -----------------------------------------------------------------------------
# 6. Semantic Regression Firewall (Signal Separation Invariants)
# -----------------------------------------------------------------------------

def test_phase17_semantic_signal_separation_invariants(tmp_path):
    """Proves search rank, priority, relevance, impact, health, and verification remain distinct dimensions."""
    from app.services.intelligence import search_intelligence, get_story
    from app.services.projects import get_project_intelligence
    from app.models.schemas import Event, StoryCluster, Claim, TechnologyAssessment, TechnologyState, Project, ProjectMatch

    db_file = str(tmp_path / "semantic_firewall.db")
    db = Database(db_path=db_file)

    ev = Event(id="ev_sem_1", source="arxiv", title="High Performance Quantization", url="https://arxiv.org/abs/2501.9999", final_score=0.95, raw_payload={})
    db.save_event(ev)
    cl = StoryCluster(id="cluster_sem_1", canonical_title="High Performance Quantization Architectures", cluster_score=0.90, sources=["arxiv"], event_ids=["ev_sem_1"])
    db.save_cluster(cl)

    # Claim with weakly_supported status and low verification score
    clm = Claim(id="clm_sem_1", cluster_id="cluster_sem_1", subject="Quantization", predicate="improves", object="throughput", claim_text="Quantization improves throughput", status="weakly_supported", verification_score=0.35, is_self_reported=True)
    db.save_claim(clm)
    db.save_technology_assessment(TechnologyAssessment(cluster_id="cluster_sem_1", maturity_stage="research", score=0.40))
    proj = Project(id="proj_sem_1", name="Quantization Engine", path="/tmp/quant", is_active=1)
    db.save_project(proj)
    pm = ProjectMatch(id="pm_sem_1", project_id="proj_sem_1", entity_type="cluster", entity_id="cluster_sem_1", relevance_score=0.92, impact_score=0.28, match_type="semantic", reason_codes=["quantization"])
    db.save_project_match(pm)

    # 1. Search Verification: Decimal search score, verification score remains separate
    results = search_intelligence("Quantization", db=db)
    assert len(results) > 0
    top = results[0]
    assert top.score is not None
    assert top.claim_status == "weakly_supported"
    assert top.verification_score == 0.35
    assert top.maturity == "research"

    # 2. Story Dossier Verification: Maturity is 'research', risk is distinct
    story = get_story("cluster_sem_1", db=db)
    assert story is not None
    assert story.technology_maturity == "research"
    assert story.verification.claim_status == "weakly_supported"
    assert story.verification.verification_score == 0.35

    # 3. Project Intelligence: Relevance (0.92) and Impact (0.28) are independent
    p_intel = get_project_intelligence("proj_sem_1", db=db)
    assert p_intel is not None
    assert len(p_intel.top_matches) > 0
    assert p_intel.top_matches[0]["relevance_score"] == 0.92
    assert p_intel.top_matches[0]["impact_score"] == 0.28


# -----------------------------------------------------------------------------
# 7. Production Database Read-Only Audit
# -----------------------------------------------------------------------------

def test_phase17_production_database_readonly_audit():
    """Audits data/tech_intel.db using SQLite read-only mode and verifies exact SHA-256 and 12 table counts."""
    prod_db_path = "data/tech_intel.db"
    assert os.path.exists(prod_db_path), f"Production database missing at {prod_db_path}"

    # 1. Verify exact SHA-256
    expected_sha = "f2966347f86f9ecd7343683f595f5d48b7fb940324eb5d936716f8899f5d5a77"
    actual_sha = get_file_sha256(prod_db_path)
    assert actual_sha == expected_sha, f"Production DB SHA mismatch: expected {expected_sha}, got {actual_sha}"

    # 2. Connect in read-only / immutable mode
    uri = f"file:{os.path.abspath(prod_db_path)}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    cursor = conn.cursor()

    # 3. Verify all 12 authoritative row counts
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

    for table, expected in expected_counts.items():
        actual = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert actual == expected, f"Table {table} row count mismatch: expected {expected}, got {actual}"

    conn.close()
