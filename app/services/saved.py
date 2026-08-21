import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.models.schemas import SavedItem, UserFeedback
from app.storage.db import Database


def get_saved_items(
    limit: int = 20,
    offset: int = 0,
    tag: Optional[str] = None,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Retrieves saved items with pagination and tag filter."""
    if db is None:
        db = Database()

    limit = max(1, min(limit, 50))
    offset = max(0, offset)

    all_saved = db.get_all_saved_items(active_only=True)
    if tag:
        tag_clean = tag.lower().strip()
        all_saved = [s for s in all_saved if any(tag_clean == t.lower() for t in s.tags)]

    paginated = all_saved[offset : offset + limit]
    out = []
    for s in paginated:
        out.append({
            "id": s.id,
            "inbox_item_id": s.inbox_item_id,
            "story_cluster_id": s.story_cluster_id,
            "title": s.title_snapshot,
            "verification_score": round(s.verification_snapshot, 4) if s.verification_snapshot is not None else None,
            "maturity_stage": s.maturity_snapshot,
            "risk_score": round(s.risk_snapshot, 4) if s.risk_snapshot is not None else None,
            "tags": list(s.tags),
            "user_note": s.user_note,
            "project_ids": list(s.project_ids),
            "saved_at": s.saved_at.isoformat(),
        })
    return out


def get_saved_item(saved_id: str, db: Optional[Database] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a specific saved item with complete snapshot and notes."""
    if db is None:
        db = Database()

    if not saved_id:
        return None

    s = db.get_saved_item(saved_id.strip())
    if not s:
        # Also try matching by inbox_item_id or story_cluster_id
        all_saved = db.get_all_saved_items(active_only=True)
        for cand in all_saved:
            if cand.inbox_item_id == saved_id.strip() or cand.story_cluster_id == saved_id.strip():
                s = cand
                break

    if not s:
        return None

    return {
        "id": s.id,
        "entity_type": s.entity_type,
        "entity_id": s.entity_id,
        "story_cluster_id": s.story_cluster_id,
        "inbox_item_id": s.inbox_item_id,
        "title": s.title_snapshot,
        "verification_score": round(s.verification_snapshot, 4) if s.verification_snapshot is not None else None,
        "maturity_stage": s.maturity_snapshot,
        "risk_score": round(s.risk_snapshot, 4) if s.risk_snapshot is not None else None,
        "user_note": s.user_note,
        "tags": list(s.tags),
        "project_ids": list(s.project_ids),
        "saved_at": s.saved_at.isoformat(),
    }


def star_inbox_item(
    inbox_item_id: str,
    db: Optional[Database] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Safely stars an inbox item and creates a SavedItem snapshot with truthful intelligence values.
    Idempotent: calling multiple times will not duplicate records.
    """
    if db is None:
        db = Database()

    if not inbox_item_id:
        return False, "Invalid or missing inbox_item_id", None

    item_id_clean = inbox_item_id.strip()
    item = db.get_inbox_item(item_id_clean)
    if not item:
        return False, f"Inbox item '{item_id_clean}' not found", None

    now = datetime.now(timezone.utc)

    # 1. Update inbox item starred state
    item.is_starred = True
    item.state = "starred"
    db.save_inbox_item(item)

    # 2. Check if already in saved library
    saved_id = f"saved:{item.story_cluster_id}"
    existing_saved = db.get_saved_item(saved_id)

    if existing_saved:
        return True, "Item is already starred and saved in library", get_saved_item(saved_id, db)

    # 3. Create persistent SavedItem snapshot with genuine intelligence values
    assessment = db.get_technology_assessment(item.story_cluster_id)
    tech_state = db.get_technology_state(item.story_cluster_id)
    claims = db.get_claims_by_cluster(item.story_cluster_id, current_only=True)
    claim_scores = [c.verification_score for c in claims]
    v_snap = float(sum(claim_scores) / len(claim_scores)) if claim_scores else None
    m_snap = assessment.maturity_stage if assessment else None
    r_snap = tech_state.risk_score if tech_state else None

    new_saved = SavedItem(
        id=saved_id,
        entity_type="cluster",
        entity_id=item.story_cluster_id,
        story_cluster_id=item.story_cluster_id,
        inbox_item_id=item.id,
        title_snapshot=item.title,
        saved_at=now,
        verification_snapshot=v_snap,
        maturity_snapshot=m_snap,
        risk_snapshot=r_snap,
        user_note=None,
        tags=["starred"],
        project_ids=list(item.matched_project_ids),
        is_active=True,
        link_status="resolved",
        event_ids_snapshot=[],
    )
    db.save_saved_item(new_saved)

    # Record feedback audit
    fb = UserFeedback(
        id=f"fb:star:{int(now.timestamp() * 1000)}",
        entity_type="inbox_item",
        entity_id=item.id,
        action="star",
        value=None,
        created_at=now,
    )
    db.save_user_feedback(fb)

    return True, "Item starred and saved successfully", get_saved_item(saved_id, db)


def unstar_inbox_item(
    inbox_item_id: str,
    db: Optional[Database] = None,
) -> Tuple[bool, str]:
    """Unstars an inbox item without deleting its historical saved record."""
    if db is None:
        db = Database()

    if not inbox_item_id:
        return False, "Invalid or missing inbox_item_id"

    item = db.get_inbox_item(inbox_item_id.strip())
    if not item:
        return False, f"Inbox item '{inbox_item_id}' not found"

    item.is_starred = False
    if item.state == "starred":
        item.state = "seen"
    db.save_inbox_item(item)
    return True, f"Item '{item.id}' unstarred successfully"


def add_saved_note(
    saved_id: str,
    note_text: str,
    db: Optional[Database] = None,
) -> Tuple[bool, str]:
    """Appends/updates a user note on a SavedItem with strict length validation."""
    if db is None:
        db = Database()

    if not saved_id or not note_text:
        return False, "saved_id and note_text are required"

    if len(note_text) > 2000:
        return False, "Note text exceeds maximum length of 2000 characters"

    s = db.get_saved_item(saved_id.strip())
    if not s:
        return False, f"Saved item '{saved_id}' not found"

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    clean_note = note_text.strip()
    if s.user_note:
        updated_note = f"{s.user_note}\n[{now_str}] {clean_note}"
    else:
        updated_note = f"[{now_str}] {clean_note}"

    db.update_saved_item_note(s.id, updated_note)

    # Record feedback audit
    fb = UserFeedback(
        id=f"fb:note:{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        entity_type="saved_item",
        entity_id=s.id,
        action="note",
        value=clean_note[:200],
        created_at=datetime.now(timezone.utc),
    )
    db.save_user_feedback(fb)

    return True, f"Note added to saved item '{saved_id}'"


def add_saved_tag(
    saved_id: str,
    tag: str,
    db: Optional[Database] = None,
) -> Tuple[bool, str]:
    """Adds a tag to a SavedItem."""
    if db is None:
        db = Database()

    if not saved_id or not tag:
        return False, "saved_id and tag are required"

    clean_tag = re.sub(r"[^a-zA-Z0-9_\-]", "", tag.strip().lower())
    if not clean_tag or len(clean_tag) > 50:
        return False, "Tag must be alphanumeric between 1 and 50 characters"

    s = db.get_saved_item(saved_id.strip())
    if not s:
        return False, f"Saved item '{saved_id}' not found"

    db.add_saved_item_tag(s.id, clean_tag)

    fb = UserFeedback(
        id=f"fb:tag:{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        entity_type="saved_item",
        entity_id=s.id,
        action="tag",
        value=clean_tag,
        created_at=datetime.now(timezone.utc),
    )
    db.save_user_feedback(fb)

    return True, f"Tag '{clean_tag}' added to saved item '{saved_id}'"


def record_feedback(
    inbox_item_id: str,
    is_useful: Optional[bool] = None,
    action: str = "useful",
    value: Optional[str] = None,
    db: Optional[Database] = None,
) -> Tuple[bool, str]:
    """Records explicit user feedback on an intelligence item."""
    if db is None:
        db = Database()

    if not inbox_item_id:
        return False, "inbox_item_id is required"

    item = db.get_inbox_item(inbox_item_id.strip())
    if not item:
        return False, f"Inbox item '{inbox_item_id}' not found"

    if value and len(value) > 2000:
        return False, "Feedback text exceeds maximum length of 2000 characters"

    now = datetime.now(timezone.utc)
    fb_id = f"fb:{item.id}:{int(now.timestamp() * 1000)}"

    fb = UserFeedback(
        id=fb_id,
        entity_type="inbox_item",
        entity_id=item.id,
        action="useful" if is_useful is True else ("not_useful" if is_useful is False else action),
        value=value.strip() if value else None,
        created_at=now,
    )
    db.save_user_feedback(fb)
    return True, "Feedback recorded successfully"
