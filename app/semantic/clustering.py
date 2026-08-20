import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from app.models.schemas import Event, StoryCluster, EventRelationship
from app.semantic.embeddings import EmbeddingService, prepare_event_text
from app.semantic.similarity import cosine_similarity, match_direct_identifiers, extract_identifiers, extract_github_repo, extract_arxiv_id
from app.storage.db import Database

STOP_WORDS = {
    "the", "and", "or", "a", "an", "new", "release", "system", "model",
    "models", "paper", "using", "based", "framework", "tool", "tools",
    "ai", "machine", "learning", "with", "for", "in", "on", "of", "to",
    "is", "by", "from", "at", "as", "into", "through", "about", "via",
    "this", "we", "our", "are", "that", "it", "all", "its", "can",
    "how", "what", "why", "when", "where", "which", "who", "your", "you",
    "more", "over", "between", "under", "after", "before", "during", "without",
    "project", "implementation", "approach", "method", "methods", "analysis"
}

SYNONYM_MAP = {
    "llm": {"large language model", "language model", "llms"},
    "rag": {"retrieval augmented generation", "retrieval-augmented generation"},
    "vlm": {"vision language model", "vision-language model"},
    "moe": {"mixture of experts", "mixture-of-experts"},
    "db": {"database", "databases"},
    "gpu": {"cuda", "graphics processing unit"},
}


def extract_distinctive_tokens(text: str) -> Set[str]:
    """Extract informative keywords/tokens preserving technical project names."""
    if not text:
        return set()

    # Extract alphanumeric words and special symbols like llama.cpp, c++, flash-attention
    raw_tokens = re.findall(r"[a-zA-Z0-9_\-\.\+]+", text.lower())
    tokens = set()

    for t in raw_tokens:
        clean = t.strip(".-")
        if len(clean) >= 2 and clean not in STOP_WORDS:
            tokens.add(clean)
            base = re.sub(r"[^\w]", "", clean)
            if len(base) >= 2 and base not in STOP_WORDS:
                tokens.add(base)

    lower_text = text.lower()
    for abbrev, full_forms in SYNONYM_MAP.items():
        if abbrev in tokens:
            for ff in full_forms:
                for word in ff.split():
                    if word not in STOP_WORDS:
                        tokens.add(word)
        for ff in full_forms:
            if ff in lower_text:
                tokens.add(abbrev)

    return tokens


def extract_owner_or_project(event: Event) -> Optional[str]:
    """Extract GitHub owner or distinctive project prefix if present."""
    gh_id = extract_github_repo(event.url) or extract_github_repo(event.id)
    if gh_id:
        parts = gh_id.replace("github:", "").split("/")
        if len(parts) == 2:
            return parts[0]  # owner
    return None


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
    db: Optional[Database] = None,
    max_candidates: int = 50,
) -> List[Event]:
    """Deterministic candidate selection combining direct identifiers, lexical overlap, and FTS5."""
    target_tokens = extract_distinctive_tokens(f"{target_event.title} {' '.join(target_event.topics)}")
    target_ids = set(extract_identifiers(target_event))
    target_owner = extract_owner_or_project(target_event)

    fts_id_set = set()
    if db and db.has_fts5 and target_tokens:
        fts_ids = db.get_fts_candidates(list(target_tokens), limit=max_candidates)
        fts_id_set = set(fts_ids)

    candidate_map = {c.id: c for c in candidate_events if c.id != target_event.id}

    if db and fts_id_set:
        missing_ids = [fid for fid in fts_id_set if fid not in candidate_map and fid != target_event.id]
        if missing_ids:
            for ev in db.get_events_by_ids(missing_ids):
                candidate_map[ev.id] = ev

    scored_candidates: List[Tuple[float, Event]] = []
    for cand_id, cand in candidate_map.items():
        cand_ids = set(extract_identifiers(cand))
        cand_tokens = extract_distinctive_tokens(f"{cand.title} {' '.join(cand.topics)}")
        cand_owner = extract_owner_or_project(cand)

        shared_ids = len(target_ids.intersection(cand_ids))
        shared_tokens = len(target_tokens.intersection(cand_tokens))
        same_owner = 1.0 if (target_owner and cand_owner and target_owner == cand_owner) else 0.0

        fts_bonus = 15.0 if cand_id in fts_id_set else 0.0
        score = (shared_ids * 100.0) + (same_owner * 30.0) + (shared_tokens * 2.0) + fts_bonus

        if score > 0:
            scored_candidates.append((score, cand))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in scored_candidates[:max_candidates]]


def compute_cluster_centroid(
    cluster_events: List[Event],
    db: Database,
    model_name: str,
) -> Optional[np.ndarray]:
    """Compute normalized mean centroid vector for a cluster."""
    if not cluster_events:
        return None
    vectors = []
    for ev in cluster_events:
        vec = db.get_embedding(ev.id, model_name)
        if vec is not None:
            vectors.append(vec)
    if not vectors:
        return None
    mean_vec = np.mean(vectors, axis=0)
    norm = np.linalg.norm(mean_vec)
    if norm == 0.0:
        return mean_vec.astype(np.float32)
    return (mean_vec / norm).astype(np.float32)


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
        start_time = time.time()
        stats = {
            "accepted_events": len(accepted_events),
            "embeddings_generated": 0,
            "embeddings_reused": 0,
            "clusters_created": 0,
            "events_attached": 0,
            "relationships_created": 0,
            "semantic_failures": 0,
            "candidate_comparisons": 0,
            "semantic_comparisons": 0,
            "avg_candidates_per_event": 0.0,
            "max_candidates_for_event": 0,
            "duration_seconds": 0.0,
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

        # 2. Retrieve pool of candidate events
        recent_events = db.get_recent_events(days=self.candidate_days, limit=400)
        events_by_id = {e.id: e for e in recent_events}
        for ev in accepted_events:
            events_by_id[ev.id] = ev

        candidate_counts = []

        # 3. Process each event into StoryClusters
        for ev in accepted_events:
            existing_cluster_id = db.get_event_cluster(ev.id)
            if existing_cluster_id:
                continue

            candidates = select_candidates(
                ev, list(events_by_id.values()), db=db, max_candidates=self.max_candidates
            )
            candidate_counts.append(len(candidates))
            stats["candidate_comparisons"] += len(candidates)

            best_cluster_id: Optional[str] = None
            best_similarity: float = 0.0
            best_matched_event: Optional[Event] = None
            direct_rel_type: Optional[str] = None
            direct_confidence: float = 0.0

            # Step 3a: Direct deterministic identifier linking
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

            # Step 3b: Semantic similarity with candidates belonging to clusters
            if not best_cluster_id:
                ev_vec = db.get_embedding(ev.id, model_name)
                if ev_vec is not None:
                    target_tokens = extract_distinctive_tokens(ev.title)
                    target_owner = extract_owner_or_project(ev)

                    for cand in candidates:
                        cand_cid = db.get_event_cluster(cand.id)
                        cand_vec = db.get_embedding(cand.id, model_name)
                        if cand_vec is not None:
                            stats["semantic_comparisons"] += 1
                            sim = cosine_similarity(ev_vec, cand_vec)

                            cand_tokens = extract_distinctive_tokens(cand.title)
                            cand_owner = extract_owner_or_project(cand)
                            shared_toks = len(target_tokens.intersection(cand_tokens))
                            same_owner = bool(target_owner and cand_owner and target_owner == cand_owner)

                            # If same owner or strong lexical overlap (>= 3 distinctive tokens), allow supported threshold (0.75)
                            has_strong_support = same_owner or (shared_toks >= 3)
                            effective_threshold = 0.75 if has_strong_support else self.similarity_threshold

                            if cand_cid:
                                # When attaching to an existing cluster, verify agreement with canonical cluster representative
                                cluster_evs = db.get_cluster_events(cand_cid)
                                rep_ev = max(cluster_evs, key=lambda x: x.final_score) if cluster_evs else cand
                                rep_vec = db.get_embedding(rep_ev.id, model_name)
                                rep_sim = cosine_similarity(ev_vec, rep_vec) if rep_vec is not None else sim

                                match_score = min(sim, rep_sim) if rep_sim > 0 else sim

                                if match_score >= effective_threshold and match_score > best_similarity:
                                    best_similarity = match_score
                                    best_matched_event = cand
                                    best_cluster_id = cand_cid
                            else:
                                if sim >= effective_threshold and sim > best_similarity:
                                    best_matched_event = cand
                                    direct_confidence = sim

            # Step 4: Attach to existing cluster or create new cluster
            if best_cluster_id and (direct_rel_type or best_similarity >= 0.75):
                db.add_event_to_cluster(best_cluster_id, ev.id, similarity_score=round(best_similarity, 4))
                stats["events_attached"] += 1

                # Update cluster metadata
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

                if best_matched_event:
                    rel_id = f"rel:{uuid.uuid4().hex[:12]}"
                    rel_type = direct_rel_type or ("same_story" if best_similarity >= 0.85 else "related")
                    rel = EventRelationship(
                        id=rel_id,
                        source_event_id=ev.id,
                        target_event_id=best_matched_event.id,
                        relationship_type=rel_type,
                        confidence=direct_confidence or round(best_similarity, 4),
                        created_at=datetime.now(timezone.utc),
                    )
                    db.save_relationship(rel)
                    stats["relationships_created"] += 1

            else:
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

                if best_matched_event and (direct_rel_type or direct_confidence >= 0.75):
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

        stats["avg_candidates_per_event"] = round(float(np.mean(candidate_counts)), 2) if candidate_counts else 0.0
        stats["max_candidates_for_event"] = max(candidate_counts) if candidate_counts else 0
        stats["duration_seconds"] = round(time.time() - start_time, 2)
        return stats
