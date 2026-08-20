import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.schemas import InboxItem, SavedItem, UserFeedback
from app.storage.db import Database


def star_inbox_item(
    inbox_item_id: str,
    db: Database,
    now: Optional[datetime] = None,
) -> Optional[SavedItem]:
    """
    Idempotently stars an inbox item and creates/reactivates a persistent SavedItem
    with historical snapshot metrics.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    inbox_item = db.get_inbox_item(inbox_item_id)
    if not inbox_item:
        return None

    cluster_id = inbox_item.story_cluster_id
    cluster = db.get_cluster(cluster_id)
    if not cluster:
        return None

    # Check for existing SavedItem for this cluster
    existing_saved = db.get_saved_item_by_cluster(cluster_id)
    if existing_saved:
        if not existing_saved.is_active:
            existing_saved.is_active = True
            existing_saved.inbox_item_id = inbox_item.id
            db.save_saved_item(existing_saved)

        # Update inbox item
        inbox_item.is_starred = True
        inbox_item.state = "starred"
        inbox_item.saved_item_id = existing_saved.id
        db.save_inbox_item(inbox_item)

        # Log feedback
        fb_id = f"fb:star:{inbox_item_id}:{int(now.timestamp())}"
        db.save_user_feedback(
            UserFeedback(
                id=fb_id,
                entity_type="inbox_item",
                entity_id=inbox_item_id,
                action="star",
                value=cluster.canonical_title,
                created_at=now,
            )
        )
        return existing_saved

    # Fetch live intelligence to build initial save snapshot
    claims = db.get_claims_by_cluster(cluster_id)
    assessment = db.get_technology_assessment(cluster_id)
    tech_state = db.get_technology_state(cluster_id)
    matches = [m for m in db.get_all_project_matches() if m.entity_id == cluster_id]

    strongest_claim = claims[0] if claims else None
    v_score = strongest_claim.verification_score if strongest_claim else 0.50
    stage = assessment.maturity_stage if assessment else "concept"
    risk = tech_state.risk_score if tech_state else 0.25

    saved_id = f"saved:{cluster_id}"
    saved_item = SavedItem(
        id=saved_id,
        entity_type="cluster",
        entity_id=cluster_id,
        story_cluster_id=cluster_id,
        inbox_item_id=inbox_item.id,
        title_snapshot=cluster.canonical_title,
        saved_at=now,
        verification_snapshot=v_score,
        maturity_snapshot=stage,
        risk_snapshot=risk,
        project_ids=[m.project_id for m in matches],
        is_active=True,
        link_status="resolved",
        event_ids_snapshot=cluster.event_ids,
    )
    db.save_saved_item(saved_item)

    # Update inbox item
    inbox_item.is_starred = True
    inbox_item.state = "starred"
    inbox_item.saved_item_id = saved_id
    db.save_inbox_item(inbox_item)

    # Record feedback
    fb_id = f"fb:star:{inbox_item_id}:{int(now.timestamp())}"
    db.save_user_feedback(
        UserFeedback(
            id=fb_id,
            entity_type="inbox_item",
            entity_id=inbox_item_id,
            action="star",
            value=cluster.canonical_title,
            created_at=now,
        )
    )

    return saved_item


def unstar_inbox_item(
    inbox_item_id: str,
    db: Database,
    now: Optional[datetime] = None,
) -> bool:
    """
    Removes starred status from inbox item and marks SavedItem inactive
    (preserving historical save snapshots and notes).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    inbox_item = db.get_inbox_item(inbox_item_id)
    if not inbox_item:
        return False

    inbox_item.is_starred = False
    inbox_item.state = "seen"
    db.save_inbox_item(inbox_item)

    if inbox_item.saved_item_id:
        db.deactivate_saved_item(inbox_item.saved_item_id)

    # Record feedback
    fb_id = f"fb:unstar:{inbox_item_id}:{int(now.timestamp())}"
    db.save_user_feedback(
        UserFeedback(
            id=fb_id,
            entity_type="inbox_item",
            entity_id=inbox_item_id,
            action="unstar",
            created_at=now,
        )
    )
    return True


def open_inbox_item(
    inbox_item_id: str,
    db: Database,
    now: Optional[datetime] = None,
) -> Optional[InboxItem]:
    """
    Marks an inbox item as opened with timestamp and records user feedback.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    inbox_item = db.get_inbox_item(inbox_item_id)
    if not inbox_item:
        return None

    if inbox_item.state != "starred":
        inbox_item.state = "opened"
    inbox_item.opened_at = now
    db.save_inbox_item(inbox_item)

    fb_id = f"fb:open:{inbox_item_id}:{int(now.timestamp())}"
    db.save_user_feedback(
        UserFeedback(
            id=fb_id,
            entity_type="inbox_item",
            entity_id=inbox_item_id,
            action="open",
            created_at=now,
        )
    )
    return inbox_item


def mark_inbox_items_seen(
    inbox_item_ids: List[str],
    db: Database,
    now: Optional[datetime] = None,
) -> None:
    """
    Transitions unseen items to seen.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    for iid in inbox_item_ids:
        item = db.get_inbox_item(iid)
        if item and item.state == "unseen":
            item.state = "seen"
            item.seen_at = now
            db.save_inbox_item(item)


def cleanup_expired_inbox_items(
    db: Database,
    now: Optional[datetime] = None,
) -> int:
    """
    Transitions expired non-starred inbox items to state='expired'.
    Preserves all saved items and underlying intelligence.
    """
    return db.expire_old_inbox_items(now=now)


def add_saved_item_note(
    saved_id: str,
    note: str,
    db: Database,
    now: Optional[datetime] = None,
) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)

    ok = db.update_saved_item_note(saved_id, note)
    if ok:
        fb_id = f"fb:note:{saved_id}:{int(now.timestamp())}"
        db.save_user_feedback(
            UserFeedback(
                id=fb_id,
                entity_type="saved_item",
                entity_id=saved_id,
                action="note",
                value=note,
                created_at=now,
            )
        )
    return ok


def add_saved_item_tag(
    saved_id: str,
    tag: str,
    db: Database,
    now: Optional[datetime] = None,
) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)

    ok = db.add_saved_item_tag(saved_id, tag)
    if ok:
        fb_id = f"fb:tag:{saved_id}:{int(now.timestamp())}"
        db.save_user_feedback(
            UserFeedback(
                id=fb_id,
                entity_type="saved_item",
                entity_id=saved_id,
                action="tag",
                value=tag,
                created_at=now,
            )
        )
    return ok
