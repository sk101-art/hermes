import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.inbox.generator import generate_daily_inbox
from app.models.schemas import DailyBriefing, DailyBriefingItem, InboxItem
from app.storage.db import Database


SECTION_HEADERS = {
    "must_know": "MUST KNOW",
    "project_relevant": "RELEVANT TO YOUR PROJECTS",
    "ai_ml": "AI / MACHINE LEARNING",
    "systems_compilers": "SYSTEMS / COMPILERS / ACCELERATION",
    "storage_databases": "STORAGE / DATABASES / VECTOR SEARCH",
    "developer_tooling": "DEVELOPER TOOLING",
    "research": "RESEARCH & BENCHMARKS",
    "corrections_updates": "WHAT CHANGED / CORRECTIONS",
    "watchlist": "WATCHLIST",
}


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

    # 1. Must Know
    must_know_items = grouped_items.get("must_know", [])
    if must_know_items:
        lines.append(f"\n{SECTION_HEADERS['must_know']}")
        lines.append("-" * 65)
        for idx, it in enumerate(must_know_items[:5], 1):
            cluster = db.get_cluster(it.story_cluster_id)
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
                top_ev = events[0]
                lines.append(f"    Source: [{top_ev.source.upper()}] {top_ev.url}")
            lines.append("")

    # 2. Project Relevant
    proj_items = grouped_items.get("project_relevant", [])
    if proj_items:
        lines.append(f"\n{SECTION_HEADERS['project_relevant']}")
        lines.append("-" * 65)

        # Group by project
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
            for idx, it in enumerate(pitems[:5], 1):
                events = db.get_cluster_events(it.story_cluster_id)
                claims = db.get_claims_by_cluster(it.story_cluster_id)
                lines.append(f"  {idx:02d}. [{it.inbox_score:.2f}] \"{it.title}\"")
                if claims:
                    lines.append(f"      Verification: {claims[0].status.upper()} ({claims[0].verification_score:.2f})")
                lines.append(f"      Why it matters: {', '.join(it.reason_codes[:4])}")
                if events:
                    lines.append(f"      Source: {events[0].url}")
                lines.append("")

    # 3. Domain Sections
    for sec_key in [
        "ai_ml",
        "systems_compilers",
        "storage_databases",
        "developer_tooling",
        "research",
        "corrections_updates",
        "watchlist",
    ]:
        sec_items = grouped_items.get(sec_key, [])
        if sec_items:
            header = SECTION_HEADERS.get(sec_key, sec_key.upper())
            lines.append(f"\n{header}")
            lines.append("-" * 65)
            for idx, it in enumerate(sec_items[:6], 1):
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
    Idempotent unless refresh=True.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if target_date is None:
        target_date = now.strftime("%Y-%m-%d")

    # 1. Check existing briefing
    existing = db.get_daily_briefing(target_date)
    if existing and not refresh:
        return existing

    # 2. Ensure today's inbox is generated
    inbox_items = generate_daily_inbox(db=db, now=now)
    if not inbox_items:
        inbox_items = db.get_active_inbox_items(include_expired=False)

    # 3. Group inbox items by section
    grouped: Dict[str, List[InboxItem]] = defaultdict(list)
    for it in inbox_items:
        grouped[it.section].append(it)

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
        total_items=len(inbox_items),
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
    for sec, it_list in grouped.items():
        for it in it_list:
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
