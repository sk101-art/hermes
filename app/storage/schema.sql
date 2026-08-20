CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT,
    url TEXT NOT NULL,
    authors_json TEXT,
    topics_json TEXT,
    metadata_json TEXT,
    raw_payload_json TEXT,
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    trust_score REAL DEFAULT 0.0,
    relevance_score REAL DEFAULT 0.0,
    novelty_score REAL DEFAULT 0.0,
    final_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_final_score ON events(final_score DESC);
CREATE INDEX IF NOT EXISTS idx_events_published_at ON events(published_at);
CREATE INDEX IF NOT EXISTS idx_events_url ON events(url);
