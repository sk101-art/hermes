import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from app.models.schemas import (
    Claim,
    Event,
    Project,
    ProjectMatch,
    ProjectTechnologyProfile,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.semantic.clustering import cosine_similarity
from app.context.embeddings import get_embedder
from app.storage.db import Database

# Maturity score lookup
MATURITY_FACTORS: Dict[str, float] = {
    "established": 1.0,
    "production_candidate": 0.85,
    "early_adoption": 0.70,
    "experimental": 0.50,
    "prototype": 0.30,
    "research": 0.25,
    "concept": 0.15,
}


def compute_token_set(text: str) -> Set[str]:
    """Extracts alphanumeric normalized tokens."""
    import re
    return set(re.findall(r"[a-zA-Z0-9_-]{2,}", text.lower()))


def match_project_with_cluster(
    project: Project,
    profile: ProjectTechnologyProfile,
    project_embedding: Optional[np.ndarray],
    cluster: StoryCluster,
    cluster_events: List[Event],
    cluster_claims: List[Claim],
    assessment: Optional[TechnologyAssessment],
    tech_state: Optional[TechnologyState],
    db: Database,
) -> Optional[ProjectMatch]:
    """
    Computes deterministic relevance, impact, match type, and recommendation
    between a project profile and a StoryCluster intelligence entity.
    """
    # 1. Dependency & Technology Overlap
    project_deps = {k.lower().replace("_", "-"): v for k, v in profile.dependencies.items()}
    project_frameworks = {f.lower() for f in profile.frameworks}
    project_langs = {l.lower() for l in profile.languages}
    project_topics = {t.lower() for t in profile.topics}

    cluster_text = f"{cluster.canonical_title} " + " ".join(e.title + " " + (e.text or "") for e in cluster_events)
    cluster_tokens = compute_token_set(cluster_text)

    # Check for direct dependency matches
    matched_deps = []
    for dep in project_deps:
        # Check exact token match or alias (e.g. torch <-> pytorch)
        aliases = [dep]
        if dep in ("torch", "pytorch"):
            aliases = ["torch", "pytorch"]
        elif dep in ("transformers", "huggingface"):
            aliases = ["transformers", "huggingface"]

        for alias in aliases:
            if alias in cluster_tokens or any(alias in (e.id + " " + e.title).lower() for e in cluster_events):
                matched_deps.append(dep)
                break

    # Check for technology / framework overlap
    matched_techs = []
    for fw in project_frameworks:
        if fw in cluster_tokens:
            matched_techs.append(fw)

    # Check for language overlap
    matched_langs = []
    for lang in project_langs:
        if lang in cluster_tokens or any(lang in (e.metadata.get("language") or "").lower() for e in cluster_events):
            matched_langs.append(lang)

    # Check for topic overlap
    matched_topics = []
    for top in project_topics:
        if top in cluster_tokens or any(top in (e.title + " " + (e.text or "")).lower() for e in cluster_events):
            matched_topics.append(top)

    # 2. Semantic Similarity
    semantic_sim = 0.0
    if project_embedding is not None and cluster.event_ids:
        # Compare project embedding against cluster event embeddings
        model_name = get_embedder().model_name
        event_sims = []
        for eid in cluster.event_ids[:5]:
            ev_emb = db.get_embedding(eid, model_name)
            if ev_emb is not None:
                sim = cosine_similarity(project_embedding, ev_emb)
                event_sims.append(sim)
        if event_sims:
            semantic_sim = max(event_sims)

    # 3. Component overlap scores [0.0 - 1.0]
    dep_overlap_score = 1.0 if matched_deps else (0.5 if any(d in cluster_text.lower() for d in project_deps) else 0.0)
    tech_overlap_score = min(1.0, len(matched_techs) / 2.0)
    lang_overlap_score = 1.0 if matched_langs else 0.0
    topic_overlap_score = min(1.0, len(matched_topics) / 2.0)

    # 4. Transparent Relevance Formula
    relevance = (
        0.45 * semantic_sim
        + 0.20 * dep_overlap_score
        + 0.15 * tech_overlap_score
        + 0.10 * lang_overlap_score
        + 0.10 * topic_overlap_score
    )

    # High direct dependency match override / boost
    if matched_deps:
        relevance = max(relevance, 0.75 + (0.20 * semantic_sim))

    relevance = round(min(1.0, max(0.0, relevance)), 4)

    # Filter out weak/irrelevant matches (< 0.35) unless direct dependency match exists
    if relevance < 0.35 and not matched_deps:
        return None

    # 5. Verification & Maturity Factors
    strongest_claim = cluster_claims[0] if cluster_claims else None
    v_score = strongest_claim.verification_score if strongest_claim else 0.50
    claim_status = strongest_claim.status if strongest_claim else "unverified"

    stage = assessment.maturity_stage if assessment else "concept"
    maturity_factor = MATURITY_FACTORS.get(stage, 0.30)
    risk_score = tech_state.risk_score if tech_state else 0.25

    # 6. Match Type Classification
    has_release = any(e.source == "github" and e.event_type == "release" for e in cluster_events)
    has_perf_claim = any(c.claim_type == "performance" for c in cluster_claims)
    has_storage = any("database" in top or "storage" in top or "vector" in top for top in matched_topics)

    if matched_deps:
        match_type = "direct_dependency"
    elif has_perf_claim and relevance >= 0.50:
        match_type = "optimization_opportunity"
    elif has_storage:
        match_type = "storage_relevant"
    elif any(c.status in ("contradicted", "mixed") for c in cluster_claims) or risk_score >= 0.60:
        match_type = "risk_relevant"
    elif any("compiler" in top or "kernel" in top or "cuda" in top for top in matched_topics):
        match_type = "architecture_relevant"
    elif matched_techs:
        match_type = "compatible_tool"
    else:
        match_type = "general_related"

    # 7. Impact Score Formula
    dep_directness = 1.0 if matched_deps else (0.50 if matched_techs else 0.20)
    raw_impact = (
        0.35 * relevance
        + 0.20 * v_score
        + 0.15 * maturity_factor
        + 0.15 * (1.0 - (risk_score * 0.5))  # Reliability/low-risk premium
        + 0.15 * dep_directness
    )

    # High risk penalty
    if risk_score >= 0.60:
        raw_impact -= 0.15

    impact = round(min(1.0, max(0.0, raw_impact)), 4)

    # 8. Recommendation Category Derivation
    if claim_status == "contradicted" or (claim_status == "mixed" and risk_score >= 0.50):
        recommendation = "potential_risk"
    elif matched_deps and has_release and v_score >= 0.50 and risk_score < 0.50:
        recommendation = "upgrade_candidate"
    elif match_type == "optimization_opportunity" and v_score >= 0.50 and risk_score < 0.50:
        recommendation = "optimization_candidate"
    elif relevance >= 0.65 and v_score >= 0.60 and stage in ("production_candidate", "established") and risk_score < 0.40:
        recommendation = "consider"
    elif relevance >= 0.55 and v_score >= 0.50 and stage in ("experimental", "early_adoption") and risk_score < 0.60:
        recommendation = "evaluate"
    elif relevance >= 0.40 or claim_status == "weakly_supported" or stage in ("prototype", "concept") or risk_score >= 0.50:
        recommendation = "watch"
    else:
        recommendation = "not_recommended_yet"

    # 9. Deterministic Reason Codes
    reason_codes = []
    if matched_deps:
        reason_codes.append(f"dependency_match:{','.join(matched_deps)}")
    if matched_techs:
        reason_codes.append(f"technology_match:{','.join(matched_techs)}")
    if matched_langs:
        reason_codes.append(f"language_match:{','.join(matched_langs)}")
    if matched_topics:
        reason_codes.append(f"topic_match:{','.join(matched_topics)}")
    reason_codes.append(f"semantic_similarity:{semantic_sim:.2f}")
    if strongest_claim:
        reason_codes.append(f"verified_claim:{v_score:.2f}")
        reason_codes.append(f"claim_status:{claim_status}")
    reason_codes.append(f"maturity:{stage}")
    reason_codes.append(f"risk:{risk_score:.2f}")

    match_id = f"match:{project.id}:{cluster.id}"
    now = datetime.now(timezone.utc)

    return ProjectMatch(
        id=match_id,
        project_id=project.id,
        entity_type="cluster",
        entity_id=cluster.id,
        match_type=match_type,
        relevance_score=relevance,
        impact_score=impact,
        recommendation=recommendation,
        reason_codes=reason_codes,
        created_at=now,
        updated_at=now,
    )


def match_all_projects_against_intelligence(
    db: Database,
    max_candidates: int = 100,
    recency_days: int = 90,
) -> Dict[str, List[ProjectMatch]]:
    """
    Runs matching across all active projects against stored HERMES clusters and claims.
    """
    projects = db.get_all_projects(active_only=True)
    if not projects:
        return {}

    clusters = db.get_all_clusters()
    # Limit to candidate clusters
    candidate_clusters = clusters[:max_candidates]

    results: Dict[str, List[ProjectMatch]] = {}
    model_name = get_embedder().model_name

    for proj in projects:
        profile = db.get_project_profile(proj.id)
        if not profile:
            continue

        proj_emb = db.get_project_embedding(proj.id, model_name)
        proj_matches: List[ProjectMatch] = []

        for cluster in candidate_clusters:
            events = db.get_cluster_events(cluster.id)
            claims = db.get_claims_by_cluster(cluster.id)
            assessment = db.get_technology_assessment(cluster.id)
            tech_state = db.get_technology_state(cluster.id)

            match = match_project_with_cluster(
                project=proj,
                profile=profile,
                project_embedding=proj_emb,
                cluster=cluster,
                cluster_events=events,
                cluster_claims=claims,
                assessment=assessment,
                tech_state=tech_state,
                db=db,
            )

            if match:
                proj_matches.append(match)
                db.save_project_match(match)

        # Sort matches by impact score DESC
        proj_matches.sort(key=lambda m: (m.impact_score, m.relevance_score), reverse=True)
        results[proj.id] = proj_matches

    return results
