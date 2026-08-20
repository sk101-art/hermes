import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

from app.models.schemas import (
    Event,
    StoryCluster,
    Relationship,
    Claim,
    Evidence,
    TechnologyAssessment,
)


class Database:
    """SQLite storage layer for events, embeddings, clusters, relationships, claims, and evidence."""

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
            id, cluster_id, claim_type, subject, predicate, object,
            claim_text, status, confidence, verification_score, self_reported,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(
            sql,
            (
                claim.id,
                claim.cluster_id,
                claim.claim_type,
                claim.subject,
                claim.predicate,
                claim.object,
                claim.claim_text,
                claim.status,
                claim.confidence,
                claim.verification_score,
                1 if claim.self_reported else 0,
                json.dumps(claim.metadata),
                claim.created_at.isoformat(),
                claim.updated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def _row_to_claim(self, r: sqlite3.Row) -> Claim:
        return Claim(
            id=r["id"],
            cluster_id=r["cluster_id"],
            claim_type=r["claim_type"],
            subject=r["subject"],
            predicate=r["predicate"],
            object=r["object"],
            claim_text=r["claim_text"],
            status=r["status"],
            confidence=r["confidence"] or 1.0,
            verification_score=r["verification_score"] or 0.0,
            self_reported=bool(r["self_reported"]),
            metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
            created_at=datetime.fromisoformat(r["created_at"]),
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM claims WHERE id = ? LIMIT 1", (claim_id,))
        row = cursor.fetchone()
        return self._row_to_claim(row) if row else None

    def get_claims_by_cluster(self, cluster_id: str) -> List[Claim]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM claims WHERE cluster_id = ? ORDER BY verification_score DESC, created_at DESC",
            (cluster_id,),
        )
        return [self._row_to_claim(r) for r in cursor.fetchall()]

    def get_all_claims(self) -> List[Claim]:
        cursor = self.conn.cursor()
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
            reproducibility_score, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                evidence.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def _row_to_evidence(self, r: sqlite3.Row) -> Evidence:
        return Evidence(
            id=r["id"],
            claim_id=r["claim_id"],
            event_id=r["event_id"],
            source=r["source"],
            evidence_type=r["evidence_type"],
            evidence_class=r["evidence_class"] if "evidence_class" in r.keys() else "primary",
            stance=r["stance"],
            excerpt=r["excerpt"] or "",
            url=r["url"],
            quality_score=r["quality_score"] or 0.50,
            independence_score=r["independence_score"] or 0.50,
            reproducibility_score=r["reproducibility_score"] or 0.50,
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

    def clear_claims_and_evidence(self) -> None:
        """Clear only claims, evidence, and technology_assessments tables."""
        self.conn.execute("DELETE FROM claims")
        self.conn.execute("DELETE FROM evidence")
        self.conn.execute("DELETE FROM technology_assessments")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
