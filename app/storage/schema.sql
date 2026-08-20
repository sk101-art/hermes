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

CREATE TABLE IF NOT EXISTS event_embeddings (
    event_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    embedding BLOB NOT NULL,
    dimension INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_event_id ON event_embeddings(event_id);

CREATE TABLE IF NOT EXISTS story_clusters (
    id TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    cluster_score REAL DEFAULT 0.0,
    source_diversity_score REAL DEFAULT 0.0,
    max_event_score REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_story_clusters_score ON story_clusters(cluster_score DESC);

CREATE TABLE IF NOT EXISTS cluster_events (
    cluster_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    similarity_score REAL DEFAULT 1.0,
    added_at TEXT NOT NULL,
    PRIMARY KEY (cluster_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_events_cid ON cluster_events(cluster_id);
CREATE INDEX IF NOT EXISTS idx_cluster_events_eid ON cluster_events(event_id);

CREATE TABLE IF NOT EXISTS event_relationships (
    id TEXT PRIMARY KEY,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rel_source ON event_relationships(source_event_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON event_relationships(target_event_id);

-- Session 5: Claims, Evidence Graph, and Technology Assessments
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unverified',
    confidence REAL DEFAULT 1.0,
    verification_score REAL DEFAULT 0.0,
    self_reported INTEGER DEFAULT 1,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_cluster_id ON claims(cluster_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_verification_score ON claims(verification_score DESC);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_class TEXT NOT NULL DEFAULT 'primary',
    stance TEXT NOT NULL DEFAULT 'supports',
    excerpt TEXT,
    url TEXT,
    quality_score REAL DEFAULT 0.50,
    independence_score REAL DEFAULT 0.50,
    reproducibility_score REAL DEFAULT 0.50,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_claim_id ON evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_evidence_event_id ON evidence(event_id);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type);
CREATE INDEX IF NOT EXISTS idx_evidence_stance ON evidence(stance);

CREATE TABLE IF NOT EXISTS technology_assessments (
    cluster_id TEXT PRIMARY KEY,
    maturity_stage TEXT NOT NULL DEFAULT 'concept',
    research_score REAL DEFAULT 0.0,
    implementation_score REAL DEFAULT 0.0,
    adoption_score REAL DEFAULT 0.0,
    reproducibility_score REAL DEFAULT 0.0,
    community_score REAL DEFAULT 0.0,
    assessment_score REAL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tech_maturity_stage ON technology_assessments(maturity_stage);
CREATE INDEX IF NOT EXISTS idx_tech_assessment_score ON technology_assessments(assessment_score DESC);
