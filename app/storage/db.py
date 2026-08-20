import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

from app.models.schemas import Event, StoryCluster, EventRelationship


class Database:
    """SQLite storage layer for events, embeddings, clusters, and relationships."""

    def __init__(self, db_path: str = "data/tech_intel.db"):
        self.db_path = db_path
        self.has_fts5 = False
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        if schema_path.exists():
            with open(schema_path, "r", encoding="utf-8") as f:
                self.conn.executescript(f.read())

        # Check and initialize FTS5 if supported
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(id UNINDEXED, title, text)"
            )
            self.has_fts5 = True
        except sqlite3.OperationalError:
            self.has_fts5 = False
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
            event.discovered_at.isoformat(),
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

    def _row_to_event(self, r: sqlite3.Row) -> Event:
        return Event(
            id=r["id"],
            source=r["source"],
            source_type=r["source_type"],
            event_type=r["event_type"],
            title=r["title"],
            text=r["text"] or "",
            url=r["url"],
            authors=json.loads(r["authors_json"]) if r["authors_json"] else [],
            topics=json.loads(r["topics_json"]) if r["topics_json"] else [],
            metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
            raw_payload=json.loads(r["raw_payload_json"]) if r["raw_payload_json"] else {},
            published_at=datetime.fromisoformat(r["published_at"]) if r["published_at"] else None,
            discovered_at=datetime.fromisoformat(r["discovered_at"]),
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
        cursor.execute("SELECT * FROM events ORDER BY final_score DESC, discovered_at DESC")
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
            WHERE discovered_at >= ? OR published_at >= ?
            ORDER BY discovered_at DESC
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
        # Construct safe match string
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
        return np.frombuffer(row["embedding"], dtype=np.float32)

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
            result[r["event_id"]] = np.frombuffer(r["embedding"], dtype=np.float32)
        return result

    def get_all_embeddings(self, model_name: str) -> Dict[str, np.ndarray]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT event_id, embedding FROM event_embeddings WHERE model_name = ?",
            (model_name,),
        )
        result = {}
        for r in cursor.fetchall():
            result[r["event_id"]] = np.frombuffer(r["embedding"], dtype=np.float32)
        return result

    # --- Story Cluster Methods ---

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
        self.conn.commit()
        return True

    def update_cluster(self, cluster: StoryCluster) -> bool:
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

        # Fetch member events
        cursor.execute("SELECT event_id FROM cluster_events WHERE cluster_id = ?", (cluster_id,))
        event_ids = [r["event_id"] for r in cursor.fetchall()]

        # Fetch sources for events
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

    def clear_clusters_and_relationships(self) -> None:
        """Clear only story_clusters, cluster_events, and event_relationships. NEVER touches events or event_embeddings."""
        self.conn.execute("DELETE FROM story_clusters")
        self.conn.execute("DELETE FROM cluster_events")
        self.conn.execute("DELETE FROM event_relationships")
        self.conn.commit()

    # --- Relationship Storage Methods ---

    def save_relationship(self, rel: EventRelationship) -> bool:
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

    def get_relationships(self, event_id: str) -> List[EventRelationship]:
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
            EventRelationship(
                id=r["id"],
                source_event_id=r["source_event_id"],
                target_event_id=r["target_event_id"],
                relationship_type=r["relationship_type"],
                confidence=r["confidence"] or 1.0,
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def get_all_relationships(self) -> List[EventRelationship]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM event_relationships ORDER BY confidence DESC")
        return [
            EventRelationship(
                id=r["id"],
                source_event_id=r["source_event_id"],
                target_event_id=r["target_event_id"],
                relationship_type=r["relationship_type"],
                confidence=r["confidence"] or 1.0,
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in cursor.fetchall()
        ]

    def close(self) -> None:
        self.conn.close()
