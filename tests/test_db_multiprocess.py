import os
import time
import sqlite3
import shutil
import hashlib
import json
import pytest
from pathlib import Path
from multiprocessing import Barrier, Process, Queue

from app.storage.db import (
    Database,
    DatabaseMigrationError,
    DatabaseInitializationError,
    connect_db,
    resolve_db_path
)
from app.models.schemas import DailyBriefing, DailyBriefingItem

# Helper to verify SHA-256
def get_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


# 1. Pure Path Precedence Resolution Test
def test_resolve_db_path(monkeypatch, tmp_path):
    # A. HERMES_DB_PATH precedence
    temp_env_db = str(tmp_path / "env_db.db")
    monkeypatch.setenv("HERMES_DB_PATH", temp_env_db)
    assert resolve_db_path("explicit.db") == os.path.abspath(temp_env_db)
    assert resolve_db_path() == os.path.abspath(temp_env_db)

    # B. Explicit path precedence when HERMES_DB_PATH is not set
    monkeypatch.delenv("HERMES_DB_PATH", raising=False)
    assert resolve_db_path("explicit.db") == os.path.abspath("explicit.db")

    # C. Default runtime path precedence when neither is set
    mock_runtime = tmp_path / "runtime" / "tech_intel.db"
    assert resolve_db_path(None, mock_runtime) == os.path.abspath(str(mock_runtime))


# 2. Default Runtime Bootstrap Test (Injected Baseline & Runtime)
def test_default_runtime_bootstrap(monkeypatch, tmp_path):
    baseline_dir = tmp_path / "baseline_dir"
    baseline_dir.mkdir()
    baseline_db = baseline_dir / "tech_intel.db"
    
    runtime_dir = tmp_path / "runtime_dir"
    runtime_dir.mkdir()
    runtime_db = runtime_dir / "tech_intel.db"

    # Copy real baseline database
    repo_root = Path(__file__).resolve().parents[1]
    real_baseline = repo_root / "data" / "tech_intel.db"
    shutil.copy2(str(real_baseline), str(baseline_db))
    
    # Delete HERMES_DB_PATH so resolution defaults to the injected default runtime
    monkeypatch.delenv("HERMES_DB_PATH", raising=False)

    # Record files in real runtime directory to prove no files are modified there
    real_runtime_dir = repo_root / "data" / "runtime"
    real_runtime_files_before = set(real_runtime_dir.glob("*")) if real_runtime_dir.exists() else set()

    # Instantiate Database
    db = Database(
        db_path=None,
        _baseline_file=baseline_db,
        _default_runtime_file=runtime_db
    )
    
    # Assert database is writable and exists at injected path
    assert os.path.exists(str(runtime_db))
    assert db.is_writable
    db.close()

    # Assert no file was created under the real runtime directory
    real_runtime_files_after = set(real_runtime_dir.glob("*")) if real_runtime_dir.exists() else set()
    new_files = real_runtime_files_after - real_runtime_files_before
    assert not new_files, f"Files leaked to real runtime directory: {new_files}"


# 3. Read-Only Baseline Protection Test
def test_baseline_readonly_protection(monkeypatch, tmp_path):
    temp_baseline = tmp_path / "tech_intel.db"
    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy2(str(repo_root / "data" / "tech_intel.db"), str(temp_baseline))
    
    monkeypatch.setenv("HERMES_DB_PATH", str(temp_baseline))
    
    db = Database(db_path=str(temp_baseline), _baseline_file=temp_baseline)
    assert not db.is_writable
    
    # Lock file must not be created for read-only baseline access
    assert not os.path.exists(str(temp_baseline) + ".lock")
    
    # Calling mutating transaction helper must raise PermissionError
    with pytest.raises(PermissionError):
        db.create_briefing_revision("b1")
        
    # Raw SQLite write bypass must fail structurally
    with pytest.raises(sqlite3.OperationalError):
        db.conn.execute("INSERT INTO user_feedback (id, feedback_text) VALUES ('1', 'bad')")
        
    db.close()


# 4. Lock Acquisition Timeout Test
def test_lock_acquisition_timeout(monkeypatch, tmp_path):
    db_file = str(tmp_path / "timeout.db")
    lock_file = db_file + ".lock"
    
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    
    # Simulate active lock owned by another host
    meta = {
        "pid": 999999,
        "timestamp": time.time(),
        "hostname": "mock_host_other",
        "token": "mock_token"
    }
    with open(lock_file, "w", encoding="utf-8") as f:
        json.dump(meta, f)
        
    # Attempting to initialize with a small timeout must raise DatabaseInitializationError
    with pytest.raises(DatabaseInitializationError) as excinfo:
        Database(db_path=db_file, timeout=0.1)
    assert "timeout" in str(excinfo.value).lower() or "timed out" in str(excinfo.value).lower()


# 5. Stale Lock Crash Recovery Test
def run_lock_holder(db_file, queue):
    try:
        from app.storage.db import InterprocessLock
        lock = InterprocessLock(db_file, timeout=5.0)
        with lock:
            queue.put({
                "status": "ACQUIRED",
                "pid": os.getpid(),
                "token": lock.token,
                "lock_path": lock.lock_path
            })
            time.sleep(30.0)
    except Exception as e:
        queue.put({"status": "ERROR", "error": str(e)})
        os._exit(1)

def test_stale_lock_crash_recovery(monkeypatch, tmp_path):
    db_file = str(tmp_path / "crash_recovery.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    
    queue = Queue()
    p = Process(target=run_lock_holder, args=(db_file, queue))
    p.start()
    
    try:
        try:
            msg = queue.get(timeout=5.0)
        except Exception as e:
            raise AssertionError(f"Child process failed to signal: {e}")
            
        assert msg["status"] == "ACQUIRED", f"Subprocess lock error: {msg.get('error')}"
        child_pid = msg["pid"]
        child_token = msg["token"]
        lock_path = msg["lock_path"]
        
        assert os.path.exists(lock_path)
        with open(lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["pid"] == child_pid
        assert data["token"] == child_token
        
        # Abruptly terminate the process holding the lock
        p.terminate()
        p.join(timeout=2.0)
        assert not p.is_alive()
        
        # Verify the lock file still exists
        assert os.path.exists(lock_path)
        
        # Open second Database instance; it must recover the stale lock and succeed
        db = Database(db_path=db_file)
        assert db.is_writable
        db.close()
    finally:
        if p.is_alive():
            p.terminate()
            p.join(timeout=2.0)


# 6. Concurrent Initialization on Existing Database
def run_init_process(db_file, barrier, queue):
    try:
        os.environ["HERMES_DB_PATH"] = db_file
        barrier.wait()
        db = Database()
        db.close()
        queue.put("SUCCESS")
    except Exception as e:
        import traceback
        queue.put(f"ERROR: {e}\n{traceback.format_exc()}")

def test_multiprocess_initialization_existing(monkeypatch, tmp_path):
    db_file = str(tmp_path / "existing_concurrency.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    
    # Initialize it first
    db = Database(db_path=db_file)
    db.close()
    
    num_processes = 3
    barrier = Barrier(num_processes)
    queue = Queue()
    
    processes = []
    for _ in range(num_processes):
        p = Process(target=run_init_process, args=(db_file, barrier, queue))
        p.start()
        processes.append(p)
        
    for p in processes:
        p.join(timeout=5.0)
        
    results = [queue.get() for _ in range(num_processes)]
    for r in results:
        assert r == "SUCCESS", f"Concurrent initialization failed: {r}"


# 7. Concurrent Bootstraps on Missing Database
def test_multiprocess_bootstrap_missing(monkeypatch, tmp_path):
    db_file = str(tmp_path / "missing_concurrency.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    
    num_processes = 3
    barrier = Barrier(num_processes)
    queue = Queue()
    
    processes = []
    for _ in range(num_processes):
        p = Process(target=run_init_process, args=(db_file, barrier, queue))
        p.start()
        processes.append(p)
        
    for p in processes:
        p.join(timeout=5.0)
        
    results = [queue.get() for _ in range(num_processes)]
    for r in results:
        assert r == "SUCCESS", f"Concurrent bootstrap failed: {r}"
        
    db = Database(db_path=db_file)
    db.close()


# 8. Injected Mid-Migration Failure Rollback
def test_migration_rollback_on_failure(monkeypatch, tmp_path):
    db_file = str(tmp_path / "rollback_test.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    
    # 1. Create a database file with just test_table (so daily_briefings does not exist)
    conn = connect_db(db_file)
    conn.execute("CREATE TABLE test_table (id TEXT PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test_table VALUES ('1', 'hello')")
    conn.commit()
    conn.close()
    
    # 2. Instantiate FailingDatabase.
    class FailingDatabase(Database):
        def _migrate_columns_internal(self, cursor):
            cursor.execute("CREATE TABLE test_mig_table (id TEXT PRIMARY KEY)")
            cursor.execute("ALTER TABLE test_table ADD COLUMN new_val TEXT")
            raise sqlite3.OperationalError("Simulated write error during migration")
            
    with pytest.raises(DatabaseMigrationError):
        FailingDatabase(db_path=db_file)
        
    # 3. Open normally and verify that test_mig_table and new_val do not exist (rolled back),
    # but test_table STILL exists and contains 'hello'!
    db = Database(db_path=db_file)
    cursor = db.conn.cursor()
    tables = {r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "test_mig_table" not in tables
    assert "test_table" in tables
    
    info = cursor.execute("PRAGMA table_info(test_table)").fetchall()
    cols = {r["name"] for r in info}
    assert "new_val" not in cols
    
    row = cursor.execute("SELECT * FROM test_table").fetchone()
    assert row["id"] == "1"
    assert row["val"] == "hello"
    db.close()


# 9. Briefing Revision Snapshots Integrity Test
def test_briefing_revision_integrity(monkeypatch, tmp_path):
    db_file = str(tmp_path / "revision_integrity.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    db = Database(db_path=db_file)
    
    # Insert dummy briefing and item
    cursor = db.conn.cursor()
    cursor.execute("""
        INSERT INTO daily_briefings (
            id, briefing_date, generated_at, total_items, high_priority_count,
            project_relevant_count, content_hash, summary_text, sections_json, created_at,
            runtime_timezone, data_cutoff_at, generation_status, source_status_json,
            daily_run_id, original_generated_at
        ) VALUES ('b1', '2026-08-25', '2026-08-25T08:00:00Z', 1, 1, 1, 'hash123', 'summary', '[]', '2026-08-25T08:00:00Z',
                  'Asia/Kolkata', '2026-08-25T08:00:00Z', 'completed', '{"src": "ok"}', 'run1', '2026-08-25T08:00:00Z')
    """)
    cursor.execute("""
        INSERT INTO daily_briefing_items (
            briefing_id, inbox_item_id, position, section,
            title, summary, story_cluster_id, item_type,
            reason_codes_json, inbox_score, rank_score,
            project_impact_score, matched_project_ids_json, snapshot_version,
            source_published_at, source_updated_at, first_seen_at, last_changed_at,
            last_evaluated_at, surfaced_at, snapshot_date, daily_run_id,
            freshness_kind, freshness_reason, content_hash, source_name
        ) VALUES ('b1', 'item1', 0, 'must_know', 'Title1', 'Summary1', 'cluster1', 'tech', '["R1"]', 0.9, 0.8, 0.7, '["p1"]', 'v1',
                  '2026-08-25T01:00:00Z', '2026-08-25T02:00:00Z', '2026-08-25T03:00:00Z', '2026-08-25T04:00:00Z',
                  '2026-08-25T05:00:00Z', '2026-08-25T06:00:00Z', '2026-08-25', 'run1', 'new_content', 'novelty', 'itemhash', 'sourcename')
    """)
    db.conn.commit()
    
    # Create revision
    rev_id = db.create_briefing_revision('b1')
    assert rev_id is not None
    
    # Verify revision record fields
    cursor.execute("SELECT * FROM daily_briefing_revisions WHERE id = ?", (rev_id,))
    rev_row = cursor.fetchone()
    assert rev_row is not None
    assert rev_row["briefing_id"] == "b1"
    assert rev_row["revision_number"] == 1
    assert rev_row["generated_at"] == "2026-08-25T08:00:00Z"
    assert rev_row["data_cutoff_at"] == "2026-08-25T08:00:00Z"
    assert rev_row["source_status_json"] == '{"src": "ok"}'
    assert rev_row["content_hash"] == "hash123"
    assert rev_row["generation_status"] == "completed"
    assert rev_row["item_count"] == 1
    assert rev_row["daily_run_id"] == "run1"
    assert rev_row["runtime_timezone"] == "Asia/Kolkata"
    assert rev_row["created_at"] == "2026-08-25T08:00:00Z"
    
    # Verify revision items fields
    cursor.execute("SELECT * FROM daily_briefing_revision_items WHERE revision_id = ?", (rev_id,))
    rev_item = cursor.fetchone()
    assert rev_item is not None
    assert rev_item["inbox_item_id"] == "item1"
    assert rev_item["position"] == 0
    assert rev_item["section"] == "must_know"
    assert rev_item["title"] == "Title1"
    assert rev_item["summary"] == "Summary1"
    assert rev_item["story_cluster_id"] == "cluster1"
    assert rev_item["item_type"] == "tech"
    assert rev_item["reason_codes_json"] == '["R1"]'
    assert rev_item["inbox_score"] == 0.9
    assert rev_item["rank_score"] == 0.8
    assert rev_item["project_impact_score"] == 0.7
    assert rev_item["matched_project_ids_json"] == '["p1"]'
    assert rev_item["snapshot_version"] == "v1"
    assert rev_item["source_published_at"] == '2026-08-25T01:00:00Z'
    assert rev_item["source_updated_at"] == '2026-08-25T02:00:00Z'
    assert rev_item["first_seen_at"] == '2026-08-25T03:00:00Z'
    assert rev_item["last_changed_at"] == '2026-08-25T04:00:00Z'
    assert rev_item["last_evaluated_at"] == '2026-08-25T05:00:00Z'
    assert rev_item["surfaced_at"] == '2026-08-25T06:00:00Z'
    assert rev_item["snapshot_date"] == '2026-08-25'
    assert rev_item["daily_run_id"] == 'run1'
    assert rev_item["freshness_kind"] == 'new_content'
    assert rev_item["freshness_reason"] == 'novelty'
    assert rev_item["content_hash"] == 'itemhash'
    assert rev_item["source_name"] == 'sourcename'
    
    # Mutating original should not affect the revision
    cursor.execute("UPDATE daily_briefings SET summary_text = 'new summary' WHERE id = 'b1'")
    cursor.execute("UPDATE daily_briefing_items SET title = 'new title' WHERE briefing_id = 'b1'")
    db.conn.commit()
    
    cursor.execute("SELECT * FROM daily_briefing_revisions WHERE id = ?", (rev_id,))
    assert cursor.fetchone()["content_hash"] == "hash123"
    
    cursor.execute("SELECT * FROM daily_briefing_revision_items WHERE revision_id = ?", (rev_id,))
    assert cursor.fetchone()["title"] == "Title1"
    
    db.close()


# 10. Briefing Revision Item Copy Failure Rolls Back Transaction
def test_briefing_revision_rollback_on_copy_failure(monkeypatch, tmp_path):
    db_file = str(tmp_path / "revision_fail.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    db = Database(db_path=db_file)
    
    cursor = db.conn.cursor()
    cursor.execute("""
        INSERT INTO daily_briefings (
            id, briefing_date, generated_at, total_items, high_priority_count,
            project_relevant_count, content_hash, summary_text, sections_json, created_at,
            runtime_timezone, data_cutoff_at, generation_status, source_status_json,
            daily_run_id, original_generated_at
        ) VALUES ('b1', '2026-08-25', '2026-08-25T08:00:00Z', 1, 1, 1, 'hash123', 'summary', '[]', '2026-08-25T08:00:00Z',
                  'Asia/Kolkata', '2026-08-25T08:00:00Z', 'completed', '{"src": "ok"}', 'run1', '2026-08-25T08:00:00Z')
    """)
    cursor.execute("""
        INSERT INTO daily_briefing_items (
            briefing_id, inbox_item_id, position, section, title
        ) VALUES ('b1', 'item1', 0, 'must_know', 'Title1')
    """)
    db.conn.commit()
    
    original_cursor_method = db.conn.cursor
    
    class MockCursor:
        def __init__(self, real_cursor):
            self.real_cursor = real_cursor
            
        def execute(self, sql, *args, **kwargs):
            if "INSERT INTO daily_briefing_revision_items" in sql:
                raise sqlite3.IntegrityError("Simulated primary key violation during copy")
            return self.real_cursor.execute(sql, *args, **kwargs)
            
        def fetchone(self, *args, **kwargs):
            return self.real_cursor.fetchone(*args, **kwargs)
            
        def fetchall(self, *args, **kwargs):
            return self.real_cursor.fetchall(*args, **kwargs)
            
        def __getattr__(self, name):
            return getattr(self.real_cursor, name)
            
    class WrappedConnection:
        def __init__(self, real_conn):
            self.real_conn = real_conn
            
        def cursor(self, *args, **kwargs):
            real_cursor = original_cursor_method(*args, **kwargs)
            return MockCursor(real_cursor)
            
        def __getattr__(self, name):
            return getattr(self.real_conn, name)
            
    db.conn = WrappedConnection(db.conn)
    
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.create_briefing_revision('b1')
    finally:
        db.conn = db.conn.real_conn
            
    # Verify no revision record exists due to complete rollback
    cursor.execute("SELECT COUNT(*) FROM daily_briefing_revisions")
    assert cursor.fetchone()[0] == 0
    
    db.close()


# 11. Concurrent Revision Creation Producing Unique Revisions
def run_revision_process(db_file, barrier, queue):
    try:
        os.environ["HERMES_DB_PATH"] = db_file
        db = Database()
        barrier.wait()
        rev_id = db.create_briefing_revision('b1')
        db.close()
        queue.put(("SUCCESS", rev_id))
    except Exception as e:
        queue.put(("ERROR", str(e)))

def test_concurrent_revision_creation(monkeypatch, tmp_path):
    db_file = str(tmp_path / "concurrent_revisions.db")
    monkeypatch.setenv("HERMES_DB_PATH", db_file)
    db = Database(db_path=db_file)
    cursor = db.conn.cursor()
    cursor.execute("""
        INSERT INTO daily_briefings (
            id, briefing_date, generated_at, total_items, high_priority_count,
            project_relevant_count, content_hash, summary_text, sections_json, created_at,
            runtime_timezone, data_cutoff_at, generation_status, source_status_json,
            daily_run_id, original_generated_at
        ) VALUES ('b1', '2026-08-25', '2026-08-25T08:00:00Z', 1, 1, 1, 'hash123', 'summary', '[]', '2026-08-25T08:00:00Z',
                  'Asia/Kolkata', '2026-08-25T08:00:00Z', 'completed', '{"src": "ok"}', 'run1', '2026-08-25T08:00:00Z')
    """)
    db.conn.commit()
    db.close()
    
    num_processes = 3
    barrier = Barrier(num_processes)
    queue = Queue()
    
    processes = []
    for _ in range(num_processes):
        p = Process(target=run_revision_process, args=(db_file, barrier, queue))
        p.start()
        processes.append(p)
        
    for p in processes:
        p.join(timeout=5.0)
        
    results = [queue.get() for _ in range(num_processes)]
    
    success_revs = []
    for status, val in results:
        assert status == "SUCCESS", f"Revision process failed: {val}"
        success_revs.append(val)
        
    # Check that all revision numbers 1, 2, 3 were created uniquely
    db = Database(db_path=db_file)
    cursor = db.conn.cursor()
    cursor.execute("SELECT revision_number FROM daily_briefing_revisions ORDER BY revision_number")
    nums = [r[0] for r in cursor.fetchall()]
    assert nums == [1, 2, 3]
    db.close()
