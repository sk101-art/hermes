-- HERMES Legacy Phase Snapshot Fixture
-- Contains older pre-session schema variants to test backward compatibility, schema migrations, and non-destructive upgrading.

CREATE TABLE events (
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

CREATE TABLE story_clusters (
    id TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    cluster_score REAL DEFAULT 0.0,
    source_diversity_score REAL DEFAULT 0.0,
    max_event_score REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE cluster_events (
    cluster_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    similarity_score REAL DEFAULT 1.0,
    added_at TEXT NOT NULL,
    PRIMARY KEY (cluster_id, event_id)
);

-- Legacy claims table without Session 6 lifecycle columns
CREATE TABLE claims (
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

-- Legacy evidence table without Session 6 temporal columns
CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    stance TEXT NOT NULL DEFAULT 'neutral',
    relevance_score REAL DEFAULT 1.0,
    independence_score REAL DEFAULT 0.0,
    quote TEXT,
    citation_url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE technology_assessments (
    cluster_id TEXT PRIMARY KEY,
    maturity_stage TEXT NOT NULL DEFAULT 'concept',
    score REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Legacy claim revisions table with NOT NULL constraint on new_verification_score
CREATE TABLE claim_revisions (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    previous_verification_score REAL,
    new_verification_score REAL NOT NULL,
    reason TEXT NOT NULL,
    trigger_event_id TEXT,
    trigger_evidence_id TEXT,
    created_at TEXT NOT NULL
);

-- Legacy assessment revisions table with NOT NULL constraint on new_score
CREATE TABLE technology_assessment_revisions (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    previous_stage TEXT,
    new_stage TEXT NOT NULL,
    previous_score REAL,
    new_score REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    description TEXT,
    tags_json TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE project_matches (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    relevance_score REAL DEFAULT 0.0,
    impact_score REAL DEFAULT 0.0,
    match_type TEXT NOT NULL DEFAULT 'semantic',
    matched_technologies_json TEXT,
    rationale TEXT,
    created_at TEXT NOT NULL
);

-- Legacy saved items without snapshot columns
CREATE TABLE saved_items (
    id TEXT PRIMARY KEY,
    story_cluster_id TEXT NOT NULL,
    user_note TEXT,
    tags_json TEXT,
    saved_at TEXT NOT NULL,
    snapshot_title TEXT,
    snapshot_cluster_score REAL,
    snapshot_maturity_stage TEXT,
    snapshot_verification_score REAL
);

-- Legacy daily briefing items table
CREATE TABLE daily_briefings (
    id TEXT PRIMARY KEY,
    briefing_date TEXT NOT NULL UNIQUE,
    generated_at TEXT NOT NULL,
    summary_markdown TEXT NOT NULL,
    item_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE daily_briefing_items (
    id TEXT PRIMARY KEY,
    briefing_id TEXT NOT NULL,
    story_cluster_id TEXT NOT NULL,
    rank_order INTEGER NOT NULL,
    section TEXT NOT NULL,
    highlight_text TEXT,
    created_at TEXT NOT NULL
);

-- Insert representative historical records
INSERT INTO events (id, source, source_type, event_type, title, text, url, published_at, discovered_at, final_score)
VALUES ('ev_legacy_001', 'github', 'repository', 'release', 'Legacy Compiler 1.0', 'Initial release of legacy compiler', 'https://github.com/legacy/compiler', '2025-01-15T00:00:00Z', '2025-01-15T00:00:00Z', 0.85);

INSERT INTO story_clusters (id, canonical_title, cluster_score, source_diversity_score, max_event_score, created_at, updated_at)
VALUES ('cluster_legacy_001', 'Legacy Compiler Innovations', 0.85, 0.5, 0.85, '2025-01-15T00:00:00Z', '2025-01-15T00:00:00Z');

INSERT INTO cluster_events (cluster_id, event_id, similarity_score, added_at)
VALUES ('cluster_legacy_001', 'ev_legacy_001', 1.0, '2025-01-15T00:00:00Z');

INSERT INTO claims (id, cluster_id, claim_type, subject, predicate, object, claim_text, status, verification_score, self_reported, created_at, updated_at)
VALUES ('clm_legacy_001', 'cluster_legacy_001', 'performance', 'Legacy Compiler', 'achieves', '2x compilation speedup', 'Legacy Compiler achieves 2x compilation speedup', 'supported', 0.82, 1, '2025-01-15T00:00:00Z', '2025-01-15T00:00:00Z');

INSERT INTO evidence (id, claim_id, event_id, evidence_type, stance, relevance_score, independence_score, quote, citation_url, created_at)
VALUES ('evi_legacy_001', 'clm_legacy_001', 'ev_legacy_001', 'benchmark', 'supports', 0.9, 0.85, 'Benchmark reports 2x speedup', 'https://github.com/legacy/compiler/bench', '2025-01-15T00:00:00Z');

INSERT INTO technology_assessments (cluster_id, maturity_stage, score, created_at, updated_at)
VALUES ('cluster_legacy_001', 'prototype', 0.75, '2025-01-15T00:00:00Z', '2025-01-15T00:00:00Z');

INSERT INTO claim_revisions (id, claim_id, previous_status, new_status, previous_verification_score, new_verification_score, reason, created_at)
VALUES ('cr_legacy_001', 'clm_legacy_001', NULL, 'supported', NULL, 0.82, 'Initial verification from benchmark', '2025-01-15T00:00:00Z');

INSERT INTO technology_assessment_revisions (id, cluster_id, previous_stage, new_stage, previous_score, new_score, reason, created_at)
VALUES ('tar_legacy_001', 'cluster_legacy_001', NULL, 'prototype', NULL, 0.75, 'Initial assessment based on release', '2025-01-15T00:00:00Z');

INSERT INTO projects (id, name, path, description, is_active, created_at, updated_at)
VALUES ('proj_legacy_001', 'Core Infrastructure Lab', '/tmp/core-infra', 'Core compiler and runtime infrastructure', 1, '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z');

INSERT INTO project_matches (id, project_id, cluster_id, relevance_score, impact_score, match_type, matched_technologies_json, rationale, created_at)
VALUES ('pm_legacy_001', 'proj_legacy_001', 'cluster_legacy_001', 0.88, 0.45, 'dependency', '["compiler"]', 'Direct infrastructure overlap', '2025-01-15T00:00:00Z');

INSERT INTO saved_items (id, story_cluster_id, user_note, tags_json, saved_at, snapshot_title, snapshot_cluster_score, snapshot_maturity_stage, snapshot_verification_score)
VALUES ('saved_legacy_001', 'cluster_legacy_001', 'Evaluate compiler speedup in Q2', '["infrastructure","compiler"]', '2025-01-16T12:00:00Z', 'Legacy Compiler Innovations', 0.85, 'prototype', 0.82);

INSERT INTO daily_briefings (id, briefing_date, generated_at, summary_markdown, item_count, created_at)
VALUES ('briefing_legacy_001', '2025-01-16', '2025-01-16T07:30:00Z', '# Morning Briefing\n- Legacy compiler release', 1, '2025-01-16T07:30:00Z');

INSERT INTO daily_briefing_items (id, briefing_id, story_cluster_id, rank_order, section, highlight_text, created_at)
VALUES ('dbi_legacy_001', 'briefing_legacy_001', 'cluster_legacy_001', 1, 'Infrastructure', 'Major speedup in legacy compiler', '2025-01-16T07:30:00Z');
