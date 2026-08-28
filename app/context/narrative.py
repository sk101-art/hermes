"""Structured README/documentation narrative extraction.

HERMES previously reduced a project's documentation to a single line ("first
non-heading README line > 5 chars"). That is not enough to answer "what does
this project do?" on the project page.

This module deterministically extracts a structured narrative from README and
documentation files:

- purpose_summary: what the project is for
- capability_summaries: what it can do
- architecture_summary: how it is structured (if documented)
- primary_components: main modules/parts
- evidence_references: pointers like "README.md:12"

Rules (from the explanation-upgrade spec):
- Skip badges, image-only lines, headings, TOC/link lists, and install
  commands.
- Never synthesize descriptions that are not grounded in the documentation.
- Persist independently from technology tags.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from app.models.schemas import EvidenceReference, ProjectFile, ProjectNarrative

NARRATIVE_VERSION = "1"

# Documentation files considered for narrative extraction, in priority order.
DOC_FILENAMES = (
    "readme.md",
    "readme.rst",
    "readme.txt",
    "readme",
    "docs/overview.md",
    "docs/architecture.md",
    "docs/readme.md",
    "about.md",
)

# Lines that are never narrative content.
_BADGE_RE = re.compile(
    r"^\s*\[!\[", re.IGNORECASE
)  # [![Build](...)](...) badge pattern
_IMAGE_ONLY_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_HTML_TAG_RE = re.compile(r"^\s*<[^>]+>\s*$")
_TOC_LINK_RE = re.compile(r"^\s*[-*]?\s*\[[^\]]+\]\(#[^)]*\)\s*$")
_INSTALL_CMD_RE = re.compile(
    r"^\s*(\$\s+)?(pip|pip3|npm|npx|yarn|pnpm|cargo|go|apt|apt-get|brew|conda|uv|poetry|docker|make|git)\s+(install|add|i|get|clone|run|build|pull)\b",
    re.IGNORECASE,
)
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")

# Section headings that indicate architecture/component content.
_ARCH_HEADINGS = re.compile(
    r"architect|structure|design|how it works|internals|overview of the (code|system)|system design",
    re.IGNORECASE,
)
_COMPONENT_HEADINGS = re.compile(
    r"component|module|package|directory structure|project structure|folder structure|layout",
    re.IGNORECASE,
)
_FEATURE_HEADINGS = re.compile(
    r"feature|capabilit|what it does|highlights|supports",
    re.IGNORECASE,
)
_SKIP_HEADINGS = re.compile(
    r"install|setup|getting started|quick start|usage|example|contributing|license|changelog|faq|acknowledg|badge|table of contents|toc\b",
    re.IGNORECASE,
)


def _clean_inline(text: str) -> str:
    """Strip markdown inline formatting down to plain text."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links -> label
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"<[^>]+>", "", text)  # html tags
    return re.sub(r"\s+", " ", text).strip()


def _is_narrative_line(line: str) -> bool:
    """True if a line can contribute narrative text."""
    if not line.strip():
        return False
    if _BADGE_RE.match(line) or _IMAGE_ONLY_RE.match(line) or _HTML_TAG_RE.match(line):
        return False
    if _TOC_LINK_RE.match(line):
        return False
    if _INSTALL_CMD_RE.match(line):
        return False
    if _CODE_FENCE_RE.match(line):
        return False
    return True


def _iter_doc_lines(content: str):
    """Yield (line_number, line) skipping fenced code blocks."""
    in_fence = False
    for idx, raw in enumerate(content.splitlines(), start=1):
        if _CODE_FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield idx, raw


def extract_narrative_from_docs(
    files: List[ProjectFile],
    user_description: Optional[str] = None,
) -> ProjectNarrative:
    """Build a ProjectNarrative from a project's indexed files.

    Deterministic and evidence-grounded: every extracted sentence is traced
    back to a file:line reference. Nothing is invented.
    """
    now = datetime.now(timezone.utc)

    # Pick documentation files in priority order.
    docs: List[Tuple[str, str]] = []  # (relative_path, content)
    by_name = {}
    for pf in files:
        rel_lower = pf.relative_path.replace("\\", "/").lower()
        name_lower = Path(pf.relative_path).name.lower()
        by_name.setdefault(rel_lower, pf)
        by_name.setdefault(name_lower, pf)
    for candidate in DOC_FILENAMES:
        pf = by_name.get(candidate)
        if pf is not None and (pf.extracted_text or "").strip():
            docs.append((pf.relative_path, pf.extracted_text))
    # Fallback: any other .md file at repo root.
    if not docs:
        for pf in files:
            rel = pf.relative_path.replace("\\", "/")
            if rel.endswith(".md") and "/" not in rel and (pf.extracted_text or "").strip():
                docs.append((pf.relative_path, pf.extracted_text))
                if len(docs) >= 2:
                    break

    if not docs:
        return ProjectNarrative(
            user_description=user_description,
            extraction_status="unavailable",
            extracted_at=now,
            narrative_version=NARRATIVE_VERSION,
        )

    purpose_summary: Optional[str] = None
    purpose_ref: Optional[EvidenceReference] = None
    capability_summaries: List[str] = []
    capability_refs: List[EvidenceReference] = []
    architecture_summary: Optional[str] = None
    architecture_ref: Optional[EvidenceReference] = None
    primary_components: List[str] = []
    component_refs: List[EvidenceReference] = []
    all_refs: List[EvidenceReference] = []

    current_section: Optional[str] = None

    def add_ref(rel_path: str, line_no: int, detail: str) -> EvidenceReference:
        ref = EvidenceReference(
            label=f"{rel_path}:{line_no}",
            kind="file",
            detail=detail[:120],
        )
        all_refs.append(ref)
        return ref

    for rel_path, content in docs:
        for line_no, raw in _iter_doc_lines(content):
            heading = _HEADING_RE.match(raw)
            if heading:
                current_section = heading.group(2).strip()
                continue

            if not _is_narrative_line(raw):
                continue

            bullet = _BULLET_RE.match(raw) or _NUMBERED_RE.match(raw) or _BLOCKQUOTE_RE.match(raw)
            text = _clean_inline(bullet.group(1) if bullet else raw)
            if len(text) < 10:
                continue

            section = current_section or ""

            # Architecture / component sections
            if _ARCH_HEADINGS.search(section) and architecture_summary is None and not bullet:
                architecture_summary = text[:300]
                architecture_ref = add_ref(rel_path, line_no, text)
                continue
            if _COMPONENT_HEADINGS.search(section) and bullet:
                if len(primary_components) < 8 and text not in primary_components:
                    primary_components.append(text[:120])
                    component_refs.append(add_ref(rel_path, line_no, text))
                continue
            if _SKIP_HEADINGS.search(section):
                continue

            # Feature bullets become capability summaries
            if bullet and _FEATURE_HEADINGS.search(section):
                if len(capability_summaries) < 6 and text not in capability_summaries:
                    capability_summaries.append(text[:200])
                    capability_refs.append(add_ref(rel_path, line_no, text))
                continue

            # First substantive prose paragraph = purpose summary
            if purpose_summary is None and not bullet:
                purpose_summary = text[:300]
                purpose_ref = add_ref(rel_path, line_no, text)
                continue

            # Additional prose in feature-ish sections -> capabilities
            if bullet and len(capability_summaries) < 6 and text not in capability_summaries:
                capability_summaries.append(text[:200])
                capability_refs.append(add_ref(rel_path, line_no, text))

    status = "extracted" if purpose_summary else "partial"
    if not purpose_summary and not capability_summaries and not architecture_summary:
        status = "unavailable"

    refs = []
    if purpose_ref:
        refs.append(purpose_ref)
    refs.extend(capability_refs[:6])
    if architecture_ref:
        refs.append(architecture_ref)
    refs.extend(component_refs[:8])
    # De-duplicate while preserving order.
    seen = set()
    unique_refs = []
    for r in refs:
        if r.label not in seen:
            seen.add(r.label)
            unique_refs.append(r)

    return ProjectNarrative(
        user_description=user_description,
        purpose_summary=purpose_summary,
        capability_summaries=capability_summaries,
        architecture_summary=architecture_summary,
        primary_components=primary_components,
        evidence_references=unique_refs[:16],
        extraction_status=status,
        extracted_at=now,
        narrative_version=NARRATIVE_VERSION,
    )
