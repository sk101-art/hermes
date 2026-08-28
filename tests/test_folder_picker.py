"""Acceptance tests for the native folder-picker feature.

Covers the plan's 12 proofs:
  1. Dialog selection returns an opaque selection token.
  2. Cancellation returns {"cancelled": true} with no mutation.
  3. POST /projects with a token -> 202 + exact approved root recorded + scan queued.
  4. Arbitrary / typed paths outside allowed roots are rejected.
  5. Expired and replayed selection tokens are rejected.
  6. Duplicate / overlapping / missing / symlink-escape folders are rejected.
  7. Missing client header / non-loopback (external exposure) / bad session -> 4xx.
  8. Approvals persist across ApprovalStore re-instantiation (survive restart).
  9. Revocation stops scans but preserves the project and its history.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.api.routes import get_db
from app.api import security as api_security
from app.storage.db import Database
from app.platform import folder_picker as fp
from app.services import folder_access


CLIENT_HEADERS = {
    "X-Hermes-Client": "hermes-ui",
}


def _completed(returncode, stdout="", stderr=""):
    """Builds a subprocess.CompletedProcess-like result for the fake launcher."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _pick_stdout(path):
    """Emits the exact marker line the native dialog prints on success."""
    import sys
    if sys.platform == "win32":
        return "HERMES_PICK:" + json.dumps({"path": str(path)}) + "\n"
    return str(path) + "\n"


def _make_launcher(result):
    """Returns a launcher callable that always yields the given CompletedProcess."""
    def launcher(args):
        return result
    return launcher


def _make_env(tmp_path, monkeypatch, set_policy: bool):
    """Shared environment builder for the picker fixtures.

    ``set_policy=True`` installs an explicit HERMES_ALLOWED_PROJECT_ROOTS
    administrator ceiling (roots_dir). ``set_policy=False`` leaves the policy
    unset so only legacy/default roots exist and native-picker approvals may
    reach any otherwise-safe folder.
    """
    db_path = tmp_path / "test_picker.db"
    approvals_file = tmp_path / "approved_project_roots.json"
    roots_dir = tmp_path / "roots"
    roots_dir.mkdir()

    monkeypatch.setenv("HERMES_DB_PATH", str(db_path))
    monkeypatch.setenv("HERMES_APPROVED_ROOTS_FILE", str(approvals_file))
    if set_policy:
        monkeypatch.setenv("HERMES_ALLOWED_PROJECT_ROOTS", str(roots_dir))
    else:
        monkeypatch.delenv("HERMES_ALLOWED_PROJECT_ROOTS", raising=False)

    db = Database(db_path=str(db_path))

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    # Reset all process-global state so tests are independent.
    folder_access.get_token_stores().clear()
    folder_access.picker_rate_limiter.reset()
    api_security.set_external_exposure(False)

    client = TestClient(app)

    return {
        "client": client,
        "db": db,
        "tmp_path": tmp_path,
        "roots_dir": roots_dir,
        "approvals_file": approvals_file,
    }


def _teardown_env(env):
    app.dependency_overrides.clear()
    fp.set_default_picker(None)
    api_security.set_external_exposure(False)
    folder_access.get_token_stores().clear()
    folder_access.picker_rate_limiter.reset()
    env["db"].close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated environment WITH an explicit admin policy ceiling (roots_dir)."""
    env = _make_env(tmp_path, monkeypatch, set_policy=True)
    yield env
    _teardown_env(env)


@pytest.fixture
def env_open(tmp_path, monkeypatch):
    """Isolated environment WITHOUT HERMES_ALLOWED_PROJECT_ROOTS: no admin
    policy ceiling, only legacy/default roots. Native-picker approvals may
    reach folders outside those legacy roots."""
    env = _make_env(tmp_path, monkeypatch, set_policy=False)
    yield env
    _teardown_env(env)


def _session(client):
    """Issues a local session token (loopback + client-header protected)."""
    resp = client.post("/local/session", headers=CLIENT_HEADERS)
    assert resp.status_code == 200, resp.text
    token = resp.json()["session_token"]
    assert token
    return token


def _headers(session_token):
    h = dict(CLIENT_HEADERS)
    h["X-Hermes-Session"] = session_token
    return h


def _select_folder(client, session_token, picker_result):
    """Installs a fake picker and calls POST /local/folder-selection."""
    fp.set_default_picker(fp.FolderPicker(launcher=_make_launcher(picker_result)))
    return client.post("/local/folder-selection", headers=_headers(session_token))


# --- 1. Dialog selection returns a token -------------------------------------
def test_dialog_selection_returns_token(env):
    client = env["client"]
    target = env["roots_dir"] / "proj_alpha"
    target.mkdir()

    session = _session(client)
    resp = _select_folder(client, session, _completed(0, _pick_stdout(target)))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["selection_token"]
    assert body["folder_name"] == "proj_alpha"
    assert "expires_at" in body
    # The display path is the exact directory chosen in the dialog.
    assert Path(body["display_path"]).resolve() == target.resolve()


# --- 2. Cancellation -> {"cancelled": true}, no mutation ---------------------
def test_dialog_cancel_no_mutation(env):
    client = env["client"]
    session = _session(client)

    # Exit code 3 == user dismissed the dialog.
    resp = _select_folder(client, session, _completed(3, "HERMES_PICK_CANCELLED\n"))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"cancelled": True}

    # No selection token was issued and nothing was approved.
    assert folder_access.get_approval_store().list_records() == []
    assert env["db"].get_all_projects(active_only=False) == []


# --- 3. Token flow -> 202 + exact approved root + scan queued ----------------
def test_add_project_with_token_202_and_exact_root(env):
    client = env["client"]
    target = env["roots_dir"] / "proj_beta"
    target.mkdir()
    (target / "package.json").write_text('{"dependencies": {"express": "^4.18.2"}}')

    session = _session(client)
    sel = _select_folder(client, session, _completed(0, _pick_stdout(target)))
    token = sel.json()["selection_token"]

    resp = client.post(
        "/projects",
        headers=_headers(session),
        json={"name": "Proj Beta", "description": "d", "folder_selection_token": token},
    )
    assert resp.status_code == 202, resp.text
    proj = resp.json()
    assert proj["id"] == "project:proj_beta"

    # Exactly one approval, for the exact selected directory.
    records = folder_access.get_approval_store().list_records()
    assert len(records) == 1
    assert Path(records[0]["path"]).resolve() == target.resolve()
    assert records[0]["approval_source"] == "native_picker"
    assert records[0]["state"] == "active"
    assert records[0]["project_id"] == "project:proj_beta"

    # A targeted project_scan operation was queued.
    ops = [
        op for op in (env["db"].get_all_refresh_operations() if hasattr(env["db"], "get_all_refresh_operations") else [])
    ]
    # Fall back to scanning the refresh_operations table directly if no helper.
    if not ops:
        rows = env["db"].conn.execute(
            "SELECT scope, target_id, status FROM refresh_operations"
        ).fetchall()
        assert any(r[0] == "project_scan" and r[1] == "project:proj_beta" for r in rows)
    else:
        assert any(op.scope == "project_scan" and op.target_id == "project:proj_beta" for op in ops)


# --- 4. Arbitrary typed path outside allowed roots is rejected ---------------
def test_arbitrary_path_rejected(env):
    client = env["client"]
    outside = env["tmp_path"] / "not_in_roots"
    outside.mkdir()

    resp = client.post(
        "/projects",
        headers=CLIENT_HEADERS,
        json={"name": "Sneaky", "path": str(outside)},
    )
    assert resp.status_code == 400, resp.text
    assert env["db"].get_all_projects(active_only=False) == []


# --- 5. Expired and replayed tokens are rejected -----------------------------
def test_expired_and_replayed_tokens_rejected(env):
    client = env["client"]
    target = env["roots_dir"] / "proj_gamma"
    target.mkdir()

    session = _session(client)

    # Replay: a token can only be consumed once.
    sel = _select_folder(client, session, _completed(0, _pick_stdout(target)))
    token = sel.json()["selection_token"]
    first = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Proj Gamma", "folder_selection_token": token},
    )
    assert first.status_code == 202, first.text
    replay = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Proj Gamma Two", "folder_selection_token": token},
    )
    assert replay.status_code == 400, replay.text

    # Expired: force the token's expiry into the past, then try to use it.
    target2 = env["roots_dir"] / "proj_delta"
    target2.mkdir()
    sel2 = _select_folder(client, session, _completed(0, _pick_stdout(target2)))
    token2 = sel2.json()["selection_token"]
    from datetime import datetime, timedelta, timezone
    store = folder_access.get_token_stores()
    store._selections[token2]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Proj Delta", "folder_selection_token": token2},
    )
    assert expired.status_code == 400, expired.text
    assert env["db"].get_project("project:proj_delta") is None


# --- 6. Duplicate / overlap / missing / symlink-escape rejected --------------
def test_duplicate_and_overlap_rejected(env):
    client = env["client"]
    session = _session(client)

    base = env["roots_dir"] / "proj_existing"
    base.mkdir()
    sel = _select_folder(client, session, _completed(0, _pick_stdout(base)))
    ok = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Proj Existing", "folder_selection_token": sel.json()["selection_token"]},
    )
    assert ok.status_code == 202, ok.text

    # Duplicate: same folder again — safety validation rejects it at selection
    # time, so no token is ever issued for an already-registered folder.
    sel_dup = _select_folder(client, session, _completed(0, _pick_stdout(base)))
    assert sel_dup.status_code == 400, sel_dup.text
    assert "selection_token" not in sel_dup.json()

    # Overlap: a nested subfolder of an already-registered project is likewise
    # rejected before any token exists.
    nested = base / "sub"
    nested.mkdir()
    sel_nested = _select_folder(client, session, _completed(0, _pick_stdout(nested)))
    assert sel_nested.status_code == 400, sel_nested.text
    assert "selection_token" not in sel_nested.json()


def test_missing_folder_rejected(env):
    client = env["client"]
    session = _session(client)
    ghost = env["roots_dir"] / "does_not_exist"

    # A nonexistent folder fails safety validation at selection time: no token.
    sel = _select_folder(client, session, _completed(0, _pick_stdout(ghost)))
    assert sel.status_code == 400, sel.text
    assert "selection_token" not in sel.json()
    assert env["db"].get_all_projects(active_only=False) == []


def test_symlink_escape_rejected(env):
    client = env["client"]
    session = _session(client)

    outside = env["tmp_path"] / "outside_target"
    outside.mkdir()
    link = env["roots_dir"] / "escape_link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("Cannot create directory symlink on this platform/session.")

    # Selecting the link resolves to a different directory than the one
    # chosen: symlink escape is rejected at selection time, no token issued.
    sel = _select_folder(client, session, _completed(0, _pick_stdout(link)))
    assert sel.status_code == 400, sel.text
    assert "selection_token" not in sel.json()


# --- 7. Origin / header / session protections --------------------------------
def test_missing_client_header_rejected(env):
    client = env["client"]
    resp = client.post("/local/session")  # no X-Hermes-Client header
    assert resp.status_code == 400, resp.text


def test_external_exposure_blocks_picker(env):
    client = env["client"]
    api_security.set_external_exposure(True)
    session_headers = dict(CLIENT_HEADERS)
    resp = client.post("/local/session", headers=session_headers)
    assert resp.status_code == 403, resp.text
    resp2 = client.post("/local/folder-selection", headers=session_headers)
    assert resp2.status_code == 403, resp2.text


def test_bad_session_token_rejected(env):
    client = env["client"]
    target = env["roots_dir"] / "proj_sess"
    target.mkdir()
    fp.set_default_picker(fp.FolderPicker(launcher=_make_launcher(_completed(0, _pick_stdout(target)))))
    resp = client.post(
        "/local/folder-selection",
        headers={**CLIENT_HEADERS, "X-Hermes-Session": "not-a-real-token"},
    )
    assert resp.status_code == 401, resp.text


def test_session_mismatch_rejected(env):
    client = env["client"]
    target = env["roots_dir"] / "proj_mismatch"
    target.mkdir()

    session_a = _session(client)
    session_b = _session(client)
    sel = _select_folder(client, session_a, _completed(0, _pick_stdout(target)))
    token = sel.json()["selection_token"]

    # Token belongs to session A; using session B must fail.
    resp = client.post(
        "/projects", headers=_headers(session_b),
        json={"name": "Mismatch", "folder_selection_token": token},
    )
    assert resp.status_code == 400, resp.text


def test_rate_limit_picker(env):
    client = env["client"]
    session = _session(client)
    target = env["roots_dir"] / "proj_rate"
    target.mkdir()
    fp.set_default_picker(fp.FolderPicker(launcher=_make_launcher(_completed(3, "HERMES_PICK_CANCELLED\n"))))

    limit = folder_access.PICKER_RATE_LIMIT_MAX_CALLS
    for _ in range(limit):
        r = client.post("/local/folder-selection", headers=_headers(session))
        assert r.status_code == 200, r.text
    blocked = client.post("/local/folder-selection", headers=_headers(session))
    assert blocked.status_code == 429, blocked.text


# --- 8. Approvals survive restart (re-instantiation) -------------------------
def test_approvals_persist_across_restart(env):
    store = folder_access.get_approval_store()
    target = env["roots_dir"] / "proj_persist"
    target.mkdir()
    store.approve(str(target), project_id="project:proj_persist", source="native_picker")

    # A brand-new store instance reading the same ledger sees the approval.
    fresh = folder_access.ApprovalStore(env["approvals_file"])
    records = fresh.list_records()
    assert len(records) == 1
    assert Path(records[0]["path"]).resolve() == target.resolve()
    assert records[0]["state"] == "active"


# --- 9. Revocation stops scans but preserves project + history ---------------
def test_revocation_stops_scan_keeps_history(env):
    client = env["client"]
    session = _session(client)
    target = env["roots_dir"] / "proj_revoke"
    target.mkdir()
    (target / "main.py").write_text("print('hi')\n")

    sel = _select_folder(client, session, _completed(0, _pick_stdout(target)))
    ok = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Proj Revoke", "folder_selection_token": sel.json()["selection_token"]},
    )
    assert ok.status_code == 202, ok.text
    project_id = ok.json()["id"]

    # Scan works while approved.
    from app.services.projects import scan_single_project
    res = scan_single_project(project_id, db=env["db"])
    assert res["status"] == "completed", res

    # Revoke access.
    rev = client.post(
        "/local/folder-approvals/revoke", headers=_headers(session),
        json={"project_id": project_id},
    )
    assert rev.status_code == 200, rev.text

    # Project and its stored files/history are preserved.
    assert env["db"].get_project(project_id) is not None
    assert folder_access.get_approval_store().is_revoked(str(target)) is True

    # Future scans are refused for the revoked folder.
    with pytest.raises(ValueError):
        scan_single_project(project_id, db=env["db"])

    # The batch context scan silently skips the revoked project.
    from app.runtime.jobs import run_context_scan
    summary = run_context_scan(env["db"])
    assert summary["status"] == "completed"


# --- 10. Approval deadlock fix: picker selections outside legacy roots --------
# The native picker IS the approval. Legacy/default allowed roots (config seeds
# + built-in defaults) must never reject a safe picker selection; only an
# explicit HERMES_ALLOWED_PROJECT_ROOTS policy can.

ASCEL_PATH = Path(r"C:\Users\sujay\Downloads\ascel")


def test_select_ascel_outside_default_roots_succeeds(env_open):
    """Selecting C:\\Users\\sujay\\Downloads\\ascel — outside every legacy/
    default allowed root and with NO admin policy set — succeeds end to end."""
    if not ASCEL_PATH.is_dir():
        pytest.skip("C:\\Users\\sujay\\Downloads\\ascel is not present on this machine.")

    client = env_open["client"]
    session = _session(client)

    sel = _select_folder(client, session, _completed(0, _pick_stdout(ASCEL_PATH)))
    assert sel.status_code == 200, sel.text
    token = sel.json()["selection_token"]

    resp = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Ascel", "description": "picker-approved", "folder_selection_token": token},
    )
    assert resp.status_code == 202, resp.text
    proj = resp.json()
    assert proj["id"] == "project:ascel"
    assert Path(proj["path"]).resolve() == ASCEL_PATH.resolve()

    # The targeted scan was queued for exactly this project.
    rows = env_open["db"].conn.execute(
        "SELECT scope, target_id, status FROM refresh_operations"
    ).fetchall()
    assert any(r[0] == "project_scan" and r[1] == "project:ascel" and r[2] == "queued" for r in rows)


def test_only_exact_folder_approved_never_parent(env_open):
    """Approving Downloads/ascel must NEVER approve all of Downloads."""
    if not ASCEL_PATH.is_dir():
        pytest.skip("C:\\Users\\sujay\\Downloads\\ascel is not present on this machine.")

    client = env_open["client"]
    session = _session(client)

    sel = _select_folder(client, session, _completed(0, _pick_stdout(ASCEL_PATH)))
    assert sel.status_code == 200, sel.text
    resp = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Ascel", "folder_selection_token": sel.json()["selection_token"]},
    )
    assert resp.status_code == 202, resp.text

    records = folder_access.get_approval_store().list_records()
    assert len(records) == 1
    approved = Path(records[0]["path"]).resolve()
    assert approved == ASCEL_PATH.resolve()

    # The parent (Downloads) is NOT approved, and the approval does not
    # extend to sibling folders.
    downloads = ASCEL_PATH.parent
    assert approved != downloads.resolve()
    from app.context.scanner import is_subpath
    # A sibling directory is not covered by the exact-folder approval.
    sibling = downloads / "ascel-sibling-not-approved"
    assert not is_subpath(sibling, approved)
    # The ledger contains exactly one record — never the parent.
    assert all(Path(r["path"]).resolve() != downloads.resolve() for r in records)


def test_manual_path_without_picker_token_fails(env_open):
    """A manually typed path outside legacy roots must fail without a token —
    the picker approval flow can never be bypassed by typing a path."""
    if not ASCEL_PATH.is_dir():
        pytest.skip("C:\\Users\\sujay\\Downloads\\ascel is not present on this machine.")

    client = env_open["client"]
    resp = client.post(
        "/projects", headers=CLIENT_HEADERS,
        json={"name": "Sneaky Ascel", "path": str(ASCEL_PATH)},
    )
    assert resp.status_code == 400, resp.text
    assert env_open["db"].get_project("project:sneaky_ascel") is None
    # Nothing was approved either.
    assert folder_access.get_approval_store().list_records() == []


def test_explicit_env_policy_blocks_out_of_policy_picker_selection(env):
    """When HERMES_ALLOWED_PROJECT_ROOTS is explicitly set, it is the hard
    admin ceiling: even a native-picker selection outside it is rejected."""
    client = env["client"]
    session = _session(client)

    outside_policy = env["tmp_path"] / "outside_policy"
    outside_policy.mkdir()

    sel = _select_folder(client, session, _completed(0, _pick_stdout(outside_policy)))
    assert sel.status_code == 400, sel.text
    assert "selection_token" not in sel.json()
    assert folder_access.get_approval_store().list_records() == []
    assert env["db"].get_all_projects(active_only=False) == []


def test_create_approve_scan_are_atomic(env_open):
    """If project creation fails after the approval was written, everything is
    rolled back: no approval, no project, no queued scan — and the token is
    consumed so it can never be replayed."""
    from app.services import projects as projects_service

    target = env_open["tmp_path"] / "atomic_proj"
    target.mkdir()

    client = env_open["client"]
    session = _session(client)
    sel = _select_folder(client, session, _completed(0, _pick_stdout(target)))
    assert sel.status_code == 200, sel.text
    token = sel.json()["selection_token"]

    def boom(**kwargs):
        raise ValueError("simulated project-creation failure")

    # Force the creation step to fail after the approval has been persisted.
    import app.services.projects as _ps
    original = _ps.add_project
    _ps.add_project = boom
    try:
        resp = client.post(
            "/projects", headers=_headers(session),
            json={"name": "Atomic", "folder_selection_token": token},
        )
    finally:
        _ps.add_project = original

    assert resp.status_code == 400, resp.text

    # Approval rolled back — the ledger is empty.
    assert folder_access.get_approval_store().list_records() == []
    # No project row.
    assert env_open["db"].get_project("project:atomic") is None
    # No scan was queued.
    rows = env_open["db"].conn.execute("SELECT * FROM refresh_operations").fetchall()
    assert rows == []

    # The token was consumed by the failed attempt: replay must fail.
    replay = client.post(
        "/projects", headers=_headers(session),
        json={"name": "Atomic Replay", "folder_selection_token": token},
    )
    assert replay.status_code == 400, replay.text
    assert env_open["db"].get_project("project:atomic_replay") is None
