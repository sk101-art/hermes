import os
import tempfile
import uuid
from datetime import datetime, timezone
import numpy as np

from app.models.schemas import Event, StoryCluster, EventRelationship
from app.semantic.similarity import (
    cosine_similarity,
    extract_github_repo,
    extract_arxiv_id,
    extract_identifiers,
    match_direct_identifiers,
)
from app.semantic.clustering import (
    ClusterManager,
    calculate_source_diversity,
    calculate_cluster_score,
    calculate_evidence_count_signal,
    extract_distinctive_tokens,
)
from app.storage.db import Database


class MockEmbeddingService:
    """Deterministic mock embedding service for offline testing."""

    def __init__(self, model_name: str = "mock-model", vector_map: dict = None):
        self.model_name = model_name
        self.vector_map = vector_map or {}
        self.call_count = 0

    def embed(self, text: str) -> np.ndarray:
        self.call_count += 1
        for k, v in self.vector_map.items():
            if k.lower() in text.lower():
                return v
        return np.ones(384, dtype=np.float32) / np.sqrt(384)

    def embed_batch(self, texts: list) -> np.ndarray:
        return np.vstack([self.embed(t) for t in texts])


def test_cosine_similarity():
    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_c = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    vec_d = np.array([-1.0, 0.0, 0.0], dtype=np.float32)

    assert abs(cosine_similarity(vec_a, vec_b) - 1.0) < 1e-5
    assert abs(cosine_similarity(vec_a, vec_c) - 0.0) < 1e-5
    assert abs(cosine_similarity(vec_a, vec_d) - (-1.0)) < 1e-5
    assert cosine_similarity(None, vec_a) == 0.0


def test_embedding_storage_and_retrieval():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    db2 = None
    try:
        db = Database(db_path=db_path)
        event_id = "arxiv:2608.12345"
        model_name = "test-minilm"
        test_vec = np.random.randn(384).astype(np.float32)
        test_vec = test_vec / np.linalg.norm(test_vec)

        saved = db.save_embedding(event_id, model_name, test_vec)
        assert saved is True
        assert db.embedding_exists(event_id, model_name) is True

        db.close()
        db = None

        db2 = Database(db_path=db_path)
        retrieved_vec = db2.get_embedding(event_id, model_name)
        assert retrieved_vec is not None
        assert retrieved_vec.shape == (384,)
        assert np.allclose(retrieved_vec, test_vec, atol=1e-6)
    finally:
        if db:
            db.close()
        if db2:
            db2.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_embedding_cache_avoids_recomputation():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    try:
        db = Database(db_path=db_path)
        event = Event(id="gh:1", title="vLLM Inference", url="https://github.com/vllm/vllm", final_score=0.9)
        db.insert_event(event)

        mock_vec = np.ones(384, dtype=np.float32) / np.sqrt(384)
        mock_svc = MockEmbeddingService(model_name="mock-model", vector_map={"vllm": mock_vec})
        mgr = ClusterManager(similarity_threshold=0.75)

        stats1 = mgr.process([event], db, mock_svc)
        assert stats1["embeddings_generated"] == 1
        assert stats1["embeddings_reused"] == 0
        assert mock_svc.call_count == 1

        stats2 = mgr.process([event], db, mock_svc)
        assert stats2["embeddings_generated"] == 0
        assert stats2["embeddings_reused"] == 1
        assert mock_svc.call_count == 1
    finally:
        if db:
            db.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_direct_github_and_arxiv_identifier_linking():
    hn_gh_event = Event(
        id="hackernews:101",
        source="hackernews",
        source_type="discussion",
        title="vLLM project discussion",
        url="https://github.com/vllm-project/vllm",
    )
    gh_event = Event(
        id="github:vllm-project/vllm",
        source="github",
        source_type="code_repository",
        title="vllm-project/vllm",
        url="https://github.com/vllm-project/vllm",
    )

    match_gh = match_direct_identifiers(hn_gh_event, gh_event)
    assert match_gh is not None
    rel_type, conf = match_gh
    assert rel_type == "discusses"
    assert conf >= 0.95

    hn_arxiv_event = Event(
        id="hackernews:102",
        source="hackernews",
        source_type="discussion",
        title="Paper discussion",
        url="https://arxiv.org/abs/2608.12345v2",
    )
    arxiv_event = Event(
        id="arxiv:2608.12345",
        source="arxiv",
        source_type="research_paper",
        title="Paper title",
        url="https://arxiv.org/abs/2608.12345",
    )
    match_ax = match_direct_identifiers(hn_arxiv_event, arxiv_event)
    assert match_ax is not None


def test_same_story_clustering():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    try:
        db = Database(db_path=db_path)

        ev_arxiv = Event(
            id="arxiv:2608.100",
            source="arxiv",
            source_type="research_paper",
            title="FlashDecoding++: Fast LLM Inference on CUDA",
            url="https://arxiv.org/abs/2608.100",
            final_score=0.90,
        )
        ev_gh = Event(
            id="github:flash-decoding",
            source="github",
            source_type="code_repository",
            title="flash-decoding - Fast LLM Inference on CUDA",
            url="https://github.com/example/flash-decoding",
            final_score=0.88,
        )
        ev_hn = Event(
            id="hackernews:999",
            source="hackernews",
            source_type="discussion",
            title="Show HN: FlashDecoding++ fast LLM inference",
            url="https://github.com/example/flash-decoding",
            final_score=0.82,
        )

        for ev in [ev_arxiv, ev_gh, ev_hn]:
            db.insert_event(ev)

        base_v = np.ones(384, dtype=np.float32) / np.sqrt(384)
        mock_svc = MockEmbeddingService(
            model_name="mock-model",
            vector_map={"flashdecoding": base_v, "flash-decoding": base_v},
        )

        mgr = ClusterManager(similarity_threshold=0.75)
        stats = mgr.process([ev_arxiv, ev_gh, ev_hn], db, mock_svc)

        top_clusters = db.get_top_clusters(limit=10)
        assert len(top_clusters) == 1
        cluster = top_clusters[0]
        assert len(cluster.event_ids) == 3
        assert set(cluster.sources) == {"arxiv", "github", "hackernews"}
        assert cluster.source_diversity_score == 1.0
    finally:
        if db:
            db.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_unrelated_stories_remain_separate():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    try:
        db = Database(db_path=db_path)

        ev_llvm = Event(
            id="github:llvm",
            source="github",
            title="LLVM Compiler Optimization Framework",
            url="https://github.com/llvm/llvm",
            final_score=0.85,
        )
        ev_vdb = Event(
            id="arxiv:vdb",
            source="arxiv",
            title="Range Filtering in Vector Databases",
            url="https://arxiv.org/abs/vdb",
            final_score=0.80,
        )

        db.insert_event(ev_llvm)
        db.insert_event(ev_vdb)

        v_llvm = np.zeros(384, dtype=np.float32)
        v_llvm[0] = 1.0
        v_vdb = np.zeros(384, dtype=np.float32)
        v_vdb[1] = 1.0

        mock_svc = MockEmbeddingService(
            model_name="mock-model",
            vector_map={"llvm": v_llvm, "vector": v_vdb},
        )

        mgr = ClusterManager(similarity_threshold=0.75)
        mgr.process([ev_llvm, ev_vdb], db, mock_svc)

        top_clusters = db.get_top_clusters(limit=10)
        assert len(top_clusters) == 2
        assert top_clusters[0].id != top_clusters[1].id
    finally:
        if db:
            db.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_source_diversity_calculation():
    assert calculate_source_diversity(["github"]) == 0.0
    assert calculate_source_diversity(["github", "github"]) == 0.0
    assert calculate_source_diversity(["github", "arxiv"]) == 0.5
    assert calculate_source_diversity(["github", "arxiv", "hackernews"]) == 1.0


def test_cluster_persistence():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    db2 = None
    try:
        db = Database(db_path=db_path)
        cluster = StoryCluster(
            id="cluster:persisted-1",
            canonical_title="Canonical Breakthrough",
            cluster_score=0.92,
            source_diversity_score=1.0,
            max_event_score=0.90,
        )
        db.create_cluster(cluster)
        db.add_event_to_cluster(cluster.id, "github:1", 1.0)
        db.add_event_to_cluster(cluster.id, "arxiv:1", 0.88)
        db.close()
        db = None

        db2 = Database(db_path=db_path)
        c = db2.get_cluster("cluster:persisted-1")
        assert c is not None
        assert c.canonical_title == "Canonical Breakthrough"
        assert c.cluster_score == 0.92
        assert len(c.event_ids) == 2
        assert "github:1" in c.event_ids
    finally:
        if db:
            db.close()
        if db2:
            db2.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_semantic_failure_fallback():
    class FailingEmbeddingService:
        model_name = "failing-model"
        def embed_batch(self, texts):
            raise RuntimeError("Model out of memory simulation")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    try:
        db = Database(db_path=db_path)
        ev = Event(id="gh:1", title="Sample Repo", url="https://github.com/sample", final_score=0.8)
        db.insert_event(ev)

        mgr = ClusterManager()
        stats = mgr.process([ev], db, FailingEmbeddingService())

        assert stats["semantic_failures"] == 1
        assert stats["clusters_created"] == 1
        top_clusters = db.get_top_clusters(limit=5)
        assert len(top_clusters) == 1
        assert top_clusters[0].canonical_title == "Sample Repo"
    finally:
        if db:
            db.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass
