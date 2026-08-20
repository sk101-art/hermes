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


def extract_identifiers(event: Event) -> List[str]:
    """Extract all deterministic canonical identifiers for an Event."""
    identifiers = set()

    # From Event.id
    if event.id.startswith("github:"):
        gh_id = extract_github_repo(event.id.replace("github:", "https://github.com/"))
        if gh_id:
            identifiers.add(gh_id)
        else:
            clean_gh = re.sub(r"\.git$", "", event.id.lower().strip())
            identifiers.add(clean_gh)

    elif event.id.startswith("arxiv:"):
        clean_ax = re.sub(r"v[0-9]+$", "", event.id.lower().strip())
        identifiers.add(clean_ax)

    # From Event.url
    gh_id = extract_github_repo(event.url)
    if gh_id:
        identifiers.add(gh_id)
    ax_id = extract_arxiv_id(event.url)
    if ax_id:
        identifiers.add(ax_id)

    # From metadata external_url
    ext_url = event.metadata.get("external_url")
    if ext_url:
        gh_ext = extract_github_repo(ext_url)
        if gh_ext:
            identifiers.add(gh_ext)
        ax_ext = extract_arxiv_id(ext_url)
        if ax_ext:
            identifiers.add(ax_ext)

    # From title / text if they mention explicit links
    text_content = f"{event.title} {event.text}"
    gh_in_text = extract_github_repo(text_content)
    if gh_in_text:
        identifiers.add(gh_in_text)
    ax_in_text = extract_arxiv_id(text_content)
    if ax_in_text:
        identifiers.add(ax_in_text)

    # Filter out empty or broken short strings
    valid_identifiers = {i for i in identifiers if len(i) >= 6 and (i.startswith("github:") or i.startswith("arxiv:"))}
    return list(valid_identifiers)


def match_direct_identifiers(event1: Event, event2: Event) -> Optional[Tuple[str, float]]:
    """Check for high-confidence deterministic direct identifier matching."""
    ids1 = set(extract_identifiers(event1))
    ids2 = set(extract_identifiers(event2))

    common = ids1.intersection(ids2)
    if common:
        # If one is a discussion (e.g. Hacker News) and other is repo/paper
        if event1.source_type == "discussion" or event2.source_type == "discussion":
            return "discusses", 0.98
        elif {event1.source_type, event2.source_type} == {"research_paper", "code_repository"}:
            return "possible_implementation", 0.95
        return "same_story", 1.0

    return None
