import hashlib
from collections import defaultdict
from datetime import datetime, timezone
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
    grouped_items: Dict[str, List[InboxItem]],
    db: Database,
) -> str:
    """Constructs deterministic, grounded morning briefing markdown."""
    lines = []
    lines.append("=" * 65)
    lines.append(f"HERMES — MORNING INTELLIGENCE BRIEFING")
    lines.append(f"Date: {briefing_date}")
    lines.append("=" * 65)

    # 1. Corrections / Updates
    corr_items = grouped_items.get("corrections_updates", [])
    if corr_items:
        lines.append(f"\n{SECTION_HEADERS['corrections_updates']}")
        lines.append("-" * 65)
        for idx, it in enumerate(corr_items, 1):
            claims = db.get_claims_by_cluster(it.story_cluster_id)
            events = db.get_cluster_events(it.story_cluster_id)
            v_str = f"{claims[0].status.upper()} ({claims[0].verification_score:.2f})" if claims else "UNVERIFIED"
            lines.append(f"{idx:02d}. [{it.inbox_score:.2f}] \"{it.title}\"")
            lines.append(f"    Verification: {v_str}")
            if it.reason_codes:
                lines.append(f"    Why: {', '.join(it.reason_codes[:3])}")
            if events:
                lines.append(f"    Source: [{events[0].source.upper()}] {events[0].url}")
            lines.append("")

    # 2. Must Know
    must_know_items = grouped_items.get("must_know", [])
    if must_know_items:
        lines.append(f"\n{SECTION_HEADERS['must_know']}")
        lines.append("-" * 65)
        for idx, it in enumerate(must_know_items, 1):
            claims = db.get_claims_by_cluster(it.story_cluster_id)
            events = db.get_cluster_events(it.story_cluster_id)
            assessment = db.get_technology_assessment(it.story_cluster_id)
            mat_str = assessment.maturity_stage.upper() if assessment else "UNKNOWN"

            lines.append(f"{idx:02d}. [{it.inbox_score:.2f}] \"{it.title}\"")
            lines.append(f"    Maturity: {mat_str} | Priority: HIGH")
            if claims:
                strongest = claims[0]
                lines.append(f"    Claim: \"{strongest.claim_text}\" (Status: {strongest.status.upper()} | Score: {strongest.verification_score:.2f})")
            if it.reason_codes:
                lines.append(f"    Why it matters: {', '.join(it.reason_codes[:4])}")
            if events:
                lines.append(f"    Source: [{events[0].source.upper()}] {events[0].url}")
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
            proj = db.get_project(pid)
            pname = proj.name if proj else pid
            lines.append(f"\n  Project: {pname}")
            for idx, it in enumerate(pitems, 1):
                events = db.get_cluster_events(it.story_cluster_id)
                claims = db.get_claims_by_cluster(it.story_cluster_id)
                lines.append(f"  {idx:02d}. [{it.inbox_score:.2f}] \"{it.title}\"")
                if claims:
                    lines.append(f"      Verification: {claims[0].status.upper()} ({claims[0].verification_score:.2f})")
                lines.append(f"      Why it matters: {', '.join(it.reason_codes[:4])}")
                if events:
                    lines.append(f"      Source: {events[0].url}")
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
                events = db.get_cluster_events(it.story_cluster_id)
                claims = db.get_claims_by_cluster(it.story_cluster_id)
                lines.append(f"{idx:02d}. [{it.inbox_score:.2f}] \"{it.title}\"")
                if claims:
                    lines.append(f"    Verification: {claims[0].status.upper()} ({claims[0].verification_score:.2f})")
                if it.reason_codes:
                    lines.append(f"    Why: {', '.join(it.reason_codes[:3])}")
                if events:
                    lines.append(f"    Source: [{events[0].source.upper()}] {events[0].url}")
                lines.append("")

    lines.append("=" * 65)
    return "\n".join(lines)


def generate_morning_briefing(
    db: Database,
    target_date: Optional[str] = None,
    refresh: bool = False,
    now: Optional[datetime] = None,
) -> DailyBriefing:
    """
    Generates or retrieves the deterministic Daily Briefing for target_date.
    Idempotent unless refresh=True. Enforces strict section caps, score floors, and repository diversity.
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

    # Filter by minimum briefing score
    qualifying_items = [it for it in inbox_items if it.inbox_score >= min_brief_score or it.is_starred]
    # Sort by inbox score DESC, project impact DESC
    qualifying_items.sort(key=lambda it: (it.inbox_score, it.project_impact_score), reverse=True)

    # 3. Select balanced briefing items with repository deduplication
    grouped: Dict[str, List[InboxItem]] = defaultdict(list)
    selected_briefing_items: List[InboxItem] = []
    seen_briefing_repos: Set[str] = set()
    total_briefing_count = 0

    for it in qualifying_items:
        if total_briefing_count >= max_total_items:
            break

        sec = it.section
        sec_cap = section_caps.get(sec, 4)

        if len(grouped[sec]) >= sec_cap:
            continue

        events = db.get_cluster_events(it.story_cluster_id)
        repo_id = extract_repository_identity(events)

        # Skip duplicate minor releases from the same repository in the briefing
        if repo_id and repo_id in seen_briefing_repos and sec != "corrections_updates" and not it.is_starred:
            continue

        grouped[sec].append(it)
        selected_briefing_items.append(it)
        total_briefing_count += 1

        if repo_id:
            seen_briefing_repos.add(repo_id)

    # Count high-priority & project-relevant
    high_priority_count = len(grouped.get("must_know", []))
    project_relevant_count = len(grouped.get("project_relevant", []))

    # 4. Build text
    summary_text = build_briefing_text(target_date, grouped, db)

    # 5. Compute content hash
    content_hash = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()

    sections_dict = {sec: [it.id for it in it_list] for sec, it_list in grouped.items()}
    briefing_id = f"briefing:{target_date}"

    briefing = DailyBriefing(
        id=briefing_id,
        briefing_date=target_date,
        generated_at=now,
        total_items=len(selected_briefing_items),
        high_priority_count=high_priority_count,
        project_relevant_count=project_relevant_count,
        content_hash=content_hash,
        summary_text=summary_text,
        sections=sections_dict,
        created_at=existing.created_at if existing else now,
    )

    db.save_daily_briefing(briefing)

    # Save briefing items
    briefing_items = []
    pos = 1
    for sec in SECTION_ORDER:
        for it in grouped.get(sec, []):
            briefing_items.append(
                DailyBriefingItem(
                    briefing_id=briefing_id,
                    inbox_item_id=it.id,
                    position=pos,
                    section=sec,
                )
            )
            pos += 1

    db.save_daily_briefing_items(briefing_items)
    return briefing
