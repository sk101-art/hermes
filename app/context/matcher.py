import hashlib
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

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
from app.context.explanation import (
    EXPLANATION_VERSION,
    detect_concern_reason_codes,
    generate_match_explanation,
)
from app.storage.db import Database

# --- Relevance score caps (explanation-upgrade spec) ---
# These caps prevent weak evidence from being presented as strong relevance.
CAP_SEMANTIC_ONLY = 0.39      # semantic similarity only, no concrete overlap
CAP_BROAD_TOPIC = 0.44        # broad topic overlap only
CAP_SPECIFIC_TECH = 0.64      # specific technology/framework overlap
CAP_VERIFIED_ARCHITECTURAL = 0.79  # verified architectural relevance
# Direct dependency matches may reach up to 1.0.

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


import yaml
from pathlib import Path

# Broad technology terms that must NEVER be treated as direct dependencies
BROAD_TECHNOLOGY_TERMS: Set[str] = {
    "cuda", "gpu", "rag", "llm", "vector", "database", "c++", "cpp", "c",
    "python", "rust", "go", "java", "inference", "quantization", "compiler",
    "kernel", "ai", "ml", "embeddings", "agent", "agents", "docker", "storage",
    "kv-cache", "attention", "transformer", "models"
}

# Python stdlib modules are never real third-party dependencies. They can
# appear in profiles built from AST import scans and must not produce
# direct-dependency matches (e.g. "re" matching "/releases" URLs).
STDLIB_MODULE_NAMES: Set[str] = {
    name.lower().replace("_", "-") for name in getattr(sys, "stdlib_module_names", frozenset())
}

# Generic URL path segments that must never count as a repository/package
# identity signal when matching dependency names against event URLs.
GENERIC_URL_SEGMENTS: Set[str] = {
    "releases", "release", "tag", "tags", "blob", "tree", "commit", "commits",
    "issues", "pull", "pulls", "wiki", "compare", "archive", "releases.atom",
    "www.github.com", "github.com", "api.github.com",
}


def load_ecosystem_config() -> Dict[str, Any]:
    cfg_path = Path("config/ecosystems.yaml")
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "ecosystems" in data:
                    return data["ecosystems"]
        except Exception:
            pass
    return {}


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
    ecosystem_map = load_ecosystem_config()

    # 1. Dependency & Technology Overlap
    project_deps = {k.lower().replace("_", "-"): v for k, v in profile.dependencies.items()}
    project_frameworks = {f.lower() for f in profile.frameworks}
    project_langs = {l.lower() for l in profile.languages}
    project_topics = {t.lower() for t in profile.topics}

    cluster_text = f"{cluster.canonical_title} " + " ".join(e.title + " " + (e.text or "") for e in cluster_events)
    cluster_tokens = compute_token_set(cluster_text)

    # Check for direct dependency matches strictly requiring concrete identity
    matched_deps = []
    for dep in project_deps:
        # Ignore broad terms from direct dependency matching
        if dep in BROAD_TECHNOLOGY_TERMS:
            continue
        # Ignore Python stdlib modules and degenerate single-char names
        if dep in STDLIB_MODULE_NAMES or len(dep) < 2:
            continue

        eco_info = ecosystem_map.get(dep)
        if eco_info:
            canonical_repos = [r.lower() for r in eco_info.get("canonical_repos", [])]
            aliases = [a.lower() for a in eco_info.get("aliases", [dep])]
            package_names = [p.lower() for p in eco_info.get("package_names", [dep])]

            # Direct match if cluster has event matching canonical repo
            repo_match = False
            for e in cluster_events:
                e_url = (e.url or "").lower()
                e_id = e.id.lower()
                for repo in canonical_repos:
                    if repo in e_url or repo in e_id:
                        repo_match = True
                        break
                if repo_match:
                    break

            # Or official release matching alias/package name
            claim_match = False
            for c in cluster_claims:
                if c.claim_type == "release" and (c.subject.lower() in aliases or c.object.lower() in aliases):
                    claim_match = True
                    break

            if repo_match or claim_match:
                matched_deps.append(dep)
        else:
            # For dependencies not explicitly in ecosystem map, require an
            # exact repository/package identity match. The dependency name
            # must equal a full URL path segment (e.g. ".../vllm/releases"
            # matches "vllm") or a full event-id segment — substring matches
            # like "/re" inside "/releases" are false positives.
            for e in cluster_events:
                if e.source != "github":
                    continue
                url_segments = {
                    seg for seg in urlparse(e.url or "").path.lower().split("/") if seg
                }
                url_segments -= GENERIC_URL_SEGMENTS
                id_segments = {seg for seg in e.id.lower().split(":") if seg}
                if dep in url_segments or dep in id_segments:
                    matched_deps.append(dep)
                    break

    # Check for technology / framework overlap
    matched_techs = []
    for fw in project_frameworks:
        fw_lower = fw.lower()
        if fw_lower in cluster_tokens or any(fw_lower in (e.title + " " + (e.text or "")).lower() for e in cluster_events):
            matched_techs.append(fw)

    # Also capture broad dependencies (like cuda) into technology overlap
    for dep in project_deps:
        if dep in BROAD_TECHNOLOGY_TERMS:
            if dep in cluster_tokens or any(dep in (e.title + " " + (e.text or "")).lower() for e in cluster_events):
                if dep not in [t.lower() for t in matched_techs]:
                    matched_techs.append(dep)

    # Check for language overlap
    matched_langs = []
    for lang in project_langs:
        if lang in cluster_tokens or any(lang in (e.metadata.get("language") or "").lower() for e in cluster_events):
            matched_langs.append(lang)

    # Check for topic overlap
    matched_topics = []
    for top in project_topics:
        top_lower = top.lower()
        if top_lower in cluster_tokens or any(top_lower in (e.title + " " + (e.text or "")).lower() for e in cluster_events):
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
    dep_overlap_score = 1.0 if matched_deps else 0.0
    tech_overlap_score = min(1.0, len(matched_techs) / 2.0)
    lang_overlap_score = 1.0 if matched_langs else 0.0
    topic_overlap_score = min(1.0, len(matched_topics) / 2.0)

    # 4. Transparent Relevance Formula
    if semantic_sim > 0.0:
        relevance = (
            0.45 * semantic_sim
            + 0.20 * dep_overlap_score
            + 0.15 * tech_overlap_score
            + 0.10 * lang_overlap_score
            + 0.10 * topic_overlap_score
        )
    else:
        relevance = (
            0.35 * dep_overlap_score
            + 0.30 * tech_overlap_score
            + 0.20 * topic_overlap_score
            + 0.15 * lang_overlap_score
        )

    # Language-only overlap is never a match.
    if matched_langs and not (matched_deps or matched_techs or matched_topics):
        return None

    # Direct dependency or explicit technology/topic match override
    if matched_deps:
        relevance = max(relevance, 0.75 + (0.20 * semantic_sim))
    elif matched_techs or matched_topics:
        relevance = max(relevance, 0.40)

    relevance = round(min(1.0, max(0.0, relevance)), 4)

    # Filter out weak/irrelevant matches (< 0.25) unless matched dependencies/techs/topics exist
    if relevance < 0.25 and not (matched_deps or matched_techs or matched_topics):
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
    has_storage = any("database" in top.lower() or "storage" in top.lower() or "vector" in top.lower() for top in matched_topics)

    if matched_deps:
        match_type = "direct_dependency"
    elif project.name.lower() in cluster.canonical_title.lower():
        match_type = "same_project"
    elif has_perf_claim and relevance >= 0.50:
        match_type = "optimization_opportunity"
    elif has_storage:
        match_type = "storage_relevant"
    elif any(c.status in ("contradicted", "mixed") for c in cluster_claims) or risk_score >= 0.60:
        match_type = "risk_relevant"
    elif any("compiler" in top.lower() or "kernel" in top.lower() or "cuda" in top.lower() for top in matched_topics):
        match_type = "architecture_relevant"
    elif any(e.source in ("arxiv", "openalex", "crossref") for e in cluster_events) or any("research" in top.lower() for top in matched_topics):
        match_type = "research_relevant"
    elif matched_techs:
        match_type = "technology_overlap"
    elif matched_topics:
        match_type = "compatible_tool"
    else:
        match_type = "general_related"

    # 6b. Apply relevance caps based on the strongest available evidence.
    has_verified_claim = any(
        c.status in ("strongly_supported", "supported") and (c.verification_score or 0) >= 0.60
        for c in cluster_claims
    )
    if matched_deps:
        cap = 1.0  # direct dependency: up to 100%
    elif match_type == "architecture_relevant" and has_verified_claim:
        cap = CAP_VERIFIED_ARCHITECTURAL
    elif matched_techs:
        cap = CAP_SPECIFIC_TECH
    elif matched_topics:
        cap = CAP_BROAD_TOPIC
    else:
        cap = CAP_SEMANTIC_ONLY  # semantic-only or general_related
    if relevance > cap:
        relevance = round(cap, 4)

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

    # Audited concern signals (vulnerability, breaking change, deprecation, ...)
    # These are the ONLY basis for engineering concerns — never impact score.
    reason_codes.extend(detect_concern_reason_codes(cluster_events, cluster_claims))

    match_id = f"match:{project.id}:{cluster.id}"
    now = datetime.now(timezone.utc)

    # 10. Generate the versioned, evidence-grounded explanation.
    explanation = generate_match_explanation(
        project=project,
        profile=profile,
        cluster=cluster,
        cluster_events=cluster_events,
        cluster_claims=cluster_claims,
        assessment=assessment,
        tech_state=tech_state,
        matched_deps=matched_deps,
        matched_techs=matched_techs,
        matched_langs=matched_langs,
        matched_topics=matched_topics,
        semantic_sim=semantic_sim,
        match_type=match_type,
        relevance_score=relevance,
        recommendation=recommendation,
    )

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
        explanation=explanation,
        explanation_version=EXPLANATION_VERSION,
        evaluated_at=now,
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
