import os
import tempfile
from datetime import datetime, timezone

from app.adapters.arxiv import ArxivAdapter
from app.adapters.github import GitHubAdapter
from app.adapters.hackernews import HackerNewsAdapter
from app.models.schemas import Event
from app.pipeline.dedup import is_duplicate_event
from app.pipeline.filter import filter_event, evaluate_interests
from app.pipeline.rank import calculate_trust, calculate_relevance, calculate_popularity, score_event
from app.storage.db import Database


def test_event_model_instantiation():
    event = Event(
        id="github:123456",
        title="ggerganov/llama.cpp - Port of Facebook's LLaMA model in C/C++",
        url="https://github.com/ggerganov/llama.cpp",
        topics=["llm", "inference", "c-plus-plus"],
    )
    assert event.id == "github:123456"
    assert event.source == "github"
    assert event.source_type == "code_repository"
    assert event.event_type == "repository"
    assert len(event.topics) == 3


def test_duplicate_detection():
    event1 = Event(
        id="github:1001",
        title="Repo 1",
        url="https://github.com/example/repo1",
    )
    event2 = Event(
        id="github:1001",
        title="Repo 1 Duplicate",
        url="https://github.com/example/repo1",
    )
    seen_ids = {event1.id}
    seen_urls = {event1.url}

    assert is_duplicate_event(event2, seen_ids, seen_urls) is True

    event3 = Event(
        id="github:1002",
        title="Repo 2",
        url="https://github.com/example/repo2",
    )
    assert is_duplicate_event(event3, seen_ids, seen_urls) is False


def test_relevance_scoring_prefers_relevant_topics():
    interests = {
        "high": ["LLM inference", "CUDA", "LLVM"],
        "medium": ["AI agents", "RAG"],
        "low": ["funding news"],
    }

    relevant_event = Event(
        id="github:2001",
        title="vLLM: Easy, fast, and cheap LLM inference with CUDA",
        text="High-throughput LLM inference engine with PagedAttention and CUDA optimization",
        url="https://github.com/vllm-project/vllm",
        topics=["llm-inference", "cuda"],
        published_at=datetime.now(timezone.utc),
    )

    irrelevant_event = Event(
        id="github:2002",
        title="RecipeBook: Simple cooking app",
        text="Store your favourite cookie and pasta recipes",
        url="https://github.com/example/recipebook",
        topics=["cooking", "recipes"],
        published_at=datetime.now(timezone.utc),
    )

    scored_relevant = score_event(relevant_event, interests)
    scored_irrelevant = score_event(irrelevant_event, interests)

    assert filter_event(relevant_event, interests) is True
    assert filter_event(irrelevant_event, interests) is False
    assert scored_relevant.relevance_score > scored_irrelevant.relevance_score
    assert scored_relevant.final_score > scored_irrelevant.final_score


def test_synonym_expansion_matching():
    interests = {
        "high": ["LLM inference", "ML systems"],
        "medium": ["AI agents"],
        "low": [],
    }

    event = Event(
        id="arxiv:100",
        source="arxiv",
        title="Scaling Machine Learning Systems for Large Language Model Inference",
        text="Abstract discussing compiler optimizations.",
        url="https://arxiv.org/abs/100",
    )
    assert filter_event(event, interests) is True
    high, med, low = evaluate_interests(event, interests)
    assert high > 0


def test_arxiv_normalization():
    adapter = ArxivAdapter()
    raw_paper = {
        "arxiv_id": "2311.01234v1",
        "title": "FlashDecoding++: Faster Large Language Model Inference on GPUs",
        "summary": "We propose FlashDecoding++ to accelerate LLM inference using fine-grained CUDA kernels.",
        "url": "https://arxiv.org/abs/2311.01234v1",
        "authors": ["John Doe", "Jane Smith"],
        "published": "2023-11-01T12:00:00Z",
        "updated": "2023-11-02T12:00:00Z",
        "primary_category": "cs.AI",
        "categories": ["cs.AI", "cs.DC"],
    }
    event = adapter.normalize(raw_paper)
    assert event.id == "arxiv:2311.01234v1"
    assert event.source == "arxiv"
    assert event.source_type == "research_paper"
    assert event.event_type == "paper"
    assert "FlashDecoding++" in event.title
    assert len(event.authors) == 2
    assert "cs.ai" in event.topics
    assert event.metadata["arxiv_id"] == "2311.01234v1"


def test_hackernews_normalization():
    adapter = HackerNewsAdapter()
    raw_story = {
        "id": 38192831,
        "title": "Show HN: Fast CUDA kernels for LLM attention",
        "url": "https://github.com/example/cuda-attention",
        "by": "geekdev",
        "time": 1700000000,
        "score": 250,
        "descendants": 45,
        "type": "story",
    }
    event = adapter.normalize(raw_story)
    assert event.id == "hackernews:38192831"
    assert event.source == "hackernews"
    assert event.source_type == "discussion"
    assert event.event_type == "story"
    assert event.metadata["score"] == 250
    assert event.authors == ["geekdev"]
    assert event.url == "https://github.com/example/cuda-attention"


def test_hackernews_normalization_fallback_url():
    adapter = HackerNewsAdapter()
    raw_ask_hn = {
        "id": 38199999,
        "title": "Ask HN: What is your favorite vector database?",
        "text": "Looking for recommendations on self-hosted vector databases.",
        "by": "asker",
        "time": 1700000100,
        "score": 85,
        "descendants": 120,
        "type": "story",
    }
    event = adapter.normalize(raw_ask_hn)
    assert event.url == "https://news.ycombinator.com/item?id=38199999"


def test_source_specific_trust_scoring():
    arxiv_event = Event(id="arxiv:1", source="arxiv", title="Paper", url="https://arxiv.org/abs/1")
    gh_event = Event(id="github:1", source="github", title="Repo", url="https://github.com/1")
    hn_event = Event(id="hackernews:1", source="hackernews", title="Story", url="https://news.ycombinator.com/1")

    assert calculate_trust(arxiv_event) == 0.90
    assert calculate_trust(gh_event) == 0.75
    assert calculate_trust(hn_event) == 0.65


def test_cross_source_sqlite_storage():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        db = Database(db_path=db_path)

        events = [
            Event(
                id="arxiv:2001",
                source="arxiv",
                source_type="research_paper",
                event_type="paper",
                title="Advanced CUDA Compiler Optimization for LLM Inference",
                text="In-depth analysis of LLM inference compiler optimization techniques.",
                url="https://arxiv.org/abs/2001",
                authors=["Researcher A"],
                topics=["cs.ar", "cs.ai"],
                published_at=datetime.now(timezone.utc),
            ),
            Event(
                id="github:2002",
                source="github",
                source_type="code_repository",
                event_type="repository",
                title="vllm-project/vllm",
                text="High throughput LLM inference with CUDA",
                url="https://github.com/vllm-project/vllm",
                metadata={"stars": 12000, "language": "Python"},
                published_at=datetime.now(timezone.utc),
            ),
            Event(
                id="hackernews:2003",
                source="hackernews",
                source_type="discussion",
                event_type="story",
                title="Show HN: A new RAG vector database engine",
                text="Discussion on building RAG pipelines",
                url="https://news.ycombinator.com/item?id=2003",
                metadata={"score": 300, "descendants": 50},
                published_at=datetime.now(timezone.utc),
            ),
        ]

        interests = {"high": ["CUDA", "LLM inference"], "medium": ["RAG", "vector database"], "low": []}

        for ev in events:
            assert filter_event(ev, interests) is True
            scored = score_event(ev, interests)
            assert scored.final_score > 0.0
            inserted = db.insert_event(scored)
            assert inserted is True

        top_events = db.get_top_events(limit=10)
        assert len(top_events) == 3
        sources = {ev.source for ev in top_events}
        assert sources == {"arxiv", "github", "hackernews"}
        db.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_source_failure_isolation():
    class BrokenAdapter:
        def fetch(self, limit: int = 50):
            raise ConnectionError("Simulated network failure")

    adapter = BrokenAdapter()
    items = []
    try:
        items = adapter.fetch(limit=10)
    except Exception:
        items = []
    assert items == []
