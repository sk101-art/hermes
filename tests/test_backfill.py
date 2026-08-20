import os
import tempfile
import numpy as np

from app.models.schemas import Event, StoryCluster
from app.semantic.clustering import ClusterManager, compute_cluster_centroid, select_candidates
from app.semantic.similarity import extract_github_repo, extract_arxiv_id, extract_identifiers, match_direct_identifiers, cosine_similarity
from app.storage.db import Database


class MockEmbeddingService:
    def __init__(self, model_name="mock-minilm", vector_map=None):
        self.model_name = model_name
        self.vector_map = vector_map or {}
        self.call_count = 0

    def embed(self, text):
        self.call_count += 1
        for k, v in self.vector_map.items():
            if k.lower() in text.lower():
                return v
        # Default pseudo vector based on hash
        h = abs(hash(text)) % 384
        vec = np.zeros(384, dtype=np.float32)
        vec[h] = 1.0
        return vec

    def embed_batch(self, texts):
        return np.vstack([self.embed(t) for t in texts])


def test_url_normalization_edge_cases():
    # GitHub edge cases
    assert extract_github_repo("https://github.com/vllm-project/vllm/issues/123") == "github:vllm-project/vllm"
    assert extract_github_repo("https://github.com/vllm-project/vllm/releases/tag/v0.6.0") == "github:vllm-project/vllm"
    assert extract_github_repo("https://github.com/vllm-project/vllm.git") == "github:vllm-project/vllm"
    assert extract_github_repo("https://github.com/VLLM-Project/Vllm/") == "github:vllm-project/vllm"
    assert extract_github_repo("git@github.com:owner/repo.git") == "github:owner/repo"
    assert extract_github_repo("https://github.com/explore") is None

    # arXiv edge cases
    assert extract_arxiv_id("https://arxiv.org/abs/2608.12345v2") == "arxiv:2608.12345"
    assert extract_arxiv_id("https://arxiv.org/pdf/2608.12345.pdf") == "arxiv:2608.12345"
    assert extract_arxiv_id("https://arxiv.org/html/2608.12345v1") == "arxiv:2608.12345"
    assert extract_arxiv_id("arxiv:2608.12345") == "arxiv:2608.12345"


def test_direct_hn_relationships():
    hn_gh = Event(
        id="hackernews:1",
        source="hackernews",
        source_type="discussion",
        title="vLLM discussion on HN",
        url="https://github.com/vllm-project/vllm/issues/99",
    )
    gh = Event(
        id="github:vllm-project/vllm",
        source="github",
        source_type="code_repository",
        title="vLLM Inference Engine",
        url="https://github.com/vllm-project/vllm",
    )

    match = match_direct_identifiers(hn_gh, gh)
    assert match is not None
    rel_type, conf = match
    assert rel_type == "discusses"
    assert conf >= 0.95

    hn_ax = Event(
        id="hackernews:2",
        source="hackernews",
        source_type="discussion",
        title="Discussion on new paper",
        url="https://arxiv.org/pdf/2608.99999.pdf",
    )
    ax = Event(
        id="arxiv:2608.99999",
        source="arxiv",
        source_type="research_paper",
        title="Paper title",
        url="https://arxiv.org/abs/2608.99999v1",
    )
    match_ax = match_direct_identifiers(hn_ax, ax)
    assert match_ax is not None


def test_historical_backfill_and_idempotence():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    try:
        db = Database(db_path=db_path)
        # Create 3 un-embedded events
        e1 = Event(id="gh:1", source="github", title="Repo A", url="https://github.com/a/a")
        e2 = Event(id="gh:2", source="github", title="Repo B", url="https://github.com/b/b")
        e3 = Event(id="ax:1", source="arxiv", title="Paper C", url="https://arxiv.org/abs/2608.11111")
        for e in [e1, e2, e3]:
            db.insert_event(e)

        mock_svc = MockEmbeddingService()
        mgr = ClusterManager()

        # Step 1: Find unembedded events and backfill
        unembedded = db.get_unembedded_events(mock_svc.model_name)
        assert len(unembedded) == 3

        stats1 = mgr.process(unembedded, db, mock_svc)
        assert stats1["embeddings_generated"] == 3
        assert stats1["embeddings_reused"] == 0

        # Verify all 3 events are now embedded
        assert len(db.get_unembedded_events(mock_svc.model_name)) == 0

        # Step 2: Idempotent run - nothing unembedded, nothing unclustered
        unembedded_2 = db.get_unembedded_events(mock_svc.model_name)
        assert len(unembedded_2) == 0

        stats2 = mgr.process(db.get_unclustered_events(), db, mock_svc)
        assert stats2["accepted_events"] == 0
        assert stats2["embeddings_generated"] == 0
    finally:
        if db:
            db.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_semantic_rebuild_preserves_events_and_cached_embeddings():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    try:
        db = Database(db_path=db_path)
        e1 = Event(id="gh:1", source="github", title="Repo A", url="https://github.com/a/a")
        db.insert_event(e1)

        vec = np.ones(384, dtype=np.float32) / np.sqrt(384)
        db.save_embedding("gh:1", "mock-minilm", vec)

        c = StoryCluster(id="cluster:1", canonical_title="Repo A", event_ids=["gh:1"])
        db.create_cluster(c)
        db.add_event_to_cluster("cluster:1", "gh:1")

        assert db.get_event_count() == 1
        assert db.embedding_exists("gh:1", "mock-minilm") is True
        assert len(db.get_top_clusters(10)) == 1

        # Perform rebuild
        db.clear_clusters_and_relationships()

        # Events and embeddings must be preserved!
        assert db.get_event_count() == 1
        assert db.embedding_exists("gh:1", "mock-minilm") is True
        assert len(db.get_top_clusters(10)) == 0  # Clusters cleared
    finally:
        if db:
            db.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_full_synthetic_clustering_regression():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = None
    try:
        db = Database(db_path=db_path)

        # Group A: FlashAttention (arXiv paper + GitHub repo + HN discussion) -> same cluster
        gA_arxiv = Event(
            id="arxiv:2608.001",
            source="arxiv",
            source_type="research_paper",
            title="FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
            url="https://arxiv.org/abs/2608.001",
            final_score=0.92,
        )
        gA_gh = Event(
            id="github:dao-ai-lab/flash-attention",
            source="github",
            source_type="code_repository",
            title="dao-ai-lab/flash-attention: Fast and memory-efficient exact attention",
            url="https://github.com/dao-ai-lab/flash-attention",
            final_score=0.90,
        )
        gA_hn = Event(
            id="hackernews:111",
            source="hackernews",
            source_type="discussion",
            title="FlashAttention gets major IO speedup",
            url="https://github.com/dao-ai-lab/flash-attention",
            final_score=0.85,
        )

        # Group B: LLVM Compiler Optimization (arXiv + GitHub) -> same cluster
        gB_arxiv = Event(
            id="arxiv:2608.002",
            source="arxiv",
            source_type="research_paper",
            title="Portable Models for Compiler Optimization in LLVM",
            url="https://arxiv.org/abs/2608.002",
            final_score=0.84,
        )
        gB_gh = Event(
            id="github:llvm/llvm-project",
            source="github",
            source_type="code_repository",
            title="llvm/llvm-project: The LLVM Project Compiler Infrastructure",
            url="https://github.com/llvm/llvm-project",
            final_score=0.88,
        )

        # Group C: Unrelated Vector DB singleton & CUDA SLAM singleton
        gC_vdb = Event(
            id="arxiv:2608.003",
            source="arxiv",
            source_type="research_paper",
            title="Range Filtering in Vector Databases for Nearest Neighbor Search",
            url="https://arxiv.org/abs/2608.003",
            final_score=0.80,
        )
        gC_slam = Event(
            id="github:slam-lab/jetson-slam",
            source="github",
            source_type="code_repository",
            title="jetson-slam: GPU ORB-SLAM3 for Edge Robotics",
            url="https://github.com/slam-lab/jetson-slam",
            final_score=0.78,
        )

        all_synthetic = [gA_arxiv, gA_gh, gA_hn, gB_arxiv, gB_gh, gC_vdb, gC_slam]
        for e in all_synthetic:
            db.insert_event(e)

        # Define high similarity vectors for Group A, Group B, and orthogonal for Group C
        v_a = np.zeros(384, dtype=np.float32)
        v_a[0:10] = 1.0
        v_a = v_a / np.linalg.norm(v_a)

        v_b = np.zeros(384, dtype=np.float32)
        v_b[10:20] = 1.0
        v_b = v_b / np.linalg.norm(v_b)

        v_c1 = np.zeros(384, dtype=np.float32)
        v_c1[20:30] = 1.0
        v_c1 = v_c1 / np.linalg.norm(v_c1)

        v_c2 = np.zeros(384, dtype=np.float32)
        v_c2[30:40] = 1.0
        v_c2 = v_c2 / np.linalg.norm(v_c2)

        vector_map = {
            "flashattention": v_a,
            "flash-attention": v_a,
            "llvm": v_b,
            "vector": v_c1,
            "slam": v_c2,
        }

        mock_svc = MockEmbeddingService(vector_map=vector_map)
        mgr = ClusterManager(similarity_threshold=0.78)

        stats = mgr.process(all_synthetic, db, mock_svc)

        top_clusters = db.get_top_clusters(10)
        assert len(top_clusters) == 4  # Group A (3 events), Group B (2 events), Group C1 (1 event), Group C2 (1 event)

        # Find Group A cluster
        group_a_cluster = next((c for c in top_clusters if "FlashAttention" in c.canonical_title or "flash-attention" in c.canonical_title), None)
        assert group_a_cluster is not None
        assert len(group_a_cluster.event_ids) == 3
        assert set(group_a_cluster.sources) == {"arxiv", "github", "hackernews"}
        assert group_a_cluster.source_diversity_score == 1.0

        # Find Group B cluster
        group_b_cluster = next((c for c in top_clusters if "llvm" in c.canonical_title.lower()), None)
        assert group_b_cluster is not None
        assert len(group_b_cluster.event_ids) == 2
        assert set(group_b_cluster.sources) == {"arxiv", "github"}
        assert group_b_cluster.source_diversity_score == 0.5
    finally:
        if db:
            db.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass
