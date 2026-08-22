import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from app.models.schemas import Claim, Event, StoryCluster, TechnologyAssessment
from app.semantic.embeddings import EmbeddingService
from app.services.schemas import (
    SearchResult,
    StoryDetail,
    EventSummary,
    ClaimSummary,
    RiskDetail,
    VerificationDetail,
    ProjectMatchSummary,
    RelationshipSummary,
)
from app.services.synthesis import synthesize_story
from app.storage.db import Database


MATURITY_ORDER = {
    "concept": 1,
    "research": 2,
    "prototype": 3,
    "experimental": 4,
    "early_adoption": 5,
    "production_candidate": 6,
    "established": 7,
    # Legacy normalization aliases
    "maturing": 5,
    "production_ready": 7,
}

RISK_ORDER = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculates cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def sanitize_fts_query(query: str) -> List[str]:
    """Extracts clean tokens suitable for search querying, preserving language/symbol keywords."""
    if not query:
        return []
    tokens = re.findall(r"[a-zA-Z0-9_\-\.+]+", query)
    return [t.lower() for t in tokens if len(t) >= 1]


def aggregate_cluster_claim_status(claims: List[Any]) -> Optional[str]:
    """
    Computes a deterministic aggregate claim verification status for a story cluster.
    
    Policy:
    - no claims -> None
    - any retracted -> 'retracted'
    - any contradicted AND any positively supported (supported / strongly_supported) -> 'mixed'
    - any contradicted and no positively supported -> 'contradicted'
    - any mixed -> 'mixed'
    - all strongly_supported -> 'strongly_supported'
    - at least one supported or strongly_supported -> 'supported'
    - at least one weakly_supported (or partially_supported) -> 'weakly_supported'
    - all remaining claims superseded -> 'superseded'
    - otherwise -> 'unverified'
    """
    if not claims:
        return None

    statuses = [getattr(c, "status", None) or (c.get("status") if isinstance(c, dict) else None) for c in claims]
    statuses = [s for s in statuses if s]
    if not statuses:
        return "unverified"

    if any(s == "retracted" for s in statuses):
        return "retracted"

    has_contradicted = any(s == "contradicted" for s in statuses)
    has_positive = any(s in ("supported", "strongly_supported") for s in statuses)

    if has_contradicted and has_positive:
        return "mixed"

    if has_contradicted:
        return "contradicted"

    if any(s == "mixed" for s in statuses):
        return "mixed"

    if all(s == "strongly_supported" for s in statuses):
        return "strongly_supported"

    if any(s in ("supported", "strongly_supported") for s in statuses):
        return "supported"

    if any(s in ("weakly_supported", "partially_supported") for s in statuses):
        return "weakly_supported"

    if all(s == "superseded" for s in statuses):
        return "superseded"

    return "unverified"


def search_intelligence(
    query: str,
    project: Optional[str] = None,
    source: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = 10,
    verified_only: bool = False,
    min_maturity: Optional[str] = None,
    max_risk: Optional[str] = None,
    mode: str = "hybrid",
    explain: bool = False,
    db: Optional[Database] = None,
) -> List[SearchResult]:
    """
    Performs safe hybrid retrieval over verified HERMES intelligence data.
    Combines SQLite FTS5 lexical matching, semantic vector reranking, verification scores,
    freshness decay, and project relevance.
    """
    if db is None:
        db = Database()

    # Enforce safe result limit: default 10, max 50
    limit = max(1, min(limit, 50))
    mode = mode.lower() if mode in ("hybrid", "lexical", "semantic") else "hybrid"

    now = datetime.now(timezone.utc)
    cutoff_time = now - timedelta(days=days) if days is not None else None

    # Resolve project filter if provided
    target_project = None
    if project:
        p_clean = project.strip()
        target_project = db.get_project(p_clean) or db.get_project(f"project:{p_clean.lower()}") or db.get_project_by_name(p_clean)

    # 1. Lexical Candidate Retrieval
    tokens = sanitize_fts_query(query)
    candidate_cluster_ids: Set[str] = set()
    event_lexical_scores: Dict[str, float] = {}

    if tokens:
        fts_matches = db.search_events_fts(query, limit=100)
        for ev_id, lex_score in fts_matches:
            c_id = db.get_event_cluster(ev_id)
            if c_id:
                candidate_cluster_ids.add(c_id)
                event_lexical_scores[c_id] = max(event_lexical_scores.get(c_id, 0.0), lex_score)

        lex_clusters = db.search_clusters_lexical(query, limit=50)
        for cl in lex_clusters:
            candidate_cluster_ids.add(cl.id)
            event_lexical_scores[cl.id] = max(event_lexical_scores.get(cl.id, 0.0), 0.8)

    # Fallback to top clusters if lexical found few candidates
    if len(candidate_cluster_ids) < 15:
        top_cl = db.get_top_clusters(limit=50)
        for cl in top_cl:
            candidate_cluster_ids.add(cl.id)

    # 2. Semantic Embedding for Query (if hybrid or semantic)
    q_emb = None
    embedder = None
    if mode in ("hybrid", "semantic") and query and query.strip():
        try:
            embedder = EmbeddingService(model_name="sentence-transformers/all-MiniLM-L6-v2", device="cpu", batch_size=16)
            q_emb = embedder.embed(query.strip())
        except Exception:
            q_emb = None

    results: List[SearchResult] = []

    for c_id in candidate_cluster_ids:
        cl = db.get_cluster(c_id)
        if not cl:
            continue

        events = db.get_cluster_events(c_id)
        if not events:
            continue

        # Filter: Source
        if source:
            src_lower = source.lower().strip()
            if not any(src_lower in s.lower() for s in cl.sources):
                continue

        # Filter: Days / Recency
        newest_event_time = max(
            [e.published_at or e.discovered_at for e in events if e.published_at or e.discovered_at],
            default=datetime.fromisoformat(cl.created_at) if isinstance(cl.created_at, str) else cl.created_at,
        )
        if cutoff_time and newest_event_time < cutoff_time:
            continue

        assessment = db.get_technology_assessment(c_id)
        tech_state = db.get_technology_state(c_id)
        claims = db.get_claims_by_cluster(c_id, current_only=True)

        claim_scores = [c.verification_score for c in claims]
        verif_score = float(np.mean(claim_scores)) if claim_scores else None
        maturity = assessment.maturity_stage if assessment else None

        if tech_state:
            if not claims and not events:
                risk_status = "insufficient_data"
                risk_score = tech_state.risk_score
                risk = None
            else:
                risk_status = "assessed"
                risk_score = tech_state.risk_score
                risk = "critical" if risk_score >= 0.7 else ("high" if risk_score >= 0.4 else ("medium" if risk_score >= 0.2 else "low"))
        else:
            risk_status = "not_assessed"
            risk_score = None
            risk = None

        claim_status = aggregate_cluster_claim_status(claims)

        # Filter: Verified Only
        if verified_only:
            if verif_score is None or verif_score < 0.60 or claim_status not in ("supported", "strongly_supported"):
                continue

        # Filter: Min Maturity
        if min_maturity and min_maturity.lower() in MATURITY_ORDER:
            req_rank = MATURITY_ORDER[min_maturity.lower()]
            if maturity is None:
                continue
            act_rank = MATURITY_ORDER.get(maturity.lower(), 1)
            if act_rank < req_rank:
                continue

        # Filter: Max Risk
        if max_risk and max_risk.lower() in RISK_ORDER:
            max_r_rank = RISK_ORDER[max_risk.lower()]
            if risk is None:
                continue
            act_r_rank = RISK_ORDER.get(risk.lower(), 1)
            if act_r_rank > max_r_rank:
                continue

        # 3. Calculate Component Scores
        # Lexical score
        lex_score = event_lexical_scores.get(c_id, 0.0)
        # Direct query substring match or token overlap ratio bonus on title
        title_lower = cl.canonical_title.lower()
        q_lower = query.lower().strip()
        if q_lower and q_lower in title_lower:
            lex_score = max(lex_score, 1.0)
        matched_tokens = [t for t in tokens if t in title_lower]
        if tokens:
            token_ratio = len(matched_tokens) / len(tokens)
            lex_score = max(lex_score, token_ratio)

        # Semantic score
        sem_score = 0.0
        if q_emb is not None:
            # Check embeddings of cluster events
            best_sim = 0.0
            for ev in events[:5]:
                ev_emb = db.get_embedding(ev.id, embedder.model_name)
                if ev_emb is not None:
                    sim = cosine_similarity(q_emb, ev_emb)
                    if sim > best_sim:
                        best_sim = sim
            sem_score = max(0.0, best_sim)

        # Evidence-strength ranking contribution (influences ordering only, not truth status)
        verif_adj = (verif_score or 0.0) * 0.15

        # Freshness adjustment (strictly bounded [0.0, 0.10])
        age_days = max(0.0, (now - newest_event_time).total_seconds() / 86400.0)
        freshness_adj = max(0.0, min(1.0, 1.0 - (age_days / 60.0))) * 0.10

        # Project relevance
        project_boost = 0.0
        project_rel = 0.0
        if target_project:
            p_matches = db.get_project_matches(target_project.id)
            for m in p_matches:
                if m.entity_id == c_id:
                    project_rel = m.relevance_score
                    project_boost = m.relevance_score * 0.25
                    break

        # Check minimum query relevance before computing final score
        if mode == "lexical" and lex_score <= 0.0:
            continue
        if mode == "semantic" and sem_score <= 0.0:
            continue
        if mode == "hybrid" and lex_score <= 0.0 and sem_score <= 0.0:
            continue

        # Final Score according to mode
        if mode == "lexical":
            final_score = (lex_score * 0.75) + verif_adj + freshness_adj + project_boost
        elif mode == "semantic":
            final_score = (sem_score * 0.75) + verif_adj + freshness_adj + project_boost
        else:  # hybrid
            final_score = (lex_score * 0.40) + (sem_score * 0.40) + verif_adj + freshness_adj + project_boost

        reason_codes = []
        if matched_tokens:
            reason_codes.append(f"matched_tokens:{','.join(matched_tokens)}")
        if sem_score > 0.60:
            reason_codes.append("high_semantic_similarity")
        if verif_score is not None and verif_score >= 0.70:
            reason_codes.append("high_verification")
        if project_rel >= 0.50:
            reason_codes.append(f"project_relevant:{target_project.name if target_project else ''}")

        urls = [e.url for e in events if e.url][:5]
        synth = synthesize_story(
            cluster=cl,
            events=events,
            claims=claims,
            assessment=assessment,
            tech_state=tech_state,
            validate_references=False,
        )
        is_synthesized = synth.is_synthesized
        summary_text = synth.what_happened.statement if synth.what_happened else (synth.fallback_excerpt if synth.fallback_excerpt else None)

        explain_dict = None
        if explain:
            explain_dict = {
                "lexical_score": round(lex_score, 4),
                "semantic_score": round(sem_score, 4),
                "verification_adjustment": round(verif_adj, 4),
                "freshness_adjustment": round(freshness_adj, 4),
                "project_boost": round(project_boost, 4),
                "final_score": round(final_score, 4),
            }

        res_item = SearchResult(
            entity_type="story_cluster",
            entity_id=c_id,
            title=cl.canonical_title,
            summary=summary_text,
            is_synthesized=is_synthesized,
            claim_status=claim_status,
            score=round(final_score, 4),
            sources=list(cl.sources),
            published_at=newest_event_time.strftime("%Y-%m-%d %H:%M:%S UTC") if isinstance(newest_event_time, datetime) else str(newest_event_time),
            verification_score=round(verif_score, 4) if verif_score is not None else None,
            maturity=maturity,
            risk=risk,
            risk_status=risk_status,
            project_relevance=round(project_rel, 4),
            reason_codes=reason_codes,
            urls=urls,
            explain=explain_dict,
        )
        results.append(res_item)

    # Free embedding model memory
    if embedder is not None:
        embedder.unload()

    # Sort results by final score descending and clamp to limit
    results.sort(key=lambda x: (x.score if x.score is not None else -1.0), reverse=True)
    return results[:limit]


def get_top_developments(
    limit: int = 10,
    project: Optional[str] = None,
    section: Optional[str] = None,
    db: Optional[Database] = None,
) -> List[SearchResult]:
    """Retrieves top developments from the current inbox or highest scoring clusters."""
    if db is None:
        db = Database()

    limit = max(1, min(limit, 50))
    now = datetime.now(timezone.utc)

    # Read active inbox items
    inbox_items = db.get_active_inbox_items()

    if section:
        s_lower = section.lower().strip()
        inbox_items = [it for it in inbox_items if it.section and it.section.lower() == s_lower]

    if project:
        p_clean = project.strip()
        target_project = db.get_project(p_clean) or db.get_project(f"project:{p_clean.lower()}") or db.get_project_by_name(p_clean)
        if target_project:
            inbox_items = [it for it in inbox_items if target_project.id in it.matched_project_ids]

    results = []
    for it in inbox_items[:limit]:
        cl = db.get_cluster(it.story_cluster_id)
        if not cl:
            continue
        events = db.get_cluster_events(cl.id)
        urls = [e.url for e in events if e.url][:3]
        assessment = db.get_technology_assessment(cl.id)
        tech_state = db.get_technology_state(cl.id)
        claims = db.get_claims_by_cluster(cl.id, current_only=True)
        claim_scores = [c.verification_score for c in claims]
        verif_score = float(np.mean(claim_scores)) if claim_scores else None
        maturity = assessment.maturity_stage if assessment else None

        if tech_state:
            if not claims and not events:
                risk_status = "insufficient_data"
                risk = None
            else:
                risk_status = "assessed"
                r_score = tech_state.risk_score
                risk = "critical" if r_score >= 0.7 else ("high" if r_score >= 0.4 else ("medium" if r_score >= 0.2 else "low"))
        else:
            risk_status = "not_assessed"
            risk = None

        synth = synthesize_story(
            cluster=cl,
            events=events,
            claims=claims,
            assessment=assessment,
            tech_state=tech_state,
            validate_references=False,
        )
        summary_text = synth.what_happened.statement if synth.what_happened else (f"Source excerpt: {synth.fallback_excerpt}" if synth.fallback_excerpt else None)

        res = SearchResult(
            entity_type="inbox_item",
            entity_id=it.id,
            title=it.title,
            summary=summary_text,
            score=round(it.rank_score, 4) if it.rank_score is not None else None,
            sources=list(cl.sources),
            published_at=it.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            verification_score=round(verif_score, 4) if verif_score is not None else None,
            maturity=maturity,
            risk=risk,
            risk_status=risk_status,
            project_relevance=round(it.project_impact_score, 4) if it.project_impact_score is not None else None,
            reason_codes=list(it.reason_codes),
            urls=urls,
        )
        results.append(res)

    if not results:
        # Fallback to top clusters
        top_cl = db.get_top_clusters(limit=limit)
        for cl in top_cl:
            events = db.get_cluster_events(cl.id)
            urls = [e.url for e in events if e.url][:3]
            assessment = db.get_technology_assessment(cl.id)
            tech_state = db.get_technology_state(cl.id)
            claims = db.get_claims_by_cluster(cl.id, current_only=True)
            claim_scores = [c.verification_score for c in claims]
            verif_score = float(np.mean(claim_scores)) if claim_scores else None
            maturity = assessment.maturity_stage if assessment else None

            if tech_state:
                if not claims and not events:
                    risk_status = "insufficient_data"
                    risk = None
                else:
                    risk_status = "assessed"
                    r_score = tech_state.risk_score
                    risk = "critical" if r_score >= 0.7 else ("high" if r_score >= 0.4 else ("medium" if r_score >= 0.2 else "low"))
            else:
                risk_status = "not_assessed"
                risk = None

            synth = synthesize_story(
                cluster=cl,
                events=events,
                claims=claims,
                assessment=assessment,
                tech_state=tech_state,
                validate_references=False,
            )
            summary_text = synth.what_happened.statement if synth.what_happened else (f"Source excerpt: {synth.fallback_excerpt}" if synth.fallback_excerpt else None)

            res = SearchResult(
                entity_type="story_cluster",
                entity_id=cl.id,
                title=cl.canonical_title,
                summary=summary_text,
                score=round(cl.cluster_score, 4),
                sources=list(cl.sources),
                published_at=cl.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC") if isinstance(cl.updated_at, datetime) else str(cl.updated_at),
                verification_score=round(verif_score, 4) if verif_score is not None else None,
                maturity=maturity,
                risk=risk,
                risk_status=risk_status,
                project_relevance=0.0,
                reason_codes=["top_story_cluster"],
                urls=urls,
            )
            results.append(res)

    return results[:limit]


def get_story(cluster_id: str, db: Optional[Database] = None) -> Optional[StoryDetail]:
    """Fetches comprehensive structured story intelligence for a cluster."""
    if db is None:
        db = Database()

    if not cluster_id or not isinstance(cluster_id, str) or not cluster_id.strip():
        return None

    cl = db.get_cluster(cluster_id.strip())
    if not cl:
        return None

    events = db.get_cluster_events(cluster_id)
    claims = db.get_claims_by_cluster(cluster_id)
    assessment = db.get_technology_assessment(cluster_id)
    tech_state = db.get_technology_state(cluster_id)

    # Supporting events (safe summary, max 10)
    ev_summaries: List[EventSummary] = []
    for e in events[:10]:
        ev_summaries.append(
            EventSummary(
                id=e.id,
                title=e.title,
                source=e.source,
                url=e.url,
                published_at=e.published_at.isoformat() if e.published_at else None,
                discovered_at=e.discovered_at.isoformat() if getattr(e, "discovered_at", None) else None,
            )
        )

    # Evidence summary counts and claim summaries
    ev_counts = {"support": 0, "contradiction": 0, "uncertainty": 0, "context": 0}
    claim_summaries: List[ClaimSummary] = []
    for c in claims:
        ev_list = db.get_evidence_by_claim(c.id)
        for ev in ev_list:
            st = (ev.stance or "").lower().strip()
            if st in ("supports", "support"):
                ev_counts["support"] += 1
            elif st in ("contradicts", "contradiction"):
                ev_counts["contradiction"] += 1
            elif st in ("context", "contextual"):
                ev_counts["context"] += 1
            elif st in ev_counts:
                ev_counts[st] += 1
            else:
                ev_counts[st] = ev_counts.get(st, 0) + 1

        claim_summaries.append(
            ClaimSummary(
                claim_id=c.id,
                claim_text=c.claim_text,
                claim_type=c.claim_type,
                assertion_level=c.assertion_level,
                status=c.status,
                verification_score=round(c.verification_score, 4) if c.verification_score is not None else None,
                is_self_reported=bool(c.self_reported),
                evidence_count=len(ev_list),
                id=c.id,
                text=c.claim_text,
                type=c.claim_type,
            )
        )

    # Verification details
    claim_scores = [c.verification_score for c in claims if c.verification_score is not None]
    verif_score = float(np.mean(claim_scores)) if claim_scores else None

    if tech_state:
        if not claims and not events:
            risk_status = "insufficient_data"
            risk_score = tech_state.risk_score
            risk_level = None
        else:
            risk_status = "assessed"
            risk_score = tech_state.risk_score
            risk_level = "critical" if risk_score >= 0.7 else ("high" if risk_score >= 0.4 else ("medium" if risk_score >= 0.2 else "low"))
    else:
        risk_status = "not_assessed"
        risk_score = None
        risk_level = None

    contradictions_count = ev_counts.get("contradiction", 0)
    contradiction_detected = contradictions_count > 0

    verif_detail = VerificationDetail(
        verification_score=round(verif_score, 4) if verif_score is not None else None,
        claim_status=claims[0].status if claims else None,
        claims_count=len(claims),
        evidence_count=sum(ev_counts.values()),
        contradiction_detected=contradiction_detected,
        contradictions_count=contradictions_count,
        maturity_stage=assessment.maturity_stage if assessment else None,
        risk_level=risk_level,
        risk_score=round(risk_score, 4) if risk_score is not None else None,
        risk_status=risk_status,
    )

    risk_detail = RiskDetail(
        level=risk_level,
        score=round(risk_score, 4) if risk_score is not None else None,
        status=risk_status,
        reason_codes=[],
    )

    # Cross-source relationships
    rel_summaries: List[RelationshipSummary] = []
    for e in events:
        rels = db.get_relationships(e.id)
        for r in rels:
            rel_summaries.append(
                RelationshipSummary(
                    source_event_id=r.source_event_id,
                    target_event_id=r.target_event_id,
                    type=r.relationship_type,
                    confidence=round(r.confidence, 4),
                )
            )

    # Project matches
    proj_matches: List[ProjectMatchSummary] = []
    all_projects = db.get_all_projects(active_only=True)
    for p in all_projects:
        matches = db.get_project_matches(p.id)
        for m in matches:
            if m.entity_id == cluster_id:
                proj_matches.append(
                    ProjectMatchSummary(
                        project_id=p.id,
                        project_name=p.name,
                        relevance_score=round(m.relevance_score, 4),
                        match_type=m.match_type,
                        recommendation=m.recommendation,
                    )
                )

    # Check saved status
    is_saved = False
    saved_items = db.get_all_saved_items()
    for s in saved_items:
        if s.story_cluster_id == cluster_id:
            is_saved = True
            break

    # Grounded synthesis
    synth = synthesize_story(
        cluster=cl,
        cluster_id=cluster_id,
        events=events,
        claims=claims,
        assessment=assessment,
        tech_state=tech_state,
        db=db,
        validate_references=False,
    )

    return StoryDetail(
        cluster_id=cl.id,
        canonical_title=cl.canonical_title,
        cluster_score=round(cl.cluster_score, 4),
        sources=list(cl.sources),
        events_count=len(events),
        events=ev_summaries,
        claims=claim_summaries,
        technology_maturity=assessment.maturity_stage if assessment else None,
        risk=risk_detail,
        evidence_summary=ev_counts,
        verification=verif_detail,
        relationships=rel_summaries[:10],
        project_matches=proj_matches,
        is_saved=is_saved,
        synthesis=synth,
    )


def _normalize_importance_rank(imp: Any) -> int:
    if isinstance(imp, (int, float)):
        if imp >= 0.85:
            return 4  # critical
        if imp >= 0.65:
            return 3  # high
        if imp >= 0.35:
            return 2  # medium
        return 1  # low
    if isinstance(imp, str):
        imp_lower = imp.strip().lower()
        if imp_lower == "critical":
            return 4
        if imp_lower == "high":
            return 3
        if imp_lower == "medium":
            return 2
        return 1
    return 1


def _format_importance_level(imp: Any) -> str:
    rank = _normalize_importance_rank(imp)
    return {1: "low", 2: "medium", 3: "high", 4: "critical"}.get(rank, "low")


def get_recent_changes(
    hours: int = 24,
    importance_min: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 20,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recent intelligence changes and claim revisions with truthful provenance."""
    if db is None:
        db = Database()

    limit = max(1, min(limit, 100))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    target_project_id = None
    matched_entity_ids = set()
    if project:
        p_clean = project.strip()
        proj = db.get_project(p_clean) or db.get_project(f"project:{p_clean.lower()}") or db.get_project_by_name(p_clean)
        if proj:
            target_project_id = proj.id
            matches = db.get_project_matches(target_project_id)
            matched_entity_ids = {m.entity_id for m in matches}

    changes = db.get_recent_intelligence_changes(hours=hours, limit=200)
    filtered = []

    min_imp_rank = _normalize_importance_rank(importance_min or "low")

    # Cache claims lookup to avoid repetitive queries
    claims_cache = {}

    for ch in changes:
        if ch.created_at < cutoff:
            continue
        imp_rank = _normalize_importance_rank(ch.importance)
        if imp_rank < min_imp_rank:
            continue

        # Resolve cluster_id for linking to Story Dossier
        cluster_id = None
        if ch.entity_type in ("cluster", "technology_assessment", "technology_state"):
            cluster_id = ch.entity_id
        elif ch.entity_type == "claim":
            if ch.entity_id not in claims_cache:
                claims_cache[ch.entity_id] = db.get_claim(ch.entity_id)
            claim_obj = claims_cache[ch.entity_id]
            if claim_obj:
                cluster_id = claim_obj.cluster_id

        if target_project_id:
            is_matched = (
                (cluster_id and cluster_id in matched_entity_ids)
                or (ch.entity_id in matched_entity_ids)
            )
            if not is_matched:
                continue

        filtered.append({
            "id": ch.id,
            "entity_type": ch.entity_type,
            "entity_id": ch.entity_id,
            "cluster_id": cluster_id,
            "change_type": ch.change_type,
            "importance": ch.importance,
            "importance_level": _format_importance_level(ch.importance),
            "reason": ch.reason,
            "origin": getattr(ch, "origin", "live_update") or "live_update",
            "old_value": ch.old_value,
            "new_value": ch.new_value,
            "detected_at": ch.created_at.isoformat(),
            "created_at": ch.created_at.isoformat(),
        })

    return filtered[:limit]


def get_today_inbox(
    unseen_only: bool = False,
    project: Optional[str] = None,
    section: Optional[str] = None,
    limit: int = 20,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves calibrated daily inbox items."""
    if db is None:
        db = Database()

    limit = max(1, min(limit, 50))
    items = db.get_active_inbox_items(limit=None)

    if unseen_only:
        items = [it for it in items if it.state == "unseen"]

    if section:
        s_clean = section.lower().strip()
        items = [it for it in items if it.section and it.section.lower() == s_clean]

    if project:
        p_clean = project.strip()
        proj = db.get_project(p_clean) or db.get_project(f"project:{p_clean.lower()}") or db.get_project_by_name(p_clean)
        if proj:
            items = [it for it in items if proj.id in it.matched_project_ids]
        else:
            items = []

    target_items = items[:limit]
    cluster_ids = [it.story_cluster_id for it in target_items if it.story_cluster_id]

    available_clusters = set()
    active_saved_map = {}
    if cluster_ids:
        placeholders = ",".join(["?"] * len(cluster_ids))
        cursor = db.conn.cursor()
        cursor.execute(f"SELECT id FROM story_clusters WHERE id IN ({placeholders})", cluster_ids)
        available_clusters = {r[0] for r in cursor.fetchall()}

        cursor.execute(
            f"SELECT id, story_cluster_id FROM saved_items WHERE is_active = 1 AND story_cluster_id IN ({placeholders})",
            cluster_ids,
        )
        for r in cursor.fetchall():
            active_saved_map[r["story_cluster_id"]] = r["id"]

    out = []
    for it in target_items:
        cid = it.story_cluster_id
        is_avail = bool(cid and cid in available_clusters)
        active_saved_id = active_saved_map.get(cid) if cid else None

        out.append({
            "id": it.id,
            "entity_type": it.entity_type,
            "entity_id": it.entity_id,
            "story_cluster_id": it.story_cluster_id,
            "title": it.title,
            "section": it.section,
            "state": it.state,
            "is_starred": bool(active_saved_id is not None),
            "inbox_score": round(it.inbox_score, 4) if it.inbox_score is not None else None,
            "rank_score": round(it.rank_score, 4) if it.rank_score is not None else None,
            "project_impact_score": round(it.project_impact_score, 4) if it.project_impact_score is not None else None,
            "matched_project_ids": it.matched_project_ids or [],
            "item_type": it.item_type,
            "reason_codes": it.reason_codes or [],
            "saved_item_id": active_saved_id,
            "story_available": is_avail,
            "expires_at": it.expires_at.isoformat() if it.expires_at else None,
            "created_at": it.created_at.isoformat() if it.created_at else None,
        })
    return out


def get_morning_brief(
    date_str: Optional[str] = None,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves the daily morning briefing for a given date as an immutable stored snapshot."""
    if db is None:
        db = Database()

    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    briefing = db.get_daily_briefing(date_str)
    if not briefing:
        return None

    briefing_items = db.get_daily_briefing_items(briefing.id)

    # Batch check cluster existence for present-day Story Dossier navigation
    cluster_ids = [bi.story_cluster_id for bi in briefing_items if bi.story_cluster_id]
    existing_cluster_ids = db.get_existing_cluster_ids(cluster_ids)

    from app.inbox.briefing import SECTION_ORDER

    items_by_section: Dict[str, List[Dict[str, Any]]] = {sec: [] for sec in SECTION_ORDER}

    RECOGNIZED_SNAPSHOT_VERSIONS = {"v1"}

    for bi in briefing_items:
        if bi.snapshot_version is None or (bi.snapshot_version in RECOGNIZED_SNAPSHOT_VERSIONS and bi.title is None):
            snapshot_status = "legacy_incomplete"
        elif bi.snapshot_version not in RECOGNIZED_SNAPSHOT_VERSIONS:
            snapshot_status = "unrecognized_version"
        else:
            snapshot_status = "complete"

        story_avail = bool(bi.story_cluster_id and bi.story_cluster_id in existing_cluster_ids)

        item_data = {
            "briefing_id": bi.briefing_id,
            "inbox_item_id": bi.inbox_item_id,
            "story_cluster_id": bi.story_cluster_id,
            "title": bi.title,
            "summary": bi.summary,
            "section": bi.section,
            "position": bi.position,
            "item_type": bi.item_type,
            "reason_codes": bi.reason_codes or [],
            "inbox_score": bi.inbox_score,
            "rank_score": bi.rank_score,
            "project_impact_score": bi.project_impact_score,
            "matched_project_ids": bi.matched_project_ids or [],
            "snapshot_status": snapshot_status,
            "snapshot_version": bi.snapshot_version,
            "story_available": story_avail,
        }

        sec = bi.section if bi.section in items_by_section else "watchlist"
        items_by_section.setdefault(sec, []).append(item_data)

    final_sections: Dict[str, List[Dict[str, Any]]] = {}
    ordered_sections: List[str] = []
    for sec in SECTION_ORDER:
        if items_by_section.get(sec):
            final_sections[sec] = items_by_section[sec]
            ordered_sections.append(sec)

    return {
        "id": briefing.id,
        "briefing_date": briefing.briefing_date,
        "generated_at": briefing.generated_at.isoformat(),
        "total_items": briefing.total_items,
        "high_priority_count": briefing.high_priority_count,
        "project_relevant_count": briefing.project_relevant_count,
        "content_hash": briefing.content_hash,
        "summary_text": briefing.summary_text,
        "sections": final_sections,
        "ordered_sections": ordered_sections,
    }
