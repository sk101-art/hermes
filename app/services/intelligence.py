import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from app.models.schemas import Claim, Event, StoryCluster, TechnologyAssessment
from app.semantic.embeddings import EmbeddingService
from app.services.schemas import SearchResult, StoryDetail
from app.storage.db import Database


MATURITY_ORDER = {
    "prototype": 1,
    "experimental": 2,
    "maturing": 3,
    "established": 4,
    "production_ready": 5,
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
    """Extracts clean alphanumeric tokens suitable for safe FTS querying."""
    if not query:
        return []
    tokens = re.findall(r"[a-zA-Z0-9_\-\.]{2,}", query)
    return [t.lower() for t in tokens if len(t) >= 2]


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
    if mode in ("hybrid", "semantic") and tokens:
        try:
            embedder = EmbeddingService(model_name="sentence-transformers/all-MiniLM-L6-v2", device="cpu", batch_size=16)
            q_emb = embedder.embed(query)
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

        claim_status = claims[0].status if claims else None

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
        # Token overlap ratio bonus on title
        title_lower = cl.canonical_title.lower()
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
        summary_text = events[0].text[:300] if events and events[0].text else None

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
    results.sort(key=lambda x: x.score, reverse=True)
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

        res = SearchResult(
            entity_type="inbox_item",
            entity_id=it.id,
            title=it.title,
            summary=events[0].text[:300] if events and events[0].text else None,
            score=round(it.rank_score, 4),
            sources=list(cl.sources),
            published_at=it.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            verification_score=round(verif_score, 4) if verif_score is not None else None,
            maturity=maturity,
            risk=risk,
            risk_status=risk_status,
            project_relevance=round(it.project_impact_score, 4),
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

            res = SearchResult(
                entity_type="story_cluster",
                entity_id=cl.id,
                title=cl.canonical_title,
                summary=events[0].text[:300] if events and events[0].text else None,
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

    cl = db.get_cluster(cluster_id)
    if not cl:
        return None

    events = db.get_cluster_events(cluster_id)
    claims = db.get_claims_by_cluster(cluster_id)
    assessment = db.get_technology_assessment(cluster_id)
    tech_state = db.get_technology_state(cluster_id)

    # Supporting events (safe summary, max 10)
    ev_summaries = []
    for e in events[:10]:
        ev_summaries.append({
            "id": e.id,
            "title": e.title,
            "source": e.source,
            "url": e.url,
            "published_at": e.published_at.isoformat() if e.published_at else None,
        })

    # Claims
    claim_summaries = []
    for c in claims:
        claim_summaries.append({
            "id": c.id,
            "text": c.claim_text,
            "type": c.claim_type,
            "status": c.status,
            "verification_score": round(c.verification_score, 4),
        })

    # Evidence summary counts
    ev_counts = {"support": 0, "contradiction": 0, "uncertainty": 0}
    for c in claims:
        ev_list = db.get_evidence_by_claim(c.id)
        for ev in ev_list:
            st = ev.stance.lower()
            if st in ev_counts:
                ev_counts[st] += 1

    # Verification details
    claim_scores = [c.verification_score for c in claims]
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

    verif_dict = {
        "verification_score": round(verif_score, 4) if verif_score is not None else None,
        "maturity_stage": assessment.maturity_stage if assessment else None,
        "risk_level": risk_level,
        "risk_score": round(risk_score, 4) if risk_score is not None else None,
        "risk_status": risk_status,
        "claim_status": claims[0].status if claims else None,
    }

    # Cross-source relationships
    rel_summaries = []
    for e in events:
        rels = db.get_relationships(e.id)
        for r in rels:
            rel_summaries.append({
                "source_event_id": r.source_event_id,
                "target_event_id": r.target_event_id,
                "type": r.relationship_type,
                "confidence": round(r.confidence, 4),
            })

    # Project matches
    proj_matches = []
    all_projects = db.get_all_projects(active_only=True)
    for p in all_projects:
        matches = db.get_project_matches(p.id)
        for m in matches:
            if m.entity_id == cluster_id:
                proj_matches.append({
                    "project_id": p.id,
                    "project_name": p.name,
                    "relevance_score": round(m.relevance_score, 4),
                    "match_type": m.match_type,
                    "recommendation": m.recommendation,
                })

    # Check saved status
    is_saved = False
    saved_items = db.get_all_saved_items()
    for s in saved_items:
        if s.story_cluster_id == cluster_id:
            is_saved = True
            break

    return StoryDetail(
        cluster_id=cl.id,
        canonical_title=cl.canonical_title,
        cluster_score=round(cl.cluster_score, 4),
        sources=list(cl.sources),
        events_count=len(events),
        events=ev_summaries,
        claims=claim_summaries,
        evidence_summary=ev_counts,
        verification=verif_dict,
        relationships=rel_summaries[:10],
        project_matches=proj_matches,
        is_saved=is_saved,
    )


def get_recent_changes(
    hours: int = 24,
    importance_min: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 20,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recent intelligence changes and claim revisions."""
    if db is None:
        db = Database()

    limit = max(1, min(limit, 50))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    target_project_id = None
    if project:
        p_clean = project.strip()
        proj = db.get_project(p_clean) or db.get_project(f"project:{p_clean.lower()}") or db.get_project_by_name(p_clean)
        if proj:
            target_project_id = proj.id

    changes = db.get_recent_intelligence_changes(days=int(max(1, hours / 24)), limit=100)
    filtered = []

    importance_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    min_imp_rank = importance_order.get((importance_min or "low").lower(), 1)

    for ch in changes:
        if ch.detected_at < cutoff:
            continue
        imp_rank = importance_order.get((ch.importance or "low").lower(), 1)
        if imp_rank < min_imp_rank:
            continue

        if target_project_id:
            matches = db.get_project_matches(target_project_id)
            if not any(m.entity_id == ch.cluster_id for m in matches):
                continue

        filtered.append({
            "id": ch.id,
            "cluster_id": ch.cluster_id,
            "change_type": ch.change_type,
            "importance": ch.importance,
            "description": ch.description,
            "old_value": ch.old_value,
            "new_value": ch.new_value,
            "detected_at": ch.detected_at.isoformat(),
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
    items = db.get_active_inbox_items()

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

    out = []
    for it in items[:limit]:
        out.append({
            "id": it.id,
            "story_cluster_id": it.story_cluster_id,
            "title": it.title,
            "section": it.section,
            "state": it.state,
            "is_starred": bool(it.is_starred),
            "inbox_score": round(it.inbox_score, 4),
            "rank_score": round(it.rank_score, 4),
            "project_impact_score": round(it.project_impact_score, 4),
            "matched_project_ids": it.matched_project_ids,
            "expires_at": it.expires_at.isoformat() if it.expires_at else None,
            "created_at": it.created_at.isoformat(),
        })
    return out


def get_morning_brief(
    date_str: Optional[str] = None,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves the daily morning briefing for a given date."""
    if db is None:
        db = Database()

    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    briefing = db.get_daily_briefing(date_str)
    if not briefing:
        return None

    briefing_items = db.get_daily_briefing_items(briefing.id)
    items_by_section: Dict[str, List[Dict[str, Any]]] = {}

    for bi in briefing_items:
        inbox_item = db.get_inbox_item(bi.inbox_item_id)
        if inbox_item:
            cluster = db.get_cluster(inbox_item.story_cluster_id) if inbox_item.story_cluster_id else None
            summary = cluster.canonical_title if cluster else inbox_item.title
            claims = db.get_claims_by_cluster(inbox_item.story_cluster_id, current_only=True) if inbox_item.story_cluster_id else []
            claim_scores = [c.verification_score for c in claims]
            verif_score = float(np.mean(claim_scores)) if claim_scores else None
            item_data = {
                "inbox_item_id": inbox_item.id,
                "cluster_id": inbox_item.story_cluster_id,
                "title": inbox_item.title,
                "summary": summary,
                "priority": round(inbox_item.rank_score, 4),
                "verification_score": round(verif_score, 4) if verif_score is not None else None,
                "position": bi.position,
            }
            items_by_section.setdefault(bi.section, []).append(item_data)

    return {
        "id": briefing.id,
        "briefing_date": briefing.briefing_date,
        "generated_at": briefing.generated_at.isoformat(),
        "total_items": briefing.total_items,
        "high_priority_count": briefing.high_priority_count,
        "project_relevant_count": briefing.project_relevant_count,
        "sections": items_by_section,
        "summary_text": briefing.summary_text,
    }
