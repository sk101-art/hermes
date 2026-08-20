import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.schemas import Event


class Database:
    """SQLite storage layer for events and full-text search."""

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
        rows = cursor.fetchall()
        events = []
        for r in rows:
            events.append(
                Event(
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
            )
        return events

    def get_event_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        row = cursor.fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self.conn.close()
