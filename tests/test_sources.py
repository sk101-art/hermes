import pytest
from datetime import datetime, timezone

from app.adapters.huggingface import HuggingFaceAdapter
from app.adapters.openalex import OpenAlexAdapter
from app.adapters.crossref import CrossrefAdapter
from app.adapters.stackexchange import StackExchangeAdapter
from app.adapters.github_releases import GitHubReleasesAdapter
from app.adapters.rss import RssAdapter, strip_html_tags, parse_feed_date
from app.models.schemas import Event, SourceProfile
from app.pipeline.rank import calculate_trust, calculate_popularity, score_event
from app.semantic.similarity import normalize_doi, extract_doi, extract_hf_repo, extract_stackexchange_id, match_direct_identifiers


def test_source_profile_instantiation():
    sp = SourceProfile(
        name="openalex",
        source_type="scholarly_index",
        trust_prior=0.90,
        supports_citations=True,
    )
    assert sp.name == "openalex"
    assert sp.enabled is True
    assert sp.supports_citations is True
    assert sp.trust_prior == 0.90


def test_huggingface_model_normalization():
    adapter = HuggingFaceAdapter()
    raw = {
        "id": "meta-llama/Llama-3.1-8B-Instruct",
        "author": "meta-llama",
        "tags": ["safetensors", "llama", "conversational"],
        "pipeline_tag": "text-generation",
        "downloads": 1500000,
        "likes": 4200,
        "lastModified": "2026-08-15T12:00:00.000Z",
        "__hf_type": "model",
    }
    event = adapter.normalize(raw)
    assert event.id == "huggingface:model:meta-llama/llama-3.1-8b-instruct"
    assert event.source == "huggingface"
    assert event.source_type == "model_registry"
    assert event.event_type == "model"
    assert "Llama-3.1-8B-Instruct" in event.title
    assert event.url == "https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct"
    assert event.metadata["downloads"] == 1500000
    assert event.metadata["likes"] == 4200
    assert event.published_at is not None


def test_huggingface_dataset_normalization():
    adapter = HuggingFaceAdapter()
    raw = {
        "id": "tatsu-lab/alpaca",
        "author": "tatsu-lab",
        "tags": ["instruction-tuning", "synthetic"],
        "downloads": 85000,
        "likes": 1200,
        "lastModified": "2026-08-10T09:30:00.000Z",
        "__hf_type": "dataset",
    }
    event = adapter.normalize(raw)
    assert event.id == "huggingface:dataset:tatsu-lab/alpaca"
    assert event.source_type == "dataset_registry"
    assert event.event_type == "dataset"
    assert event.url == "https://huggingface.co/datasets/tatsu-lab/alpaca"


def test_openalex_normalization():
    adapter = OpenAlexAdapter()
    raw = {
        "id": "https://openalex.org/W4389283748",
        "display_name": "FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning",
        "doi": "https://doi.org/10.48550/arxiv.2307.08691",
        "publication_date": "2023-07-17",
        "cited_by_count": 850,
        "authorships": [
            {"author": {"display_name": "Tri Dao"}},
        ],
        "concepts": [
            {"display_name": "Attention"},
            {"display_name": "Graphics processing unit"},
        ],
        "primary_location": {
            "source": {"display_name": "arXiv (Cornell University)"},
            "landing_page_url": "https://arxiv.org/abs/2307.08691",
        },
        "open_access": {"is_oa": True, "oa_status": "gold"},
    }
    event = adapter.normalize(raw)
    assert event.id == "openalex:w4389283748"
    assert event.source == "openalex"
    assert event.source_type == "scholarly_index"
    assert event.event_type == "scholarly_work"
    assert event.doi == "10.48550/arxiv.2307.08691"
    assert event.cited_by_count == 850
    assert "Tri Dao" in event.authors
    assert event.metadata["venue"] == "arXiv (Cornell University)"


def test_crossref_normalization_and_doi_handling():
    adapter = CrossrefAdapter()
    raw = {
        "DOI": "10.1145/3620665.3640366",
        "title": ["vLLM: Easy, Fast, and Cheap LLM Serving with PagedAttention"],
        "author": [
            {"given": "Woosuk", "family": "Kwon"},
            {"given": "Zhuohan", "family": "Li"},
        ],
        "container-title": ["Proceedings of the 29th ACM SOSP"],
        "publisher": "Association for Computing Machinery",
        "references-count": 48,
        "published-print": {"date-parts": [[2023, 10, 23]]},
        "type": "proceedings-article",
    }
    event = adapter.normalize(raw)
    assert event.id == "crossref:10.1145/3620665.3640366"
    assert event.source == "crossref"
    assert event.source_type == "doi_registry"
    assert event.doi == "10.1145/3620665.3640366"
    assert "Woosuk Kwon" in event.authors
    assert event.metadata["publisher"] == "Association for Computing Machinery"
    assert event.metadata["references_count"] == 48


def test_stackexchange_normalization():
    adapter = StackExchangeAdapter()
    raw = {
        "question_id": 78912345,
        "title": "How to optimize CUDA kernel for &lt;b&gt;FlashAttention&lt;/b&gt; on Blackwell?",
        "tags": ["cuda", "llm", "gpu", "optimization"],
        "score": 42,
        "answer_count": 5,
        "is_answered": True,
        "view_count": 1820,
        "owner": {"display_name": "cuda_guru"},
        "creation_date": 1724150000,
        "link": "https://stackoverflow.com/questions/78912345/how-to-optimize-cuda-kernel",
        "__site": "stackoverflow",
    }
    event = adapter.normalize(raw)
    assert event.id == "stackexchange:stackoverflow:78912345"
    assert event.source == "stackexchange"
    assert event.source_type == "developer_community"
    assert event.event_type == "question"
    assert "<b>" not in event.title  # HTML unescaped
    assert "cuda_guru" in event.authors
    assert event.metadata["score"] == 42
    assert event.metadata["answer_count"] == 5


def test_github_release_normalization():
    adapter = GitHubReleasesAdapter()
    raw = {
        "id": 168920112,
        "tag_name": "v0.6.0",
        "name": "v0.6.0: Chunked Prefill & Speculative Decoding",
        "body": "Major release introducing chunked prefill, FP8 KV cache support, and improved multi-GPU scheduling.",
        "html_url": "https://github.com/vllm-project/vllm/releases/tag/v0.6.0",
        "published_at": "2026-08-18T14:30:00Z",
        "prerelease": False,
        "draft": False,
        "author": {"login": "vllm-bot"},
        "__repository": "vllm-project/vllm",
    }
    event = adapter.normalize(raw)
    assert event.id == "github:release:168920112"
    assert event.source == "github"
    assert event.source_type == "code_repository"
    assert event.event_type == "release"
    assert "Release v0.6.0 for vllm-project/vllm" in event.title
    assert event.metadata["repository"] == "vllm-project/vllm"
    assert event.metadata["tag_name"] == "v0.6.0"


def test_rss_xml_parsing_and_normalization():
    adapter = RssAdapter()
    rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Hugging Face Blog</title>
        <link>https://huggingface.co/blog</link>
        <item>
          <title>Introducing Fast Inference on Apple Silicon</title>
          <link>https://huggingface.co/blog/apple-silicon-fast</link>
          <description>&lt;p&gt;We are excited to announce new optimizations for MLX and Transformers.&lt;/p&gt;</description>
          <guid>https://huggingface.co/blog/apple-silicon-fast</guid>
          <pubDate>Mon, 18 Aug 2026 10:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    items = adapter._parse_feed_xml(rss_xml, "Hugging Face Blog", "https://huggingface.co/blog/feed.xml")
    assert len(items) == 1
    event = adapter.normalize(items[0])
    assert event.source == "rss"
    assert event.source_type == "technical_publication"
    assert event.event_type == "article"
    assert "<p>" not in event.text
    assert "MLX and Transformers" in event.text


def test_doi_and_identifier_helpers():
    assert normalize_doi("https://doi.org/10.1145/3620665.3640366") == "10.1145/3620665.3640366"
    assert normalize_doi("doi:10.1000/182") == "10.1000/182"
    assert normalize_doi("10.1234/INVALID ") == "10.1234/invalid"
    assert normalize_doi("not-a-doi") is None

    assert extract_doi("Published at https://doi.org/10.48550/arXiv.2307.08691") == "10.48550/arxiv.2307.08691"
    assert extract_hf_repo("https://huggingface.co/meta-llama/Llama-3-8B") == "huggingface:model:meta-llama/llama-3-8b"
    assert extract_hf_repo("https://huggingface.co/datasets/squad") == "huggingface:dataset:squad"
    assert extract_stackexchange_id("https://stackoverflow.com/questions/123456/title") == "stackexchange:stackoverflow:123456"


def test_scholarly_and_cross_source_relationships():
    # arXiv ↔ OpenAlex sharing same DOI
    ax = Event(
        id="arxiv:2307.08691",
        source="arxiv",
        source_type="research_paper",
        title="FlashAttention-2",
        url="https://arxiv.org/abs/2307.08691",
        doi="10.48550/arxiv.2307.08691",
    )
    oa = Event(
        id="openalex:w4389283748",
        source="openalex",
        source_type="scholarly_index",
        event_type="scholarly_work",
        title="FlashAttention-2 Work",
        url="https://openalex.org/W4389283748",
        doi="10.48550/arxiv.2307.08691",
    )
    match = match_direct_identifiers(ax, oa)
    assert match is not None
    rel_type, conf = match
    assert rel_type == "indexed_as"
    assert conf == 1.0

    # GitHub Repo ↔ GitHub Release
    gh_repo = Event(
        id="github:vllm-project/vllm",
        source="github",
        source_type="code_repository",
        event_type="repository",
        title="vLLM repository",
        url="https://github.com/vllm-project/vllm",
    )
    gh_rel = Event(
        id="github:release:12345",
        source="github",
        source_type="code_repository",
        event_type="release",
        title="Release v0.6.0 for vllm-project/vllm",
        url="https://github.com/vllm-project/vllm/releases/tag/v0.6.0",
        metadata={"repository": "vllm-project/vllm"},
    )
    match_rel = match_direct_identifiers(gh_repo, gh_rel)
    assert match_rel is not None
    assert match_rel[0] == "release_of"

    # HN ↔ GitHub
    hn = Event(
        id="hackernews:999",
        source="hackernews",
        source_type="discussion",
        title="Show HN: vLLM",
        url="https://github.com/vllm-project/vllm",
    )
    match_hn = match_direct_identifiers(hn, gh_repo)
    assert match_hn is not None
    assert match_hn[0] == "discussion_of"


def test_source_specific_popularity_and_trust():
    ev_crossref = Event(
        id="crossref:1", source="crossref", source_type="doi_registry", title="CR", url="https://doi.org/1"
    )
    ev_hf = Event(
        id="hf:1", source="huggingface", source_type="model_registry", title="HF", url="https://hf.co/1",
        metadata={"downloads": 10000, "likes": 500}
    )
    ev_se = Event(
        id="se:1", source="stackexchange", source_type="developer_community", title="SE", url="https://so.com/1",
        metadata={"score": 50, "answer_count": 8}
    )

    assert calculate_trust(ev_crossref) == 0.95
    assert calculate_trust(ev_hf) == 0.70
    assert calculate_trust(ev_se) == 0.65

    assert calculate_popularity(ev_hf) > 0.5
    assert calculate_popularity(ev_se) > 0.5
