import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from app.models.schemas import Event, StoryCluster, EventRelationship
from app.semantic.embeddings import EmbeddingService, prepare_event_text
from app.semantic.similarity import cosine_similarity, match_direct_identifiers, extract_identifiers
from app.storage.db import Database

STOP_WORDS = {
    "the", "and", "or", "a", "an", "new", "release", "system", "model",
    "models", "paper", "using", "based", "framework", "tool", "tools",
    "ai", "machine", "learning", "with", "for", "in", "on", "of", "to",
    "is", "by", "from", "at", "as", "into", "through", "about", "via",
    "this", "we", "our", "are", "that", "it", "an", "all", "its"
}


def extract_distinctive_tokens(text: str) -> Set[str]:
    """Extract informative keywords/tokens ignoring common stop words."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\-\.]+", " ", text.lower())
    tokens = {w.strip(".-") for w in cleaned.split() if len(w.strip(".-")) >= 3}
    return tokens - STOP_WORDS


def calculate_source_diversity(sources: List[str]) -> float:
    """Calculate source diversity signal (1 source = 0.0, 2 sources = 0.5, 3+ sources = 1.0)."""
    unique_count = len(set(sources))
    if unique_count <= 1:
        return 0.0
    elif unique_count == 2:
        return 0.5
    else:
        return 1.0


def calculate_evidence_count_signal(num_events: int) -> float:
    """Small bounded boost for multiple independent supporting events."""
    if num_events <= 1:
        return 0.0
    elif num_events == 2:
        return 0.5
    else:
        return min(1.0, 0.5 + (num_events - 2) * 0.25)


def calculate_cluster_score(max_event_score: float, sources: List[str], num_events: int) -> float:
    """Deterministic cluster scoring combining event relevance, source diversity, and evidence count."""
    div_score = calculate_source_diversity(sources)
    count_score = calculate_evidence_count_signal(num_events)

    score = (
        max_event_score * 0.75
        + div_score * 0.15
        + count_score * 0.10
    )
    return round(max(0.0, min(1.0, score)), 4)


def select_candidates(
    target_event: Event,
    candidate_events: List[Event],
    max_candidates: int = 50,
) -> List[Event]:
    """Cheap deterministic candidate selection before semantic vector comparison."""
    target_tokens = extract_distinctive_tokens(f"{target_event.title} {' '.join(target_event.topics)}")
    target_ids = set(extract_identifiers(target_event))

    scored_candidates: List[Tuple[float, Event]] = []
    for cand in candidate_events:
        if cand.id == target_event.id:
            continue

        cand_ids = set(extract_identifiers(cand))
        cand_tokens = extract_distinctive_tokens(f"{cand.title} {' '.join(cand.topics)}")

        shared_ids = len(target_ids.intersection(cand_ids))
        shared_tokens = len(target_tokens.intersection(cand_tokens))

        score = (shared_ids * 10.0) + (shared_tokens * 1.0)
        if score > 0:
            scored_candidates.append((score, cand))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in scored_candidates[:max_candidates]]


class ClusterManager:
    """Orchestrates embedding caching, candidate filtering, direct linking, and clustering."""

    def __init__(
        self,
        similarity_threshold: float = 0.78,
        candidate_days: int = 30,
        max_candidates: int = 50,
        max_chars: int = 2500,
    ):
        self.similarity_threshold = similarity_threshold
        self.candidate_days = candidate_days
        self.max_candidates = max_candidates
        self.max_chars = max_chars

    def process(
        self,
        accepted_events: List[Event],
        db: Database,
        embedding_service: EmbeddingService,
    ) -> Dict[str, Any]:
        stats = {
            "accepted_events": len(accepted_events),
            "embeddings_generated": 0,
            "embeddings_reused": 0,
            "clusters_created": 0,
            "events_attached": 0,
            "relationships_created": 0,
            "semantic_failures": 0,
        }

        if not accepted_events:
            return stats

        model_name = embedding_service.model_name

        # 1. Manage Embedding Cache & Generation in Batches
        uncached_events: List[Event] = []
        uncached_texts: List[str] = []

        for ev in accepted_events:
            if db.embedding_exists(ev.id, model_name):
                stats["embeddings_reused"] += 1
            else:
                uncached_events.append(ev)
                uncached_texts.append(prepare_event_text(ev, max_chars=self.max_chars))

        if uncached_events:
            try:
                vecs = embedding_service.embed_batch(uncached_texts)
                for ev, vec in zip(uncached_events, vecs):
                    db.save_embedding(ev.id, model_name, vec)
                    stats["embeddings_generated"] += 1
            except Exception as e:
                print(f"[Warning] Batch embedding generation error: {e}", flush=True)
                stats["semantic_failures"] += len(uncached_events)

        # 2. Retrieve recent events pool for candidate generation
        recent_events = db.get_recent_events(days=self.candidate_days, limit=300)
        events_by_id = {e.id: e for e in recent_events}
        for ev in accepted_events:
            events_by_id[ev.id] = ev

        # 3. Process each accepted event into clusters
        for ev in accepted_events:
            # Check if event is already part of an existing cluster in DB
            existing_cluster_id = db.get_event_cluster(ev.id)
            if existing_cluster_id:
                continue

            candidates = select_candidates(ev, list(events_by_id.values()), max_candidates=self.max_candidates)

            best_cluster_id: Optional[str] = None
            best_similarity: float = 0.0
            best_matched_event: Optional[Event] = None
            direct_rel_type: Optional[str] = None
            direct_confidence: float = 0.0

            # First: Direct deterministic identifier linking against existing clustered candidates
            for cand in candidates:
                direct_match = match_direct_identifiers(ev, cand)
                if direct_match:
                    rel_type, conf = direct_match
                    cand_cid = db.get_event_cluster(cand.id)
                    if cand_cid:
                        best_cluster_id = cand_cid
                        best_similarity = conf
                        best_matched_event = cand
                        direct_rel_type = rel_type
                        direct_confidence = conf
                        break
                    elif not best_matched_event:
                        best_matched_event = cand
                        direct_rel_type = rel_type
                        direct_confidence = conf

            # Second: Semantic similarity with candidates belonging to existing clusters
            if not best_cluster_id:
                ev_vec = db.get_embedding(ev.id, model_name)
                if ev_vec is not None:
                    for cand in candidates:
                        cand_cid = db.get_event_cluster(cand.id)
                        cand_vec = db.get_embedding(cand.id, model_name)
                        if cand_vec is not None:
                            sim = cosine_similarity(ev_vec, cand_vec)
                            if cand_cid and sim >= self.similarity_threshold and sim > best_similarity:
                                best_similarity = sim
                                best_matched_event = cand
                                best_cluster_id = cand_cid
                            elif not best_cluster_id and sim >= self.similarity_threshold and sim > best_similarity:
                                best_matched_event = cand
                                direct_confidence = sim

            # 4. Attach to existing cluster or create new cluster
            if best_cluster_id and best_similarity >= self.similarity_threshold:
                db.add_event_to_cluster(best_cluster_id, ev.id, similarity_score=round(best_similarity, 4))
                stats["events_attached"] += 1

                # Update cluster metadata and ranking
                cluster = db.get_cluster(best_cluster_id)
                if cluster:
                    cluster_events = db.get_cluster_events(best_cluster_id)
                    max_event = max(cluster_events, key=lambda x: x.final_score)
                    cluster.canonical_title = max_event.title
                    cluster.max_event_score = max_event.final_score
                    cluster.sources = list({e.source for e in cluster_events})
                    cluster.source_diversity_score = calculate_source_diversity(cluster.sources)
                    cluster.cluster_score = calculate_cluster_score(
                        cluster.max_event_score, cluster.sources, len(cluster_events)
                    )
                    cluster.updated_at = datetime.now(timezone.utc)
                    db.update_cluster(cluster)

                # Persist relationship if matched with an event
                if best_matched_event:
                    rel_id = f"rel:{uuid.uuid4().hex[:12]}"
                    rel = EventRelationship(
                        id=rel_id,
                        source_event_id=ev.id,
                        target_event_id=best_matched_event.id,
                        relationship_type=direct_rel_type or "same_story",
                        confidence=direct_confidence or round(best_similarity, 4),
                        created_at=datetime.now(timezone.utc),
                    )
                    db.save_relationship(rel)
                    stats["relationships_created"] += 1

            else:
                # Create a new StoryCluster
                new_cluster_id = f"cluster:{uuid.uuid4().hex[:12]}"
                new_cluster = StoryCluster(
                    id=new_cluster_id,
                    canonical_title=ev.title,
                    event_ids=[ev.id],
                    sources=[ev.source],
                    cluster_score=calculate_cluster_score(ev.final_score, [ev.source], 1),
                    source_diversity_score=calculate_source_diversity([ev.source]),
                    max_event_score=ev.final_score,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                db.create_cluster(new_cluster)
                db.add_event_to_cluster(new_cluster_id, ev.id, similarity_score=1.0)
                stats["clusters_created"] += 1

                if best_matched_event and (direct_rel_type or direct_confidence >= self.similarity_threshold):
                    rel_id = f"rel:{uuid.uuid4().hex[:12]}"
                    rel = EventRelationship(
                        id=rel_id,
                        source_event_id=ev.id,
                        target_event_id=best_matched_event.id,
                        relationship_type=direct_rel_type or "related",
                        confidence=direct_confidence or 0.80,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.save_relationship(rel)
                    stats["relationships_created"] += 1

        return stats
