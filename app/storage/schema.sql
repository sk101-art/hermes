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

-- Session 5 & 6: Claims, Evidence Graph, and Technology Assessments
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    assertion_level TEXT NOT NULL DEFAULT 'artifact_fact',
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unverified',
    confidence REAL DEFAULT 1.0,
    verification_score REAL DEFAULT 0.0,
    self_reported INTEGER DEFAULT 1,
    is_current INTEGER DEFAULT 1,
    superseded_by TEXT,
    last_verified_at TEXT,
    staleness_score REAL DEFAULT 0.0,
    valid_from TEXT,
    valid_until TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_cluster_id ON claims(cluster_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_assertion_level ON claims(assertion_level);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_is_current ON claims(is_current);
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
    is_current INTEGER DEFAULT 1,
    superseded_by TEXT,
    observed_at TEXT,
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_claim_id ON evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_evidence_event_id ON evidence(event_id);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type);
CREATE INDEX IF NOT EXISTS idx_evidence_stance ON evidence(stance);
CREATE INDEX IF NOT EXISTS idx_evidence_is_current ON evidence(is_current);

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

-- Session 6: Longitudinal Verification, Revisions, Recheck Queue & Changes
CREATE TABLE IF NOT EXISTS claim_revisions (
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

CREATE INDEX IF NOT EXISTS idx_claim_rev_claim_id ON claim_revisions(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_rev_created_at ON claim_revisions(created_at DESC);

CREATE TABLE IF NOT EXISTS technology_assessment_revisions (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    previous_stage TEXT,
    new_stage TEXT NOT NULL,
    previous_score REAL,
    new_score REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tech_rev_cluster_id ON technology_assessment_revisions(cluster_id);
CREATE INDEX IF NOT EXISTS idx_tech_rev_created_at ON technology_assessment_revisions(created_at DESC);

CREATE TABLE IF NOT EXISTS technology_states (
    cluster_id TEXT PRIMARY KEY,
    current_status TEXT NOT NULL DEFAULT 'active',
    latest_event_at TEXT,
    latest_release TEXT,
    latest_claim_revision_at TEXT,
    active_claim_count INTEGER DEFAULT 0,
    supported_claim_count INTEGER DEFAULT 0,
    contradicted_claim_count INTEGER DEFAULT 0,
    superseded_claim_count INTEGER DEFAULT 0,
    risk_score REAL DEFAULT 0.0,
    trend TEXT NOT NULL DEFAULT 'stable',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tech_states_risk ON technology_states(risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_tech_states_trend ON technology_states(trend);
CREATE INDEX IF NOT EXISTS idx_tech_states_status ON technology_states(current_status);

CREATE TABLE IF NOT EXISTS recheck_queue (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'claim',
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    priority REAL DEFAULT 0.50,
    not_before TEXT,
    last_checked_at TEXT,
    next_check_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recheck_priority ON recheck_queue(priority DESC);
CREATE INDEX IF NOT EXISTS idx_recheck_status ON recheck_queue(status);
CREATE INDEX IF NOT EXISTS idx_recheck_next_check ON recheck_queue(next_check_at);

CREATE TABLE IF NOT EXISTS intelligence_changes (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'claim',
    entity_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    importance REAL DEFAULT 0.50,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intel_change_type ON intelligence_changes(change_type);
CREATE INDEX IF NOT EXISTS idx_intel_importance ON intelligence_changes(importance DESC);
CREATE INDEX IF NOT EXISTS idx_intel_created_at ON intelligence_changes(created_at DESC);

-- Session 7: Reference / Context Folder Personalization
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    description TEXT,
    languages_json TEXT,
    frameworks_json TEXT,
    libraries_json TEXT,
    databases_json TEXT,
    infrastructure_json TEXT,
    models_json TEXT,
    tools_json TEXT,
    topics_json TEXT,
    keywords_json TEXT,
    is_active INTEGER DEFAULT 1,
    context_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_indexed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
CREATE INDEX IF NOT EXISTS idx_projects_is_active ON projects(is_active);

CREATE TABLE IF NOT EXISTS project_files (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    extracted_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proj_files_proj ON project_files(project_id);
CREATE INDEX IF NOT EXISTS idx_proj_files_hash ON project_files(content_hash);

CREATE TABLE IF NOT EXISTS project_technology_profiles (
    project_id TEXT PRIMARY KEY,
    languages_json TEXT,
    frameworks_json TEXT,
    libraries_json TEXT,
    dependencies_json TEXT,
    databases_json TEXT,
    storage_json TEXT,
    infrastructure_json TEXT,
    ml_stack_json TEXT,
    deployment_json TEXT,
    observability_json TEXT,
    testing_json TEXT,
    topics_json TEXT,
    profile_text TEXT NOT NULL DEFAULT '',
    profile_hash TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_embeddings (
    project_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    embedding BLOB NOT NULL,
    dimension INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proj_emb_hash ON project_embeddings(content_hash);

CREATE TABLE IF NOT EXISTS project_matches (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'cluster',
    entity_id TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'general_related',
    relevance_score REAL DEFAULT 0.0,
    impact_score REAL DEFAULT 0.0,
    recommendation TEXT NOT NULL DEFAULT 'watch',
    reason_codes_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proj_matches_proj ON project_matches(project_id);
CREATE INDEX IF NOT EXISTS idx_proj_matches_relevance ON project_matches(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_proj_matches_impact ON project_matches(impact_score DESC);
CREATE INDEX IF NOT EXISTS idx_proj_matches_rec ON project_matches(recommendation);

