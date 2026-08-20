import re
from typing import List, Optional, Tuple
import numpy as np

from app.models.schemas import Event


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Compute cosine similarity between two float32 vectors."""
    if vec1 is None or vec2 is None or len(vec1) == 0 or len(vec2) == 0:
        return 0.0

    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    sim = float(np.dot(vec1, vec2) / (norm1 * norm2))
    return max(-1.0, min(1.0, sim))


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Normalize any DOI string or URL to canonical 10.xxxx/... format."""
    if not doi:
        return None

    clean = doi.strip()
    clean = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^doi:\s*", "", clean, flags=re.IGNORECASE)
    clean = clean.strip().rstrip(".").lower()

    if re.match(r"^10\.[0-9]{4,9}/[^\s]+$", clean):
        return clean
    return None


def extract_doi(text: Optional[str]) -> Optional[str]:
    """Extract a normalized DOI from free text or URLs."""
    if not text:
        return None
    match = re.search(r"\b(10\.[0-9]{4,9}/[-._;()/:a-zA-Z0-9]+)\b", text)
    if match:
        return normalize_doi(match.group(1))
    return None


def extract_github_repo(url: Optional[str]) -> Optional[str]:
    """Extract canonical github:owner/repo identifier from any GitHub URL or text."""
    if not url:
        return None

    match = re.search(r"github\.com[:/]([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)", url, re.IGNORECASE)
    if match:
        owner = match.group(1).lower().strip()
        repo = match.group(2).lower().strip()

        if repo.endswith(".git"):
            repo = repo[:-4]

        repo = re.sub(r"[/#\?].*$", "", repo)

        ignored_owners = {
            "topics", "orgs", "collections", "search", "trending",
            "settings", "marketplace", "explore", "features", "about",
            "pricing", "security", "customer-stories", "login", "signup"
        }
        if owner in ignored_owners or not repo:
            return None

        return f"github:{owner}/{repo}"

    return None


def extract_arxiv_id(url: Optional[str]) -> Optional[str]:
    """Extract canonical arxiv:id identifier from any arXiv URL or text."""
    if not url:
        return None

    match = re.search(
        r"arxiv\.org/(?:abs|pdf|html|ps)/([0-9]{4}\.[0-9]{4,5}|[a-zA-Z\-]+/[0-9]{7})(?:v[0-9]+)?(?:\.pdf)?",
        url,
        re.IGNORECASE,
    )
    if match:
        base_id = match.group(1).lower().strip()
        return f"arxiv:{base_id}"

    direct_match = re.search(r"arxiv:([0-9]{4}\.[0-9]{4,5}|[a-zA-Z\-]+/[0-9]{7})", url, re.IGNORECASE)
    if direct_match:
        return f"arxiv:{direct_match.group(1).lower().strip()}"

    return None


def extract_hf_repo(text_or_url: Optional[str]) -> Optional[str]:
    """Extract canonical Hugging Face repository identifier (e.g. huggingface:model:owner/name)."""
    if not text_or_url:
        return None

    ds_match = re.search(r"huggingface\.co/datasets/([a-zA-Z0-9_\-\./]+)", text_or_url, re.IGNORECASE)
    if ds_match:
        ds_id = ds_match.group(1).lower().strip().rstrip("/")
        return f"huggingface:dataset:{ds_id}"

    model_match = re.search(r"huggingface\.co/([a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+)", text_or_url, re.IGNORECASE)
    if model_match:
        ignored = {"datasets", "spaces", "docs", "blog", "pricing", "models", "join", "login"}
        parts = model_match.group(1).split("/")
        if parts[0].lower() not in ignored:
            return f"huggingface:model:{model_match.group(1).lower().strip()}"

    return None


def extract_stackexchange_id(text_or_url: Optional[str]) -> Optional[str]:
    """Extract canonical Stack Exchange question identifier."""
    if not text_or_url:
        return None

    match = re.search(r"(?:https?://)?(?:www\.)?(stackoverflow|serverfault|superuser|askubuntu|dba|[a-z]+)\.(?:com|stackexchange\.com)/questions/([0-9]+)", text_or_url, re.IGNORECASE)
    if match:
        site = match.group(1).lower()
        qid = match.group(2)
        return f"stackexchange:{site}:{qid}"

    return None


def extract_identifiers(event: Event) -> List[str]:
    """Extract all deterministic canonical identifiers for an Event."""
    identifiers = set()

    eid = event.id.lower().strip()
    if eid.startswith("github:"):
        if eid.startswith("github:release:"):
            repo = event.metadata.get("repository")
            if repo:
                identifiers.add(f"github:{repo.lower().strip()}")
            identifiers.add(eid)
        else:
            gh_id = extract_github_repo(event.id.replace("github:", "https://github.com/"))
            if gh_id:
                identifiers.add(gh_id)
            else:
                identifiers.add(re.sub(r"\.git$", "", eid))

    elif eid.startswith("arxiv:"):
        clean_ax = re.sub(r"v[0-9]+$", "", eid)
        identifiers.add(clean_ax)

    elif eid.startswith("openalex:"):
        identifiers.add(eid)

    elif eid.startswith("crossref:"):
        norm = normalize_doi(eid.replace("crossref:", ""))
        if norm:
            identifiers.add(f"doi:{norm}")
        identifiers.add(eid)

    elif eid.startswith("huggingface:"):
        identifiers.add(eid)

    elif eid.startswith("stackexchange:"):
        identifiers.add(eid)

    # From explicit event.doi attribute
    if event.doi:
        norm_d = normalize_doi(event.doi)
        if norm_d:
            identifiers.add(f"doi:{norm_d}")

    # From metadata DOI / OpenAlex / Arxiv / GitHub
    if event.metadata:
        m_doi = normalize_doi(event.metadata.get("doi"))
        if m_doi:
            identifiers.add(f"doi:{m_doi}")
        m_repo = event.metadata.get("repo_id") or event.metadata.get("repository")
        if m_repo and ("/" in m_repo):
            identifiers.add(f"github:{m_repo.lower().strip()}")
            identifiers.add(f"huggingface:model:{m_repo.lower().strip()}")

    # From Event.url
    gh_id = extract_github_repo(event.url)
    if gh_id:
        identifiers.add(gh_id)
    ax_id = extract_arxiv_id(event.url)
    if ax_id:
        identifiers.add(ax_id)
    doi_id = extract_doi(event.url)
    if doi_id:
        identifiers.add(f"doi:{doi_id}")
    hf_id = extract_hf_repo(event.url)
    if hf_id:
        identifiers.add(hf_id)
    se_id = extract_stackexchange_id(event.url)
    if se_id:
        identifiers.add(se_id)

    # From metadata external_url
    ext_url = event.metadata.get("external_url")
    if ext_url:
        gh_ext = extract_github_repo(ext_url)
        if gh_ext:
            identifiers.add(gh_ext)
        ax_ext = extract_arxiv_id(ext_url)
        if ax_ext:
            identifiers.add(ax_ext)
        doi_ext = extract_doi(ext_url)
        if doi_ext:
            identifiers.add(f"doi:{doi_ext}")
        hf_ext = extract_hf_repo(ext_url)
        if hf_ext:
            identifiers.add(hf_ext)

    # From text content
    text_content = f"{event.title} {event.text}"
    gh_txt = extract_github_repo(text_content)
    if gh_txt:
        identifiers.add(gh_txt)
    ax_txt = extract_arxiv_id(text_content)
    if ax_txt:
        identifiers.add(ax_txt)
    doi_txt = extract_doi(text_content)
    if doi_txt:
        identifiers.add(f"doi:{doi_txt}")
    hf_txt = extract_hf_repo(text_content)
    if hf_txt:
        identifiers.add(hf_txt)

    valid_identifiers = {
        i for i in identifiers
        if len(i) >= 6 and any(i.startswith(p) for p in [
            "github:", "arxiv:", "doi:", "openalex:", "crossref:", "huggingface:", "stackexchange:"
        ])
    }
    return list(valid_identifiers)


def match_direct_identifiers(event1: Event, event2: Event) -> Optional[Tuple[str, float]]:
    """Check for deterministic direct cross-source and artifact identifier matching."""
    ids1 = set(extract_identifiers(event1))
    ids2 = set(extract_identifiers(event2))

    common = ids1.intersection(ids2)
    if not common:
        return None

    # 1. Scholarly Identity Matching (DOI / arXiv ID across arXiv, OpenAlex, Crossref)
    scholarly_sources = {"arxiv", "openalex", "crossref"}
    if event1.source in scholarly_sources and event2.source in scholarly_sources:
        if any(c.startswith("doi:") or c.startswith("arxiv:") for c in common):
            if {event1.source, event2.source} == {"arxiv", "openalex"}:
                return "indexed_as", 1.0
            elif {event1.source, event2.source} == {"openalex", "crossref"}:
                return "same_work", 1.0
            elif {event1.source, event2.source} == {"arxiv", "crossref"}:
                return "published_version", 1.0
            return "same_work", 1.0

    # 2. GitHub Release to Repository linking
    if event1.source == "github" and event2.source == "github":
        if {event1.event_type, event2.event_type} == {"release", "repository"}:
            return "release_of", 1.0

    # 3. Discussion to Code/Paper linking (Hacker News or Stack Exchange -> GitHub/arXiv)
    if event1.source_type == "discussion" or event2.source_type == "discussion":
        return "discussion_of", 0.98

    if event1.source_type == "developer_community" or event2.source_type == "developer_community":
        return "discussion_of", 0.95

    # 4. GitHub to Hugging Face Model registry linking
    if {event1.source, event2.source} == {"github", "huggingface"}:
        return "hosts_model_for", 0.95

    # 5. Paper to Code repository linking (arXiv -> GitHub)
    if {event1.source_type, event2.source_type} == {"research_paper", "code_repository"}:
        return "possible_implementation", 0.95

    return "same_story", 1.0
