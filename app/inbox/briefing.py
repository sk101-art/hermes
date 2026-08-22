import hashlib
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.inbox.generator import extract_repository_identity, generate_daily_inbox, load_inbox_config
from app.models.schemas import DailyBriefing, DailyBriefingItem, InboxItem
from app.storage.db import Database


SECTION_HEADERS = {
    "corrections_updates": "WHAT CHANGED / CORRECTIONS",
    "must_know": "MUST KNOW",
    "project_relevant": "RELEVANT TO YOUR PROJECTS",
    "systems_compilers": "SYSTEMS / COMPILERS / ACCELERATION",
    "storage_databases": "STORAGE / DATABASES / VECTOR SEARCH",
    "research": "RESEARCH & BENCHMARKS",
    "ai_ml": "AI / MACHINE LEARNING",
    "developer_tooling": "DEVELOPER TOOLING",
    "watchlist": "WATCHLIST",
}

SECTION_ORDER = [
    "corrections_updates",
    "must_know",
    "project_relevant",
    "systems_compilers",
    "storage_databases",
    "research",
    "ai_ml",
    "developer_tooling",
    "watchlist",
]


def build_briefing_text(
    briefing_date: str,
    grouped_items: Dict[str, List[Any]],
    db: Optional[Database] = None,
) -> str:
    """
    Constructs deterministic, grounded morning briefing markdown directly from
    the stored snapshot items without issuing extra database queries or mislabeling priority.
    """
    lines = []
    lines.append("=" * 65)
    lines.append("HERMES — MORNING INTELLIGENCE BRIEFING")
    lines.append(f"Date: {briefing_date}")
    lines.append("=" * 65)

    # 1. Corrections / Updates
    corr_items = grouped_items.get("corrections_updates", [])
    if corr_items:
        lines.append(f"\n{SECTION_HEADERS['corrections_updates']}")
        lines.append("-" * 65)
        for idx, it in enumerate(corr_items, 1):
            score_str = f"[{it.inbox_score:.2f}]" if it.inbox_score is not None else "[Priority: unrated]"
            lines.append(f"{idx:02d}. {score_str} \"{it.title}\"")
            if it.item_type:
                lines.append(f"    Type: {it.item_type}")
            if it.reason_codes:
                lines.append(f"    Why included: {', '.join(it.reason_codes[:3])}")
            lines.append("")

    # 2. Must Know
    must_know_items = grouped_items.get("must_know", [])
    if must_know_items:
        lines.append(f"\n{SECTION_HEADERS['must_know']}")
        lines.append("-" * 65)
        for idx, it in enumerate(must_know_items, 1):
            score_str = f"[{it.inbox_score:.2f}]" if it.inbox_score is not None else "[Priority: unrated]"
            lines.append(f"{idx:02d}. {score_str} \"{it.title}\"")
            lines.append(f"    Priority: HIGH")
            if it.summary and it.summary != it.title:
                lines.append(f"    Summary: {it.summary}")
            if it.reason_codes:
                lines.append(f"    Why included: {', '.join(it.reason_codes[:4])}")
            lines.append("")

    # 3. Project Relevant
    proj_items = grouped_items.get("project_relevant", [])
    if proj_items:
        lines.append(f"\n{SECTION_HEADERS['project_relevant']}")
        lines.append("-" * 65)

        by_project = defaultdict(list)
        for it in proj_items:
            if it.matched_project_ids:
                for pid in it.matched_project_ids:
                    by_project[pid].append(it)
            else:
                by_project["general"].append(it)

        for pid, pitems in by_project.items():
            lines.append(f"\n  Project: {pid}")
            for idx, it in enumerate(pitems, 1):
                score_str = f"[{it.inbox_score:.2f}]" if it.inbox_score is not None else "[Priority: unrated]"
                lines.append(f"  {idx:02d}. {score_str} \"{it.title}\"")
                if it.project_impact_score is not None:
                    lines.append(f"      Project Impact: {it.project_impact_score:.2f}")
                if it.reason_codes:
                    lines.append(f"      Why included: {', '.join(it.reason_codes[:4])}")
                lines.append("")

    # 4. Domain & Watch Sections
    for sec_key in [
        "systems_compilers",
        "storage_databases",
        "research",
        "ai_ml",
        "developer_tooling",
        "watchlist",
    ]:
        sec_items = grouped_items.get(sec_key, [])
        if sec_items:
            header = SECTION_HEADERS.get(sec_key, sec_key.upper())
            lines.append(f"\n{header}")
            lines.append("-" * 65)
            for idx, it in enumerate(sec_items, 1):
                score_str = f"[{it.inbox_score:.2f}]" if it.inbox_score is not None else "[Priority: unrated]"
                lines.append(f"{idx:02d}. {score_str} \"{it.title}\"")
                if it.reason_codes:
                    lines.append(f"    Why included: {', '.join(it.reason_codes[:3])}")
                lines.append("")

    lines.append("=" * 65)
    return "\n".join(lines)


def export_briefing_markdown(
    briefing_date: str,
    text: str,
    export_dir: str = "data/briefings",
    filename: Optional[str] = None,
) -> str:
    """
    Safely exports morning briefing text to disk using a temporary file
    and atomic rename to prevent partial/corrupted writes.
    Canonical filename: data/briefings/{briefing_date}.md
    """
    os.makedirs(export_dir, exist_ok=True)
    fname = filename or f"{briefing_date}.md"
    target_file = Path(export_dir) / fname
    tmp_file = Path(export_dir) / f"{fname}.tmp.{os.getpid()}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_file, target_file)
        return str(target_file)
    finally:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass


def generate_morning_briefing(
    db: Database,
    target_date: Optional[str] = None,
    refresh: bool = False,
    now: Optional[datetime] = None,
) -> DailyBriefing:
    """
    Generates or retrieves the deterministic Daily Briefing for target_date.
    Idempotent unless refresh=True. Enforces strict section caps, score floors,
    repository diversity, and atomic persistence of immutable item snapshots.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if target_date is None:
        target_date = now.strftime("%Y-%m-%d")

    # 1. Check existing briefing
    existing = db.get_daily_briefing(target_date)
    if existing and not refresh:
        return existing

    cfg = load_inbox_config()
    b_cfg = cfg.get("briefing", {})
    min_brief_score = b_cfg.get("min_briefing_score", 0.55)
    max_total_items = b_cfg.get("max_items", 20)

    section_caps = {
        "corrections_updates": b_cfg.get("max_corrections", 4),
        "must_know": b_cfg.get("max_must_know", 5),
        "project_relevant": b_cfg.get("max_project_relevant", 6),
        "systems_compilers": b_cfg.get("max_systems", 4),
        "storage_databases": b_cfg.get("max_storage", 4),
        "research": b_cfg.get("max_research", 4),
        "ai_ml": b_cfg.get("max_ai_ml", 5),
        "developer_tooling": b_cfg.get("max_developer_tooling", 3),
        "watchlist": b_cfg.get("max_watch", 4),
    }

    # 2. Get active inbox items
    inbox_items = db.get_active_inbox_items(include_expired=False)
    if not inbox_items:
        inbox_items = generate_daily_inbox(db=db, now=now)

    # Filter by minimum briefing score or star
    qualifying_items = [
        it for it in inbox_items
        if (it.inbox_score is not None and it.inbox_score >= min_brief_score) or it.is_starred
    ]

    # Deterministic sorting:
    # 1. inbox_score DESC (None sorts last as -1.0 in-memory)
    # 2. project_impact_score DESC (None sorts last as -1.0 in-memory)
    # 3. id ASC for stable deterministic tie-breaking
    def item_sort_key(it: InboxItem) -> Tuple[float, float, str]:
        s = it.inbox_score if it.inbox_score is not None else -1.0
        p = it.project_impact_score if it.project_impact_score is not None else -1.0
        return (-s, -p, it.id)

    qualifying_items.sort(key=item_sort_key)

    # 3. Batch load cluster events for repository deduplication
    cluster_ids = [it.story_cluster_id for it in qualifying_items if it.story_cluster_id]
    events_by_cluster = db.get_cluster_events_batch(cluster_ids)

    # 4. Select balanced briefing items with repository deduplication
    grouped: Dict[str, List[InboxItem]] = defaultdict(list)
    selected_briefing_items: List[InboxItem] = []
    seen_briefing_repos: Set[str] = set()
    total_briefing_count = 0

    for it in qualifying_items:
        if total_briefing_count >= max_total_items:
            break

        sec = it.section or "ai_ml"
        sec_cap = section_caps.get(sec, 4)

        if len(grouped[sec]) >= sec_cap:
            continue

        events = events_by_cluster.get(it.story_cluster_id, [])
        repo_id = extract_repository_identity(events)

        # Skip duplicate minor releases from the same repository in the briefing
        if repo_id and repo_id in seen_briefing_repos and sec != "corrections_updates" and not it.is_starred:
            continue

        grouped[sec].append(it)
        selected_briefing_items.append(it)
        total_briefing_count += 1

        if repo_id:
            seen_briefing_repos.add(repo_id)

    # 5. Build snapshot items in canonical SECTION_ORDER
    briefing_id = f"briefing:{target_date}"
    briefing_items: List[DailyBriefingItem] = []
    grouped_snapshot_items: Dict[str, List[DailyBriefingItem]] = defaultdict(list)
    pos = 1

    for sec in SECTION_ORDER:
        for it in grouped.get(sec, []):
            dbi = DailyBriefingItem(
                briefing_id=briefing_id,
                inbox_item_id=it.id,
                position=pos,
                section=sec,
                title=it.title,
                summary=it.title,
                story_cluster_id=it.story_cluster_id,
                item_type=it.item_type,
                reason_codes=list(it.reason_codes) if it.reason_codes else [],
                inbox_score=it.inbox_score,
                rank_score=it.rank_score,
                project_impact_score=it.project_impact_score,
                matched_project_ids=list(it.matched_project_ids) if it.matched_project_ids else [],
                snapshot_version="v1",
            )
            briefing_items.append(dbi)
            grouped_snapshot_items[sec].append(dbi)
            pos += 1

    # Count high-priority & project-relevant
    high_priority_count = len(grouped.get("must_know", []))
    project_relevant_count = len(grouped.get("project_relevant", []))

    # 6. Build text directly from snapshot items
    summary_text = build_briefing_text(target_date, grouped_snapshot_items, db=db)

    # 7. Compute content hash
    content_hash = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()

    sections_dict = {sec: [it.inbox_item_id for it in it_list] for sec, it_list in grouped_snapshot_items.items()}

    briefing = DailyBriefing(
        id=briefing_id,
        briefing_date=target_date,
        generated_at=now,
        total_items=len(briefing_items),
        high_priority_count=high_priority_count,
        project_relevant_count=project_relevant_count,
        content_hash=content_hash,
        summary_text=summary_text,
        sections=sections_dict,
        created_at=existing.created_at if existing else now,
    )

    # 8. Atomically persist briefing header and snapshot items in a single transaction
    db.save_daily_briefing_with_items(briefing, briefing_items)
    return briefing
