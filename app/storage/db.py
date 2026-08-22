import json
import os
import sqlite3
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
    InboxItem,
    SavedItem,
    UserFeedback,
    DailyBriefing,
    DailyBriefingItem,
    SourceCheckpoint,
    RuntimeJob,
    RuntimeJobRun,
)


class Database:
    """SQLite storage layer for events, embeddings, clusters, relationships, claims, evidence, revisions, and longitudinal state."""

    def __init__(self, db_path: str = "data/tech_intel.db"):
        self.db_path = db_path
        self.has_fts5 = False
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self) -> None:
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass

        self._migrate_columns()

        schema_path = Path(__file__).parent / "schema.sql"
        if schema_path.exists():
            with open(schema_path, "r", encoding="utf-8") as f:
                self.conn.executescript(f.read())

        self._migrate_columns()

        # Check and initialize FTS5 if supported
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(id UNINDEXED, title, text)"
            )
            self.has_fts5 = True
        except sqlite3.OperationalError:
            self.has_fts5 = False
        self.conn.commit()

    def _migrate_columns(self) -> None:
        """Ensure columns added in Session 6 exist in previously created tables."""
        claim_info = self.conn.execute("PRAGMA table_info(claims)").fetchall()
        existing_claim_cols = {r["name"] for r in claim_info}
        claim_additions = [
            ("assertion_level", "TEXT NOT NULL DEFAULT 'artifact_fact'"),
            ("is_current", "INTEGER DEFAULT 1"),
            ("superseded_by", "TEXT"),
            ("last_verified_at", "TEXT"),
            ("staleness_score", "REAL DEFAULT 0.0"),
            ("valid_from", "TEXT"),
            ("valid_until", "TEXT"),
        ]
        for col_name, col_def in claim_additions:
            if col_name not in existing_claim_cols:
                try:
                    self.conn.execute(f"ALTER TABLE claims ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

        ev_info = self.conn.execute("PRAGMA table_info(evidence)").fetchall()
        existing_ev_cols = {r["name"] for r in ev_info}
        ev_additions = [
            ("is_current", "INTEGER DEFAULT 1"),
            ("superseded_by", "TEXT"),
            ("observed_at", "TEXT"),
            ("valid_from", "TEXT"),
            ("valid_until", "TEXT"),
        ]
        for col_name, col_def in ev_additions:
            if col_name not in existing_ev_cols:
                try:
                    self.conn.execute(f"ALTER TABLE evidence ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

        ic_info = self.conn.execute("PRAGMA table_info(intelligence_changes)").fetchall()
        existing_ic_cols = {r["name"] for r in ic_info}
        if "origin" not in existing_ic_cols:
            try:
                self.conn.execute("ALTER TABLE intelligence_changes ADD COLUMN origin TEXT NOT NULL DEFAULT 'live_update'")
            except Exception:
                pass

        # Check claim_revisions.new_verification_score nullability
        cr_info = self.conn.execute("PRAGMA table_info(claim_revisions)").fetchall()
        for col in cr_info:
            if col["name"] == "new_verification_score" and col["notnull"] == 1:
                try:
                    self.conn.execute("PRAGMA foreign_keys=OFF")
                    self.conn.execute("""
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
                    self.conn.execute("""
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
                    self.conn.execute("DROP TABLE claim_revisions")
                    self.conn.execute("ALTER TABLE claim_revisions_mig_tmp RENAME TO claim_revisions")
                    self.conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_rev_claim_id ON claim_revisions(claim_id)")
                    self.conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_rev_created_at ON claim_revisions(created_at DESC)")
                    self.conn.execute("PRAGMA foreign_keys=ON")
                except Exception:
                    pass
                break

        # Check technology_assessment_revisions.new_score nullability
        tar_info = self.conn.execute("PRAGMA table_info(technology_assessment_revisions)").fetchall()
        for col in tar_info:
            if col["name"] == "new_score" and col["notnull"] == 1:
                try:
                    self.conn.execute("PRAGMA foreign_keys=OFF")
                    self.conn.execute("""
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
                    self.conn.execute("""
                        INSERT INTO technology_assessment_revisions_mig_tmp (
                            id, cluster_id, previous_stage, new_stage,
                            previous_score, new_score, reason, created_at
                        )
                        SELECT
                            id, cluster_id, previous_stage, new_stage,
                            previous_score, new_score, reason, created_at
                        FROM technology_assessment_revisions
                    """)
                    self.conn.execute("DROP TABLE technology_assessment_revisions")
                    self.conn.execute("ALTER TABLE technology_assessment_revisions_mig_tmp RENAME TO technology_assessment_revisions")
                    self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tech_rev_cluster_id ON technology_assessment_revisions(cluster_id)")
                    self.conn.execute("PRAGMA foreign_keys=ON")
                except Exception:
                    pass
                break

        saved_info = self.conn.execute("PRAGMA table_info(saved_items)").fetchall()
        existing_saved_cols = {r["name"] for r in saved_info}
        saved_additions = [
            ("claim_status_snapshot", "TEXT"),
            ("risk_status_snapshot", "TEXT"),
            ("risk_level_snapshot", "TEXT"),
        ]
        for col_name, col_def in saved_additions:
            if col_name not in existing_saved_cols:
                try:
                    self.conn.execute(f"ALTER TABLE saved_items ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

        dbi_info = self.conn.execute("PRAGMA table_info(daily_briefing_items)").fetchall()
        existing_dbi_cols = {r["name"] for r in dbi_info}
        dbi_additions = [
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
        ]
        for col_name, col_def in dbi_additions:
            if col_name not in existing_dbi_cols:
                try:
                    self.conn.execute(f"ALTER TABLE daily_briefing_items ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

        # Phase 13: Runtime error categories, threshold state, evaluation status, and blocked reasons
        scp_info = self.conn.execute("PRAGMA table_info(source_checkpoints)").fetchall()
        existing_scp_cols = {r["name"] for r in scp_info}
        for col_name, col_def in [
            ("last_error_category", "TEXT"),
            ("failure_threshold_reached", "INTEGER DEFAULT 0"),
            ("max_consecutive_failures", "INTEGER DEFAULT 5"),
        ]:
            if col_name not in existing_scp_cols:
                try:
                    self.conn.execute(f"ALTER TABLE source_checkpoints ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

        rj_info = self.conn.execute("PRAGMA table_info(runtime_jobs)").fetchall()
        existing_rj_cols = {r["name"] for r in rj_info}
        for col_name, col_def in [
            ("last_error_category", "TEXT"),
            ("evaluation_status", "TEXT DEFAULT 'pending'"),
            ("evaluated_at", "TEXT"),
            ("next_run_at", "TEXT"),
            ("blocked_by", "TEXT"),
            ("blocked_reason", "TEXT"),
        ]:
            if col_name not in existing_rj_cols:
                try:
                    self.conn.execute(f"ALTER TABLE runtime_jobs ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

        rjr_info = self.conn.execute("PRAGMA table_info(runtime_job_runs)").fetchall()
        existing_rjr_cols = {r["name"] for r in rjr_info}
        if "error_category" not in existing_rjr_cols:
            try:
                self.conn.execute("ALTER TABLE runtime_job_runs ADD COLUMN error_category TEXT")
            except Exception:
                pass

        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_jobs_eval_status ON runtime_jobs(evaluation_status)")
        except Exception:
            pass

        self.conn.commit()

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

        clusters = []
        for cid in matched_ids:
            cl = self.get_cluster(cid)
            if cl:
                clusters.append(cl)
        return clusters

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
        cursor = self.conn.cursor()
        ph = ",".join(["?"] * len(cluster_ids))
        cursor.execute(f"SELECT * FROM story_clusters WHERE id IN ({ph})", tuple(cluster_ids))
        rows = cursor.fetchall()
        return [
            StoryCluster(
                id=r["id"],
                canonical_title=r["canonical_title"],
                event_ids=[],
                sources=[],
                cluster_score=r["cluster_score"] or 0.0,
                source_diversity_score=r["source_diversity_score"] or 0.0,
                max_event_score=r["max_event_score"] or 0.0,
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in rows
        ]

    def get_all_clusters(self) -> List[StoryCluster]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM story_clusters ORDER BY cluster_score DESC")
        cluster_ids = [r["id"] for r in cursor.fetchall()]
        return [self.get_cluster(cid) for cid in cluster_ids if cid]

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
        clusters = []
        for row in cluster_rows:
            cid = row["id"]
            cursor.execute("SELECT event_id FROM cluster_events WHERE cluster_id = ?", (cid,))
            event_ids = [r["event_id"] for r in cursor.fetchall()]

            sources = []
            if event_ids:
                ph = ",".join(["?"] * len(event_ids))
                cursor.execute(f"SELECT DISTINCT source FROM events WHERE id IN ({ph})", tuple(event_ids))
                sources = [r["source"] for r in cursor.fetchall()]

            clusters.append(
                StoryCluster(
                    id=cid,
                    canonical_title=row["canonical_title"],
                    event_ids=event_ids,
                    sources=sources,
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
        clean_ids = list({cid for cid in cluster_ids if cid})
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
        clean_ids = list({cid for cid in cluster_ids if cid})
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

    # --- Technology Assessment Storage Methods ---

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
        if not row:
            return None
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

    def get_all_technology_assessments(self) -> List[TechnologyAssessment]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_assessments ORDER BY assessment_score DESC")
        return [
            TechnologyAssessment(
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
            for row in cursor.fetchall()
        ]

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

    def get_technology_state(self, cluster_id: str) -> Optional[TechnologyState]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_states WHERE cluster_id = ? LIMIT 1", (cluster_id,))
        row = cursor.fetchone()
        if not row:
            return None
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

    def get_all_technology_states(self) -> List[TechnologyState]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM technology_states ORDER BY risk_score DESC, updated_at DESC")
        return [
            TechnologyState(
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
            for row in cursor.fetchall()
        ]

    def get_technology_states_by_cluster_ids(self, cluster_ids: List[str]) -> List[TechnologyState]:
        if not cluster_ids:
            return []
        cursor = self.conn.cursor()
        ph = ",".join(["?"] * len(cluster_ids))
        cursor.execute(f"SELECT * FROM technology_states WHERE cluster_id IN ({ph})", tuple(cluster_ids))
        return [
            TechnologyState(
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
            for row in cursor.fetchall()
        ]

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
            created_at, updated_at, last_indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self.conn.commit()
        return True

    def _row_to_project(self, r: sqlite3.Row) -> Project:
        return Project(
            id=r["id"],
            name=r["name"],
            path=r["path"],
            description=r["description"],
            languages=json.loads(r["languages_json"]) if r["languages_json"] else [],
            frameworks=json.loads(r["frameworks_json"]) if r["frameworks_json"] else [],
            libraries=json.loads(r["libraries_json"]) if r["libraries_json"] else [],
            databases=json.loads(r["databases_json"]) if r["databases_json"] else [],
            infrastructure=json.loads(r["infrastructure_json"]) if r["infrastructure_json"] else [],
            models=json.loads(r["models_json"]) if r["models_json"] else [],
            tools=json.loads(r["tools_json"]) if r["tools_json"] else [],
            topics=json.loads(r["topics_json"]) if r["topics_json"] else [],
            keywords=json.loads(r["keywords_json"]) if r["keywords_json"] else [],
            is_active=bool(r["is_active"]),
            context_hash=r["context_hash"] or "",
            created_at=datetime.fromisoformat(r["created_at"]),
            updated_at=datetime.fromisoformat(r["updated_at"]),
            last_indexed_at=datetime.fromisoformat(r["last_indexed_at"]) if r["last_indexed_at"] else None,
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
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                match.created_at.isoformat(),
                match.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_project_matches(self, project_id: str) -> List[ProjectMatch]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM project_matches WHERE project_id = ? ORDER BY impact_score DESC, relevance_score DESC",
            (project_id,),
        )
        return [
            ProjectMatch(
                id=r["id"],
                project_id=r["project_id"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                match_type=r["match_type"],
                relevance_score=r["relevance_score"] if r["relevance_score"] is not None else None,
                impact_score=r["impact_score"] if r["impact_score"] is not None else None,
                recommendation=r["recommendation"],
                reason_codes=json.loads(r["reason_codes_json"]) if r["reason_codes_json"] else [],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_all_project_matches(self) -> List[ProjectMatch]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM project_matches ORDER BY impact_score DESC, relevance_score DESC")
        return [
            ProjectMatch(
                id=r["id"],
                project_id=r["project_id"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                match_type=r["match_type"],
                relevance_score=r["relevance_score"] if r["relevance_score"] is not None else None,
                impact_score=r["impact_score"] if r["impact_score"] is not None else None,
                recommendation=r["recommendation"],
                reason_codes=json.loads(r["reason_codes_json"]) if r["reason_codes_json"] else [],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_project_match_counts(self) -> Dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT project_id, count(*) as cnt FROM project_matches GROUP BY project_id")
        return {r["project_id"]: r["cnt"] for r in cursor.fetchall()}

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
        return InboxItem(
            id=r["id"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            story_cluster_id=r["story_cluster_id"],
            title=r["title"],
            section=r["section"],
            inbox_score=r["inbox_score"] if r["inbox_score"] is not None else None,
            rank_score=r["rank_score"] if r["rank_score"] is not None else None,
            project_impact_score=r["project_impact_score"] if r["project_impact_score"] is not None else None,
            state=r["state"],
            item_type=r["item_type"],
            created_at=datetime.fromisoformat(r["created_at"]),
            first_seen_at=datetime.fromisoformat(r["first_seen_at"]) if r["first_seen_at"] else None,
            last_seen_at=datetime.fromisoformat(r["last_seen_at"]) if r["last_seen_at"] else None,
            expires_at=datetime.fromisoformat(r["expires_at"]),
            seen_at=datetime.fromisoformat(r["seen_at"]) if r["seen_at"] else None,
            opened_at=datetime.fromisoformat(r["opened_at"]) if r["opened_at"] else None,
            is_starred=bool(r["is_starred"]),
            saved_item_id=r["saved_item_id"],
            matched_project_ids=json.loads(r["matched_project_ids_json"]) if r["matched_project_ids_json"] else [],
            reason_codes=json.loads(r["reason_codes_json"]) if r["reason_codes_json"] else [],
        )

    def save_inbox_item(self, item: InboxItem) -> bool:
        sql = """
        INSERT OR REPLACE INTO inbox_items (
            id, entity_type, entity_id, story_cluster_id, title, section,
            inbox_score, rank_score, project_impact_score, state, item_type,
            created_at, first_seen_at, last_seen_at, expires_at, seen_at,
            opened_at, is_starred, saved_item_id, matched_project_ids_json,
            reason_codes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        # Expire non-starred items whose expires_at is in the past and state != 'expired'
        cursor.execute(
            """
            UPDATE inbox_items
            SET state = 'expired'
            WHERE expires_at <= ? AND is_starred = 0 AND state != 'expired'
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
        keys = r.keys() if hasattr(r, "keys") else []
        claim_status_snap = r["claim_status_snapshot"] if "claim_status_snapshot" in keys and r["claim_status_snapshot"] is not None else None
        risk_status_snap = r["risk_status_snapshot"] if "risk_status_snapshot" in keys and r["risk_status_snapshot"] is not None else None
        risk_level_snap = r["risk_level_snapshot"] if "risk_level_snapshot" in keys and r["risk_level_snapshot"] is not None else None

        return SavedItem(
            id=r["id"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            story_cluster_id=r["story_cluster_id"],
            inbox_item_id=r["inbox_item_id"],
            title_snapshot=r["title_snapshot"],
            saved_at=datetime.fromisoformat(r["saved_at"]),
            verification_snapshot=r["verification_snapshot"] if r["verification_snapshot"] is not None else None,
            maturity_snapshot=r["maturity_snapshot"] if r["maturity_snapshot"] is not None else None,
            risk_snapshot=r["risk_snapshot"] if r["risk_snapshot"] is not None else None,
            claim_status_snapshot=claim_status_snap,
            risk_status_snapshot=risk_status_snap,
            risk_level_snapshot=risk_level_snap,
            user_note=r["user_note"],
            tags=json.loads(r["tags_json"]) if r["tags_json"] else [],
            project_ids=json.loads(r["project_ids_json"]) if r["project_ids_json"] else [],
            is_active=bool(r["is_active"]),
            link_status=r["link_status"] or "resolved",
            event_ids_snapshot=json.loads(r["event_ids_snapshot_json"]) if r["event_ids_snapshot_json"] else [],
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
            project_relevant_count, content_hash, summary_text, sections_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self.conn.commit()
        return True

    def get_daily_briefing(self, briefing_date: str) -> Optional[DailyBriefing]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_briefings WHERE briefing_date = ?", (briefing_date,))
        row = cursor.fetchone()
        if not row:
            return None
        return DailyBriefing(
            id=row["id"],
            briefing_date=row["briefing_date"],
            generated_at=datetime.fromisoformat(row["generated_at"]),
            total_items=row["total_items"],
            high_priority_count=row["high_priority_count"],
            project_relevant_count=row["project_relevant_count"],
            content_hash=row["content_hash"],
            summary_text=row["summary_text"],
            sections=json.loads(row["sections_json"]) if row["sections_json"] else {},
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_latest_daily_briefing(self) -> Optional[DailyBriefing]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_briefings ORDER BY briefing_date DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        return DailyBriefing(
            id=row["id"],
            briefing_date=row["briefing_date"],
            generated_at=datetime.fromisoformat(row["generated_at"]),
            total_items=row["total_items"],
            high_priority_count=row["high_priority_count"],
            project_relevant_count=row["project_relevant_count"],
            content_hash=row["content_hash"],
            summary_text=row["summary_text"],
            sections=json.loads(row["sections_json"]) if row["sections_json"] else {},
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_daily_briefing_with_items(self, briefing: DailyBriefing, items: List[DailyBriefingItem]) -> bool:
        """Atomically saves daily briefing header and its item snapshots in a single transaction."""
        cursor = self.conn.cursor()
        cursor.execute("BEGIN TRANSACTION")
        try:
            sql_briefing = """
            INSERT OR REPLACE INTO daily_briefings (
                id, briefing_date, generated_at, total_items, high_priority_count,
                project_relevant_count, content_hash, summary_text, sections_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(
                sql_briefing,
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
                ),
            )
            cursor.execute("DELETE FROM daily_briefing_items WHERE briefing_id = ?", (briefing.id,))
            sql_item = """
            INSERT OR REPLACE INTO daily_briefing_items (
                briefing_id, inbox_item_id, position, section,
                title, summary, story_cluster_id, item_type,
                reason_codes_json, inbox_score, rank_score,
                project_impact_score, matched_project_ids_json, snapshot_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def save_daily_briefing_items(self, items: List[DailyBriefingItem]) -> bool:
        if not items:
            return True
        briefing_id = items[0].briefing_id
        cursor = self.conn.cursor()
        cursor.execute("BEGIN TRANSACTION")
        try:
            cursor.execute("DELETE FROM daily_briefing_items WHERE briefing_id = ?", (briefing_id,))
            sql_item = """
            INSERT OR REPLACE INTO daily_briefing_items (
                briefing_id, inbox_item_id, position, section,
                title, summary, story_cluster_id, item_type,
                reason_codes_json, inbox_score, rank_score,
                project_impact_score, matched_project_ids_json, snapshot_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def get_daily_briefing_items(self, briefing_id: str) -> List[DailyBriefingItem]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM daily_briefing_items WHERE briefing_id = ? ORDER BY position ASC", (briefing_id,))
        items = []
        for r in cursor.fetchall():
            keys = r.keys()
            rc = json.loads(r["reason_codes_json"]) if "reason_codes_json" in keys and r["reason_codes_json"] else []
            mp = json.loads(r["matched_project_ids_json"]) if "matched_project_ids_json" in keys and r["matched_project_ids_json"] else []
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

    def close(self) -> None:
        self.conn.close()

