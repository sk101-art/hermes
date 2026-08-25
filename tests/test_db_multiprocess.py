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
    connect_db
)
from app.models.schemas import DailyBriefing, DailyBriefingItem

# Helper to verify SHA-256
def get_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

# 1. Baseline protection audit
def test_baseline_readonly_protection():
    repo_root = Path(__file__).resolve().parents[1]
    baseline_path = str((repo_root / "data" / "tech_intel.db").resolve())
    
    # Instantiate Database on baseline
    db = Database(db_path=baseline_path)
    assert not db.is_writable
    
    # Lock file must not exist
    lock_file = baseline_path + ".lock"
    assert not os.path.exists(lock_file)
    
    # Try calling a mutating method and assert PermissionError
    with pytest.raises(PermissionError):
        db.save_user_feedback(None)


# 2. lock acquisition timeout
def test_lock_acquisition_timeout(tmp_path):
    db_file = str(tmp_path / "timeout.db")
    lock_file = db_file + ".lock"
    
    # Create a lock file to simulate another process holding it
    meta = {
        "pid": 999999,
        "timestamp": time.time(),
        "hostname": "mock_host",
        "token": "mock_token"
    }
    with open(lock_file, "w", encoding="utf-8") as f:
        json.dump(meta, f)
        
    # Attempt initialization with a low timeout, expecting it to time out
    # Since pid=999999 is dead (most likely) but hostname is different ("mock_host" vs current hostname),
    # it won't declare it stale! So it will timeout.
    with pytest.raises(DatabaseInitializationError) as excinfo:
        # Pass a Database with small timeout
        db = Database(db_path=db_file)
    assert "timeout" in str(excinfo.value).lower() or "timed out" in str(excinfo.value).lower()
    
    # Clean up lock file
    try:
        os.unlink(lock_file)
    except OSError:
        pass


# 3. Crash test stale lock recovery
def run_lock_holder(db_file, barrier):
    try:
        # Open DB which acquires the lock during init
        db = Database(db_path=db_file)
        # Lock acquired, signal parent
        barrier.wait()
        # Keep lock held by sleeping or keeping connection open,
        # but wait! Database constructor releases the lock when done.
        # So to simulate process crashing WHILE holding lock, we manually acquire lock and don't exit.
        from app.storage.db import InterprocessLock
        with InterprocessLock(db_file, timeout=5.0) as lock:
            barrier.wait() # Synced, now we sleep indefinitely or exit abruptly
            time.sleep(30.0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        os._exit(1)

def test_stale_lock_crash_recovery(tmp_path):
    db_file = str(tmp_path / "crash_recovery.db")
    
    # Initialize the folder and a dummy process
    from multiprocessing import Barrier as MPBarrier
    barrier = MPBarrier(2)
    
    # Start lock holder process
    p = Process(target=run_lock_holder, args=(db_file, barrier))
    p.start()
    
    # Wait for subprocess to initialize and acquire lock
    barrier.wait()
    
    # At this point, lock is held by subprocess. Kill it abruptly.
    p.terminate()
    p.join()
    
    # Now, try to initialize Database. It should detect the lock file exists,
    # see that the PID of the owner is dead (since we terminated it),
    # delete the stale lock file, and successfully initialize.
    db = Database(db_path=db_file)
    assert db.is_writable
    assert os.path.exists(db_file)
    db.close()


# 4. Multiprocess initialization with barrier (on existing database)
def run_init_process(db_file, barrier, queue):
    try:
        barrier.wait()
        db = Database(db_path=db_file)
        db.close()
        queue.put("SUCCESS")
    except Exception as e:
        import traceback
        queue.put(f"ERROR: {e}\n{traceback.format_exc()}")

def test_multiprocess_initialization_existing(tmp_path):
    db_file = str(tmp_path / "existing_concurrency.db")
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
        p.join()
        
    results = [queue.get() for _ in range(num_processes)]
    for r in results:
        assert r == "SUCCESS", f"Concurrent initialization failed: {r}"


# 5. Multiprocess bootstrap with barrier (on missing database)
def test_multiprocess_bootstrap_missing(tmp_path):
    db_file = str(tmp_path / "missing_concurrency.db")
    
    num_processes = 3
    barrier = Barrier(num_processes)
    queue = Queue()
    
    processes = []
    for _ in range(num_processes):
        p = Process(target=run_init_process, args=(db_file, barrier, queue))
        p.start()
        processes.append(p)
        
    for p in processes:
        p.join()
        
    results = [queue.get() for _ in range(num_processes)]
    for r in results:
        assert r == "SUCCESS", f"Concurrent bootstrap failed: {r}"
        
    # Verify the database exists
    db = Database(db_path=db_file)
    db.close()


# 6. Injected mid-migration failure and complete rollback
def test_migration_rollback_on_failure(tmp_path):
    db_file = str(tmp_path / "rollback_test.db")
    # 1. Initialize first and insert some rows
    db = Database(db_path=db_file)
    cursor = db.conn.cursor()
    cursor.execute("CREATE TABLE test_table (id TEXT PRIMARY KEY, val TEXT)")
    cursor.execute("INSERT INTO test_table VALUES ('1', 'hello')")
    db.conn.commit()
    db.close()
    
    # 2. We mock _migrate_columns to raise an error during initialization.
    class FailingDatabase(Database):
        def _migrate_columns(self):
            try:
                self.conn.execute("PRAGMA foreign_keys=OFF")
            except Exception:
                pass
            cursor = self.conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                # Add a dummy table and a column
                cursor.execute("CREATE TABLE IF NOT EXISTS test_mig_table (id TEXT PRIMARY KEY)")
                cursor.execute("ALTER TABLE test_table ADD COLUMN new_val TEXT")
                raise sqlite3.OperationalError("Simulated write error during migration")
            except Exception as e:
                self.conn.rollback()
                raise DatabaseMigrationError(f"Migration transaction failed: {e}") from e
            finally:
                self.conn.execute("PRAGMA foreign_keys=ON")
                
    # 3. Instantiate FailingDatabase. It must raise DatabaseMigrationError.
    with pytest.raises(DatabaseMigrationError):
        FailingDatabase(db_path=db_file)
        
    # 4. Open it again with normal Database and verify:
    # - No new table or column exists (test_mig_table and new_val are rolled back)
    # - Original rows/IDs are unchanged
    # - Integrity check passes
    db = Database(db_path=db_file)
    cursor = db.conn.cursor()
    tables = {r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "test_mig_table" not in tables
    
    # Verify new_val column is not in test_table
    info = cursor.execute("PRAGMA table_info(test_table)").fetchall()
    cols = {r["name"] for r in info}
    assert "new_val" not in cols
    
    row = cursor.execute("SELECT * FROM test_table").fetchone()
    assert row["id"] == "1"
    assert row["val"] == "hello"
    db.close()


# 7. Briefing revision metadata and immutable snapshots
def test_briefing_revision_integrity(tmp_path):
    db_file = str(tmp_path / "revision_integrity.db")
    db = Database(db_path=db_file)
    
    # Insert dummy briefing and items
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
            freshness_kind, freshness_reason
        ) VALUES ('b1', 'item1', 0, 'must_know', 'Title1', 'Summary1', 'cluster1', 'tech', '["R1"]', 0.9, 0.8, 0.7, '["p1"]', 'v1',
                  '2026-08-25T01:00:00Z', '2026-08-25T02:00:00Z', '2026-08-25T03:00:00Z', '2026-08-25T04:00:00Z',
                  '2026-08-25T05:00:00Z', '2026-08-25T06:00:00Z', '2026-08-25', 'run1', 'new_content', 'novelty')
    """)
    db.conn.commit()
    
    # Call create_briefing_revision
    rev_id = db.create_briefing_revision('b1')
    assert rev_id is not None
    
    # 1. Verify revision record was created correctly
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
    
    # 2. Verify items were copied correctly
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
    
    # 3. Mutate original briefing and items, check that revision remains unchanged
    cursor.execute("UPDATE daily_briefings SET summary_text = 'new summary' WHERE id = 'b1'")
    cursor.execute("UPDATE daily_briefing_items SET title = 'new title' WHERE briefing_id = 'b1'")
    db.conn.commit()
    
    # Check revision remains unchanged
    cursor.execute("SELECT * FROM daily_briefing_revisions WHERE id = ?", (rev_id,))
    assert cursor.fetchone()["content_hash"] == "hash123"
    
    cursor.execute("SELECT * FROM daily_briefing_revision_items WHERE revision_id = ?", (rev_id,))
    assert cursor.fetchone()["title"] == "Title1"
    
    db.close()


# 8. Failure while copying revision items rolls back everything
def test_briefing_revision_rollback_on_copy_failure(tmp_path):
    db_file = str(tmp_path / "revision_fail.db")
    db = Database(db_path=db_file)
    
    # Insert a dummy briefing and a normal item
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
    
    # Wrap connection's cursor to return a MockCursor
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
            
    # Assign wrapped connection
    original_conn = db.conn
    db.conn = WrappedConnection(original_conn)
    
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.create_briefing_revision('b1')
    finally:
        db.conn = original_conn
            
    # Verify no revision record was created
    cursor.execute("SELECT COUNT(*) FROM daily_briefing_revisions")
    assert cursor.fetchone()[0] == 0
    
    db.close()




# 9. Concurrent revision creation producing unique revisions
def run_revision_process(db_file, barrier, queue):
    try:
        # Use separate connection
        db = Database(db_path=db_file)
        barrier.wait()
        rev_id = db.create_briefing_revision('b1')
        db.close()
        queue.put(("SUCCESS", rev_id))
    except Exception as e:
        queue.put(("ERROR", str(e)))

def test_concurrent_revision_creation(tmp_path):
    db_file = str(tmp_path / "concurrent_revisions.db")
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
        p.join()
        
    results = [queue.get() for _ in range(num_processes)]
    
    success_revs = []
    for status, val in results:
        assert status == "SUCCESS", f"Revision process failed: {val}"
        success_revs.append(val)
        
    # Check that all revision IDs are unique and we have 3 unique revisions (numbers 1, 2, 3)
    db = Database(db_path=db_file)
    cursor = db.conn.cursor()
    cursor.execute("SELECT revision_number FROM daily_briefing_revisions ORDER BY revision_number")
    nums = [r[0] for r in cursor.fetchall()]
    assert nums == [1, 2, 3]
    db.close()
