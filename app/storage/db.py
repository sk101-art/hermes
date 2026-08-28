import json
import os
import sqlite3
import time
import socket
import uuid
import ctypes
import shutil
import hashlib
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from app.models.schemas import (
    Event,
    StoryCluster,
    Relationship,
    Claim,
    Evidence,
    TechnologyAssessment,
    ClaimRevision,
    TechnologyAssessmentRevision,
    TechnologyState,
    RecheckQueueItem,
    IntelligenceChange,
    Project,
    ProjectFile,
    ProjectTechnologyProfile,
    ProjectMatch,
    ProjectMatchExplanation,
    ProjectNarrative,
    InboxItem,
    SavedItem,
    UserFeedback,
    DailyBriefing,
    DailyBriefingItem,
    SourceCheckpoint,
    RuntimeJob,
    RuntimeJobRun,
    DailySignalRun,
    RefreshOperation,
)



class DatabaseMigrationError(Exception):
    """Raised when an unexpected database schema migration or table rebuild failure occurs."""
    pass


class DatabaseInitializationError(Exception):
    """Raised when database initialization, locking, or bootstrap fails."""
    pass


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == 'nt':
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                success = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                if success:
                    # 259 is STILL_ACTIVE
                    return exit_code.value == 259
                return True
            err = kernel32.GetLastError()
            if err == 5:  # Access Denied means process is alive
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except OSError as e:
        if getattr(e, 'errno', None) == 1:  # EPERM (operation not permitted)
            return True
        return False
    except Exception:
        return True



def connect_db(db_path: str, timeout: float = 10.0, read_only: bool = False, journal_mode: Optional[str] = None, **kwargs) -> sqlite3.Connection:
    conn = None
    try:
        if read_only:
            path_uri = Path(os.path.abspath(db_path)).as_uri()
            uri_str = f"{path_uri}?mode=ro&immutable=1"
            conn = sqlite3.connect(uri_str, timeout=timeout, uri=True, check_same_thread=False, **kwargs)
        else:
            conn = sqlite3.connect(db_path, timeout=timeout, check_same_thread=False, **kwargs)
            
        conn.row_factory = sqlite3.Row
        
        # 1. Verify busy_timeout
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        if int(bt) != int(timeout * 1000):
            raise DatabaseInitializationError(f"Failed to verify busy_timeout (got {bt})")
            
        # 2. Verify journal_mode
        if journal_mode and not read_only:
            actual_jm = conn.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()[0]
            if actual_jm.upper() != journal_mode.upper():
                raise DatabaseInitializationError(f"Failed to verify journal_mode {journal_mode} (got {actual_jm})")
                
        # 3. Verify foreign_keys
        conn.execute("PRAGMA foreign_keys=ON")
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if int(fk) != 1:
            raise DatabaseInitializationError("Failed to enable foreign_keys pragma.")
            
        # 4. Verify query_only
        if read_only:
            conn.execute("PRAGMA query_only=ON")
            qo = conn.execute("PRAGMA query_only").fetchone()[0]
            if int(qo) != 1:
                raise DatabaseInitializationError("Failed to verify query_only for read-only database.")
                
        return conn
    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if isinstance(e, DatabaseInitializationError):
            raise
        raise DatabaseInitializationError(f"Failed to configure database connection: {e}") from e



class InterprocessLock:
    def __init__(self, db_path: str, timeout: float = 10.0):
        self.db_path = os.path.abspath(db_path)
        self.lock_path = self.db_path + ".lock"
        self.timeout = timeout
        self.token = str(uuid.uuid4())
        self.acquired = False

    def __enter__(self):
        start = time.monotonic()
        while True:
            try:
                # Try to create exclusively
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    meta = {
                        "pid": os.getpid(),
                        "timestamp": time.time(),
                        "hostname": socket.gethostname(),
                        "token": self.token
                    }
                    os.write(fd, json.dumps(meta).encode("utf-8"))
                finally:
                    os.close(fd)
                self.acquired = True
                break
            except FileExistsError:
                # Lock file exists, check if it's stale
                if os.path.exists(self.lock_path):
                    try:
                        mtime = os.path.getmtime(self.lock_path)
                        age = time.time() - mtime
                    except Exception:
                        age = 0
                    
                    is_stale = False
                    stale_token = None
                    if age > 2.0:  # 2.0-second grace period
                        try:
                            with open(self.lock_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            pid = data.get("pid")
                            hostname = data.get("hostname")
                            stale_token = data.get("token")
                            if hostname == socket.gethostname():
                                if pid and not is_pid_alive(pid):
                                    is_stale = True
                        except (json.JSONDecodeError, ValueError, KeyError, OSError):
                            is_stale = True
                            
                    if is_stale:
                        try:
                            # Re-open and re-read immediately before deletion to prevent race condition
                            with open(self.lock_path, "r", encoding="utf-8") as f:
                                re_read_data = json.load(f)
                            if re_read_data.get("token") == stale_token:
                                os.unlink(self.lock_path)
                        except (json.JSONDecodeError, ValueError, KeyError, OSError) as cleanup_err:
                            if stale_token is None:
                                try:
                                    os.unlink(self.lock_path)
                                except OSError as unlink_err:
                                    import sys
                                    print(f"[LOCK] Nonfatal lock cleanup failure for {self.lock_path}: {unlink_err}", file=sys.stderr)
                            else:
                                import sys
                                print(f"[LOCK] Stale lock token changed before deletion: {cleanup_err}", file=sys.stderr)
                        except Exception as cleanup_err:
                            import sys
                            print(f"[LOCK] Nonfatal lock cleanup failure for {self.lock_path}: {cleanup_err}", file=sys.stderr)
                            
                if time.monotonic() - start > self.timeout:
                    raise DatabaseInitializationError(f"Lock acquisition timed out for {self.lock_path}")
                time.sleep(0.05)
            except Exception as e:
                if time.monotonic() - start > self.timeout:
                    raise DatabaseInitializationError(f"Failed to acquire lock: {e}") from e
                time.sleep(0.05)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            try:
                if os.path.exists(self.lock_path):
                    with open(self.lock_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("token") == self.token:
                        os.unlink(self.lock_path)
            except Exception as cleanup_err:
                import sys
                print(f"[LOCK] Failed to release lock {self.lock_path}: {cleanup_err}", file=sys.stderr)



def resolve_db_path(db_path: Optional[str] = None, _default_runtime_file: Optional[Path] = None) -> str:
    # Authoritative precedence: HERMES_DB_PATH > explicit constructor path >
    # default runtime file > repo default.
    env_path = os.environ.get("HERMES_DB_PATH")
    if env_path:
        return os.path.abspath(env_path)
    if db_path is not None:
        return os.path.abspath(db_path)
    if _default_runtime_file is not None:
        return os.path.abspath(str(_default_runtime_file))
    repo_root = Path(__file__).resolve().parents[2]
    return os.path.abspath(str(repo_root / "data" / "runtime" / "tech_intel.db"))


class Database:
    """SQLite storage layer for events, embeddings, clusters, relationships, claims, evidence, revisions, and longitudinal state."""

    def __init__(self, db_path: Optional[str] = None, timeout: float = 10.0, _baseline_file: Optional[Path] = None, _default_runtime_file: Optional[Path] = None):
        self.db_path = resolve_db_path(db_path, _default_runtime_file)
        self.has_fts5 = False
        
        # Determine canonical baseline path
        repo_root = Path(__file__).resolve().parents[2]
        if _baseline_file is not None:
            baseline_file = _baseline_file.resolve()
        else:
            baseline_file = (repo_root / "data" / "tech_intel.db").resolve()
            
        if _default_runtime_file is not None:
            default_runtime_file = _default_runtime_file.resolve()
        else:
            default_runtime_file = (repo_root / "data" / "runtime" / "tech_intel.db").resolve()
            
        # Check identity using samefile or casing comparison
        is_baseline = False
        if os.path.exists(self.db_path) and baseline_file.exists():
            try:
                is_baseline = os.path.samefile(self.db_path, baseline_file)
            except Exception:
                pass
        if not is_baseline:
            if str(self.db_path).lower() == str(baseline_file).lower():
                is_baseline = True
                
        self.is_baseline = is_baseline
        self.is_writable = not is_baseline
        
        if self.is_baseline:
            # Baseline is read-only
            self.conn = connect_db(self.db_path, timeout=timeout, read_only=True)
            try:
                cursor = self.conn.cursor()
                tables = {r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                self.has_fts5 = "events_fts" in tables
            except Exception as e:
                if hasattr(self, "conn") and self.conn:
                    try:
                        self.conn.close()
                    except Exception:
                        pass
                self.conn = None
                raise DatabaseInitializationError(f"Failed to inspect read-only baseline database: {e}") from e
            return

        # Writable databases:
        is_default_runtime = False
        if os.path.exists(self.db_path) and default_runtime_file.exists():
            try:
                is_default_runtime = os.path.samefile(self.db_path, default_runtime_file)
            except Exception:
                pass
        if not is_default_runtime:
            if str(self.db_path).lower() == str(default_runtime_file).lower():
                is_default_runtime = True
                
        # Validate parent directory
        parent_dir = os.path.dirname(self.db_path)
        os.makedirs(parent_dir, exist_ok=True)
        if not os.path.isdir(parent_dir):
            raise DatabaseInitializationError(f"Database parent directory {parent_dir} is not valid.")
            
        # Serialize initialization sequence
        lock = InterprocessLock(self.db_path, timeout=timeout)
        with lock:
            db_exists = os.path.exists(self.db_path)
            
            if not db_exists:
                if is_default_runtime:
                    # Operational bootstrap from baseline
                    import tempfile
                    temp_fd, temp_db_path = tempfile.mkstemp(suffix=".db", dir=parent_dir)
                    os.close(temp_fd)
                    
                    self.conn = None
                    try:
                        # Copy baseline
                        shutil.copy2(str(baseline_file), temp_db_path)
                        
                        # Verify baseline SHA
                        h = hashlib.sha256()
                        with open(temp_db_path, 'rb') as f:
                            while chunk := f.read(8192):
                                h.update(chunk)
                        if h.hexdigest() != "f2966347f86f9ecd7343683f595f5d48b7fb940324eb5d936716f8899f5d5a77":
                            raise DatabaseInitializationError("Copied baseline SHA-256 mismatch.")
                            
                        # Open and migrate the copy using DELETE journal mode (no WAL)
                        self.conn = connect_db(temp_db_path, timeout=timeout, journal_mode="DELETE")
                        self.init_db()
                        self.conn.close()
                        self.conn = None
                        
                        # Assert no -wal / -shm exists
                        for ext in ["-wal", "-shm"]:
                            sidecar = temp_db_path + ext
                            if os.path.exists(sidecar) and os.path.getsize(sidecar) > 0:
                                raise DatabaseInitializationError(f"Temp DB has sidecar file {ext}")
                                
                        # Publish atomically
                        os.replace(temp_db_path, self.db_path)
                    except Exception as e:
                        if self.conn:
                            try:
                                self.conn.close()
                            except Exception as close_err:
                                import sys
                                print(f"[DB] Nonfatal connection close failure: {close_err}", file=sys.stderr)
                            self.conn = None
                        for suffix in ["", "-wal", "-shm", "-journal"]:
                            p = temp_db_path + suffix
                            if os.path.exists(p):
                                try:
                                    os.unlink(p)
                                except OSError as cleanup_err:
                                    import sys
                                    print(f"[DB] Nonfatal cleanup failure for {p}: {cleanup_err}", file=sys.stderr)
                        raise DatabaseInitializationError(f"Failed to bootstrap default runtime database: {e}") from e
                else:
                    # Isolated test database fresh initialization
                    import tempfile
                    temp_fd, temp_db_path = tempfile.mkstemp(suffix=".db", dir=parent_dir)
                    os.close(temp_fd)
                    
                    self.conn = None
                    try:
                        self.conn = connect_db(temp_db_path, timeout=timeout, journal_mode="DELETE")
                        self.init_db()
                        self.conn.close()
                        self.conn = None
                        
                        for ext in ["-wal", "-shm"]:
                            sidecar = temp_db_path + ext
                            if os.path.exists(sidecar) and os.path.getsize(sidecar) > 0:
                                raise DatabaseInitializationError(f"Temp DB has sidecar file {ext}")
                                
                        os.replace(temp_db_path, self.db_path)
                    except Exception as e:
                        if self.conn:
                            try:
                                self.conn.close()
                            except Exception as close_err:
                                import sys
                                print(f"[DB] Nonfatal connection close failure: {close_err}", file=sys.stderr)
                            self.conn = None
                        for suffix in ["", "-wal", "-shm", "-journal"]:
                            p = temp_db_path + suffix
                            if os.path.exists(p):
                                try:
                                    os.unlink(p)
                                except OSError as cleanup_err:
                                    import sys
                                    print(f"[DB] Nonfatal cleanup failure for {p}: {cleanup_err}", file=sys.stderr)
                        raise DatabaseInitializationError(f"Failed to initialize isolated test database: {e}") from e
            
            # Open final connection normally and enable WAL
            self.conn = connect_db(self.db_path, timeout=timeout, journal_mode="WAL")
            if db_exists:
                # If database existed, run init_db to run any migrations and validation
                self.conn = connect_db(self.db_path, timeout=timeout, journal_mode="WAL")
                try:
                    self.init_db()
                except Exception as e:
                    if self.conn:
                        try:
                            self.conn.close()
                        except Exception as close_err:
                            import sys
                            print(f"[DB] Nonfatal connection close failure: {close_err}", file=sys.stderr)
                        self.conn = None
                    raise e


    def _require_writable(self, operation_name: str) -> None:
        if not getattr(self, "is_writable", True):
            raise PermissionError(f"Mutation operation '{operation_name}' is disabled on this read-only database instance.")

    def _execute_in_write_transaction(self, operation, operation_name="Write transaction"):
        self._require_writable(operation_name)
        in_trans = self.conn.in_transaction
        cursor = self.conn.cursor()
        if not in_trans:
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    raise DatabaseMigrationError(f"Database write lock timeout exceeded: {e}") from e
                raise
        try:
            result = operation(cursor)
            if not in_trans:
                self.conn.commit()
            return result
        except Exception as e:
            if not in_trans:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            raise e

    def init_db(self) -> None:
        if not getattr(self, "is_writable", True):
            return

        cursor = self.conn.cursor()
        
        # Check if schema is already initialized
        try:
            cursor.execute("SELECT 1 FROM daily_briefings LIMIT 1")
            schema_exists = True
        except sqlite3.OperationalError:
            schema_exists = False

        # 1. Disable foreign keys when required
        try:
            self.conn.execute("PRAGMA foreign_keys=OFF")
            fk_state = self.conn.execute("PRAGMA foreign_keys").fetchone()[0]
            if int(fk_state) != 0:
                raise DatabaseMigrationError("Failed to disable foreign keys before migration.")
        except Exception as e:
            if isinstance(e, DatabaseMigrationError):
                raise
            raise DatabaseMigrationError(f"Failed to disable foreign keys: {e}") from e

        # Legacy daily_signal_runs rebuild is performed inside _migrate_columns_internal,
        # within the single BEGIN IMMEDIATE transaction started by init_db.
        
        try:
            if not schema_exists:
                schema_path = Path(__file__).parent / "schema.sql"
                schema_sql = ""
                if schema_path.exists():
                    with open(schema_path, "r", encoding="utf-8") as f:
                        schema_sql = f.read()
                        
                # Assert schema_sql contains no transaction-control statements (case-insensitive)
                for keyword in ["BEGIN", "COMMIT", "ROLLBACK"]:
                    import re
                    if re.search(r"\b" + keyword + r"\b", schema_sql, re.IGNORECASE):
                        raise DatabaseMigrationError(f"schema.sql contains forbidden transaction control statement: {keyword}")

                # 2. Acquire one BEGIN IMMEDIATE transaction and load schema.sql
                self.conn.executescript("BEGIN IMMEDIATE;\n" + schema_sql)
                cursor = self.conn.cursor()
            else:
                # Schema exists, start transaction for migrations
                self.conn.execute("BEGIN IMMEDIATE")
                cursor = self.conn.cursor()

            # 3. Run column migrations (idempotent, safe to run on fresh and existing databases)
            self._migrate_columns_internal(cursor)
            
            # 4. Set up FTS inside the same transaction (create or repair)
            try:
                cursor.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(id UNINDEXED, title, text)"
                )
                self.has_fts5 = True
            except sqlite3.OperationalError as fts_err:
                if "no such module: fts5" in str(fts_err).lower():
                    self.has_fts5 = False
                else:
                    raise fts_err
                    
            # 5. Commit once
            self.conn.commit()
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception as rb_err:
                raise DatabaseMigrationError(f"Rollback failed after migration error: {rb_err}") from e
            raise DatabaseMigrationError(f"Database schema initialization and migration transaction failed: {e}") from e
        finally:
            # 6. Restore foreign keys
            try:
                self.conn.execute("PRAGMA foreign_keys=ON")
                fk_state = self.conn.execute("PRAGMA foreign_keys").fetchone()[0]
                if int(fk_state) != 1:
                    raise DatabaseMigrationError("Failed to re-enable foreign keys after migration.")
            except Exception as e:
                if isinstance(e, DatabaseMigrationError):
                    raise
                raise DatabaseMigrationError(f"Failed to restore foreign keys: {e}") from e

        # 7. Run integrity checks
        try:
            qc = self.conn.execute("PRAGMA quick_check").fetchone()[0]
            if qc != "ok":
                raise DatabaseMigrationError(f"PRAGMA quick_check failed: {qc}")
            fk_violations = self.conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_violations:
                raise DatabaseMigrationError(f"PRAGMA foreign_key_check found violations: {fk_violations}")
        except Exception as check_err:
            if not isinstance(check_err, DatabaseMigrationError):
                raise DatabaseMigrationError(f"Integrity check failed: {check_err}") from check_err
            raise

    def _migrate_columns_internal(self, cursor) -> None:
        """Internal helper to apply migrations on the given cursor inside an active transaction."""
        try:
            all_tables = {r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            def _safe_add_column(table: str, col_name: str, col_def: str, existing_cols: set):
                if table not in all_tables:
                    return
                if col_name not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    except sqlite3.OperationalError as e:
                        err_str = str(e).lower()
                        if "duplicate column name" not in err_str:
                            sanitized = str(e).split("\n")[0]
                            raise DatabaseMigrationError(f"Failed adding column {col_name} to {table}: {sanitized}") from e

            # 1. Claims columns
            if "claims" in all_tables:
                claim_info = cursor.execute("PRAGMA table_info(claims)").fetchall()
                existing_claim_cols = {r["name"] for r in claim_info}
                for col_name, col_def in [
                    ("assertion_level", "TEXT NOT NULL DEFAULT 'artifact_fact'"),
                    ("is_current", "INTEGER DEFAULT 1"),
                    ("superseded_by", "TEXT"),
                    ("last_verified_at", "TEXT"),
                    ("staleness_score", "REAL DEFAULT 0.0"),
                    ("valid_from", "TEXT"),
                    ("valid_until", "TEXT"),
                ]:
                    _safe_add_column("claims", col_name, col_def, existing_claim_cols)

            # 2. Evidence columns
            if "evidence" in all_tables:
                ev_info = cursor.execute("PRAGMA table_info(evidence)").fetchall()
                existing_ev_cols = {r["name"] for r in ev_info}
                for col_name, col_def in [
                    ("source", "TEXT NOT NULL DEFAULT 'unknown'"),
                    ("evidence_class", "TEXT NOT NULL DEFAULT 'primary'"),
                    ("excerpt", "TEXT"),
                    ("url", "TEXT"),
                    ("quality_score", "REAL DEFAULT 0.50"),
                    ("independence_score", "REAL DEFAULT 0.50"),
                    ("reproducibility_score", "REAL DEFAULT 0.50"),
                    ("is_current", "INTEGER DEFAULT 1"),
                    ("superseded_by", "TEXT"),
                    ("observed_at", "TEXT"),
                    ("valid_from", "TEXT"),
                    ("valid_until", "TEXT"),
                ]:
                    _safe_add_column("evidence", col_name, col_def, existing_ev_cols)

            # 3. Intelligence Changes columns
            if "intelligence_changes" in all_tables:
                ic_info = cursor.execute("PRAGMA table_info(intelligence_changes)").fetchall()
                existing_ic_cols = {r["name"] for r in ic_info}
                _safe_add_column("intelligence_changes", "origin", "TEXT NOT NULL DEFAULT 'live_update'", existing_ic_cols)

            # 4. Technology Assessments columns
            if "technology_assessments" in all_tables:
                ta_info = cursor.execute("PRAGMA table_info(technology_assessments)").fetchall()
                existing_ta_cols = {r["name"] for r in ta_info}
                for col_name, col_def in [
                    ("research_score", "REAL DEFAULT 0.0"),
                    ("implementation_score", "REAL DEFAULT 0.0"),
                    ("adoption_score", "REAL DEFAULT 0.0"),
                    ("reproducibility_score", "REAL DEFAULT 0.0"),
                    ("community_score", "REAL DEFAULT 0.0"),
                    ("assessment_score", "REAL DEFAULT 0.0"),
                ]:
                    _safe_add_column("technology_assessments", col_name, col_def, existing_ta_cols)

            # 5. Check claim_revisions.new_verification_score nullability
            if "claim_revisions" in all_tables:
                cr_info = cursor.execute("PRAGMA table_info(claim_revisions)").fetchall()
                for col in cr_info:
                    if col["name"] == "new_verification_score" and col["notnull"] == 1:
                        try:
                            cursor.execute("""
                                CREATE TABLE IF NOT EXISTS claim_revisions_mig_tmp (
                                    id TEXT PRIMARY KEY,
                                    claim_id TEXT NOT NULL,
                                    previous_status TEXT,
                                    new_status TEXT NOT NULL,
                                    previous_verification_score REAL,
                                    new_verification_score REAL,
                                    reason TEXT NOT NULL,
                                    trigger_event_id TEXT,
                                    trigger_evidence_id TEXT,
                                    created_at TEXT NOT NULL
                                )
                            """)
                            cursor.execute("""
                                INSERT INTO claim_revisions_mig_tmp (
                                    id, claim_id, previous_status, new_status,
                                    previous_verification_score, new_verification_score,
                                    reason, trigger_event_id, trigger_evidence_id, created_at
                                )
                                SELECT
                                    id, claim_id, previous_status, new_status,
                                    previous_verification_score, new_verification_score,
                                    reason, trigger_event_id, trigger_evidence_id, created_at
                                FROM claim_revisions
                            """)
                            cursor.execute("DROP TABLE claim_revisions")
                            cursor.execute("ALTER TABLE claim_revisions_mig_tmp RENAME TO claim_revisions")
                            cursor.execute("CREATE INDEX IF NOT EXISTS idx_claim_rev_claim_id ON claim_revisions(claim_id)")
                            cursor.execute("CREATE INDEX IF NOT EXISTS idx_claim_rev_created_at ON claim_revisions(created_at DESC)")
                        except Exception as err:
                            cursor.execute("DROP TABLE IF EXISTS claim_revisions_mig_tmp")
                            sanitized = str(err).split("\n")[0]
                            raise DatabaseMigrationError(f"Failed migrating claim_revisions: {sanitized}") from err
                        break

            # 6. Check technology_assessment_revisions.new_score nullability
            if "technology_assessment_revisions" in all_tables:
                tar_info = cursor.execute("PRAGMA table_info(technology_assessment_revisions)").fetchall()
                for col in tar_info:
                    if col["name"] == "new_score" and col["notnull"] == 1:
                        try:
                            cursor.execute("""
                                CREATE TABLE IF NOT EXISTS technology_assessment_revisions_mig_tmp (
                                    id TEXT PRIMARY KEY,
                                    cluster_id TEXT NOT NULL,
                                    previous_stage TEXT,
                                    new_stage TEXT NOT NULL,
                                    previous_score REAL,
                                    new_score REAL,
                                    reason TEXT NOT NULL,
                                    created_at TEXT NOT NULL
                                )
                            """)
                            cursor.execute("""
                                INSERT INTO technology_assessment_revisions_mig_tmp (
                                    id, cluster_id, previous_stage, new_stage,
                                    previous_score, new_score, reason, created_at
                                )
                                SELECT
                                    id, cluster_id, previous_stage, new_stage,
                                    previous_score, new_score, reason, created_at
                                FROM technology_assessment_revisions
                            """)
                            cursor.execute("DROP TABLE technology_assessment_revisions")
                            cursor.execute("ALTER TABLE technology_assessment_revisions_mig_tmp RENAME TO technology_assessment_revisions")
                            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tech_rev_cluster_id ON technology_assessment_revisions(cluster_id)")
                        except Exception as err:
                            cursor.execute("DROP TABLE IF EXISTS technology_assessment_revisions_mig_tmp")
                            sanitized = str(err).split("\n")[0]
                            raise DatabaseMigrationError(f"Failed migrating technology_assessment_revisions: {sanitized}") from err
                        break

            # 7. Projects and Project Matches columns
            if "projects" in all_tables:
                p_info = cursor.execute("PRAGMA table_info(projects)").fetchall()
                existing_p_cols = {r["name"] for r in p_info}
                for col_name, col_def in [
                    ("languages_json", "TEXT"),
                    ("frameworks_json", "TEXT"),
                    ("libraries_json", "TEXT"),
                    ("databases_json", "TEXT"),
                    ("infrastructure_json", "TEXT"),
                    ("models_json", "TEXT"),
                    ("tools_json", "TEXT"),
                    ("topics_json", "TEXT"),
                    ("keywords_json", "TEXT"),
                    ("is_active", "INTEGER DEFAULT 1"),
                    ("context_hash", "TEXT NOT NULL DEFAULT ''"),
                    ("last_indexed_at", "TEXT"),
                    ("tags_json", "TEXT"),
                    ("description", "TEXT"),
                    ("status", "TEXT NOT NULL DEFAULT 'active'"),
                    ("archived_at", "TEXT"),
                    ("archive_reason", "TEXT"),
                    ("last_scan_status", "TEXT"),
                    ("last_scan_started_at", "TEXT"),
                    ("last_scan_completed_at", "TEXT"),
                    ("last_scan_error", "TEXT"),
                    ("narrative_json", "TEXT"),
                ]:
                    _safe_add_column("projects", col_name, col_def, existing_p_cols)

            if "project_matches" in all_tables:
                pm_info = cursor.execute("PRAGMA table_info(project_matches)").fetchall()
                existing_pm_cols = {r["name"] for r in pm_info}
                for col_name, col_def in [
                    ("entity_type", "TEXT NOT NULL DEFAULT 'cluster'"),
                    ("entity_id", "TEXT"),
                    ("recommendation", "TEXT"),
                    ("reason_codes_json", "TEXT"),
                    ("updated_at", "TEXT"),
                    ("explanation_json", "TEXT"),
                    ("explanation_version", "TEXT"),
                    ("evaluated_at", "TEXT"),
                ]:
                    _safe_add_column("project_matches", col_name, col_def, existing_pm_cols)
                if "cluster_id" in existing_pm_cols and "entity_id" in existing_pm_cols:
                    try:
                        cursor.execute("UPDATE project_matches SET entity_id = cluster_id WHERE (entity_id IS NULL OR entity_id = '') AND cluster_id IS NOT NULL")
                    except Exception:
                        pass

            # 8. Saved items columns
            if "saved_items" in all_tables:
                saved_info = cursor.execute("PRAGMA table_info(saved_items)").fetchall()
                existing_saved_cols = {r["name"] for r in saved_info}
                for col_name, col_def in [
                    ("is_active", "INTEGER DEFAULT 1"),
                    ("title", "TEXT"),
                    ("summary", "TEXT"),
                    ("sources_json", "TEXT"),
                    ("cluster_score_snapshot", "REAL"),
                    ("verification_snapshot", "REAL"),
                    ("maturity_snapshot", "TEXT"),
                    ("risk_snapshot", "REAL"),
                    ("claim_status_snapshot", "TEXT"),
                    ("risk_status_snapshot", "TEXT"),
                    ("risk_level_snapshot", "TEXT"),
                    ("project_ids_json", "TEXT"),
                    ("link_status", "TEXT DEFAULT 'resolved'"),
                    ("event_ids_snapshot_json", "TEXT"),
                ]:
                    _safe_add_column("saved_items", col_name, col_def, existing_saved_cols)

            # 9. Daily briefing items columns
            if "daily_briefing_items" in all_tables:
                dbi_info = cursor.execute("PRAGMA table_info(daily_briefing_items)").fetchall()
                existing_dbi_cols = {r["name"] for r in dbi_info}
                for col_name, col_def in [
                    ("title", "TEXT"),
                    ("summary", "TEXT"),
                    ("story_cluster_id", "TEXT"),
                    ("item_type", "TEXT"),
                    ("reason_codes_json", "TEXT"),
                    ("inbox_score", "REAL"),
                    ("rank_score", "REAL"),
                    ("project_impact_score", "REAL"),
                    ("matched_project_ids_json", "TEXT"),
                    ("snapshot_version", "TEXT"),
                    ("source_published_at", "TEXT"),
                    ("source_updated_at", "TEXT"),
                    ("first_seen_at", "TEXT"),
                    ("last_changed_at", "TEXT"),
                    ("last_evaluated_at", "TEXT"),
                    ("surfaced_at", "TEXT"),
                    ("snapshot_date", "TEXT"),
                    ("daily_run_id", "TEXT"),
                    ("freshness_kind", "TEXT"),
                    ("freshness_reason", "TEXT"),
                    ("content_hash", "TEXT"),
                    ("source_name", "TEXT"),
                ]:
                    _safe_add_column("daily_briefing_items", col_name, col_def, existing_dbi_cols)

            # 10. Source Checkpoints columns
            if "source_checkpoints" in all_tables:
                scp_info = cursor.execute("PRAGMA table_info(source_checkpoints)").fetchall()
                existing_scp_cols = {r["name"] for r in scp_info}
                for col_name, col_def in [
                    ("last_error_category", "TEXT"),
                    ("failure_threshold_reached", "INTEGER DEFAULT 0"),
                    ("max_consecutive_failures", "INTEGER DEFAULT 5"),
                ]:
                    _safe_add_column("source_checkpoints", col_name, col_def, existing_scp_cols)

            # 11. Runtime Jobs columns
            if "runtime_jobs" in all_tables:
                rj_info = cursor.execute("PRAGMA table_info(runtime_jobs)").fetchall()
                existing_rj_cols = {r["name"] for r in rj_info}
                for col_name, col_def in [
                    ("last_error_category", "TEXT"),
                    ("evaluation_status", "TEXT DEFAULT 'pending'"),
                    ("evaluated_at", "TEXT"),
                    ("next_run_at", "TEXT"),
                    ("blocked_by", "TEXT"),
                    ("blocked_reason", "TEXT"),
                ]:
                    _safe_add_column("runtime_jobs", col_name, col_def, existing_rj_cols)

            # 12. Runtime Job Runs columns
            if "runtime_job_runs" in all_tables:
                rjr_info = cursor.execute("PRAGMA table_info(runtime_job_runs)").fetchall()
                existing_rjr_cols = {r["name"] for r in rjr_info}
                _safe_add_column("runtime_job_runs", "error_category", "TEXT", existing_rjr_cols)

            # 13. Inbox Items new columns
            if "inbox_items" in all_tables:
                inb_info = cursor.execute("PRAGMA table_info(inbox_items)").fetchall()
                existing_inb_cols = {r["name"] for r in inb_info}
                for col_name, col_def in [
                    ("surface_date", "TEXT"),
                    ("latest_event_at", "TEXT"),
                    ("last_materialized_at", "TEXT"),
                    ("data_cutoff_at", "TEXT"),
                    ("freshness_kind", "TEXT"),
                    ("daily_run_id", "TEXT"),
                    ("source_published_at", "TEXT"),
                    ("source_updated_at", "TEXT"),
                    ("last_changed_at", "TEXT"),
                    ("last_evaluated_at", "TEXT"),
                    ("surfaced_at", "TEXT"),
                    ("snapshot_date", "TEXT"),
                    ("freshness_reason", "TEXT"),
                ]:
                    _safe_add_column("inbox_items", col_name, col_def, existing_inb_cols)

            # 14. Daily Briefings new columns
            if "daily_briefings" in all_tables:
                db_info = cursor.execute("PRAGMA table_info(daily_briefings)").fetchall()
                existing_db_cols = {r["name"] for r in db_info}
                for col_name, col_def in [
                    ("runtime_timezone", "TEXT"),
                    ("data_cutoff_at", "TEXT"),
                    ("generation_status", "TEXT"),
                    ("source_status_json", "TEXT"),
                    ("daily_run_id", "TEXT"),
                    ("original_generated_at", "TEXT"),
                ]:
                    _safe_add_column("daily_briefings", col_name, col_def, existing_db_cols)

            # 15. daily_signal_runs table
            if "daily_signal_runs" not in all_tables:
                try:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS daily_signal_runs (
                            id TEXT PRIMARY KEY,
                            runtime_date TEXT NOT NULL,
                            runtime_timezone TEXT NOT NULL,
                            run_kind TEXT NOT NULL DEFAULT 'daily_refresh',
                            started_at TEXT NOT NULL,
                            completed_at TEXT,
                            data_cutoff_at TEXT,
                            status TEXT NOT NULL,
                            new_signal_count INTEGER DEFAULT 0,
                            updated_signal_count INTEGER DEFAULT 0,
                            carried_signal_count INTEGER DEFAULT 0,
                            retry_count INTEGER DEFAULT 0,
                            briefing_id TEXT,
                            source_status_json TEXT,
                            error_summary TEXT,
                            content_hash TEXT NOT NULL DEFAULT ''
                        )
                    """)
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_runs_date ON daily_signal_runs(runtime_date)")
                    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_runs_composite ON daily_signal_runs(runtime_date, runtime_timezone, run_kind)")
                except Exception as e:
                    sanitized = str(e).split("\n")[0]
                    raise DatabaseMigrationError(f"Failed creating daily_signal_runs table: {sanitized}") from e
            else:
                dsr_info = cursor.execute("PRAGMA table_info(daily_signal_runs)").fetchall()
                existing_dsr_cols = {r["name"] for r in dsr_info}

                # Legacy schema detection: needs a full column-aware rebuild when the
                # canonical timezone column is absent (legacy timezone_name), run_kind
                # is missing, or the legacy single-column runtime_date UNIQUE constraint
                # exists. Only columns confirmed by PRAGMA table_info are referenced.
                has_runtime_timezone = "runtime_timezone" in existing_dsr_cols
                has_run_kind = "run_kind" in existing_dsr_cols
                has_timezone_name = "timezone_name" in existing_dsr_cols

                # Detect legacy runtime_date UNIQUE via index introspection. The normal
                # non-unique idx_daily_runs_date must NOT trigger a rebuild.
                def _has_legacy_date_unique() -> bool:
                    try:
                        idx_rows = cursor.execute("PRAGMA index_list(daily_signal_runs)").fetchall()
                    except Exception:
                        return False
                    for idx_row in idx_rows:
                        # Row layout: seq, name, unique, origin, partial (SQLite >= 3.9)
                        idx_name = idx_row["name"]
                        is_unique = bool(idx_row["unique"])
                        if not is_unique:
                            continue
                        try:
                            col_rows = cursor.execute(f'PRAGMA index_info("{idx_name}")').fetchall()
                        except Exception:
                            continue
                        indexed_cols = [r["name"] for r in sorted(col_rows, key=lambda c: c["seqno"])]
                        if indexed_cols == ["runtime_date"]:
                            return True
                    return False

                needs_rebuild = (
                    not has_runtime_timezone or not has_run_kind or _has_legacy_date_unique()
                )

                if needs_rebuild:
                    try:
                        cursor.execute("""
                            CREATE TABLE daily_signal_runs_mig_tmp (
                                id TEXT PRIMARY KEY,
                                runtime_date TEXT NOT NULL,
                                runtime_timezone TEXT NOT NULL,
                                run_kind TEXT NOT NULL DEFAULT 'daily_refresh',
                                started_at TEXT NOT NULL,
                                completed_at TEXT,
                                data_cutoff_at TEXT,
                                status TEXT NOT NULL,
                                new_signal_count INTEGER DEFAULT 0,
                                updated_signal_count INTEGER DEFAULT 0,
                                carried_signal_count INTEGER DEFAULT 0,
                                retry_count INTEGER DEFAULT 0,
                                briefing_id TEXT,
                                source_status_json TEXT,
                                error_summary TEXT,
                                content_hash TEXT NOT NULL DEFAULT ''
                            )
                        """)

                        # Column-aware SELECT expressions: only reference columns found
                        # by PRAGMA table_info.
                        def _int_default(col: str) -> str:
                            return f"COALESCE({col}, 0)" if col in existing_dsr_cols else "0"

                        def _text_or_null(col: str) -> str:
                            return col if col in existing_dsr_cols else "NULL"

                        content_hash_expr = (
                            "COALESCE(content_hash, '')" if "content_hash" in existing_dsr_cols else "''"
                        )
                        if has_runtime_timezone:
                            tz_expr = "runtime_timezone"
                        elif has_timezone_name:
                            tz_expr = "COALESCE(timezone_name, 'UTC')"
                        else:
                            tz_expr = "'UTC'"
                        run_kind_expr = "run_kind" if has_run_kind else "'daily_refresh'"

                        select_cols = ", ".join([
                            "id",
                            "runtime_date",
                            tz_expr,
                            run_kind_expr,
                            "started_at",
                            _text_or_null("completed_at"),
                            _text_or_null("data_cutoff_at"),
                            "status",
                            _int_default("new_signal_count"),
                            _int_default("updated_signal_count"),
                            _int_default("carried_signal_count"),
                            _int_default("retry_count"),
                            _text_or_null("briefing_id"),
                            _text_or_null("source_status_json"),
                            _text_or_null("error_summary"),
                            content_hash_expr,
                        ])

                        cursor.execute(f"""
                            INSERT INTO daily_signal_runs_mig_tmp (
                                id, runtime_date, runtime_timezone, run_kind, started_at,
                                completed_at, data_cutoff_at, status, new_signal_count,
                                updated_signal_count, carried_signal_count, retry_count,
                                briefing_id, source_status_json, error_summary, content_hash
                            )
                            SELECT {select_cols}
                            FROM daily_signal_runs
                        """)
                        cursor.execute("DROP TABLE daily_signal_runs")
                        cursor.execute("ALTER TABLE daily_signal_runs_mig_tmp RENAME TO daily_signal_runs")
                        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_runs_date ON daily_signal_runs(runtime_date)")
                        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_runs_composite ON daily_signal_runs(runtime_date, runtime_timezone, run_kind)")
                    except Exception as rebuild_err:
                        cursor.execute("DROP TABLE IF EXISTS daily_signal_runs_mig_tmp")
                        sanitized = str(rebuild_err).split("\n")[0]
                        raise DatabaseMigrationError(f"Failed to rebuild legacy daily_signal_runs table: {sanitized}") from rebuild_err
                else:
                    # Migrate existing table: add missing columns, update indexes
                    _safe_add_column("daily_signal_runs", "runtime_timezone", "TEXT", existing_dsr_cols)
                    _safe_add_column("daily_signal_runs", "run_kind", "TEXT NOT NULL DEFAULT 'daily_refresh'", existing_dsr_cols)
                    # Drop old UNIQUE constraint on runtime_date and create composite unique index
                    try:
                        cursor.execute("DROP INDEX IF EXISTS idx_daily_runs_date")
                        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_runs_date ON daily_signal_runs(runtime_date)")
                        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_runs_composite ON daily_signal_runs(runtime_date, runtime_timezone, run_kind)")
                    except sqlite3.OperationalError as idx_err:
                        raise DatabaseMigrationError(f"Failed to update daily_signal_runs indexes: {idx_err}") from idx_err

            # 16. refresh_operations table
            if "refresh_operations" in all_tables:
                ro_info = cursor.execute("PRAGMA table_info(refresh_operations)").fetchall()
                existing_ro_cols = {r["name"] for r in ro_info}
                _safe_add_column("refresh_operations", "idempotency_key", "TEXT", existing_ro_cols)

            if "refresh_operations" not in all_tables:
                try:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS refresh_operations (
                            id TEXT PRIMARY KEY,
                            scope TEXT NOT NULL,
                            target_id TEXT,
                            requested_at TEXT NOT NULL,
                            started_at TEXT,
                            completed_at TEXT,
                            status TEXT NOT NULL,
                            [trigger] TEXT NOT NULL DEFAULT 'user_requested',
                            job_names_json TEXT,
                            items_processed INTEGER DEFAULT 0,
                            error_summary TEXT,
                            result_json TEXT,
                            claimed_at TEXT,
                            lease_expires_at TEXT,
                            heartbeat_at TEXT,
                            worker_id TEXT,
                            idempotency_key TEXT
                        )
                    """)
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_ops_status ON refresh_operations(status)")
                except Exception as e:
                    sanitized = str(e).split("\n")[0]
                    raise DatabaseMigrationError(f"Failed creating refresh_operations table: {sanitized}") from e

            if "runtime_jobs" in all_tables:
                rj_info = cursor.execute("PRAGMA table_info(runtime_jobs)").fetchall()
                existing_rj_cols = {r["name"] for r in rj_info}
                if "evaluation_status" in existing_rj_cols:
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_runtime_jobs_eval_status ON runtime_jobs(evaluation_status)")
                if "next_run_at" in existing_rj_cols:
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_runtime_jobs_next_run ON runtime_jobs(next_run_at)")
        except Exception as e:
            if isinstance(e, DatabaseMigrationError):
                raise
            raise DatabaseMigrationError(f"Migration internal step failed: {e}") from e

        # 16b. Phase 4.5 briefing-revision tables. schema.sql defines these, but
        # init_db() skips schema.sql on databases that already have
        # daily_briefings, and the column migrations above never created the
        # tables. Pre-Phase-4.5 databases therefore lack them entirely, which
        # breaks the combined briefing-metadata read path. Create them
        # idempotently with their full column set (so the column-add steps
        # below are no-ops for freshly created tables).
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_briefing_revisions (
                    id TEXT PRIMARY KEY,
                    briefing_id TEXT NOT NULL,
                    revision_number INTEGER NOT NULL,
                    generated_at TEXT NOT NULL,
                    data_cutoff_at TEXT,
                    source_status_json TEXT,
                    content_hash TEXT NOT NULL,
                    generation_status TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    daily_run_id TEXT,
                    runtime_timezone TEXT,
                    created_at TEXT,
                    UNIQUE(briefing_id, revision_number)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_briefing_revision_items (
                    revision_id TEXT NOT NULL,
                    inbox_item_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    section TEXT NOT NULL,
                    title TEXT,
                    summary TEXT,
                    story_cluster_id TEXT,
                    item_type TEXT,
                    reason_codes_json TEXT,
                    inbox_score REAL,
                    rank_score REAL,
                    project_impact_score REAL,
                    matched_project_ids_json TEXT,
                    snapshot_version TEXT,
                    source_published_at TEXT,
                    source_updated_at TEXT,
                    first_seen_at TEXT,
                    last_changed_at TEXT,
                    last_evaluated_at TEXT,
                    surfaced_at TEXT,
                    snapshot_date TEXT,
                    daily_run_id TEXT,
                    freshness_kind TEXT,
                    freshness_reason TEXT,
                    content_hash TEXT,
                    source_name TEXT,
                    PRIMARY KEY (revision_id, inbox_item_id)
                )
            """)
        except Exception as e:
            sanitized = str(e).split("\n")[0]
            raise DatabaseMigrationError(f"Failed creating briefing revision tables: {sanitized}") from e

        # Refresh the table set so the column-add steps below see the tables
        # created above.
        all_tables = {r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        # 17. daily_briefing_revisions new columns
        if "daily_briefing_revisions" in all_tables:
            dbr_info = cursor.execute("PRAGMA table_info(daily_briefing_revisions)").fetchall()
            existing_dbr_cols = {r["name"] for r in dbr_info}
            _safe_add_column("daily_briefing_revisions", "runtime_timezone", "TEXT", existing_dbr_cols)
            _safe_add_column("daily_briefing_revisions", "created_at", "TEXT", existing_dbr_cols)
            
        # 18. daily_briefing_items new columns
        if "daily_briefing_items" in all_tables:
            dbi_info = cursor.execute("PRAGMA table_info(daily_briefing_items)").fetchall()
            existing_dbi_cols = {r["name"] for r in dbi_info}
            _safe_add_column("daily_briefing_items", "content_hash", "TEXT", existing_dbi_cols)
            _safe_add_column("daily_briefing_items", "source_name", "TEXT", existing_dbi_cols)
            
        # 19. daily_briefing_revision_items new columns
        if "daily_briefing_revision_items" in all_tables:
            dbri_info = cursor.execute("PRAGMA table_info(daily_briefing_revision_items)").fetchall()
            existing_dbri_cols = {r["name"] for r in dbri_info}
            _safe_add_column("daily_briefing_revision_items", "content_hash", "TEXT", existing_dbri_cols)
            _safe_add_column("daily_briefing_revision_items", "source_name", "TEXT", existing_dbri_cols)

    def _migrate_columns(self) -> None:
        """Ensure columns added across all sessions exist in previously created tables with strict atomicity and error discipline."""
        try:
            self.conn.execute("PRAGMA foreign_keys=OFF")
            fk_state = self.conn.execute("PRAGMA foreign_keys").fetchone()[0]
            if int(fk_state) != 0:
                raise DatabaseMigrationError("Failed to disable foreign keys before migration.")
        except Exception as e:
            if isinstance(e, DatabaseMigrationError):
                raise
            raise DatabaseMigrationError(f"Failed to disable foreign keys: {e}") from e

        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            self._migrate_columns_internal(cursor)
            self.conn.commit()
        except sqlite3.OperationalError as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            if "locked" in str(e).lower():
                raise DatabaseMigrationError(f"Database write lock timeout exceeded during migration: {e}") from e
            raise DatabaseMigrationError(f"Failed to acquire database write lock: {e}") from e
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            try:
                cursor.execute("DROP TABLE IF EXISTS claim_revisions_mig_tmp")
                cursor.execute("DROP TABLE IF EXISTS technology_assessment_revisions_mig_tmp")
            except sqlite3.OperationalError as cleanup_err:
                raise DatabaseMigrationError(f"Cleanup failed during migration rollback: {cleanup_err}") from cleanup_err
            raise DatabaseMigrationError(f"Migration transaction failed: {e}") from e
        finally:
            try:
                self.conn.execute("PRAGMA foreign_keys=ON")
                fk_state = self.conn.execute("PRAGMA foreign_keys").fetchone()[0]
                if int(fk_state) != 1:
                    raise DatabaseMigrationError("Failed to re-enable foreign keys after migration.")
            except Exception as e:
                if isinstance(e, DatabaseMigrationError):
                    raise
                raise DatabaseMigrationError(f"Failed to restore foreign keys: {e}") from e
            
        # Post-transaction validation checks (Run quick_check and foreign_key_check)
        try:
            qc = self.conn.execute("PRAGMA quick_check").fetchone()[0]
            if qc != "ok":
                raise DatabaseMigrationError(f"PRAGMA quick_check failed: {qc}")
            fk_violations = self.conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_violations:
                raise DatabaseMigrationError(f"PRAGMA foreign_key_check found violations: {fk_violations}")
        except Exception as check_err:
            if not isinstance(check_err, DatabaseMigrationError):
                raise DatabaseMigrationError(f"Integrity check failed: {check_err}") from check_err
            raise


    # --- Event Methods ---

    def event_exists(self, event_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM events WHERE id = ? LIMIT 1", (event_id,))
        return cursor.fetchone() is not None

    def url_exists(self, url: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM events WHERE url = ? LIMIT 1", (url,))
        return cursor.fetchone() is not None

    def insert_event(self, event: Event) -> bool:
        """Insert event into SQLite. Returns True if inserted, False if duplicate."""
        if self.event_exists(event.id):
            return False

        sql = """
        INSERT INTO events (
            id, source, source_type, event_type, title, text, url,
            authors_json, topics_json, metadata_json, raw_payload_json,
            published_at, discovered_at, trust_score, relevance_score,
            novelty_score, final_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        disc_at = event.discovered_at if hasattr(event, "discovered_at") else datetime.now(timezone.utc)
        params = (
            event.id,
            event.source,
            event.source_type,
            event.event_type,
            event.title,
            event.text,
            event.url,
            json.dumps(event.authors),
            json.dumps(event.topics),
            json.dumps(event.metadata),
            json.dumps(event.raw_payload),
            event.published_at.isoformat() if event.published_at else None,
            disc_at.isoformat(),
            event.trust_score,
            event.relevance_score,
            event.novelty_score,
            event.final_score,
        )

        self.conn.execute(sql, params)

        if self.has_fts5:
            try:
                self.conn.execute(
                    "INSERT INTO events_fts (id, title, text) VALUES (?, ?, ?)",
                    (event.id, event.title, event.text),
                )
            except Exception:
                pass

        self.conn.commit()
        return True

    def save_event(self, event: Event) -> bool:
        return self.insert_event(event)

    def _row_to_event(self, r: sqlite3.Row) -> Event:
        disc_at = datetime.fromisoformat(r["discovered_at"]) if "discovered_at" in r.keys() and r["discovered_at"] else datetime.now(timezone.utc)
        doi_val = None
        m = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        if "doi" in m:
            doi_val = m.get("doi")
        cited_val = m.get("cited_by_count")

        return Event(
            id=r["id"],
            source=r["source"],
            source_type=r["source_type"],
            event_type=r["event_type"],
            title=r["title"],
            text=r["text"] or "",
            url=r["url"],
            doi=doi_val,
            cited_by_count=cited_val,
            authors=json.loads(r["authors_json"]) if r["authors_json"] else [],
            topics=json.loads(r["topics_json"]) if r["topics_json"] else [],
            metadata=m,
            raw_payload=json.loads(r["raw_payload_json"]) if r["raw_payload_json"] else {},
            published_at=datetime.fromisoformat(r["published_at"]) if r["published_at"] else None,
            discovered_at=disc_at,
            trust_score=r["trust_score"] or 0.0,
            relevance_score=r["relevance_score"] or 0.0,
            novelty_score=r["novelty_score"] or 0.0,
            final_score=r["final_score"] or 0.0,
        )

    def get_event(self, event_id: str) -> Optional[Event]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM events WHERE id = ? LIMIT 1", (event_id,))
        row = cursor.fetchone()
        return self._row_to_event(row) if row else None

    def get_all_events(self) -> List[Event]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY final_score DESC, published_at DESC")
        return [self._row_to_event(r) for r in cursor.fetchall()]

    def get_events_by_ids(self, event_ids: List[str]) -> List[Event]:
        if not event_ids:
            return []
        placeholders = ",".join(["?"] * len(event_ids))
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT * FROM events WHERE id IN ({placeholders})", tuple(event_ids))
        return [self._row_to_event(r) for r in cursor.fetchall()]

    def get_top_events(self, limit: int = 20) -> List[Event]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM events
            ORDER BY final_score DESC, published_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_event(r) for r in cursor.fetchall()]

    def get_recent_events(self, days: int = 30, limit: int = 300) -> List[Event]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM events
            WHERE published_at >= ? OR created_at >= ?
            ORDER BY final_score DESC
            LIMIT ?
            """,
            (cutoff, cutoff, limit),
        )
        return [self._row_to_event(r) for r in cursor.fetchall()]

    def get_event_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_event_counts_by_source(self) -> Dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT source, COUNT(*) FROM events GROUP BY source")
        return {r[0]: r[1] for r in cursor.fetchall()}

    def get_unembedded_events(self, model_name: str) -> List[Event]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT e.* FROM events e
            LEFT JOIN event_embeddings ee ON e.id = ee.event_id AND ee.model_name = ?
            WHERE ee.event_id IS NULL
            ORDER BY e.final_score DESC
            """,
            (model_name,),
        )
        return [self._row_to_event(r) for r in cursor.fetchall()]

    def get_unclustered_events(self) -> List[Event]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT e.* FROM events e
            LEFT JOIN cluster_events ce ON e.id = ce.event_id
            WHERE ce.event_id IS NULL
            ORDER BY e.final_score DESC
            """
        )
        return [self._row_to_event(r) for r in cursor.fetchall()]

    def get_fts_candidates(self, query_tokens: List[str], limit: int = 50) -> List[str]:
        if not self.has_fts5 or not query_tokens:
            return []
        clean_tokens = [t.replace('"', '""') for t in query_tokens if len(t) >= 3]
        if not clean_tokens:
            return []
        match_query = " OR ".join([f'"{t}"' for t in clean_tokens[:10]])
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id FROM events_fts WHERE events_fts MATCH ? LIMIT ?",
                (match_query, limit),
            )
            return [r[0] for r in cursor.fetchall()]
        except Exception:
            return []

    def search_events_fts(self, query: str, limit: int = 100) -> List[Tuple[str, float]]:
        """
        Safely searches events_fts with BM25 ranking or falls back to parameterized LIKE queries.
        Returns: list of (event_id, lexical_score)
        """
        if not query or not query.strip():
            return []

        import re
        raw_tokens = re.findall(r"[a-zA-Z0-9_\-\.+]+", query)
        clean_fts_tokens = [re.sub(r'[^a-zA-Z0-9_\-\.]', '', t) for t in raw_tokens]
        clean_fts_tokens = [t.lower() for t in clean_fts_tokens if len(t) >= 2]

        results = []
        if self.has_fts5 and clean_fts_tokens:
            # Build safe match query (each token quoted, joined by OR)
            clean_tokens = [t.replace('"', '""') for t in clean_fts_tokens[:10]]
            match_query = " OR ".join([f'"{t}"' for t in clean_tokens])
            try:
                cursor = self.conn.cursor()
                cursor.execute(
                    "SELECT id, rank FROM events_fts WHERE events_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match_query, limit),
                )
                rows = cursor.fetchall()
                for r in rows:
                    # SQLite FTS5 rank is negative (lower = better), convert to positive normalized score
                    raw_rank = abs(float(r[1])) if len(r) > 1 and r[1] is not None else 1.0
                    lex_score = 1.0 / (1.0 + raw_rank * 0.1)
                    results.append((r[0], lex_score))
            except Exception:
                pass

        if not results and query.strip():
            # Fallback to parameterized LIKE queries with exact query substring and tokens
            like_pat = f"%{query.strip()}%"
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id FROM events WHERE title LIKE ? OR text LIKE ? LIMIT ?",
                (like_pat, like_pat, limit),
            )
            for r in cursor.fetchall():
                results.append((r[0], 0.7))

        return results

    def search_clusters_lexical(self, query: str, limit: int = 50) -> List[StoryCluster]:
        """Performs lexical candidate search across StoryClusters."""
        if not query or not query.strip():
            return []
        import re
        like_pat = f"%{query.strip()}%"
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id FROM story_clusters WHERE canonical_title LIKE ? ORDER BY cluster_score DESC LIMIT ?",
            (like_pat, limit),
        )
        matched_ids = [r[0] for r in cursor.fetchall()]

        # Also search by individual alphanumeric/symbol tokens
        tokens = re.findall(r"[a-zA-Z0-9_\-\.+]+", query)
        for t in tokens:
            if len(t) >= 2 and len(matched_ids) < limit:
                cursor.execute(
                    "SELECT id FROM story_clusters WHERE canonical_title LIKE ? ORDER BY cluster_score DESC LIMIT ?",
                    (f"%{t}%", limit - len(matched_ids)),
                )
                for r in cursor.fetchall():
                    if r[0] not in matched_ids:
                        matched_ids.append(r[0])

        return self.get_clusters_by_ids(matched_ids)

    # --- Embedding Storage Methods ---

    def save_embedding(self, event_id: str, model_name: str, embedding: np.ndarray) -> bool:
        vec_bytes = embedding.astype(np.float32).tobytes()
        dim = int(embedding.shape[0])
        now_str = datetime.now(timezone.utc).isoformat()
        sql = """
        INSERT OR REPLACE INTO event_embeddings (event_id, model_name, embedding, dimension, created_at)
        VALUES (?, ?, ?, ?, ?)
        """
        self.conn.execute(sql, (event_id, model_name, vec_bytes, dim, now_str))
        self.conn.commit()
        return True

    def get_embedding(self, event_id: str, model_name: str) -> Optional[np.ndarray]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT embedding, dimension FROM event_embeddings WHERE event_id = ? AND model_name = ? LIMIT 1",
            (event_id, model_name),
        )
        row = cursor.fetchone()
        if not row:
            return None
        vec_bytes = row["embedding"]
        dim = row["dimension"]
        return np.frombuffer(vec_bytes, dtype=np.float32).reshape((dim,))

    def embedding_exists(self, event_id: str, model_name: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT 1 FROM event_embeddings WHERE event_id = ? AND model_name = ? LIMIT 1",
            (event_id, model_name),
        )
        return cursor.fetchone() is not None

    def get_embeddings_batch(self, event_ids: List[str], model_name: str) -> Dict[str, np.ndarray]:
        if not event_ids:
            return {}
        placeholders = ",".join(["?"] * len(event_ids))
        cursor = self.conn.cursor()
        cursor.execute(
            f"SELECT event_id, embedding, dimension FROM event_embeddings WHERE model_name = ? AND event_id IN ({placeholders})",
            (model_name, *event_ids),
        )
        result = {}
        for r in cursor.fetchall():
            result[r["event_id"]] = np.frombuffer(r["embedding"], dtype=np.float32).reshape((r["dimension"],))
        return result

    def get_all_embeddings(self, model_name: str) -> Dict[str, np.ndarray]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT event_id, embedding, dimension FROM event_embeddings WHERE model_name = ?",
            (model_name,),
        )
        embeddings = {}
        for row in cursor.fetchall():
            embeddings[row["event_id"]] = np.frombuffer(row["embedding"], dtype=np.float32).reshape((row["dimension"],))
        return embeddings

    # --- Story Clustering Storage Methods ---

    def create_cluster(self, cluster: StoryCluster) -> bool:
        sql = """
        INSERT OR REPLACE INTO story_clusters (
            id, canonical_title, cluster_score, source_diversity_score, max_event_score, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                cluster.id,
                cluster.canonical_title,
                cluster.cluster_score,
                cluster.source_diversity_score,
                cluster.max_event_score,
                cluster.created_at.isoformat(),
                cluster.updated_at.isoformat(),
            ),
        )
        for eid in cluster.event_ids:
            self.add_event_to_cluster(cluster.id, eid)
        self.conn.commit()
        return True

    def update_cluster(self, cluster: StoryCluster) -> bool:
        return self.create_cluster(cluster)

    def save_cluster(self, cluster: StoryCluster) -> bool:
        return self.create_cluster(cluster)

    def add_event_to_cluster(self, cluster_id: str, event_id: str, similarity_score: float = 1.0) -> bool:
        now_str = datetime.now(timezone.utc).isoformat()
        sql = """
        INSERT OR REPLACE INTO cluster_events (cluster_id, event_id, similarity_score, added_at)
        VALUES (?, ?, ?, ?)
        """
        self.conn.execute(sql, (cluster_id, event_id, similarity_score, now_str))
        self.conn.commit()
        return True

    def get_cluster(self, cluster_id: str) -> Optional[StoryCluster]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM story_clusters WHERE id = ? LIMIT 1", (cluster_id,))
        row = cursor.fetchone()
        if not row:
            return None

        cursor.execute("SELECT event_id FROM cluster_events WHERE cluster_id = ?", (cluster_id,))
        event_ids = [r["event_id"] for r in cursor.fetchall()]

        sources = []
        if event_ids:
            ph = ",".join(["?"] * len(event_ids))
            cursor.execute(f"SELECT DISTINCT source FROM events WHERE id IN ({ph})", tuple(event_ids))
            sources = [r["source"] for r in cursor.fetchall()]

        return StoryCluster(
            id=row["id"],
            canonical_title=row["canonical_title"],
            event_ids=event_ids,
            sources=sources,
            cluster_score=row["cluster_score"] or 0.0,
            source_diversity_score=row["source_diversity_score"] or 0.0,
            max_event_score=row["max_event_score"] or 0.0,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_clusters_by_ids(self, cluster_ids: List[str]) -> List[StoryCluster]:
        if not cluster_ids:
            return []
        clean_ids = list(dict.fromkeys(cid for cid in cluster_ids if cid))
        if not clean_ids:
            return []
        cursor = self.conn.cursor()
        cluster_map = {}
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            ph = ",".join("?" for _ in chunk)
            cursor.execute(f"SELECT * FROM story_clusters WHERE id IN ({ph})", tuple(chunk))
            rows = cursor.fetchall()
            if not rows:
                continue
            cursor.execute(
                f"""
                SELECT ce.cluster_id, ce.event_id, e.source
                FROM cluster_events ce
                LEFT JOIN events e ON ce.event_id = e.id
                WHERE ce.cluster_id IN ({ph})
                """,
                tuple(chunk),
            )
            events_by_cluster = defaultdict(list)
            sources_by_cluster = defaultdict(set)
            for r in cursor.fetchall():
                cid = r["cluster_id"]
                if r["event_id"]:
                    events_by_cluster[cid].append(r["event_id"])
                if r["source"]:
                    sources_by_cluster[cid].add(r["source"])

            for r in rows:
                cid = r["id"]
                cluster_map[cid] = StoryCluster(
                    id=cid,
                    canonical_title=r["canonical_title"],
                    event_ids=events_by_cluster.get(cid, []),
                    sources=sorted(list(sources_by_cluster.get(cid, set()))),
                    cluster_score=r["cluster_score"] or 0.0,
                    source_diversity_score=r["source_diversity_score"] or 0.0,
                    max_event_score=r["max_event_score"] or 0.0,
                    created_at=datetime.fromisoformat(r["created_at"]),
                    updated_at=datetime.fromisoformat(r["updated_at"]),
                )
        return [cluster_map[cid] for cid in clean_ids if cid in cluster_map]

    def get_all_clusters(self) -> List[StoryCluster]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM story_clusters ORDER BY cluster_score DESC")
        cluster_ids = [r["id"] for r in cursor.fetchall()]
        return self.get_clusters_by_ids(cluster_ids)

    def get_top_clusters(self, limit: int = 20) -> List[StoryCluster]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM story_clusters
            ORDER BY cluster_score DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        cluster_rows = cursor.fetchall()
        if not cluster_rows:
            return []
        cids = [r["id"] for r in cluster_rows]
        ph = ",".join("?" for _ in cids)
        cursor.execute(
            f"""
            SELECT ce.cluster_id, ce.event_id, e.source
            FROM cluster_events ce
            LEFT JOIN events e ON ce.event_id = e.id
            WHERE ce.cluster_id IN ({ph})
            """,
            cids,
        )
        events_by_cluster = defaultdict(list)
        sources_by_cluster = defaultdict(set)
        for r in cursor.fetchall():
            cid = r["cluster_id"]
            if r["event_id"]:
                events_by_cluster[cid].append(r["event_id"])
            if r["source"]:
                sources_by_cluster[cid].add(r["source"])

        clusters = []
        for row in cluster_rows:
            cid = row["id"]
            clusters.append(
                StoryCluster(
                    id=cid,
                    canonical_title=row["canonical_title"],
                    event_ids=events_by_cluster.get(cid, []),
                    sources=sorted(list(sources_by_cluster.get(cid, set()))),
                    cluster_score=row["cluster_score"] or 0.0,
                    source_diversity_score=row["source_diversity_score"] or 0.0,
                    max_event_score=row["max_event_score"] or 0.0,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            )
        return clusters

    def get_event_cluster(self, event_id: str) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT cluster_id FROM cluster_events WHERE event_id = ? LIMIT 1", (event_id,))
        row = cursor.fetchone()
        return row["cluster_id"] if row else None

    def get_event_clusters_batch(self, event_ids: List[str]) -> Dict[str, str]:
        """Batch lookup cluster_id for multiple event_ids."""
        if not event_ids:
            return {}
        clean_ids = list(dict.fromkeys(eid for eid in event_ids if eid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        out = {}
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            ph = ",".join("?" for _ in chunk)
            cursor.execute(f"SELECT event_id, cluster_id FROM cluster_events WHERE event_id IN ({ph})", chunk)
            for r in cursor.fetchall():
                out[r["event_id"]] = r["cluster_id"]
        return out

    def get_cluster_events(self, cluster_id: str) -> List[Event]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT e.* FROM events e
            JOIN cluster_events ce ON e.id = ce.event_id
            WHERE ce.cluster_id = ?
            ORDER BY e.final_score DESC
            """,
            (cluster_id,),
        )
        return [self._row_to_event(r) for r in cursor.fetchall()]

    def get_cluster_events_batch(self, cluster_ids: List[str]) -> Dict[str, List[Event]]:
        """Batch load events for multiple cluster IDs to avoid N+1 queries."""
        if not cluster_ids:
            return {}
        clean_ids = list(dict.fromkeys(cid for cid in cluster_ids if cid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        placeholders = ",".join("?" for _ in clean_ids)
        sql = f"""
        SELECT ce.cluster_id, e.*
        FROM events e
        JOIN cluster_events ce ON e.id = ce.event_id
        WHERE ce.cluster_id IN ({placeholders})
        ORDER BY e.final_score DESC
        """
        cursor.execute(sql, clean_ids)
        out = defaultdict(list)
        for r in cursor.fetchall():
            cid = r["cluster_id"]
            out[cid].append(self._row_to_event(r))
        return dict(out)

    def get_existing_cluster_ids(self, cluster_ids: List[str]) -> Set[str]:
        """Batch check existence of story cluster IDs."""
        if not cluster_ids:
            return set()
        clean_ids = list(dict.fromkeys(cid for cid in cluster_ids if cid))
        if not clean_ids:
            return set()
        cursor = self.conn.cursor()
        placeholders = ",".join("?" for _ in clean_ids)
        cursor.execute(f"SELECT id FROM story_clusters WHERE id IN ({placeholders})", clean_ids)
        return {r["id"] for r in cursor.fetchall()}

    def clear_clusters_and_relationships(self) -> None:
        """Clear story_clusters, cluster_events, and event_relationships."""
        self.conn.execute("DELETE FROM story_clusters")
        self.conn.execute("DELETE FROM cluster_events")
        self.conn.execute("DELETE FROM event_relationships")
        self.conn.commit()

    # --- Relationship Storage Methods ---

    def save_relationship(self, rel: Relationship) -> bool:
        sql = """
        INSERT OR REPLACE INTO event_relationships (id, source_event_id, target_event_id, relationship_type, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                rel.id,
                rel.source_event_id,
                rel.target_event_id,
                rel.relationship_type,
                rel.confidence,
                rel.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_relationships(self, event_id: str) -> List[Relationship]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM event_relationships
            WHERE source_event_id = ? OR target_event_id = ?
            ORDER BY confidence DESC
            """,
            (event_id, event_id),
        )
        return [
            Relationship(
                id=r["id"],
                source_event_id=r["source_event_id"],
                target_event_id=r["target_event_id"],
                relationship_type=r["relationship_type"],
                confidence=r["confidence"] or 1.0,
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_all_relationships(self) -> List[Relationship]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM event_relationships ORDER BY confidence DESC")
        return [
            Relationship(
                id=r["id"],
                source_event_id=r["source_event_id"],
                target_event_id=r["target_event_id"],
                relationship_type=r["relationship_type"],
                confidence=r["confidence"] or 1.0,
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    # --- Claim Storage Methods ---

    def claim_exists(self, claim_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM claims WHERE id = ? LIMIT 1", (claim_id,))
        return cursor.fetchone() is not None

    def save_claim(self, claim: Claim) -> bool:
        sql = """
        INSERT OR REPLACE INTO claims (
            id, cluster_id, claim_type, assertion_level, subject, predicate, object,
            claim_text, status, confidence, verification_score, self_reported,
            is_current, superseded_by, last_verified_at, staleness_score,
            valid_from, valid_until, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                claim.id,
                claim.cluster_id,
                claim.claim_type,
                claim.assertion_level,
                claim.subject,
                claim.predicate,
                claim.object,
                claim.claim_text,
                claim.status,
                claim.confidence,
                claim.verification_score,
                1 if claim.self_reported else 0,
                1 if claim.is_current else 0,
                claim.superseded_by,
                claim.last_verified_at.isoformat() if claim.last_verified_at else None,
                claim.staleness_score,
                claim.valid_from.isoformat() if claim.valid_from else None,
                claim.valid_until.isoformat() if claim.valid_until else None,
                json.dumps(claim.metadata),
                claim.created_at.isoformat(),
                claim.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def _row_to_claim(self, r: sqlite3.Row) -> Claim:
        keys = r.keys()
        return Claim(
            id=r["id"],
            cluster_id=r["cluster_id"],
            claim_type=r["claim_type"],
            assertion_level=r["assertion_level"] if "assertion_level" in keys and r["assertion_level"] else "artifact_fact",
            subject=r["subject"],
            predicate=r["predicate"],
            object=r["object"],
            claim_text=r["claim_text"],
            status=r["status"],
            confidence=r["confidence"] or 1.0,
            verification_score=r["verification_score"] or 0.0,
            self_reported=bool(r["self_reported"]),
            is_current=bool(r["is_current"]) if "is_current" in keys and r["is_current"] is not None else True,
            superseded_by=r["superseded_by"] if "superseded_by" in keys else None,
            last_verified_at=datetime.fromisoformat(r["last_verified_at"]) if "last_verified_at" in keys and r["last_verified_at"] else None,
            staleness_score=r["staleness_score"] if "staleness_score" in keys and r["staleness_score"] is not None else 0.0,
            valid_from=datetime.fromisoformat(r["valid_from"]) if "valid_from" in keys and r["valid_from"] else None,
            valid_until=datetime.fromisoformat(r["valid_until"]) if "valid_until" in keys and r["valid_until"] else None,
            metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
            created_at=datetime.fromisoformat(r["created_at"]),
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM claims WHERE id = ? LIMIT 1", (claim_id,))
        row = cursor.fetchone()
        return self._row_to_claim(row) if row else None

    def get_claims_by_cluster(self, cluster_id: str, current_only: bool = False) -> List[Claim]:
        cursor = self.conn.cursor()
        if current_only:
            cursor.execute(
                "SELECT * FROM claims WHERE cluster_id = ? AND is_current = 1 ORDER BY verification_score DESC, created_at DESC",
                (cluster_id,),
            )
        else:
            cursor.execute(
                "SELECT * FROM claims WHERE cluster_id = ? ORDER BY verification_score DESC, created_at DESC",
                (cluster_id,),
            )
        return [self._row_to_claim(r) for r in cursor.fetchall()]

    def get_all_claims(self, current_only: bool = False) -> List[Claim]:
        cursor = self.conn.cursor()
        if current_only:
            cursor.execute("SELECT * FROM claims WHERE is_current = 1 ORDER BY verification_score DESC, created_at DESC")
        else:
            cursor.execute("SELECT * FROM claims ORDER BY verification_score DESC, created_at DESC")
        return [self._row_to_claim(r) for r in cursor.fetchall()]

    def get_claims_by_status(self, status: str) -> List[Claim]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM claims WHERE status = ? ORDER BY verification_score DESC", (status,))
        return [self._row_to_claim(r) for r in cursor.fetchall()]

    def get_claims_by_cluster_ids(self, cluster_ids: List[str], current_only: bool = False) -> Dict[str, List[Claim]]:
        """Batch load claims for multiple cluster IDs grouped by cluster_id."""
        if not cluster_ids:
            return {}
        clean_ids = list(dict.fromkeys(cid for cid in cluster_ids if cid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        out = defaultdict(list)
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            placeholders = ",".join("?" for _ in chunk)
            sql = f"SELECT * FROM claims WHERE cluster_id IN ({placeholders})"
            if current_only:
                sql += " AND is_current = 1"
            sql += " ORDER BY verification_score DESC, created_at DESC"
            cursor.execute(sql, chunk)
            for r in cursor.fetchall():
                out[r["cluster_id"]].append(self._row_to_claim(r))
        return dict(out)

    def get_claims_by_ids(self, claim_ids: List[str]) -> Dict[str, Claim]:
        """Batch load claims by claim IDs as a mapping."""
        if not claim_ids:
            return {}
        clean_ids = list(dict.fromkeys(cid for cid in claim_ids if cid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        out = {}
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            ph = ",".join("?" for _ in chunk)
            cursor.execute(f"SELECT * FROM claims WHERE id IN ({ph})", tuple(chunk))
            for r in cursor.fetchall():
                out[r["id"]] = self._row_to_claim(r)
        return out

    # --- Evidence Storage Methods ---

    def evidence_exists(self, evidence_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM evidence WHERE id = ? LIMIT 1", (evidence_id,))
        return cursor.fetchone() is not None

    def save_evidence(self, evidence: Evidence) -> bool:
        sql = """
        INSERT OR REPLACE INTO evidence (
            id, claim_id, event_id, source, evidence_type, evidence_class,
            stance, excerpt, url, quality_score, independence_score,
            reproducibility_score, is_current, superseded_by, observed_at,
            valid_from, valid_until, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                evidence.id,
                evidence.claim_id,
                evidence.event_id,
                evidence.source,
                evidence.evidence_type,
                evidence.evidence_class,
                evidence.stance,
                evidence.excerpt,
                evidence.url,
                evidence.quality_score,
                evidence.independence_score,
                evidence.reproducibility_score,
                1 if evidence.is_current else 0,
                evidence.superseded_by,
                evidence.observed_at.isoformat() if evidence.observed_at else None,
                evidence.valid_from.isoformat() if evidence.valid_from else None,
                evidence.valid_until.isoformat() if evidence.valid_until else None,
                evidence.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def _row_to_evidence(self, r: sqlite3.Row) -> Evidence:
        keys = r.keys()
        return Evidence(
            id=r["id"],
            claim_id=r["claim_id"],
            event_id=r["event_id"],
            source=r["source"],
            evidence_type=r["evidence_type"],
            evidence_class=r["evidence_class"] if "evidence_class" in keys else "primary",
            stance=r["stance"],
            excerpt=r["excerpt"] or "",
            url=r["url"],
            quality_score=r["quality_score"] or 0.50,
            independence_score=r["independence_score"] or 0.50,
            reproducibility_score=r["reproducibility_score"] or 0.50,
            is_current=bool(r["is_current"]) if "is_current" in keys and r["is_current"] is not None else True,
            superseded_by=r["superseded_by"] if "superseded_by" in keys else None,
            observed_at=datetime.fromisoformat(r["observed_at"]) if "observed_at" in keys and r["observed_at"] else None,
            valid_from=datetime.fromisoformat(r["valid_from"]) if "valid_from" in keys and r["valid_from"] else None,
            valid_until=datetime.fromisoformat(r["valid_until"]) if "valid_until" in keys and r["valid_until"] else None,
            created_at=datetime.fromisoformat(r["created_at"]),
        )

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM evidence WHERE id = ? LIMIT 1", (evidence_id,))
        row = cursor.fetchone()
        return self._row_to_evidence(row) if row else None

    def get_evidence_by_claim(self, claim_id: str) -> List[Evidence]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM evidence WHERE claim_id = ? ORDER BY quality_score DESC", (claim_id,))
        return [self._row_to_evidence(r) for r in cursor.fetchall()]

    def get_all_evidence(self) -> List[Evidence]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM evidence ORDER BY quality_score DESC")
        return [self._row_to_evidence(r) for r in cursor.fetchall()]

    def get_evidence_by_claim_ids(self, claim_ids: List[str]) -> Dict[str, List[Evidence]]:
        """Batch load evidence records for multiple claim IDs grouped by claim_id."""
        if not claim_ids:
            return {}
        clean_ids = list(dict.fromkeys(cid for cid in claim_ids if cid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        out = defaultdict(list)
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            placeholders = ",".join("?" for _ in chunk)
            sql = f"SELECT * FROM evidence WHERE claim_id IN ({placeholders}) ORDER BY quality_score DESC, created_at DESC"
            cursor.execute(sql, chunk)
            for r in cursor.fetchall():
                out[r["claim_id"]].append(self._row_to_evidence(r))
        return dict(out)

    # --- Technology Assessment Storage Methods ---

    def _row_to_assessment(self, row: sqlite3.Row) -> TechnologyAssessment:
        return TechnologyAssessment(
            cluster_id=row["cluster_id"],
            maturity_stage=row["maturity_stage"],
            research_score=row["research_score"] or 0.0,
            implementation_score=row["implementation_score"] or 0.0,
            adoption_score=row["adoption_score"] or 0.0,
            reproducibility_score=row["reproducibility_score"] or 0.0,
            community_score=row["community_score"] or 0.0,
            assessment_score=row["assessment_score"] or 0.0,
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save_technology_assessment(self, assessment: TechnologyAssessment) -> bool:
        sql = """
        INSERT OR REPLACE INTO technology_assessments (
            cluster_id, maturity_stage, research_score, implementation_score,
            adoption_score, reproducibility_score, community_score,
            assessment_score, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                assessment.cluster_id,
                assessment.maturity_stage,
                assessment.research_score,
                assessment.implementation_score,
                assessment.adoption_score,
                assessment.reproducibility_score,
                assessment.community_score,
                assessment.assessment_score,
                assessment.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_technology_assessment(self, cluster_id: str) -> Optional[TechnologyAssessment]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_assessments WHERE cluster_id = ? LIMIT 1", (cluster_id,))
        row = cursor.fetchone()
        return self._row_to_assessment(row) if row else None

    def get_all_technology_assessments(self) -> List[TechnologyAssessment]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_assessments ORDER BY assessment_score DESC")
        return [self._row_to_assessment(row) for row in cursor.fetchall()]

    def get_assessments_by_cluster_ids(self, cluster_ids: List[str]) -> Dict[str, TechnologyAssessment]:
        """Batch load technology assessments for multiple cluster IDs."""
        if not cluster_ids:
            return {}
        clean_ids = list(dict.fromkeys(cid for cid in cluster_ids if cid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        out = {}
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            placeholders = ",".join("?" for _ in chunk)
            sql = f"SELECT * FROM technology_assessments WHERE cluster_id IN ({placeholders})"
            cursor.execute(sql, chunk)
            for r in cursor.fetchall():
                out[r["cluster_id"]] = self._row_to_assessment(r)
        return out

    # --- Session 6: Claim Revisions ---

    def insert_claim_revision(self, rev: ClaimRevision) -> bool:
        sql = """
        INSERT OR REPLACE INTO claim_revisions (
            id, claim_id, previous_status, new_status,
            previous_verification_score, new_verification_score,
            reason, trigger_event_id, trigger_evidence_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                rev.id,
                rev.claim_id,
                rev.previous_status,
                rev.new_status,
                rev.previous_verification_score,
                rev.new_verification_score,
                rev.reason,
                rev.trigger_event_id,
                rev.trigger_evidence_id,
                rev.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_claim_revisions(self, claim_id: str) -> List[ClaimRevision]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM claim_revisions WHERE claim_id = ? ORDER BY created_at ASC", (claim_id,))
        return [
            ClaimRevision(
                id=r["id"],
                claim_id=r["claim_id"],
                previous_status=r["previous_status"],
                new_status=r["new_status"],
                previous_verification_score=r["previous_verification_score"],
                new_verification_score=r["new_verification_score"],
                reason=r["reason"],
                trigger_event_id=r["trigger_event_id"],
                trigger_evidence_id=r["trigger_evidence_id"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_claim_revisions_by_cluster(self, cluster_id: str) -> List[ClaimRevision]:
        claims = self.get_claims_by_cluster(cluster_id)
        if not claims:
            return []
        claim_ids = [c.id for c in claims]
        placeholders = ",".join("?" for _ in claim_ids)
        cursor = self.conn.cursor()
        cursor.execute(
            f"SELECT * FROM claim_revisions WHERE claim_id IN ({placeholders}) ORDER BY created_at ASC",
            claim_ids,
        )
        return [
            ClaimRevision(
                id=r["id"],
                claim_id=r["claim_id"],
                previous_status=r["previous_status"],
                new_status=r["new_status"],
                previous_verification_score=r["previous_verification_score"],
                new_verification_score=r["new_verification_score"],
                reason=r["reason"],
                trigger_event_id=r["trigger_event_id"],
                trigger_evidence_id=r["trigger_evidence_id"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_all_claim_revisions(self) -> List[ClaimRevision]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM claim_revisions ORDER BY created_at DESC")
        return [
            ClaimRevision(
                id=r["id"],
                claim_id=r["claim_id"],
                previous_status=r["previous_status"],
                new_status=r["new_status"],
                previous_verification_score=r["previous_verification_score"],
                new_verification_score=r["new_verification_score"],
                reason=r["reason"],
                trigger_event_id=r["trigger_event_id"],
                trigger_evidence_id=r["trigger_evidence_id"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_latest_claim_revision(self, claim_id: str) -> Optional[ClaimRevision]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM claim_revisions WHERE claim_id = ? ORDER BY created_at DESC LIMIT 1", (claim_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return ClaimRevision(
            id=row["id"],
            claim_id=row["claim_id"],
            previous_status=row["previous_status"],
            new_status=row["new_status"],
            previous_verification_score=row["previous_verification_score"],
            new_verification_score=row["new_verification_score"],
            reason=row["reason"],
            trigger_event_id=row["trigger_event_id"],
            trigger_evidence_id=row["trigger_evidence_id"],
            created_at=datetime.fromisoformat(r["created_at"]) if (r := row) else datetime.now(timezone.utc),
        )

    # --- Session 6: Technology Assessment Revisions ---

    def insert_technology_assessment_revision(self, rev: TechnologyAssessmentRevision) -> bool:
        sql = """
        INSERT OR REPLACE INTO technology_assessment_revisions (
            id, cluster_id, previous_stage, new_stage, previous_score, new_score, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                rev.id,
                rev.cluster_id,
                rev.previous_stage,
                rev.new_stage,
                rev.previous_score,
                rev.new_score,
                rev.reason,
                rev.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_technology_assessment_revisions(self, cluster_id: str) -> List[TechnologyAssessmentRevision]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_assessment_revisions WHERE cluster_id = ? ORDER BY created_at ASC", (cluster_id,))
        return [
            TechnologyAssessmentRevision(
                id=r["id"],
                cluster_id=r["cluster_id"],
                previous_stage=r["previous_stage"],
                new_stage=r["new_stage"],
                previous_score=r["previous_score"],
                new_score=r["new_score"],
                reason=r["reason"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_all_technology_assessment_revisions(self) -> List[TechnologyAssessmentRevision]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_assessment_revisions ORDER BY created_at DESC")
        return [
            TechnologyAssessmentRevision(
                id=r["id"],
                cluster_id=r["cluster_id"],
                previous_stage=r["previous_stage"],
                new_stage=r["new_stage"],
                previous_score=r["previous_score"],
                new_score=r["new_score"],
                reason=r["reason"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    # --- Session 6: Technology State ---

    def save_technology_state(self, state: TechnologyState) -> bool:
        sql = """
        INSERT OR REPLACE INTO technology_states (
            cluster_id, current_status, latest_event_at, latest_release,
            latest_claim_revision_at, active_claim_count, supported_claim_count,
            contradicted_claim_count, superseded_claim_count, risk_score,
            trend, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                state.cluster_id,
                state.current_status,
                state.latest_event_at.isoformat() if state.latest_event_at else None,
                state.latest_release,
                state.latest_claim_revision_at.isoformat() if state.latest_claim_revision_at else None,
                state.active_claim_count,
                state.supported_claim_count,
                state.contradicted_claim_count,
                state.superseded_claim_count,
                state.risk_score,
                state.trend,
                state.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def _row_to_technology_state(self, row: sqlite3.Row) -> TechnologyState:
        return TechnologyState(
            cluster_id=row["cluster_id"],
            current_status=row["current_status"],
            latest_event_at=datetime.fromisoformat(row["latest_event_at"]) if row["latest_event_at"] else None,
            latest_release=row["latest_release"],
            latest_claim_revision_at=datetime.fromisoformat(row["latest_claim_revision_at"]) if row["latest_claim_revision_at"] else None,
            active_claim_count=row["active_claim_count"] or 0,
            supported_claim_count=row["supported_claim_count"] or 0,
            contradicted_claim_count=row["contradicted_claim_count"] or 0,
            superseded_claim_count=row["superseded_claim_count"] or 0,
            risk_score=row["risk_score"] if row["risk_score"] is not None else None,
            trend=row["trend"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_technology_state(self, cluster_id: str) -> Optional[TechnologyState]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_states WHERE cluster_id = ? LIMIT 1", (cluster_id,))
        row = cursor.fetchone()
        return self._row_to_technology_state(row) if row else None

    def get_all_technology_states(self) -> List[TechnologyState]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_states ORDER BY risk_score DESC, updated_at DESC")
        return [self._row_to_technology_state(row) for row in cursor.fetchall()]

    def get_technology_states_by_cluster_ids(self, cluster_ids: List[str]) -> List[TechnologyState]:
        if not cluster_ids:
            return []
        clean_ids = list({cid for cid in cluster_ids if cid})
        if not clean_ids:
            return []
        cursor = self.conn.cursor()
        out = []
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            cursor.execute(f"SELECT * FROM technology_states WHERE cluster_id IN ({ph})", tuple(chunk))
            out.extend([self._row_to_technology_state(row) for row in cursor.fetchall()])
        return out

    def get_current_states_by_cluster_ids(self, cluster_ids: List[str]) -> Dict[str, TechnologyState]:
        """Batch load current technology states for multiple cluster IDs as a mapping."""
        if not cluster_ids:
            return {}
        clean_ids = list(dict.fromkeys(cid for cid in cluster_ids if cid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        out = {}
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            cursor.execute(f"SELECT * FROM technology_states WHERE cluster_id IN ({ph})", tuple(chunk))
            for row in cursor.fetchall():
                out[row["cluster_id"]] = self._row_to_technology_state(row)
        return out

    # --- Session 6: Recheck Queue ---

    def insert_recheck_queue_item(self, item: RecheckQueueItem) -> bool:
        sql = """
        INSERT OR REPLACE INTO recheck_queue (
            id, entity_type, entity_id, reason, priority, not_before,
            last_checked_at, next_check_at, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                item.id,
                item.entity_type,
                item.entity_id,
                item.reason,
                item.priority,
                item.not_before.isoformat() if item.not_before else None,
                item.last_checked_at.isoformat() if item.last_checked_at else None,
                item.next_check_at.isoformat() if item.next_check_at else None,
                item.status,
                item.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_pending_recheck_items(self, limit: Optional[int] = None) -> List[RecheckQueueItem]:
        cursor = self.conn.cursor()
        sql = "SELECT * FROM recheck_queue WHERE status = 'pending' ORDER BY priority DESC, created_at ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cursor.execute(sql)
        return [
            RecheckQueueItem(
                id=r["id"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                reason=r["reason"],
                priority=r["priority"] or 0.50,
                not_before=datetime.fromisoformat(r["not_before"]) if r["not_before"] else None,
                last_checked_at=datetime.fromisoformat(r["last_checked_at"]) if r["last_checked_at"] else None,
                next_check_at=datetime.fromisoformat(r["next_check_at"]) if r["next_check_at"] else None,
                status=r["status"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_all_recheck_items(self) -> List[RecheckQueueItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM recheck_queue ORDER BY priority DESC, created_at ASC")
        return [
            RecheckQueueItem(
                id=r["id"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                reason=r["reason"],
                priority=r["priority"] or 0.50,
                not_before=datetime.fromisoformat(r["not_before"]) if r["not_before"] else None,
                last_checked_at=datetime.fromisoformat(r["last_checked_at"]) if r["last_checked_at"] else None,
                next_check_at=datetime.fromisoformat(r["next_check_at"]) if r["next_check_at"] else None,
                status=r["status"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def update_recheck_item_status(self, item_id: str, status: str, last_checked_at: Optional[datetime] = None) -> bool:
        cursor = self.conn.cursor()
        if last_checked_at:
            cursor.execute(
                "UPDATE recheck_queue SET status = ?, last_checked_at = ? WHERE id = ?",
                (status, last_checked_at.isoformat(), item_id),
            )
        else:
            cursor.execute(
                "UPDATE recheck_queue SET status = ? WHERE id = ?",
                (status, item_id),
            )
        self.conn.commit()
        return True

    def clear_recheck_queue(self) -> None:
        self.conn.execute("DELETE FROM recheck_queue")
        self.conn.commit()

    # --- Session 6: Intelligence Changes ---

    def insert_intelligence_change(self, change: IntelligenceChange) -> bool:
        sql = """
        INSERT OR REPLACE INTO intelligence_changes (
            id, entity_type, entity_id, change_type, old_value, new_value,
            importance, reason, origin, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                change.id,
                change.entity_type,
                change.entity_id,
                change.change_type,
                change.old_value,
                change.new_value,
                change.importance,
                change.reason,
                getattr(change, "origin", "live_update") or "live_update",
                change.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def save_intelligence_change(self, change: IntelligenceChange) -> bool:
        return self.insert_intelligence_change(change)

    def _row_to_intelligence_change(self, r: sqlite3.Row) -> IntelligenceChange:
        return IntelligenceChange(
            id=r["id"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            change_type=r["change_type"],
            old_value=r["old_value"],
            new_value=r["new_value"],
            importance=r["importance"] or 0.50,
            reason=r["reason"],
            origin=r["origin"] if "origin" in r.keys() and r["origin"] else "live_update",
            created_at=datetime.fromisoformat(r["created_at"]),
        )

    def get_recent_intelligence_changes(
        self, days: Optional[int] = None, hours: Optional[int] = None, limit: int = 100
    ) -> List[IntelligenceChange]:
        cursor = self.conn.cursor()
        if hours is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            cursor.execute(
                "SELECT * FROM intelligence_changes WHERE created_at >= ? ORDER BY importance DESC, created_at DESC LIMIT ?",
                (cutoff, limit),
            )
        elif days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            cursor.execute(
                "SELECT * FROM intelligence_changes WHERE created_at >= ? ORDER BY importance DESC, created_at DESC LIMIT ?",
                (cutoff, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM intelligence_changes ORDER BY importance DESC, created_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_intelligence_change(r) for r in cursor.fetchall()]

    def get_all_intelligence_changes(self) -> List[IntelligenceChange]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM intelligence_changes ORDER BY importance DESC, created_at DESC")
        return [self._row_to_intelligence_change(r) for r in cursor.fetchall()]

    # --- Session 7: Reference / Context Projects ---

    def save_project(self, project: Project) -> bool:
        sql = """
        INSERT OR REPLACE INTO projects (
            id, name, path, description, languages_json, frameworks_json,
            libraries_json, databases_json, infrastructure_json, models_json,
            tools_json, topics_json, keywords_json, is_active, context_hash,
            created_at, updated_at, last_indexed_at, status, archived_at,
            archive_reason, last_scan_status, last_scan_started_at,
            last_scan_completed_at, last_scan_error, narrative_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                project.id,
                project.name,
                project.path,
                project.description,
                json.dumps(project.languages),
                json.dumps(project.frameworks),
                json.dumps(project.libraries),
                json.dumps(project.databases),
                json.dumps(project.infrastructure),
                json.dumps(project.models),
                json.dumps(project.tools),
                json.dumps(project.topics),
                json.dumps(project.keywords),
                1 if project.is_active else 0,
                project.context_hash,
                project.created_at.isoformat(),
                project.updated_at.isoformat(),
                project.last_indexed_at.isoformat() if project.last_indexed_at else None,
                project.status,
                project.archived_at.isoformat() if project.archived_at else None,
                project.archive_reason,
                project.last_scan_status,
                project.last_scan_started_at.isoformat() if project.last_scan_started_at else None,
                project.last_scan_completed_at.isoformat() if project.last_scan_completed_at else None,
                project.last_scan_error,
                project.narrative.model_dump_json() if project.narrative else None,
            ),
        )
        self.conn.commit()
        return True

    def _row_to_project(self, r: sqlite3.Row) -> Project:
        d = dict(r)
        
        def parse_dt(k):
            val = d.get(k)
            return datetime.fromisoformat(val) if val else None

        narrative = None
        if d.get("narrative_json"):
            try:
                narrative = ProjectNarrative.model_validate_json(d["narrative_json"])
            except Exception:
                narrative = None

        return Project(
            id=d["id"],
            name=d["name"],
            path=d["path"],
            description=d.get("description"),
            narrative=narrative,
            languages=json.loads(d["languages_json"]) if d.get("languages_json") else [],
            frameworks=json.loads(d["frameworks_json"]) if d.get("frameworks_json") else [],
            libraries=json.loads(d["libraries_json"]) if d.get("libraries_json") else [],
            databases=json.loads(d["databases_json"]) if d.get("databases_json") else [],
            infrastructure=json.loads(d["infrastructure_json"]) if d.get("infrastructure_json") else [],
            models=json.loads(d["models_json"]) if d.get("models_json") else [],
            tools=json.loads(d["tools_json"]) if d.get("tools_json") else [],
            topics=json.loads(d["topics_json"]) if d.get("topics_json") else [],
            keywords=json.loads(d["keywords_json"]) if d.get("keywords_json") else [],
            is_active=bool(d.get("is_active", 1)),
            context_hash=d.get("context_hash") or "",
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            last_indexed_at=parse_dt("last_indexed_at"),
            status=d.get("status") or "active",
            archived_at=parse_dt("archived_at"),
            archive_reason=d.get("archive_reason"),
            last_scan_status=d.get("last_scan_status"),
            last_scan_started_at=parse_dt("last_scan_started_at"),
            last_scan_completed_at=parse_dt("last_scan_completed_at"),
            last_scan_error=d.get("last_scan_error"),
        )


    def get_project(self, project_id: str) -> Optional[Project]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE id = ? LIMIT 1", (project_id,))
        row = cursor.fetchone()
        return self._row_to_project(row) if row else None

    def get_project_by_name(self, name: str) -> Optional[Project]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE LOWER(name) = LOWER(?) OR LOWER(id) = LOWER(?) LIMIT 1", (name, name))
        row = cursor.fetchone()
        return self._row_to_project(row) if row else None

    def get_all_projects(self, active_only: bool = True) -> List[Project]:
        cursor = self.conn.cursor()
        if active_only:
            cursor.execute("SELECT * FROM projects WHERE is_active = 1 ORDER BY name ASC")
        else:
            cursor.execute("SELECT * FROM projects ORDER BY name ASC")
        return [self._row_to_project(r) for r in cursor.fetchall()]

    def deactivate_project(self, project_id: str) -> bool:
        self.conn.execute("UPDATE projects SET is_active = 0 WHERE id = ?", (project_id,))
        self.conn.commit()
        return True

    # --- Project Files ---

    def save_project_file(self, pfile: ProjectFile) -> bool:
        sql = """
        INSERT OR REPLACE INTO project_files (
            id, project_id, relative_path, file_type, size_bytes, content_hash,
            extracted_text, created_at, updated_at, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                pfile.id,
                pfile.project_id,
                pfile.relative_path,
                pfile.file_type,
                pfile.size_bytes,
                pfile.content_hash,
                pfile.extracted_text,
                pfile.created_at.isoformat(),
                pfile.updated_at.isoformat(),
                pfile.indexed_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_project_files(self, project_id: str) -> List[ProjectFile]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM project_files WHERE project_id = ? ORDER BY relative_path ASC", (project_id,))
        return [
            ProjectFile(
                id=r["id"],
                project_id=r["project_id"],
                relative_path=r["relative_path"],
                file_type=r["file_type"],
                size_bytes=r["size_bytes"] or 0,
                content_hash=r["content_hash"],
                extracted_text=r["extracted_text"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
                indexed_at=datetime.fromisoformat(r["indexed_at"]),
            )
            for r in cursor.fetchall()
        ]

    def delete_project_file(self, pfile_id: str) -> bool:
        self.conn.execute("DELETE FROM project_files WHERE id = ?", (pfile_id,))
        self.conn.commit()
        return True

    def delete_project_files(self, project_id: str) -> bool:
        self.conn.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
        self.conn.commit()
        return True

    # --- Project Technology Profiles ---

    def save_project_profile(self, profile: ProjectTechnologyProfile) -> bool:
        sql = """
        INSERT OR REPLACE INTO project_technology_profiles (
            project_id, languages_json, frameworks_json, libraries_json,
            dependencies_json, databases_json, storage_json, infrastructure_json,
            ml_stack_json, deployment_json, observability_json, testing_json,
            topics_json, profile_text, profile_hash, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                profile.project_id,
                json.dumps(profile.languages),
                json.dumps(profile.frameworks),
                json.dumps(profile.libraries),
                json.dumps(profile.dependencies),
                json.dumps(profile.databases),
                json.dumps(profile.storage),
                json.dumps(profile.infrastructure),
                json.dumps(profile.ml_stack),
                json.dumps(profile.deployment),
                json.dumps(profile.observability),
                json.dumps(profile.testing),
                json.dumps(profile.topics),
                profile.profile_text,
                profile.profile_hash,
                profile.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_project_profile(self, project_id: str) -> Optional[ProjectTechnologyProfile]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM project_technology_profiles WHERE project_id = ? LIMIT 1", (project_id,))
        r = cursor.fetchone()
        if not r:
            return None
        return ProjectTechnologyProfile(
            project_id=r["project_id"],
            languages=json.loads(r["languages_json"]) if r["languages_json"] else [],
            frameworks=json.loads(r["frameworks_json"]) if r["frameworks_json"] else [],
            libraries=json.loads(r["libraries_json"]) if r["libraries_json"] else [],
            dependencies=json.loads(r["dependencies_json"]) if r["dependencies_json"] else {},
            databases=json.loads(r["databases_json"]) if r["databases_json"] else [],
            storage=json.loads(r["storage_json"]) if r["storage_json"] else [],
            infrastructure=json.loads(r["infrastructure_json"]) if r["infrastructure_json"] else [],
            ml_stack=json.loads(r["ml_stack_json"]) if r["ml_stack_json"] else [],
            deployment=json.loads(r["deployment_json"]) if r["deployment_json"] else [],
            observability=json.loads(r["observability_json"]) if r["observability_json"] else [],
            testing=json.loads(r["testing_json"]) if r["testing_json"] else [],
            topics=json.loads(r["topics_json"]) if r["topics_json"] else [],
            profile_text=r["profile_text"] or "",
            profile_hash=r["profile_hash"] or "",
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )

    # --- Project Embeddings ---

    def save_project_embedding(self, project_id: str, model_name: str, embedding: np.ndarray, content_hash: str) -> bool:
        emb_bytes = embedding.astype(np.float32).tobytes()
        dim = int(embedding.shape[0])
        now_str = datetime.now(timezone.utc).isoformat()
        sql = """
        INSERT OR REPLACE INTO project_embeddings (project_id, model_name, embedding, dimension, content_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(sql, (project_id, model_name, emb_bytes, dim, content_hash, now_str))
        self.conn.commit()
        return True

    def get_project_embedding(self, project_id: str, model_name: str) -> Optional[np.ndarray]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT embedding, dimension FROM project_embeddings WHERE project_id = ? AND model_name = ? LIMIT 1",
            (project_id, model_name),
        )
        row = cursor.fetchone()
        if not row:
            return None
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        return emb

    def get_cached_project_embedding(self, content_hash: str, model_name: str) -> Optional[np.ndarray]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT embedding, dimension FROM project_embeddings WHERE content_hash = ? AND model_name = ? LIMIT 1",
            (content_hash, model_name),
        )
        row = cursor.fetchone()
        if not row:
            return None
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        return emb

    # --- Project Matches ---

    def save_project_match(self, match: ProjectMatch) -> bool:
        sql = """
        INSERT OR REPLACE INTO project_matches (
            id, project_id, entity_type, entity_id, match_type,
            relevance_score, impact_score, recommendation, reason_codes_json,
            explanation_json, explanation_version, evaluated_at,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                match.id,
                match.project_id,
                match.entity_type,
                match.entity_id,
                match.match_type,
                match.relevance_score,
                match.impact_score,
                match.recommendation,
                json.dumps(match.reason_codes),
                match.explanation.model_dump_json() if match.explanation else None,
                match.explanation_version,
                match.evaluated_at.isoformat() if match.evaluated_at else None,
                match.created_at.isoformat(),
                match.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    @staticmethod
    def _row_to_project_match(r: sqlite3.Row) -> ProjectMatch:
        d = dict(r)
        explanation = None
        if d.get("explanation_json"):
            try:
                explanation = ProjectMatchExplanation.model_validate_json(d["explanation_json"])
            except Exception:
                explanation = None
        return ProjectMatch(
            id=d["id"],
            project_id=d["project_id"],
            entity_type=d["entity_type"],
            entity_id=d["entity_id"],
            match_type=d["match_type"],
            relevance_score=d["relevance_score"] if d["relevance_score"] is not None else None,
            impact_score=d["impact_score"] if d["impact_score"] is not None else None,
            recommendation=d["recommendation"],
            reason_codes=json.loads(d["reason_codes_json"]) if d.get("reason_codes_json") else [],
            explanation=explanation,
            explanation_version=d.get("explanation_version"),
            evaluated_at=datetime.fromisoformat(d["evaluated_at"]) if d.get("evaluated_at") else None,
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
        )

    def get_project_matches(self, project_id: str) -> List[ProjectMatch]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM project_matches WHERE project_id = ? ORDER BY impact_score DESC, relevance_score DESC",
            (project_id,),
        )
        return [self._row_to_project_match(r) for r in cursor.fetchall()]

    def get_all_project_matches(self) -> List[ProjectMatch]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM project_matches ORDER BY impact_score DESC, relevance_score DESC")
        return [self._row_to_project_match(r) for r in cursor.fetchall()]

    def get_project_match(self, project_id: str, entity_id: str) -> Optional[ProjectMatch]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM project_matches WHERE project_id = ? AND entity_id = ? LIMIT 1",
            (project_id, entity_id),
        )
        row = cursor.fetchone()
        return self._row_to_project_match(row) if row else None

    def get_project_match_counts(self) -> Dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT project_id, count(*) as cnt FROM project_matches GROUP BY project_id")
        return {r["project_id"]: r["cnt"] for r in cursor.fetchall()}

    def get_project_matches_by_cluster_ids(self, cluster_ids: List[str]) -> Dict[str, List[ProjectMatch]]:
        """Batch load project matches for multiple cluster IDs grouped by cluster ID."""
        if not cluster_ids:
            return {}
        clean_ids = list(dict.fromkeys(cid for cid in cluster_ids if cid))
        if not clean_ids:
            return {}
        cursor = self.conn.cursor()
        out = defaultdict(list)
        for i in range(0, len(clean_ids), 500):
            chunk = clean_ids[i:i + 500]
            ph = ",".join("?" for _ in chunk)
            sql = f"""
            SELECT * FROM project_matches
            WHERE entity_id IN ({ph}) AND entity_type = 'cluster'
            ORDER BY impact_score DESC, relevance_score DESC
            """
            cursor.execute(sql, chunk)
            for r in cursor.fetchall():
                out[r["entity_id"]].append(self._row_to_project_match(r))
        return dict(out)

    def get_claim_counts_by_cluster_ids(self, cluster_ids: List[str]) -> Dict[str, int]:
        if not cluster_ids:
            return {}
        cursor = self.conn.cursor()
        ph = ",".join(["?"] * len(cluster_ids))
        cursor.execute(f"SELECT cluster_id, count(*) as cnt FROM claims WHERE cluster_id IN ({ph}) GROUP BY cluster_id", tuple(cluster_ids))
        return {r["cluster_id"]: r["cnt"] for r in cursor.fetchall()}

    def get_event_counts_by_cluster_ids(self, cluster_ids: List[str]) -> Dict[str, int]:
        if not cluster_ids:
            return {}
        cursor = self.conn.cursor()
        ph = ",".join(["?"] * len(cluster_ids))
        cursor.execute(f"SELECT cluster_id, count(*) as cnt FROM cluster_events WHERE cluster_id IN ({ph}) GROUP BY cluster_id", tuple(cluster_ids))
        return {r["cluster_id"]: r["cnt"] for r in cursor.fetchall()}

    def clear_project_matches(self, project_id: Optional[str] = None) -> bool:
        if project_id:
            self.conn.execute("DELETE FROM project_matches WHERE project_id = ?", (project_id,))
        else:
            self.conn.execute("DELETE FROM project_matches")
        self.conn.commit()
        return True

    def clear_claims_and_evidence(self) -> None:
        """Clear only claims, evidence, and technology_assessments tables."""
        self.conn.execute("DELETE FROM claims")
        self.conn.execute("DELETE FROM evidence")
        self.conn.execute("DELETE FROM technology_assessments")
        self.conn.execute("DELETE FROM claim_revisions")
        self.conn.execute("DELETE FROM technology_assessment_revisions")
        self.conn.execute("DELETE FROM technology_states")
        self.conn.execute("DELETE FROM recheck_queue")
        self.conn.execute("DELETE FROM intelligence_changes")
        self.conn.commit()

    # --- Session 8: Inbox, Saved Items, User Feedback, and Daily Briefings ---

    def _row_to_inbox_item(self, r: sqlite3.Row) -> InboxItem:
        d = dict(r)
        return InboxItem(
            id=d["id"],
            entity_type=d["entity_type"],
            entity_id=d["entity_id"],
            story_cluster_id=d["story_cluster_id"],
            title=d["title"],
            section=d["section"],
            inbox_score=d["inbox_score"] if d["inbox_score"] is not None else None,
            rank_score=d["rank_score"] if d["rank_score"] is not None else None,
            project_impact_score=d["project_impact_score"] if d["project_impact_score"] is not None else None,
            state=d["state"],
            item_type=d["item_type"],
            created_at=datetime.fromisoformat(d["created_at"]),
            first_seen_at=datetime.fromisoformat(d["first_seen_at"]) if d.get("first_seen_at") else None,
            last_seen_at=datetime.fromisoformat(d["last_seen_at"]) if d.get("last_seen_at") else None,
            expires_at=datetime.fromisoformat(d["expires_at"]),
            seen_at=datetime.fromisoformat(d["seen_at"]) if d.get("seen_at") else None,
            opened_at=datetime.fromisoformat(d["opened_at"]) if d.get("opened_at") else None,
            is_starred=bool(d["is_starred"]),
            saved_item_id=d.get("saved_item_id"),
            matched_project_ids=json.loads(d["matched_project_ids_json"]) if d.get("matched_project_ids_json") else [],
            reason_codes=json.loads(d["reason_codes_json"]) if d.get("reason_codes_json") else [],
            surface_date=d.get("surface_date"),
            latest_event_at=d.get("latest_event_at"),
            last_materialized_at=d.get("last_materialized_at"),
            data_cutoff_at=d.get("data_cutoff_at"),
            freshness_kind=d.get("freshness_kind"),
            daily_run_id=d.get("daily_run_id"),
            source_published_at=datetime.fromisoformat(d["source_published_at"]) if d.get("source_published_at") else None,
            source_updated_at=datetime.fromisoformat(d["source_updated_at"]) if d.get("source_updated_at") else None,
            last_changed_at=datetime.fromisoformat(d["last_changed_at"]) if d.get("last_changed_at") else None,
            last_evaluated_at=datetime.fromisoformat(d["last_evaluated_at"]) if d.get("last_evaluated_at") else None,
            surfaced_at=datetime.fromisoformat(d["surfaced_at"]) if d.get("surfaced_at") else None,
            snapshot_date=d.get("snapshot_date"),
            freshness_reason=d.get("freshness_reason"),
        )

    def save_inbox_item(self, item: InboxItem) -> bool:
        sql = """
        INSERT OR REPLACE INTO inbox_items (
            id, entity_type, entity_id, story_cluster_id, title, section,
            inbox_score, rank_score, project_impact_score, state, item_type,
            created_at, first_seen_at, last_seen_at, expires_at, seen_at,
            opened_at, is_starred, saved_item_id, matched_project_ids_json,
            reason_codes_json, surface_date, latest_event_at, last_materialized_at,
            data_cutoff_at, freshness_kind, daily_run_id,
            source_published_at, source_updated_at, last_changed_at,
            last_evaluated_at, surfaced_at, snapshot_date, freshness_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                item.id,
                item.entity_type,
                item.entity_id,
                item.story_cluster_id,
                item.title,
                item.section,
                item.inbox_score,
                item.rank_score,
                item.project_impact_score,
                item.state,
                item.item_type,
                item.created_at.isoformat(),
                item.first_seen_at.isoformat() if item.first_seen_at else None,
                item.last_seen_at.isoformat() if item.last_seen_at else None,
                item.expires_at.isoformat(),
                item.seen_at.isoformat() if item.seen_at else None,
                item.opened_at.isoformat() if item.opened_at else None,
                1 if item.is_starred else 0,
                item.saved_item_id,
                json.dumps(item.matched_project_ids),
                json.dumps(item.reason_codes),
                item.surface_date,
                item.latest_event_at,
                item.last_materialized_at,
                item.data_cutoff_at,
                item.freshness_kind,
                item.daily_run_id,
                item.source_published_at.isoformat() if item.source_published_at else None,
                item.source_updated_at.isoformat() if item.source_updated_at else None,
                item.last_changed_at.isoformat() if item.last_changed_at else None,
                item.last_evaluated_at.isoformat() if item.last_evaluated_at else None,
                item.surfaced_at.isoformat() if item.surfaced_at else None,
                item.snapshot_date,
                item.freshness_reason,
            ),
        )
        self.conn.commit()
        return True


    def get_inbox_item(self, inbox_id: str) -> Optional[InboxItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM inbox_items WHERE id = ?", (inbox_id,))
        row = cursor.fetchone()
        return self._row_to_inbox_item(row) if row else None

    def get_inbox_item_by_cluster(self, cluster_id: str) -> Optional[InboxItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM inbox_items WHERE story_cluster_id = ? ORDER BY created_at DESC LIMIT 1", (cluster_id,))
        row = cursor.fetchone()
        return self._row_to_inbox_item(row) if row else None

    def get_active_inbox_items(
        self,
        include_expired: bool = False,
        include_suppressed: bool = False,
        limit: Optional[int] = None,
    ) -> List[InboxItem]:
        cursor = self.conn.cursor()
        if include_expired:
            query = "SELECT * FROM inbox_items ORDER BY inbox_score DESC"
        elif include_suppressed:
            query = "SELECT * FROM inbox_items WHERE state NOT IN ('expired', 'archived') ORDER BY inbox_score DESC"
        else:
            query = "SELECT * FROM inbox_items WHERE state IN ('unseen', 'seen', 'opened', 'starred') ORDER BY inbox_score DESC"

        params: List[Any] = []
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)
        return [self._row_to_inbox_item(r) for r in cursor.fetchall()]

    def get_inbox_items_by_surface_date(
        self,
        surface_date: str,
        include_expired: bool = False,
        include_suppressed: bool = False,
        limit: Optional[int] = None,
    ) -> List[InboxItem]:
        """Returns inbox items materialized for an EXACT surface_date snapshot.

        This is the date-specific immutable snapshot query: it never returns
        historically active rows from other days.
        """
        cursor = self.conn.cursor()
        if include_expired:
            state_filter = ""
        elif include_suppressed:
            state_filter = " AND state NOT IN ('expired', 'archived')"
        else:
            state_filter = " AND state IN ('unseen', 'seen', 'opened', 'starred')"
        query = f"SELECT * FROM inbox_items WHERE surface_date = ?{state_filter} ORDER BY inbox_score DESC"
        params: List[Any] = [surface_date]
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        cursor.execute(query, params)
        return [self._row_to_inbox_item(r) for r in cursor.fetchall()]

    def get_inbox_items_by_daily_run_id(
        self,
        daily_run_id: str,
        limit: Optional[int] = None,
    ) -> List[InboxItem]:
        """Returns inbox items produced by an EXACT daily_run_id."""
        cursor = self.conn.cursor()
        query = "SELECT * FROM inbox_items WHERE daily_run_id = ? ORDER BY inbox_score DESC"
        params: List[Any] = [daily_run_id]
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        cursor.execute(query, params)
        return [self._row_to_inbox_item(r) for r in cursor.fetchall()]

    def get_active_inbox_items_for_date(
        self,
        surface_date: str,
        limit: Optional[int] = None,
    ) -> List[InboxItem]:
        """Returns active inbox items for the requested runtime-local date.

        Includes legacy rows with no surface_date (NULL) so pre-snapshot data
        remains visible, but never returns dated rows from other days.
        """
        cursor = self.conn.cursor()
        query = (
            "SELECT * FROM inbox_items "
            "WHERE state IN ('unseen', 'seen', 'opened', 'starred') "
            "AND (surface_date IS NULL OR surface_date = ?) "
            "ORDER BY inbox_score DESC"
        )
        params: List[Any] = [surface_date]
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        cursor.execute(query, params)
        return [self._row_to_inbox_item(r) for r in cursor.fetchall()]

    def get_inbox_items_by_state(self, state: str) -> List[InboxItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM inbox_items WHERE state = ? ORDER BY inbox_score DESC", (state,))
        return [self._row_to_inbox_item(r) for r in cursor.fetchall()]

    def get_all_inbox_items(self, limit: int = 200) -> List[InboxItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM inbox_items ORDER BY created_at DESC, inbox_score DESC LIMIT ?", (limit,))
        return [self._row_to_inbox_item(r) for r in cursor.fetchall()]

    def update_inbox_item_state(
        self,
        inbox_id: str,
        state: str,
        seen_at: Optional[datetime] = None,
        opened_at: Optional[datetime] = None,
        is_starred: Optional[bool] = None,
        saved_item_id: Optional[str] = None,
    ) -> bool:
        item = self.get_inbox_item(inbox_id)
        if not item:
            return False
        item.state = state
        if seen_at:
            item.seen_at = seen_at
        if opened_at:
            item.opened_at = opened_at
        if is_starred is not None:
            item.is_starred = is_starred
        if saved_item_id is not None:
            item.saved_item_id = saved_item_id
        return self.save_inbox_item(item)

    def expire_old_inbox_items(self, now: Optional[datetime] = None) -> int:
        if now is None:
            now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        cursor = self.conn.cursor()
        # Expire non-starred items whose expires_at is in the past and state != 'expired'.
        # Phase 4 Req 3: TTL expiry applies only to legacy rows without a
        # surface_date. Date-specific snapshot rows are governed by the daily
        # materialization lifecycle (prior-day suppression), not by the TTL,
        # so they remain recoverable as carry-forward candidates.
        cursor.execute(
            """
            UPDATE inbox_items
            SET state = 'expired'
            WHERE expires_at <= ? AND is_starred = 0 AND state != 'expired'
              AND surface_date IS NULL
            """,
            (now_str,),
        )
        expired_count = cursor.rowcount
        self.conn.commit()
        return expired_count

    def clear_inbox_items(self) -> None:
        self.conn.execute("DELETE FROM inbox_items")
        self.conn.commit()

    # --- SavedItem Methods ---

    def _row_to_saved_item(self, r: sqlite3.Row) -> SavedItem:
        d = dict(r)
        entity_type = d.get("entity_type") or "cluster"
        entity_id = d.get("entity_id") or d.get("story_cluster_id") or ""
        story_cluster_id = d.get("story_cluster_id") or entity_id
        title_snap = d.get("title_snapshot") or d.get("snapshot_title")
        mat_snap = d.get("maturity_snapshot") or d.get("snapshot_maturity_stage")
        ver_snap = d.get("verification_snapshot") or d.get("snapshot_verification_score")
        risk_snap = d.get("risk_snapshot")
        claim_status_snap = d.get("claim_status_snapshot")
        risk_status_snap = d.get("risk_status_snapshot")
        risk_level_snap = d.get("risk_level_snapshot")
        tags = json.loads(d["tags_json"]) if d.get("tags_json") else []
        proj_ids = json.loads(d["project_ids_json"]) if d.get("project_ids_json") else []
        event_ids = json.loads(d["event_ids_snapshot_json"]) if d.get("event_ids_snapshot_json") else []

        return SavedItem(
            id=d["id"],
            entity_type=entity_type,
            entity_id=entity_id,
            story_cluster_id=story_cluster_id,
            inbox_item_id=d.get("inbox_item_id"),
            title_snapshot=title_snap,
            saved_at=datetime.fromisoformat(d["saved_at"]),
            verification_snapshot=ver_snap,
            maturity_snapshot=mat_snap,
            risk_snapshot=risk_snap,
            claim_status_snapshot=claim_status_snap,
            risk_status_snapshot=risk_status_snap,
            risk_level_snapshot=risk_level_snap,
            user_note=d.get("user_note"),
            tags=tags,
            project_ids=proj_ids,
            is_active=bool(d.get("is_active", 1)),
            link_status=d.get("link_status") or "resolved",
            event_ids_snapshot=event_ids,
        )

    def save_saved_item(self, item: SavedItem) -> bool:
        sql = """
        INSERT OR REPLACE INTO saved_items (
            id, entity_type, entity_id, story_cluster_id, inbox_item_id,
            title_snapshot, saved_at, verification_snapshot, maturity_snapshot,
            risk_snapshot, claim_status_snapshot, risk_status_snapshot, risk_level_snapshot,
            user_note, tags_json, project_ids_json, is_active,
            link_status, event_ids_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                item.id,
                item.entity_type,
                item.entity_id,
                item.story_cluster_id,
                item.inbox_item_id,
                item.title_snapshot,
                item.saved_at.isoformat(),
                item.verification_snapshot,
                item.maturity_snapshot,
                item.risk_snapshot,
                item.claim_status_snapshot,
                item.risk_status_snapshot,
                item.risk_level_snapshot,
                item.user_note,
                json.dumps(item.tags),
                json.dumps(item.project_ids),
                1 if item.is_active else 0,
                item.link_status,
                json.dumps(item.event_ids_snapshot),
            ),
        )
        self.conn.commit()
        return True

    def get_saved_item(self, saved_id: str) -> Optional[SavedItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM saved_items WHERE id = ?", (saved_id,))
        row = cursor.fetchone()
        return self._row_to_saved_item(row) if row else None

    def get_saved_item_by_cluster(self, cluster_id: str) -> Optional[SavedItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM saved_items WHERE story_cluster_id = ? ORDER BY saved_at DESC LIMIT 1", (cluster_id,))
        row = cursor.fetchone()
        return self._row_to_saved_item(row) if row else None

    def get_all_saved_items(self, active_only: bool = True) -> List[SavedItem]:
        cursor = self.conn.cursor()
        if active_only:
            cursor.execute("SELECT * FROM saved_items WHERE is_active = 1 ORDER BY saved_at DESC")
        else:
            cursor.execute("SELECT * FROM saved_items ORDER BY saved_at DESC")
        return [self._row_to_saved_item(r) for r in cursor.fetchall()]

    def get_saved_items(self, active_only: bool = True) -> List[SavedItem]:
        return self.get_all_saved_items(active_only=active_only)

    def update_saved_item_note(self, saved_id: str, user_note: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE saved_items SET user_note = ? WHERE id = ?", (user_note, saved_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def add_saved_item_tag(self, saved_id: str, tag: str) -> bool:
        item = self.get_saved_item(saved_id)
        if not item:
            return False
        clean_tag = tag.strip().lower()
        if clean_tag and clean_tag not in item.tags:
            item.tags.append(clean_tag)
            return self.save_saved_item(item)
        return True

    def deactivate_saved_item(self, saved_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE saved_items SET is_active = 0 WHERE id = ?", (saved_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def clear_saved_items(self) -> None:
        self.conn.execute("DELETE FROM saved_items")
        self.conn.commit()

    # --- UserFeedback Methods ---

    def save_user_feedback(self, feedback: UserFeedback) -> bool:
        sql = """
        INSERT OR REPLACE INTO user_feedback (
            id, entity_type, entity_id, action, value, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                feedback.id,
                feedback.entity_type,
                feedback.entity_id,
                feedback.action,
                feedback.value,
                feedback.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_user_feedback(self, limit: int = 100) -> List[UserFeedback]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_feedback ORDER BY created_at DESC LIMIT ?", (limit,))
        return [
            UserFeedback(
                id=r["id"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                action=r["action"],
                value=r["value"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_feedback_counts(self) -> Dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT action, COUNT(*) as count FROM user_feedback GROUP BY action")
        counts = {"star": 0, "unstar": 0, "open": 0, "dismiss": 0, "useful": 0, "not_useful": 0}
        for row in cursor.fetchall():
            counts[row["action"]] = row["count"]
        return counts

    # --- DailyBriefing Methods ---

    def save_daily_briefing(self, briefing: DailyBriefing) -> bool:
        sql = """
        INSERT OR REPLACE INTO daily_briefings (
            id, briefing_date, generated_at, total_items, high_priority_count,
            project_relevant_count, content_hash, summary_text, sections_json, created_at,
            runtime_timezone, data_cutoff_at, generation_status, source_status_json,
            daily_run_id, original_generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                briefing.id,
                briefing.briefing_date,
                briefing.generated_at.isoformat(),
                briefing.total_items,
                briefing.high_priority_count,
                briefing.project_relevant_count,
                briefing.content_hash,
                briefing.summary_text,
                json.dumps(briefing.sections),
                briefing.created_at.isoformat(),
                briefing.runtime_timezone,
                briefing.data_cutoff_at,
                briefing.generation_status,
                briefing.source_status_json,
                briefing.daily_run_id,
                briefing.original_generated_at,
            ),
        )
        self.conn.commit()
        return True

    def _row_to_daily_briefing(self, row: sqlite3.Row) -> DailyBriefing:
        d = dict(row)
        return DailyBriefing(
            id=d["id"],
            briefing_date=d["briefing_date"],
            generated_at=datetime.fromisoformat(d["generated_at"]),
            total_items=d["total_items"],
            high_priority_count=d["high_priority_count"],
            project_relevant_count=d["project_relevant_count"],
            content_hash=d["content_hash"],
            summary_text=d["summary_text"],
            sections=json.loads(d["sections_json"]) if d["sections_json"] else {},
            created_at=datetime.fromisoformat(d["created_at"]),
            runtime_timezone=d.get("runtime_timezone"),
            data_cutoff_at=d.get("data_cutoff_at"),
            generation_status=d.get("generation_status"),
            source_status_json=d.get("source_status_json"),
            daily_run_id=d.get("daily_run_id"),
            original_generated_at=d.get("original_generated_at"),
        )

    def get_daily_briefing(self, briefing_date: str) -> Optional[DailyBriefing]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_briefings WHERE briefing_date = ?", (briefing_date,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_daily_briefing(row)

    def get_briefing_with_metadata(
        self, briefing_date: str
    ) -> Tuple[Optional[DailyBriefing], Optional[DailySignalRun], int, Optional[str]]:
        """Loads a briefing plus its Phase 4 display metadata in ONE query.

        Returns (briefing, daily_run, revision_count, last_successful_date).
        Batches what used to be get_daily_briefing + get_daily_signal_run_by_date
        + count_briefing_revisions + get_last_successful_briefing_date so the
        Morning Brief read path stays at a constant, minimal query count.
        The run join uses a LIMIT-1 subquery because (runtime_date,
        runtime_timezone, run_kind) is the uniqueness key, so a date can have
        more than one run row.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT b.*,
                   r.id AS run_id,
                   r.runtime_date AS run_runtime_date,
                   r.runtime_timezone AS run_runtime_timezone,
                   r.run_kind AS run_run_kind,
                   r.started_at AS run_started_at,
                   r.completed_at AS run_completed_at,
                   r.data_cutoff_at AS run_data_cutoff_at,
                   r.status AS run_status,
                   r.new_signal_count AS run_new_signal_count,
                   r.updated_signal_count AS run_updated_signal_count,
                   r.carried_signal_count AS run_carried_signal_count,
                   r.retry_count AS run_retry_count,
                   r.briefing_id AS run_briefing_id,
                   r.source_status_json AS run_source_status_json,
                   r.error_summary AS run_error_summary,
                   r.content_hash AS run_content_hash,
                   (SELECT COUNT(*) FROM daily_briefing_revisions rev
                     WHERE rev.briefing_id = b.id) AS revision_count,
                   (SELECT MAX(b2.briefing_date) FROM daily_briefings b2
                     WHERE b2.briefing_date < b.briefing_date
                       AND b2.generation_status IN ('completed', 'completed_empty')
                   ) AS last_successful_date
            FROM daily_briefings b
            LEFT JOIN (
                SELECT * FROM daily_signal_runs WHERE runtime_date = ? LIMIT 1
            ) r ON 1 = 1
            WHERE b.briefing_date = ?
            """,
            (briefing_date, briefing_date),
        )
        row = cursor.fetchone()
        if not row:
            return None, None, 0, None
        d = dict(row)
        briefing = self._row_to_daily_briefing(row)

        daily_run: Optional[DailySignalRun] = None
        if d.get("run_id") is not None:
            daily_run = DailySignalRun(
                id=d["run_id"],
                runtime_date=d["run_runtime_date"],
                runtime_timezone=d["run_runtime_timezone"],
                run_kind=d.get("run_run_kind") or "daily_refresh",
                started_at=datetime.fromisoformat(d["run_started_at"]),
                completed_at=datetime.fromisoformat(d["run_completed_at"]) if d.get("run_completed_at") else None,
                data_cutoff_at=datetime.fromisoformat(d["run_data_cutoff_at"]) if d.get("run_data_cutoff_at") else None,
                status=d["run_status"],
                new_signal_count=d.get("run_new_signal_count") or 0,
                updated_signal_count=d.get("run_updated_signal_count") or 0,
                carried_signal_count=d.get("run_carried_signal_count") or 0,
                retry_count=d.get("run_retry_count") or 0,
                briefing_id=d.get("run_briefing_id"),
                source_status_json=d.get("run_source_status_json"),
                error_summary=d.get("run_error_summary"),
                content_hash=d.get("run_content_hash") or "",
            )

        revision_count = int(d.get("revision_count") or 0)
        last_successful_date = d.get("last_successful_date")
        return briefing, daily_run, revision_count, last_successful_date

    def get_latest_daily_briefing(self) -> Optional[DailyBriefing]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_briefings ORDER BY briefing_date DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_daily_briefing(row)

    def get_last_successful_briefing_date(self, before_date: str) -> Optional[str]:
        """Returns the most recent briefing date strictly before `before_date`
        whose generation succeeded (completed or a valid completed_empty quiet
        day). Used for the "last successful briefing" link on failed days."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT briefing_date FROM daily_briefings "
            "WHERE briefing_date < ? AND generation_status IN ('completed', 'completed_empty') "
            "ORDER BY briefing_date DESC LIMIT 1",
            (before_date,),
        )
        row = cursor.fetchone()
        return row["briefing_date"] if row else None

    def count_briefing_revisions(self, briefing_id: str) -> int:
        """Returns the number of immutable revisions recorded for a briefing."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS n FROM daily_briefing_revisions WHERE briefing_id = ?",
            (briefing_id,),
        )
        row = cursor.fetchone()
        return int(row["n"]) if row else 0

    def create_briefing_revision(self, briefing_id: str) -> Optional[str]:
        """Snapshots the current briefing state into a new immutable revision record."""
        def _operation(cursor):
            # 1. Determine next revision number
            cursor.execute(
                "SELECT MAX(revision_number) FROM daily_briefing_revisions WHERE briefing_id = ?",
                (briefing_id,)
            )
            row = cursor.fetchone()
            next_rev = 1
            if row and row[0] is not None:
                next_rev = row[0] + 1

            # 2. Check if revision already exists (to never overwrite)
            cursor.execute(
                "SELECT 1 FROM daily_briefing_revisions WHERE briefing_id = ? AND revision_number = ?",
                (briefing_id, next_rev)
            )
            if cursor.fetchone():
                raise DatabaseMigrationError(f"Revision {next_rev} already exists for briefing {briefing_id}")

            import uuid
            rev_id = str(uuid.uuid4())

            # 3. Fetch current briefing
            cursor.execute("SELECT * FROM daily_briefings WHERE id = ?", (briefing_id,))
            b_row = cursor.fetchone()
            if not b_row:
                return None

            b_dict = dict(b_row)

            # 4. Insert into revisions
            sql_rev = """
            INSERT INTO daily_briefing_revisions (
                id, briefing_id, revision_number, generated_at, data_cutoff_at,
                source_status_json, content_hash, generation_status, item_count,
                daily_run_id, runtime_timezone, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(sql_rev, (
                rev_id,
                briefing_id,
                next_rev,
                b_dict["generated_at"],
                b_dict["data_cutoff_at"],
                b_dict["source_status_json"],
                b_dict["content_hash"],
                b_dict["generation_status"],
                b_dict["total_items"],
                b_dict["daily_run_id"],
                b_dict.get("runtime_timezone"),
                b_dict.get("created_at"),
            ))

            # 5. Copy items
            cursor.execute("SELECT * FROM daily_briefing_items WHERE briefing_id = ?", (briefing_id,))
            items = cursor.fetchall()

            if items:
                sql_item_rev = """
                INSERT INTO daily_briefing_revision_items (
                    revision_id, inbox_item_id, position, section, title, summary,
                    story_cluster_id, item_type, reason_codes_json, inbox_score,
                    rank_score, project_impact_score, matched_project_ids_json,
                    snapshot_version, source_published_at, source_updated_at,
                    first_seen_at, last_changed_at, last_evaluated_at, surfaced_at,
                    snapshot_date, daily_run_id, freshness_kind, freshness_reason,
                    content_hash, source_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                for it_row in items:
                    it = dict(it_row)
                    cursor.execute(sql_item_rev, (
                        rev_id,
                        it["inbox_item_id"],
                        it["position"],
                        it["section"],
                        it["title"],
                        it["summary"],
                        it["story_cluster_id"],
                        it["item_type"],
                        it["reason_codes_json"],
                        it["inbox_score"],
                        it["rank_score"],
                        it["project_impact_score"],
                        it["matched_project_ids_json"],
                        it["snapshot_version"],
                        it.get("source_published_at"),
                        it.get("source_updated_at"),
                        it.get("first_seen_at"),
                        it.get("last_changed_at"),
                        it.get("last_evaluated_at"),
                        it.get("surfaced_at"),
                        it.get("snapshot_date"),
                        it.get("daily_run_id"),
                        it.get("freshness_kind"),
                        it.get("freshness_reason"),
                        it.get("content_hash"),
                        it.get("source_name")
                    ))
            return rev_id

        return self._execute_in_write_transaction(_operation, operation_name="create_briefing_revision")

    def save_daily_briefing_with_items(self, briefing: DailyBriefing, items: List[DailyBriefingItem]) -> bool:
        """Atomically saves daily briefing header and its item snapshots in a single transaction."""
        self._require_writable("save_daily_briefing_with_items")
        def _operation(cursor):
            sql_briefing = """
            INSERT OR REPLACE INTO daily_briefings (
                id, briefing_date, generated_at, total_items, high_priority_count,
                project_relevant_count, content_hash, summary_text, sections_json, created_at,
                runtime_timezone, data_cutoff_at, generation_status, source_status_json,
                daily_run_id, original_generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(
                sql_briefing,
                (
                    briefing.id,
                    briefing.briefing_date,
                    briefing.generated_at.isoformat() if hasattr(briefing.generated_at, "isoformat") else briefing.generated_at,
                    briefing.total_items,
                    briefing.high_priority_count,
                    briefing.project_relevant_count,
                    briefing.content_hash,
                    briefing.summary_text,
                    json.dumps(briefing.sections),
                    briefing.created_at.isoformat() if hasattr(briefing.created_at, "isoformat") else briefing.created_at,
                    briefing.runtime_timezone,
                    briefing.data_cutoff_at,
                    briefing.generation_status,
                    briefing.source_status_json,
                    briefing.daily_run_id,
                    briefing.original_generated_at,
                ),
            )
            cursor.execute("DELETE FROM daily_briefing_items WHERE briefing_id = ?", (briefing.id,))
            sql_item = """
            INSERT OR REPLACE INTO daily_briefing_items (
                briefing_id, inbox_item_id, position, section,
                title, summary, story_cluster_id, item_type,
                reason_codes_json, inbox_score, rank_score,
                project_impact_score, matched_project_ids_json, snapshot_version,
                source_published_at, source_updated_at, first_seen_at, last_changed_at,
                last_evaluated_at, surfaced_at, snapshot_date, daily_run_id,
                freshness_kind, freshness_reason, content_hash, source_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            for it in items:
                cursor.execute(
                    sql_item,
                    (
                        it.briefing_id,
                        it.inbox_item_id,
                        it.position,
                        it.section,
                        it.title,
                        it.summary,
                        it.story_cluster_id,
                        it.item_type,
                        json.dumps(it.reason_codes) if it.reason_codes else None,
                        it.inbox_score,
                        it.rank_score,
                        it.project_impact_score,
                        json.dumps(it.matched_project_ids) if it.matched_project_ids else None,
                        getattr(it, "snapshot_version", None),
                        getattr(it, "source_published_at", None).isoformat() if hasattr(getattr(it, "source_published_at", None), "isoformat") else getattr(it, "source_published_at", None),
                        getattr(it, "source_updated_at", None).isoformat() if hasattr(getattr(it, "source_updated_at", None), "isoformat") else getattr(it, "source_updated_at", None),
                        getattr(it, "first_seen_at", None).isoformat() if hasattr(getattr(it, "first_seen_at", None), "isoformat") else getattr(it, "first_seen_at", None),
                        getattr(it, "last_changed_at", None).isoformat() if hasattr(getattr(it, "last_changed_at", None), "isoformat") else getattr(it, "last_changed_at", None),
                        getattr(it, "last_evaluated_at", None).isoformat() if hasattr(getattr(it, "last_evaluated_at", None), "isoformat") else getattr(it, "last_evaluated_at", None),
                        getattr(it, "surfaced_at", None).isoformat() if hasattr(getattr(it, "surfaced_at", None), "isoformat") else getattr(it, "surfaced_at", None),
                        getattr(it, "snapshot_date", None),
                        getattr(it, "daily_run_id", None),
                        getattr(it, "freshness_kind", None),
                        getattr(it, "freshness_reason", None),
                        getattr(it, "content_hash", None),
                        getattr(it, "source_name", None),
                    ),
                )
            return True

        return self._execute_in_write_transaction(_operation, operation_name="save_daily_briefing_with_items")

    def save_daily_briefing_items(self, items: List[DailyBriefingItem]) -> bool:
        if not items:
            return True
        self._require_writable("save_daily_briefing_items")
        briefing_id = items[0].briefing_id
        def _operation(cursor):
            cursor.execute("DELETE FROM daily_briefing_items WHERE briefing_id = ?", (briefing_id,))
            sql_item = """
            INSERT OR REPLACE INTO daily_briefing_items (
                briefing_id, inbox_item_id, position, section,
                title, summary, story_cluster_id, item_type,
                reason_codes_json, inbox_score, rank_score,
                project_impact_score, matched_project_ids_json, snapshot_version,
                source_published_at, source_updated_at, first_seen_at, last_changed_at,
                last_evaluated_at, surfaced_at, snapshot_date, daily_run_id,
                freshness_kind, freshness_reason, content_hash, source_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            for it in items:
                cursor.execute(
                    sql_item,
                    (
                        it.briefing_id,
                        it.inbox_item_id,
                        it.position,
                        it.section,
                        it.title,
                        it.summary,
                        it.story_cluster_id,
                        it.item_type,
                        json.dumps(it.reason_codes) if it.reason_codes else None,
                        it.inbox_score,
                        it.rank_score,
                        it.project_impact_score,
                        json.dumps(it.matched_project_ids) if it.matched_project_ids else None,
                        getattr(it, "snapshot_version", None),
                        getattr(it, "source_published_at", None).isoformat() if hasattr(getattr(it, "source_published_at", None), "isoformat") else getattr(it, "source_published_at", None),
                        getattr(it, "source_updated_at", None).isoformat() if hasattr(getattr(it, "source_updated_at", None), "isoformat") else getattr(it, "source_updated_at", None),
                        getattr(it, "first_seen_at", None).isoformat() if hasattr(getattr(it, "first_seen_at", None), "isoformat") else getattr(it, "first_seen_at", None),
                        getattr(it, "last_changed_at", None).isoformat() if hasattr(getattr(it, "last_changed_at", None), "isoformat") else getattr(it, "last_changed_at", None),
                        getattr(it, "last_evaluated_at", None).isoformat() if hasattr(getattr(it, "last_evaluated_at", None), "isoformat") else getattr(it, "last_evaluated_at", None),
                        getattr(it, "surfaced_at", None).isoformat() if hasattr(getattr(it, "surfaced_at", None), "isoformat") else getattr(it, "surfaced_at", None),
                        getattr(it, "snapshot_date", None),
                        getattr(it, "daily_run_id", None),
                        getattr(it, "freshness_kind", None),
                        getattr(it, "freshness_reason", None),
                        getattr(it, "content_hash", None),
                        getattr(it, "source_name", None),
                    ),
                )
            return True

        return self._execute_in_write_transaction(_operation, operation_name="save_daily_briefing_items")

    def get_daily_briefing_items(self, briefing_id: str) -> List[DailyBriefingItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_briefing_items WHERE briefing_id = ? ORDER BY position ASC", (briefing_id,))
        items = []
        for r in cursor.fetchall():
            keys = r.keys()
            rc = json.loads(r["reason_codes_json"]) if "reason_codes_json" in keys and r["reason_codes_json"] else []
            mp = json.loads(r["matched_project_ids_json"]) if "matched_project_ids_json" in keys and r["matched_project_ids_json"] else []
            
            def to_dt(val):
                if not val:
                    return None
                try:
                    return datetime.fromisoformat(val)
                except Exception:
                    return None
                    
            items.append(
                DailyBriefingItem(
                    briefing_id=r["briefing_id"],
                    inbox_item_id=r["inbox_item_id"],
                    position=r["position"],
                    section=r["section"],
                    title=r["title"] if "title" in keys else None,
                    summary=r["summary"] if "summary" in keys else None,
                    story_cluster_id=r["story_cluster_id"] if "story_cluster_id" in keys else None,
                    item_type=r["item_type"] if "item_type" in keys else None,
                    reason_codes=rc,
                    inbox_score=r["inbox_score"] if "inbox_score" in keys else None,
                    rank_score=r["rank_score"] if "rank_score" in keys else None,
                    project_impact_score=r["project_impact_score"] if "project_impact_score" in keys else None,
                    matched_project_ids=mp,
                    snapshot_version=r["snapshot_version"] if "snapshot_version" in keys else None,
                    source_published_at=to_dt(r["source_published_at"]) if "source_published_at" in keys and r["source_published_at"] else None,
                    source_updated_at=to_dt(r["source_updated_at"]) if "source_updated_at" in keys and r["source_updated_at"] else None,
                    first_seen_at=to_dt(r["first_seen_at"]) if "first_seen_at" in keys and r["first_seen_at"] else None,
                    last_changed_at=to_dt(r["last_changed_at"]) if "last_changed_at" in keys and r["last_changed_at"] else None,
                    last_evaluated_at=to_dt(r["last_evaluated_at"]) if "last_evaluated_at" in keys and r["last_evaluated_at"] else None,
                    surfaced_at=to_dt(r["surfaced_at"]) if "surfaced_at" in keys and r["surfaced_at"] else None,
                    snapshot_date=r["snapshot_date"] if "snapshot_date" in keys else None,
                    daily_run_id=r["daily_run_id"] if "daily_run_id" in keys else None,
                    freshness_kind=r["freshness_kind"] if "freshness_kind" in keys else None,
                    freshness_reason=r["freshness_reason"] if "freshness_reason" in keys else None,
                    content_hash=r["content_hash"] if "content_hash" in keys else None,
                    source_name=r["source_name"] if "source_name" in keys else None
                )
            )
        return items

    # --- Session 9: Autonomous Runtime, Checkpoints, and Recovery ---

    def save_source_checkpoint(self, cp: SourceCheckpoint) -> bool:
        sql = """
        INSERT OR REPLACE INTO source_checkpoints (
            source, last_success_at, last_attempt_at, last_cursor, last_event_time,
            last_error, last_error_category, consecutive_failures, failure_threshold_reached,
            max_consecutive_failures, next_retry_at, health_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                cp.source,
                cp.last_success_at.isoformat() if cp.last_success_at else None,
                cp.last_attempt_at.isoformat() if cp.last_attempt_at else None,
                cp.last_cursor,
                cp.last_event_time.isoformat() if cp.last_event_time else None,
                cp.last_error,
                cp.last_error_category,
                cp.consecutive_failures,
                1 if cp.failure_threshold_reached else 0,
                cp.max_consecutive_failures,
                cp.next_retry_at.isoformat() if cp.next_retry_at else None,
                cp.health_status,
                cp.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def _row_to_source_checkpoint(self, r: sqlite3.Row) -> SourceCheckpoint:
        keys = r.keys()
        max_f = r["max_consecutive_failures"] if "max_consecutive_failures" in keys and r["max_consecutive_failures"] is not None else 5
        consec_f = r["consecutive_failures"] if r["consecutive_failures"] is not None else 0
        thresh_reached = bool(r["failure_threshold_reached"]) if "failure_threshold_reached" in keys and r["failure_threshold_reached"] is not None else (consec_f >= max_f)

        return SourceCheckpoint(
            source=r["source"],
            last_success_at=datetime.fromisoformat(r["last_success_at"]) if r["last_success_at"] else None,
            last_attempt_at=datetime.fromisoformat(r["last_attempt_at"]) if r["last_attempt_at"] else None,
            last_cursor=r["last_cursor"],
            last_event_time=datetime.fromisoformat(r["last_event_time"]) if r["last_event_time"] else None,
            last_error=r["last_error"],
            last_error_category=r["last_error_category"] if "last_error_category" in keys else None,
            consecutive_failures=consec_f,
            failure_threshold_reached=thresh_reached,
            max_consecutive_failures=max_f,
            next_retry_at=datetime.fromisoformat(r["next_retry_at"]) if r["next_retry_at"] else None,
            health_status=r["health_status"] or "unknown",
            updated_at=datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else datetime.now(timezone.utc),
        )

    def get_source_checkpoint(self, source: str) -> Optional[SourceCheckpoint]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM source_checkpoints WHERE source = ?", (source,))
        row = cursor.fetchone()
        return self._row_to_source_checkpoint(row) if row else None

    def get_all_source_checkpoints(self) -> List[SourceCheckpoint]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM source_checkpoints ORDER BY source ASC")
        return [self._row_to_source_checkpoint(r) for r in cursor.fetchall()]

    def get_all_source_checkpoints_map(self) -> Dict[str, SourceCheckpoint]:
        """Batch loads all source checkpoints into a dictionary keyed by source name."""
        cps = self.get_all_source_checkpoints()
        return {cp.source: cp for cp in cps}

    def save_runtime_job(self, job: RuntimeJob) -> bool:
        sql = """
        INSERT OR REPLACE INTO runtime_jobs (
            job_name, last_started_at, last_completed_at, last_status,
            evaluation_status, evaluated_at, last_error, last_error_category,
            duration_seconds, run_count, failure_count, next_run_at,
            blocked_by, blocked_reason, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                job.job_name,
                job.last_started_at.isoformat() if job.last_started_at else None,
                job.last_completed_at.isoformat() if job.last_completed_at else None,
                job.last_status,
                job.evaluation_status,
                job.evaluated_at.isoformat() if job.evaluated_at else None,
                job.last_error,
                job.last_error_category,
                job.duration_seconds,
                job.run_count,
                job.failure_count,
                job.next_run_at.isoformat() if job.next_run_at else None,
                job.blocked_by,
                job.blocked_reason,
                job.updated_at.isoformat() if job.updated_at else datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def _row_to_runtime_job(self, r: sqlite3.Row) -> RuntimeJob:
        keys = r.keys()
        eval_st = r["evaluation_status"] if "evaluation_status" in keys and r["evaluation_status"] else "pending"
        return RuntimeJob(
            job_name=r["job_name"],
            last_started_at=datetime.fromisoformat(r["last_started_at"]) if r["last_started_at"] else None,
            last_completed_at=datetime.fromisoformat(r["last_completed_at"]) if r["last_completed_at"] else None,
            last_status=r["last_status"] or "pending",
            evaluation_status=eval_st,
            evaluated_at=datetime.fromisoformat(r["evaluated_at"]) if "evaluated_at" in keys and r["evaluated_at"] else None,
            last_error=r["last_error"],
            last_error_category=r["last_error_category"] if "last_error_category" in keys else None,
            duration_seconds=r["duration_seconds"],
            run_count=r["run_count"],
            failure_count=r["failure_count"],
            next_run_at=datetime.fromisoformat(r["next_run_at"]) if "next_run_at" in keys and r["next_run_at"] else None,
            blocked_by=r["blocked_by"] if "blocked_by" in keys else None,
            blocked_reason=r["blocked_reason"] if "blocked_reason" in keys else None,
            updated_at=datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else datetime.now(timezone.utc),
        )

    def get_runtime_job(self, job_name: str) -> Optional[RuntimeJob]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM runtime_jobs WHERE job_name = ?", (job_name,))
        row = cursor.fetchone()
        return self._row_to_runtime_job(row) if row else None

    def get_all_runtime_jobs(self) -> List[RuntimeJob]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM runtime_jobs ORDER BY job_name ASC")
        return [self._row_to_runtime_job(r) for r in cursor.fetchall()]

    def get_all_runtime_jobs_map(self) -> Dict[str, RuntimeJob]:
        """Batch loads all runtime jobs into a dictionary keyed by job_name."""
        jobs = self.get_all_runtime_jobs()
        return {j.job_name: j for j in jobs}

    def save_runtime_job_run(self, run: RuntimeJobRun) -> bool:
        sql = """
        INSERT OR REPLACE INTO runtime_job_runs (
            id, job_name, started_at, completed_at, status, items_processed,
            error_summary, error_category, duration_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                run.id,
                run.job_name,
                run.started_at.isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
                run.status,
                run.items_processed,
                run.error_summary,
                run.error_category,
                run.duration_seconds,
            ),
        )
        self.conn.commit()
        return True

    def _row_to_runtime_job_run(self, r: sqlite3.Row) -> RuntimeJobRun:
        keys = r.keys()
        return RuntimeJobRun(
            id=r["id"],
            job_name=r["job_name"],
            started_at=datetime.fromisoformat(r["started_at"]),
            completed_at=datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
            status=r["status"] or "running",
            items_processed=r["items_processed"],
            error_summary=r["error_summary"],
            error_category=r["error_category"] if "error_category" in keys else None,
            duration_seconds=r["duration_seconds"],
        )

    def get_recent_runtime_job_runs(self, limit: int = 50, job_name: Optional[str] = None) -> List[RuntimeJobRun]:
        cursor = self.conn.cursor()
        if job_name:
            cursor.execute(
                "SELECT * FROM runtime_job_runs WHERE job_name = ? ORDER BY started_at DESC LIMIT ?",
                (job_name, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM runtime_job_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_runtime_job_run(r) for r in cursor.fetchall()]

    def get_running_job_runs(self) -> List[RuntimeJobRun]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM runtime_job_runs WHERE status = 'running'")
        return [self._row_to_runtime_job_run(r) for r in cursor.fetchall()]

    def get_active_project_count(self) -> int:
        """Returns the count of configured active projects."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM projects WHERE is_active = 1")
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def increment_runtime_metric(self, key: str, delta: int = 1) -> int:
        now_str = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO runtime_metrics (metric_key, metric_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(metric_key) DO UPDATE SET
                metric_value = metric_value + excluded.metric_value,
                updated_at = excluded.updated_at
            """,
            (key, delta, now_str),
        )
        self.conn.commit()
        cursor.execute("SELECT metric_value FROM runtime_metrics WHERE metric_key = ?", (key,))
        row = cursor.fetchone()
        return row["metric_value"] if row else delta

    def get_runtime_metrics(self) -> Dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT metric_key, metric_value FROM runtime_metrics")
        return {r["metric_key"]: r["metric_value"] for r in cursor.fetchall()}

    def backup_database(self, backup_path: str) -> bool:
        """Performs safe online SQLite backup to backup_path."""
        os.makedirs(os.path.dirname(os.path.abspath(backup_path)), exist_ok=True)
        backup_conn = sqlite3.connect(backup_path)
        with backup_conn:
            self.conn.backup(backup_conn, pages=100, sleep=0.01)
        backup_conn.close()
        return True

    def save_daily_signal_run(self, run: DailySignalRun) -> bool:
        sql = """
        INSERT OR REPLACE INTO daily_signal_runs (
            id, runtime_date, runtime_timezone, run_kind, started_at, completed_at, data_cutoff_at,
            status, new_signal_count, updated_signal_count, carried_signal_count,
            retry_count, briefing_id, source_status_json, error_summary, content_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                run.id,
                run.runtime_date,
                run.runtime_timezone,
                run.run_kind,
                run.started_at.isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
                run.data_cutoff_at.isoformat() if run.data_cutoff_at else None,
                run.status,
                run.new_signal_count,
                run.updated_signal_count,
                run.carried_signal_count,
                run.retry_count,
                run.briefing_id,
                run.source_status_json,
                run.error_summary,
                run.content_hash,
            ),
        )
        self.conn.commit()
        return True

    def _row_to_daily_signal_run(self, r: sqlite3.Row) -> DailySignalRun:
        d = dict(r)
        return DailySignalRun(
            id=d["id"],
            runtime_date=d["runtime_date"],
            runtime_timezone=d["runtime_timezone"],
            run_kind=d.get("run_kind", "daily_refresh"),
            started_at=datetime.fromisoformat(d["started_at"]),
            completed_at=datetime.fromisoformat(d["completed_at"]) if d.get("completed_at") else None,
            data_cutoff_at=datetime.fromisoformat(d["data_cutoff_at"]) if d.get("data_cutoff_at") else None,
            status=d["status"],
            new_signal_count=d.get("new_signal_count", 0),
            updated_signal_count=d.get("updated_signal_count", 0),
            carried_signal_count=d.get("carried_signal_count", 0),
            retry_count=d.get("retry_count", 0),
            briefing_id=d.get("briefing_id"),
            source_status_json=d.get("source_status_json"),
            error_summary=d.get("error_summary"),
            content_hash=d.get("content_hash", ""),
        )

    def get_daily_signal_run(self, run_id: str) -> Optional[DailySignalRun]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_signal_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        return self._row_to_daily_signal_run(row) if row else None

    def get_daily_signal_run_by_date(self, date_str: str) -> Optional[DailySignalRun]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_signal_runs WHERE runtime_date = ?", (date_str,))
        row = cursor.fetchone()
        return self._row_to_daily_signal_run(row) if row else None

    def save_refresh_operation(self, op: RefreshOperation) -> bool:
        sql = """
        INSERT OR REPLACE INTO refresh_operations (
            id, scope, target_id, requested_at, started_at, completed_at,
            status, [trigger], job_names_json, items_processed, error_summary, result_json,
            claimed_at, lease_expires_at, heartbeat_at, worker_id, idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                op.id,
                op.scope,
                op.target_id,
                op.requested_at.isoformat(),
                op.started_at.isoformat() if op.started_at else None,
                op.completed_at.isoformat() if op.completed_at else None,
                op.status,
                op.trigger,
                op.job_names_json,
                op.items_processed,
                op.error_summary,
                op.result_json,
                op.claimed_at.isoformat() if op.claimed_at else None,
                op.lease_expires_at.isoformat() if op.lease_expires_at else None,
                op.heartbeat_at.isoformat() if op.heartbeat_at else None,
                op.worker_id,
                op.idempotency_key,
            ),
        )
        self.conn.commit()
        return True

    def _row_to_refresh_operation(self, r: sqlite3.Row) -> RefreshOperation:
        d = dict(r)
        return RefreshOperation(
            id=d["id"],
            scope=d["scope"],
            target_id=d.get("target_id"),
            requested_at=datetime.fromisoformat(d["requested_at"]),
            started_at=datetime.fromisoformat(d["started_at"]) if d.get("started_at") else None,
            completed_at=datetime.fromisoformat(d["completed_at"]) if d.get("completed_at") else None,
            status=d["status"],
            trigger=d.get("trigger") or "user_requested",
            job_names_json=d.get("job_names_json"),
            items_processed=d.get("items_processed", 0),
            error_summary=d.get("error_summary"),
            result_json=d.get("result_json"),
            claimed_at=datetime.fromisoformat(d["claimed_at"]) if d.get("claimed_at") else None,
            lease_expires_at=datetime.fromisoformat(d["lease_expires_at"]) if d.get("lease_expires_at") else None,
            heartbeat_at=datetime.fromisoformat(d["heartbeat_at"]) if d.get("heartbeat_at") else None,
            worker_id=d.get("worker_id"),
            idempotency_key=d.get("idempotency_key"),
        )

    def get_refresh_operation(self, op_id: str) -> Optional[RefreshOperation]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM refresh_operations WHERE id = ?", (op_id,))
        row = cursor.fetchone()
        return self._row_to_refresh_operation(row) if row else None

    def get_next_queued_operation(self) -> Optional[RefreshOperation]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM refresh_operations WHERE status = 'queued' ORDER BY requested_at ASC LIMIT 1")
        row = cursor.fetchone()
        return self._row_to_refresh_operation(row) if row else None

    def claim_refresh_operation(self, op_id: str, worker_id: str, claimed_at: datetime, lease_expires_at: datetime) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE refresh_operations
            SET status = 'running', worker_id = ?, claimed_at = ?, lease_expires_at = ?, heartbeat_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (worker_id, claimed_at.isoformat(), lease_expires_at.isoformat(), claimed_at.isoformat(), op_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def recover_stale_refresh_operations(self, now: datetime) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE refresh_operations
            SET status = 'failed', error_summary = 'Abandoned by worker: lease expired without heartbeat updates'
            WHERE status = 'running' AND lease_expires_at < ?
            """,
            (now.isoformat(),),
        )
        self.conn.commit()
        return cursor.rowcount

    def renew_refresh_operation_heartbeat(self, op_id: str, worker_id: str, now: datetime, lease_expires_at: datetime) -> bool:
        """Renews the lease and heartbeat of a running operation owned by worker_id.

        Returns True when the renewal was applied; False when the operation is
        not in 'running' state or is owned by a different worker (lease lost).
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE refresh_operations
            SET heartbeat_at = ?, lease_expires_at = ?
            WHERE id = ? AND status = 'running' AND worker_id = ?
            """,
            (now.isoformat(), lease_expires_at.isoformat(), op_id, worker_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def has_active_operation_in_scope(self, scope: str, target_id: Optional[str] = None) -> bool:
        cursor = self.conn.cursor()
        if target_id is not None:
            cursor.execute(
                "SELECT 1 FROM refresh_operations WHERE scope = ? AND target_id = ? AND status IN ('queued', 'running') LIMIT 1",
                (scope, target_id),
            )
        else:
            cursor.execute(
                "SELECT 1 FROM refresh_operations WHERE scope = ? AND status IN ('queued', 'running') LIMIT 1",
                (scope,),
            )
        return cursor.fetchone() is not None

    def close(self) -> None:
        if self.conn:
            try:
                if self.conn.in_transaction:
                    self.conn.rollback()
            except Exception as e:
                raise DatabaseInitializationError(f"Failed to rollback transaction on close: {e}") from e
            try:
                self.conn.close()
            except Exception as e:
                raise DatabaseInitializationError(f"Failed to close database connection: {e}") from e
            self.conn = None



