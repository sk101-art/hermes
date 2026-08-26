"""Focused Phase 3 corrective contract and security tests.

Covers:
- POST /projects returns 202 and enqueues a targeted project_scan operation
- PUT /projects/{id} returns 202 and enqueues a targeted project_scan operation
- DELETE /projects/{id} is an idempotent archive (replaces POST /archive)
- POST /projects/{id}/restore returns 202 with a queued targeted operation
- The synchronous POST /projects/{id}/scan API is removed (405)
- Path safety: configurable allowed_project_roots, directory-only validation,
  traversal rejection
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_db
from app.api.server import app
from app.context.scanner import (
    get_allowed_project_roots,
    is_path_safe_and_inside_allowed_roots,
)
from app.models.schemas import Project
from app.storage.db import Database


@pytest.fixture
def client_and_db(tmp_path):
    db_path = str(tmp_path / "contract.db")
    db = Database(db_path=db_path)

    proj = Project(
        id="project:contract-demo",
        name="contract-demo",
        path=str(tmp_path / "demo_proj"),
    )
    db.save_project(proj)

    def override_get_db():
        request_db = Database(db_path=db_path)
        try:
            yield request_db
        finally:
            request_db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client, db, tmp_path
    app.dependency_overrides.clear()
    db.close()


def _queued_project_scan_ops(db, target_id):
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT * FROM refresh_operations WHERE scope = 'project_scan' AND target_id = ? ORDER BY requested_at",
        (target_id,),
    )
    return [db._row_to_refresh_operation(r) for r in cursor.fetchall()]


# --- POST /projects ----------------------------------------------------------

def test_add_project_returns_202_and_enqueues_targeted_scan(client_and_db, tmp_path):
    client, db, _ = client_and_db
    proj_dir = tmp_path / "new_project"
    proj_dir.mkdir()

    resp = client.post("/projects", json={"name": "New Project", "path": str(proj_dir)})
    assert resp.status_code == 202, f"add must return 202, got {resp.status_code}"

    body = resp.json()
    assert body["id"] == "project:new_project"
    assert body["last_scan_status"] == "pending"

    ops = _queued_project_scan_ops(db, "project:new_project")
    assert len(ops) == 1
    assert ops[0].status == "queued"
    assert ops[0].target_id == "project:new_project"


def test_add_project_rejects_path_outside_allowed_roots(client_and_db, tmp_path, monkeypatch):
    client, db, _ = client_and_db
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("HERMES_ALLOWED_PROJECT_ROOTS", str(allowed))

    resp = client.post("/projects", json={"name": "Evil", "path": "C:/Windows"})
    assert resp.status_code == 400
    assert db.get_project("project:evil") is None


def test_add_project_rejects_file_path(client_and_db, tmp_path, monkeypatch):
    client, db, _ = client_and_db
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("HERMES_ALLOWED_PROJECT_ROOTS", str(allowed))

    a_file = allowed / "not_a_dir.txt"
    a_file.write_text("data")
    resp = client.post("/projects", json={"name": "FileProj", "path": str(a_file)})
    assert resp.status_code == 400
    assert db.get_project("project:fileproj") is None


# --- PUT /projects/{id} ------------------------------------------------------

def test_update_project_returns_202_and_enqueues_targeted_scan(client_and_db):
    client, db, _ = client_and_db

    resp = client.put("/projects/project:contract-demo", json={"description": "updated"})
    assert resp.status_code == 202, f"update must return 202, got {resp.status_code}"
    assert resp.json()["description"] == "updated"

    ops = _queued_project_scan_ops(db, "project:contract-demo")
    assert len(ops) == 1
    assert ops[0].status == "queued"


def test_update_project_not_found_returns_404(client_and_db):
    client, _, _ = client_and_db
    resp = client.put("/projects/project:nonexistent", json={"description": "x"})
    assert resp.status_code == 404


def test_update_project_rejects_path_outside_allowed_roots(client_and_db, tmp_path, monkeypatch):
    client, db, _ = client_and_db
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("HERMES_ALLOWED_PROJECT_ROOTS", str(allowed))

    resp = client.put("/projects/project:contract-demo", json={"path": "C:/Windows"})
    assert resp.status_code == 400
    # Path must not have been mutated.
    assert db.get_project("project:contract-demo").path != "C:/Windows"


# --- DELETE /projects/{id} (idempotent archive) -------------------------------

def test_delete_archive_is_idempotent(client_and_db):
    client, db, _ = client_and_db

    resp1 = client.delete("/projects/project:contract-demo")
    assert resp1.status_code == 200
    proj = db.get_project("project:contract-demo")
    assert proj.is_active is False
    assert proj.status == "archived"

    # Second DELETE on the same project must also succeed (idempotent).
    resp2 = client.delete("/projects/project:contract-demo")
    assert resp2.status_code == 200

    # Unknown project returns 404.
    resp_404 = client.delete("/projects/project:nonexistent")
    assert resp_404.status_code == 404


def test_post_archive_endpoint_removed(client_and_db):
    client, _, _ = client_and_db
    resp = client.post("/projects/project:contract-demo/archive")
    assert resp.status_code == 404, "POST /archive must be removed in favor of idempotent DELETE"


# --- POST /projects/{id}/restore ----------------------------------------------

def test_restore_returns_202_with_targeted_operation(client_and_db):
    client, db, _ = client_and_db

    assert client.delete("/projects/project:contract-demo").status_code == 200

    resp = client.post("/projects/project:contract-demo/restore")
    assert resp.status_code == 202
    op = resp.json()
    assert op["scope"] == "project_scan"
    assert op["target_id"] == "project:contract-demo"
    assert op["status"] == "queued"


# --- Synchronous scan API removed ----------------------------------------------

def test_sync_scan_endpoint_removed(client_and_db):
    client, _, _ = client_and_db
    resp = client.post("/projects/project:contract-demo/scan")
    assert resp.status_code == 404, "Synchronous POST /scan API must be removed"


# --- Path safety unit tests ------------------------------------------------------

def test_get_allowed_project_roots_env_precedence(tmp_path, monkeypatch):
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    monkeypatch.setenv("HERMES_ALLOWED_PROJECT_ROOTS", f"{root_a}{os.pathsep}{root_b}")

    roots = get_allowed_project_roots()
    assert root_a.resolve() in roots
    assert root_b.resolve() in roots


def test_path_validator_requires_existing_directory(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("HERMES_ALLOWED_PROJECT_ROOTS", str(allowed))

    # Existing directory inside allowed root: OK
    inside = allowed / "proj"
    inside.mkdir()
    assert is_path_safe_and_inside_allowed_roots(inside) is True

    # File inside allowed root: rejected
    a_file = allowed / "file.txt"
    a_file.write_text("x")
    assert is_path_safe_and_inside_allowed_roots(a_file) is False

    # Nonexistent directory: rejected
    assert is_path_safe_and_inside_allowed_roots(allowed / "missing") is False


def test_path_validator_rejects_traversal_escape(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HERMES_ALLOWED_PROJECT_ROOTS", str(allowed))

    # Traversal that resolves outside the allowed root must be rejected.
    escape = allowed / ".." / "outside"
    assert is_path_safe_and_inside_allowed_roots(escape) is False

    # Direct outside path rejected as well.
    assert is_path_safe_and_inside_allowed_roots(outside) is False
