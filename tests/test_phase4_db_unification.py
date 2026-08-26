"""Phase 4 — Requirement 1: Unified operational database.

Proves:
1. API and daemon resolve the SAME writable runtime DB via the canonical resolver.
2. Neither the API nor the daemon ever writes to the tracked baseline DB.
3. /health/ready reports resolved path, writability, baseline/runtime identity,
   daemon heartbeat status, and current runtime date/timezone.
4. Readiness FAILS when the API resolves the immutable baseline for operational use.
5. get_db is a generator dependency that closes every connection.
"""
import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_db, get_db_path
from app.api.server import app
from app.storage.db import Database, resolve_db_path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DB = REPO_ROOT / "data" / "tech_intel.db"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def test_canonical_resolver_precedence(tmp_path, monkeypatch):
    """HERMES_DB_PATH > explicit path > default runtime file > repo default."""
    env_db = tmp_path / "env.db"
    explicit = tmp_path / "explicit.db"
    default_rt = tmp_path / "default_rt.db"

    # 1. Env wins over everything
    monkeypatch.setenv("HERMES_DB_PATH", str(env_db))
    assert resolve_db_path(str(explicit), default_rt) == str(env_db.resolve())

    # 2. Explicit path wins when no env
    monkeypatch.delenv("HERMES_DB_PATH", raising=False)
    assert resolve_db_path(str(explicit), default_rt) == str(explicit.resolve())

    # 3. Default runtime file wins when no env/explicit
    assert resolve_db_path(None, default_rt) == str(default_rt.resolve())

    # 4. Repo default when nothing else
    resolved = resolve_db_path(None, None)
    assert resolved.endswith(os.path.join("data", "runtime", "tech_intel.db"))
    # Must NEVER default to the immutable baseline
    assert os.path.abspath(resolved) != str(BASELINE_DB.resolve())


def test_get_db_path_never_defaults_to_baseline(monkeypatch):
    """The API path helper must never fall back to data/tech_intel.db."""
    monkeypatch.delenv("HERMES_DB_PATH", raising=False)
    resolved = get_db_path()
    assert os.path.abspath(resolved) != str(BASELINE_DB.resolve())
    assert resolved.endswith(os.path.join("data", "runtime", "tech_intel.db"))


def test_api_and_daemon_resolve_same_runtime_db(tmp_path, monkeypatch):
    """API dependency and daemon entrypoint must resolve the identical runtime DB."""
    shared_db = tmp_path / "shared_runtime.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(shared_db))

    # API resolution path
    api_path = get_db_path()

    # Daemon resolution path (runner.main uses Database() -> resolve_db_path)
    daemon_path = resolve_db_path(None)

    assert api_path == daemon_path == str(shared_db.resolve())

    # Both open the same writable database
    api_db = Database()
    daemon_db = Database()
    try:
        assert api_db.db_path == daemon_db.db_path
        assert api_db.is_writable and daemon_db.is_writable
        assert not api_db.is_baseline and not daemon_db.is_baseline
    finally:
        api_db.close()
        daemon_db.close()


def test_get_db_is_closing_generator(tmp_path, monkeypatch):
    """get_db must be a generator dependency that closes the connection."""
    db_file = tmp_path / "gen.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))

    gen = get_db()
    db = next(gen)
    assert isinstance(db, Database)
    assert db.conn is not None
    conn = db.conn

    # Exhaust the generator -> finally block closes the connection
    with pytest.raises(StopIteration):
        next(gen)

    # Connection must be closed after generator exhaustion
    with pytest.raises(Exception):
        conn.execute("SELECT 1")


def test_health_ready_extended_fields(tmp_path, monkeypatch):
    """/health/ready reports path, writability, identity, heartbeat, date, tz."""
    db_file = tmp_path / "ready.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(db_file))
    monkeypatch.setenv("HERMES_TEST_INSTANCE_ID", "phase4-test")

    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "ready"
    assert os.path.abspath(data["database_path"]) == str(db_file.resolve())
    assert data["database_writable"] is True
    assert data["is_baseline"] is False
    assert "daemon_heartbeat_alive" in data
    assert "runtime_date" in data and len(data["runtime_date"]) == 10
    assert "runtime_timezone" in data and data["runtime_timezone"]
    assert data["test_instance_id"] == "phase4-test"


def test_health_ready_fails_on_baseline(monkeypatch):
    """Readiness must FAIL (503) when the API resolves the immutable baseline."""
    monkeypatch.setenv("HERMES_DB_PATH", str(BASELINE_DB))

    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert "baseline" in resp.json()["detail"].lower()


def test_baseline_sha_never_changes(tmp_path, monkeypatch):
    """Prove the tracked baseline DB file is never mutated by API or daemon ops."""
    if not BASELINE_DB.exists():
        pytest.skip("Baseline DB not present in this checkout")

    sha_before = _sha256(BASELINE_DB)

    # Exercise a writable runtime DB bootstrapped FROM the baseline (as daemon does)
    runtime_db = tmp_path / "runtime" / "tech_intel.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(runtime_db))

    db = Database()
    try:
        assert db.is_writable and not db.is_baseline
        # Perform a write through the runtime DB
        db.conn.execute(
            "INSERT OR REPLACE INTO runtime_metrics (metric_key, metric_value, updated_at) "
            "VALUES ('phase4_probe', 1, '2026-01-01T00:00:00+00:00')"
        )
        db.conn.commit()
    finally:
        db.close()

    # Exercise the API against the same runtime DB
    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == 200

    sha_after = _sha256(BASELINE_DB)
    assert sha_before == sha_after, "Baseline database file was mutated!"


def test_api_write_lands_in_runtime_db_not_baseline(tmp_path, monkeypatch):
    """A write issued through the API dependency must land in the runtime DB."""
    runtime_db = tmp_path / "rt.db"
    monkeypatch.setenv("HERMES_DB_PATH", str(runtime_db))

    gen = get_db()
    db = next(gen)
    try:
        assert os.path.abspath(db.db_path) == str(runtime_db.resolve())
        db.conn.execute(
            "INSERT OR REPLACE INTO runtime_metrics (metric_key, metric_value, updated_at) "
            "VALUES ('api_write_probe', 42, '2026-01-01T00:00:00+00:00')"
        )
        db.conn.commit()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass

    # Verify the row exists in the runtime DB file directly
    conn = sqlite3.connect(str(runtime_db))
    row = conn.execute(
        "SELECT metric_value FROM runtime_metrics WHERE metric_key = 'api_write_probe'"
    ).fetchone()
    conn.close()
    assert row is not None and row[0] == 42
