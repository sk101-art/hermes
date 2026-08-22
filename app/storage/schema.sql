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
    new_verification_score REAL,
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
    new_score REAL,
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
    risk_score REAL,
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
    origin TEXT NOT NULL DEFAULT 'live_update',
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
    relevance_score REAL,
    impact_score REAL,
    recommendation TEXT,
    reason_codes_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proj_matches_proj ON project_matches(project_id);
CREATE INDEX IF NOT EXISTS idx_proj_matches_relevance ON project_matches(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_proj_matches_impact ON project_matches(impact_score DESC);
CREATE INDEX IF NOT EXISTS idx_proj_matches_rec ON project_matches(recommendation);

-- Session 8: Daily Inbox, Stars, Saved Library, Retention, and Morning Briefing
CREATE TABLE IF NOT EXISTS inbox_items (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'cluster',
    entity_id TEXT NOT NULL,
    story_cluster_id TEXT NOT NULL,
    title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT 'ai_ml',
    inbox_score REAL DEFAULT 0.50,
    rank_score REAL DEFAULT 0.50,
    project_impact_score REAL DEFAULT 0.0,
    state TEXT NOT NULL DEFAULT 'unseen',
    item_type TEXT NOT NULL DEFAULT 'new_story',
    created_at TEXT NOT NULL,
    first_seen_at TEXT,
    last_seen_at TEXT,
    expires_at TEXT NOT NULL,
    seen_at TEXT,
    opened_at TEXT,
    is_starred INTEGER DEFAULT 0,
    saved_item_id TEXT,
    matched_project_ids_json TEXT,
    reason_codes_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_inbox_state ON inbox_items(state);
CREATE INDEX IF NOT EXISTS idx_inbox_expires ON inbox_items(expires_at);
CREATE INDEX IF NOT EXISTS idx_inbox_score ON inbox_items(inbox_score DESC);
CREATE INDEX IF NOT EXISTS idx_inbox_cluster ON inbox_items(story_cluster_id);
CREATE INDEX IF NOT EXISTS idx_inbox_created ON inbox_items(created_at DESC);

CREATE TABLE IF NOT EXISTS saved_items (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'cluster',
    entity_id TEXT NOT NULL,
    story_cluster_id TEXT NOT NULL,
    inbox_item_id TEXT,
    title_snapshot TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    verification_snapshot REAL,
    maturity_snapshot TEXT,
    risk_snapshot REAL,
    claim_status_snapshot TEXT,
    risk_status_snapshot TEXT,
    risk_level_snapshot TEXT,
    user_note TEXT,
    tags_json TEXT,
    project_ids_json TEXT,
    is_active INTEGER DEFAULT 1,
    link_status TEXT DEFAULT 'resolved',
    event_ids_snapshot_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_saved_cluster ON saved_items(story_cluster_id);
CREATE INDEX IF NOT EXISTS idx_saved_is_active ON saved_items(is_active);
CREATE INDEX IF NOT EXISTS idx_saved_saved_at ON saved_items(saved_at DESC);

CREATE TABLE IF NOT EXISTS user_feedback (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'inbox_item',
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    value TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_entity ON user_feedback(entity_id);
CREATE INDEX IF NOT EXISTS idx_feedback_action ON user_feedback(action);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON user_feedback(created_at DESC);

CREATE TABLE IF NOT EXISTS daily_briefings (
    id TEXT PRIMARY KEY,
    briefing_date TEXT UNIQUE NOT NULL,
    generated_at TEXT NOT NULL,
    total_items INTEGER DEFAULT 0,
    high_priority_count INTEGER DEFAULT 0,
    project_relevant_count INTEGER DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    summary_text TEXT,
    sections_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefings_date ON daily_briefings(briefing_date);

CREATE TABLE IF NOT EXISTS daily_briefing_items (
    briefing_id TEXT NOT NULL,
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
    PRIMARY KEY (briefing_id, inbox_item_id)
);

CREATE INDEX IF NOT EXISTS idx_briefing_items_brief ON daily_briefing_items(briefing_id);

-- Session 9: Autonomous Always-On Runtime, Scheduling, Checkpoints, and Recovery
CREATE TABLE IF NOT EXISTS source_checkpoints (
    source TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_attempt_at TEXT,
    last_cursor TEXT,
    last_event_time TEXT,
    last_error TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    next_retry_at TEXT,
    health_status TEXT NOT NULL DEFAULT 'unknown',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_checkpoints_health ON source_checkpoints(health_status);
CREATE INDEX IF NOT EXISTS idx_source_checkpoints_next_retry ON source_checkpoints(next_retry_at);

CREATE TABLE IF NOT EXISTS runtime_jobs (
    job_name TEXT PRIMARY KEY,
    last_started_at TEXT,
    last_completed_at TEXT,
    last_status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    duration_seconds REAL DEFAULT 0.0,
    run_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    next_run_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_jobs_status ON runtime_jobs(last_status);
CREATE INDEX IF NOT EXISTS idx_runtime_jobs_next_run ON runtime_jobs(next_run_at);

CREATE TABLE IF NOT EXISTS runtime_job_runs (
    id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    items_processed INTEGER DEFAULT 0,
    error_summary TEXT,
    duration_seconds REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_job_runs_name ON runtime_job_runs(job_name);
CREATE INDEX IF NOT EXISTS idx_job_runs_started ON runtime_job_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_runs_status ON runtime_job_runs(status);

CREATE TABLE IF NOT EXISTS runtime_metrics (
    metric_key TEXT PRIMARY KEY,
    metric_value INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);


