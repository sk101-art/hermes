"""Phase 4 — Requirement 6: Sync Data end-to-end contracts.

Proves:
1. process_next_queued_operation lifecycle: queued → claimed (running,
   worker_id, heartbeat) → completed, with the dispatched job invoked.
2. saved_hydration scope dispatches run_saved_hydration.
3. A job exception settles the operation as failed with a sanitized error.
4. project_scan without target_id fails terminally (never scans everything).
5. Stale running operations (expired lease, no heartbeat) are recovered to
   failed before the next claim.
6. POST /runtime/refresh contracts: 202 enqueue, idempotent replay returns
   the same operation, conflicting key → 409, unknown scope → 422,
   project_scan without target_id → 422, with target_id → persisted.
7. GET /runtime/operations/{id}: 200 for known, 404 for unknown.
8. /health/ready probe exposes the fields the frontend pre-Sync probe relies
   on (status, database_path, database_writable, daemon_heartbeat_alive,
   runtime_date, runtime_timezone).

All tests use isolated temporary databases — never the tracked baseline.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.models.schemas import RefreshOperation
from app.runtime import runner as runner_mod
from app.runtime.runner import process_next_queued_operation
from app.storage.db import Database

UTC = timezone.utc
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _make_db(tmp_path: Path, name: str = "sync6.db") -> Database:
    return Database(db_path=str(tmp_path / name))


def _enqueue(db: Database, scope: str, target_id=None, idempotency_key=None,
             requested_at=None) -> RefreshOperation:
    op = RefreshOperation(
        id=f"refresh:{scope}:{(requested_at or NOW).timestamp()}",
        scope=scope,
        target_id=target_id,
        status="queued",
        requested_at=requested_at or NOW,
        idempotency_key=idempotency_key,
    )
    db.save_refresh_operation(op)
    return op


# ---------------------------------------------------------------------------
# 1. Lifecycle: queued → claimed (running + worker + heartbeat) → completed
# ---------------------------------------------------------------------------

def test_operation_lifecycle_queued_claimed_completed(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    op = _enqueue(db, "saved_hydration")

    observed = {}

    def _spy_saved_hydration(db_arg, now=None, **kwargs):
        # While the job executes, the operation must be claimed: running,
        # owned by a worker, with a heartbeat/lease recorded.
        live = db.get_refresh_operation(op.id)
        observed["status"] = live.status
        observed["worker_id"] = live.worker_id
        observed["heartbeat_at"] = live.heartbeat_at
        observed["lease_expires_at"] = live.lease_expires_at
        observed["called"] = True
        return {"status": "completed"}

    monkeypatch.setattr(runner_mod, "run_saved_hydration", _spy_saved_hydration)

    result = process_next_queued_operation(db, worker_id="worker-test", now=NOW)

    assert observed.get("called") is True
    assert observed["status"] == "running"
    assert observed["worker_id"] == "worker-test"
    assert observed["heartbeat_at"] is not None
    assert observed["lease_expires_at"] is not None

    assert result is not None
    assert result["operation_id"] == op.id
    assert result["status"] == "completed"

    final = db.get_refresh_operation(op.id)
    assert final.status == "completed"
    assert final.completed_at is not None
    assert final.lease_expires_at is None  # lease released on completion
    db.close()


def test_no_queued_operation_returns_none(tmp_path):
    db = _make_db(tmp_path, "sync6_empty.db")
    assert process_next_queued_operation(db, now=NOW) is None
    db.close()


# ---------------------------------------------------------------------------
# 2. saved_hydration dispatch
# ---------------------------------------------------------------------------

def test_saved_hydration_scope_dispatches_job(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "sync6_hydration.db")
    op = _enqueue(db, "saved_hydration")

    calls = []
    monkeypatch.setattr(
        runner_mod, "run_saved_hydration",
        lambda db_arg, now=None, **kw: calls.append("saved_hydration") or {"status": "completed"},
    )

    result = process_next_queued_operation(db, now=NOW)
    assert result["status"] == "completed"
    assert result["scope"] == "saved_hydration"
    assert calls == ["saved_hydration"]
    db.close()


# ---------------------------------------------------------------------------
# 3. Job exception → failed with sanitized error
# ---------------------------------------------------------------------------

def test_job_exception_settles_failed_with_sanitized_error(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "sync6_failed.db")
    op = _enqueue(db, "saved_hydration")

    def _boom(db_arg, now=None, **kw):
        raise RuntimeError("hydration exploded: token=supersecret999")

    monkeypatch.setattr(runner_mod, "run_saved_hydration", _boom)

    result = process_next_queued_operation(db, now=NOW)
    assert result["status"] == "failed"
    assert "error" in result

    final = db.get_refresh_operation(op.id)
    assert final.status == "failed"
    assert final.error_summary
    assert "supersecret999" not in final.error_summary  # sanitized
    assert final.completed_at is not None
    assert final.lease_expires_at is None
    db.close()


# ---------------------------------------------------------------------------
# 4. project_scan without target_id fails terminally
# ---------------------------------------------------------------------------

def test_project_scan_without_target_id_fails(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "sync6_scan.db")
    op = _enqueue(db, "project_scan", target_id=None)

    # Guard: the all-projects scan path must never be reached.
    def _never(db_arg, **kw):
        raise AssertionError("scan_single_project must not run without target_id")

    import app.services.projects as projects_service
    monkeypatch.setattr(projects_service, "scan_single_project", _never)

    result = process_next_queued_operation(db, now=NOW)
    assert result["status"] == "failed"
    assert "target_id" in result["error"]
    db.close()


def test_project_scan_with_target_id_scans_only_that_project(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "sync6_scan2.db")
    op = _enqueue(db, "project_scan", target_id="project:alpha")

    scanned = []

    def _scan(project_id=None, db=None, **kw):
        scanned.append(project_id)
        return {"status": "completed"}

    import app.services.projects as projects_service
    monkeypatch.setattr(projects_service, "scan_single_project", _scan)

    result = process_next_queued_operation(db, now=NOW)
    assert result["status"] == "completed"
    assert scanned == ["project:alpha"]
    db.close()


# ---------------------------------------------------------------------------
# 5. Stale running operations are recovered before the next claim
# ---------------------------------------------------------------------------

def test_stale_running_operation_recovered_to_failed(tmp_path, monkeypatch):
    db = _make_db(tmp_path, "sync6_stale.db")

    stale = RefreshOperation(
        id="refresh:saved_hydration:stale",
        scope="saved_hydration",
        status="running",
        requested_at=NOW - timedelta(hours=2),
        claimed_at=NOW - timedelta(hours=2),
        worker_id="worker-dead",
        heartbeat_at=NOW - timedelta(hours=2),
        lease_expires_at=NOW - timedelta(minutes=30),  # expired
    )
    db.save_refresh_operation(stale)

    fresh = _enqueue(db, "saved_hydration", requested_at=NOW - timedelta(minutes=1))
    monkeypatch.setattr(
        runner_mod, "run_saved_hydration",
        lambda db_arg, now=None, **kw: {"status": "completed"},
    )

    result = process_next_queued_operation(db, now=NOW)
    assert result["operation_id"] == fresh.id
    assert result["status"] == "completed"

    recovered = db.get_refresh_operation(stale.id)
    assert recovered.status == "failed"
    assert "Abandoned" in (recovered.error_summary or "")
    db.close()


# ---------------------------------------------------------------------------
# 6-7. HTTP contracts: 202 / idempotent replay / 409 / 422 / 404
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    db_file = tmp_path / "sync6_api.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))
    monkeypatch.setenv("HERMES_TEST_INSTANCE_ID", "phase4-req6")

    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "load_runtime_config", lambda *a, **k: {
        "timezone": "UTC",
        "jobs": {"daily_refresh": {"time": "07:00", "timeout_minutes": 60,
                                   "max_retries": 8, "retry_interval_minutes": 15}},
        "sources": {},
    })

    return TestClient(app)


def test_enqueue_refresh_202_and_idempotent_replay(api_client):
    resp = api_client.post("/runtime/refresh", json={
        "scope": "saved_hydration", "idempotency_key": "key-1",
    })
    assert resp.status_code == 202, resp.text
    op1 = resp.json()
    assert op1["status"] == "queued"
    assert op1["scope"] == "saved_hydration"

    # Same idempotency key → same operation replayed, still 202.
    resp2 = api_client.post("/runtime/refresh", json={
        "scope": "saved_hydration", "idempotency_key": "key-1",
    })
    assert resp2.status_code == 202, resp2.text
    assert resp2.json()["id"] == op1["id"]


def test_enqueue_refresh_conflict_409(api_client):
    api_client.post("/runtime/refresh", json={
        "scope": "saved_hydration", "idempotency_key": "key-a",
    })
    resp = api_client.post("/runtime/refresh", json={
        "scope": "saved_hydration", "idempotency_key": "key-b",
    })
    assert resp.status_code == 409, resp.text


def test_enqueue_refresh_unknown_scope_422(api_client):
    resp = api_client.post("/runtime/refresh", json={"scope": "not_a_scope"})
    assert resp.status_code == 422, resp.text


def test_project_scan_requires_target_id_422(api_client):
    resp = api_client.post("/runtime/refresh", json={"scope": "project_scan"})
    assert resp.status_code == 422, resp.text
    assert "target_id" in resp.json()["detail"]


def test_project_scan_with_target_id_persisted(api_client):
    resp = api_client.post("/runtime/refresh", json={
        "scope": "project_scan", "target_id": "project:alpha",
    })
    assert resp.status_code == 202, resp.text
    op = resp.json()
    assert op["target_id"] == "project:alpha"

    got = api_client.get(f"/runtime/operations/{op['id']}")
    assert got.status_code == 200
    assert got.json()["target_id"] == "project:alpha"


def test_get_operation_404_for_unknown(api_client):
    resp = api_client.get("/runtime/operations/refresh:missing:0")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 8. /health/ready probe fields used by the frontend pre-Sync probe
# ---------------------------------------------------------------------------

def test_health_ready_probe_fields(api_client):
    resp = api_client.get("/health/ready")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "ready"
    assert data["database_path"]
    assert data["database_writable"] is True
    assert data["is_baseline"] is False
    assert isinstance(data["daemon_heartbeat_alive"], bool)
    assert data["runtime_date"]
    assert data["runtime_timezone"]
    assert data["test_instance_id"] == "phase4-req6"
