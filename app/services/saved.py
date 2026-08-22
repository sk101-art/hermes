import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from app.models.schemas import Claim, SavedItem, StoryCluster, TechnologyAssessment, TechnologyState, UserFeedback
from app.services.intelligence import aggregate_cluster_claim_status
from app.services.schemas import CurrentIntelligenceState, SavedItemDetail
from app.storage.db import Database


def get_saved_items(
    limit: int = 20,
    offset: int = 0,
    tag: Optional[str] = None,
    include_current: bool = False,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves saved items with pagination and tag filter.
    When include_current=True, performs efficient batch hydration of current intelligence state
    without N+1 database queries.
    """
    if db is None:
        db = Database()

    limit = max(1, min(limit, 50))
    offset = max(0, offset)

    all_saved = db.get_all_saved_items(active_only=True)
    if tag:
        tag_clean = tag.lower().strip()
        all_saved = [s for s in all_saved if any(tag_clean == t.lower() for t in s.tags)]

    paginated = all_saved[offset : offset + limit]

    current_states_by_cluster: Dict[str, Dict[str, Any]] = {}
    if include_current and paginated:
        cluster_ids = list({s.story_cluster_id for s in paginated if s.story_cluster_id})
        if cluster_ids:
            placeholders = ",".join("?" for _ in cluster_ids)
            cursor = db.conn.cursor()

            # 1. Batch fetch clusters
            cursor.execute(f"SELECT * FROM story_clusters WHERE id IN ({placeholders})", cluster_ids)
            cluster_map = {
                r["id"]: StoryCluster(
                    id=r["id"],
                    canonical_title=r["canonical_title"],
                    cluster_score=r["cluster_score"] or 0.0,
                    created_at=datetime.fromisoformat(r["created_at"]),
                    updated_at=datetime.fromisoformat(r["updated_at"]),
                )
                for r in cursor.fetchall()
            }

            # 2. Batch fetch current claims
            cursor.execute(
                f"SELECT * FROM claims WHERE cluster_id IN ({placeholders}) AND is_current = 1",
                cluster_ids,
            )
            claims_map: Dict[str, List[Claim]] = {cid: [] for cid in cluster_ids}
            for r in cursor.fetchall():
                c = db._row_to_claim(r)
                claims_map.setdefault(c.cluster_id, []).append(c)

            # 3. Batch fetch assessments
            cursor.execute(
                f"SELECT * FROM technology_assessments WHERE cluster_id IN ({placeholders})",
                cluster_ids,
            )
            assess_map: Dict[str, TechnologyAssessment] = {}
            for r in cursor.fetchall():
                a = TechnologyAssessment(
                    cluster_id=r["cluster_id"],
                    maturity_stage=r["maturity_stage"],
                    research_score=r["research_score"] or 0.0,
                    implementation_score=r["implementation_score"] or 0.0,
                    adoption_score=r["adoption_score"] or 0.0,
                    reproducibility_score=r["reproducibility_score"] or 0.0,
                    community_score=r["community_score"] or 0.0,
                    assessment_score=r["assessment_score"] or 0.0,
                    updated_at=datetime.fromisoformat(r["updated_at"]),
                )
                assess_map[a.cluster_id] = a

            # 4. Batch fetch technology states
            cursor.execute(
                f"SELECT * FROM technology_states WHERE cluster_id IN ({placeholders})",
                cluster_ids,
            )
            tech_state_map: Dict[str, TechnologyState] = {}
            for r in cursor.fetchall():
                ts = TechnologyState(
                    cluster_id=r["cluster_id"],
                    current_status=r["current_status"],
                    latest_event_at=datetime.fromisoformat(r["latest_event_at"]) if r["latest_event_at"] else None,
                    latest_release=r["latest_release"],
                    latest_claim_revision_at=datetime.fromisoformat(r["latest_claim_revision_at"]) if r["latest_claim_revision_at"] else None,
                    active_claim_count=r["active_claim_count"] or 0,
                    supported_claim_count=r["supported_claim_count"] or 0,
                    contradicted_claim_count=r["contradicted_claim_count"] or 0,
                    superseded_claim_count=r["superseded_claim_count"] or 0,
                    risk_score=r["risk_score"] or 0.0,
                    trend=r["trend"],
                    updated_at=datetime.fromisoformat(r["updated_at"]),
                )
                tech_state_map[ts.cluster_id] = ts

            # 5. Batch fetch events count
            cursor.execute(
                f"SELECT cluster_id, COUNT(*) as cnt FROM cluster_events WHERE cluster_id IN ({placeholders}) GROUP BY cluster_id",
                cluster_ids,
            )
            event_counts_map = {r["cluster_id"]: r["cnt"] for r in cursor.fetchall()}

            for cid in cluster_ids:
                cl = cluster_map.get(cid)
                if not cl:
                    continue
                cl_claims = claims_map.get(cid, [])
                assessment = assess_map.get(cid)
                tech_state = tech_state_map.get(cid)
                ev_count = event_counts_map.get(cid, len(cl.event_ids) if hasattr(cl, "event_ids") else 0)

                claim_scores = [c.verification_score for c in cl_claims if c.verification_score is not None]
                verif_score = float(np.mean(claim_scores)) if claim_scores else None

                if tech_state:
                    if not cl_claims and ev_count == 0:
                        risk_status = "insufficient_data"
                        risk_score = tech_state.risk_score
                        risk_level = None
                    else:
                        risk_status = "assessed"
                        risk_score = tech_state.risk_score
                        risk_level = (
                            "critical" if risk_score >= 0.7
                            else ("high" if risk_score >= 0.4
                            else ("medium" if risk_score >= 0.2
                            else "low"))
                        )
                else:
                    risk_status = "not_assessed"
                    risk_score = None
                    risk_level = None

                cur_state = CurrentIntelligenceState(
                    title=cl.canonical_title,
                    cluster_score=round(cl.cluster_score, 4),
                    verification_score=round(verif_score, 4) if verif_score is not None else None,
                    maturity_stage=assessment.maturity_stage if assessment else None,
                    risk_level=risk_level,
                    risk_score=round(risk_score, 4) if risk_score is not None else None,
                    risk_status=risk_status,
                    claim_status=aggregate_cluster_claim_status(cl_claims),
                    claims_count=len(cl_claims),
                    events_count=ev_count,
                    is_active=True,
                )
                current_states_by_cluster[cid] = cur_state.model_dump()

    out = []
    for s in paginated:
        item = {
            "id": s.id,
            "inbox_item_id": s.inbox_item_id,
            "story_cluster_id": s.story_cluster_id,
            "title": s.title_snapshot,
            "verification_score": round(s.verification_snapshot, 4) if s.verification_snapshot is not None else None,
            "claim_status": s.claim_status_snapshot,
            "maturity_stage": s.maturity_snapshot,
            "risk_level": s.risk_level_snapshot,
            "risk_status": s.risk_status_snapshot,
            "risk_score": round(s.risk_snapshot, 4) if s.risk_snapshot is not None else None,
            "tags": list(s.tags),
            "user_note": s.user_note,
            "project_ids": list(s.project_ids),
            "saved_at": s.saved_at.isoformat(),
        }
        if include_current:
            item["current_state"] = current_states_by_cluster.get(s.story_cluster_id) if s.story_cluster_id else None
        out.append(item)
    return out


def get_saved_item(
    saved_id: str,
    include_current: bool = False,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a specific saved item with complete snapshot and optional current state."""
    if db is None:
        db = Database()

    if not saved_id or not isinstance(saved_id, str) or not saved_id.strip():
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

    item = {
        "id": s.id,
        "entity_type": s.entity_type,
        "entity_id": s.entity_id,
        "story_cluster_id": s.story_cluster_id,
        "inbox_item_id": s.inbox_item_id,
        "title": s.title_snapshot,
        "verification_score": round(s.verification_snapshot, 4) if s.verification_snapshot is not None else None,
        "claim_status": s.claim_status_snapshot,
        "maturity_stage": s.maturity_snapshot,
        "risk_level": s.risk_level_snapshot,
        "risk_status": s.risk_status_snapshot,
        "risk_score": round(s.risk_snapshot, 4) if s.risk_snapshot is not None else None,
        "user_note": s.user_note,
        "tags": list(s.tags),
        "project_ids": list(s.project_ids),
        "saved_at": s.saved_at.isoformat(),
    }

    if include_current and s.story_cluster_id:
        # Hydrate single item
        cur_list = get_saved_items(limit=1, tag=None, include_current=True, db=db)
        cur_matched = [ci["current_state"] for ci in cur_list if ci["id"] == s.id and "current_state" in ci]
        item["current_state"] = cur_matched[0] if cur_matched else None

    return item


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
        if not existing_saved.is_active:
            existing_saved.is_active = True
            db.save_saved_item(existing_saved)
        return True, "Item is already starred and saved in library", get_saved_item(saved_id, db=db)

    # 3. Create persistent SavedItem snapshot with genuine intelligence values
    assessment = db.get_technology_assessment(item.story_cluster_id)
    tech_state = db.get_technology_state(item.story_cluster_id)
    claims = db.get_claims_by_cluster(item.story_cluster_id, current_only=True)
    claim_scores = [c.verification_score for c in claims if c.verification_score is not None]
    v_snap = float(sum(claim_scores) / len(claim_scores)) if claim_scores else None
    claim_status_snap = aggregate_cluster_claim_status(claims)
    m_snap = assessment.maturity_stage if assessment else None

    if tech_state:
        if not claims and len(item.matched_project_ids) == 0:
            r_status_snap = "insufficient_data"
            r_level_snap = None
        else:
            r_status_snap = "assessed"
            r_level_snap = (
                "critical" if tech_state.risk_score >= 0.7
                else ("high" if tech_state.risk_score >= 0.4
                else ("medium" if tech_state.risk_score >= 0.2
                else "low"))
            )
        r_snap = tech_state.risk_score
    else:
        r_status_snap = "not_assessed"
        r_level_snap = None
        r_snap = None

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
        claim_status_snapshot=claim_status_snap,
        risk_status_snapshot=r_status_snap,
        risk_level_snapshot=r_level_snap,
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

    return True, "Item starred and saved successfully", get_saved_item(saved_id, db=db)


def save_cluster_item(
    story_cluster_id: str,
    inbox_item_id: Optional[str] = None,
    user_note: Optional[str] = None,
    tags: Optional[List[str]] = None,
    db: Optional[Database] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Saves a Story Cluster directly to the Saved Intelligence library with complete snapshot values.
    Idempotent: Re-saving an existing active item preserves snapshot and merges notes/tags.
    Reactivating a deactivated item restores it without duplicate rows.
    """
    if db is None:
        db = Database()

    if not story_cluster_id or not isinstance(story_cluster_id, str) or not story_cluster_id.strip():
        return False, "story_cluster_id must be provided and non-empty", None

    cid_clean = story_cluster_id.strip()

    # Validate inbox_item_id association if provided
    if inbox_item_id:
        inbox_item = db.get_inbox_item(inbox_item_id.strip())
        if not inbox_item:
            return False, f"Inbox item '{inbox_item_id}' not found", None
        if inbox_item.story_cluster_id != cid_clean:
            return False, f"Inbox item '{inbox_item_id}' does not belong to story_cluster_id '{cid_clean}'", None

    cluster = db.get_cluster(cid_clean)
    if not cluster:
        return False, f"Story cluster '{cid_clean}' not found", None

    saved_id = f"saved:{cid_clean}"
    existing_saved = db.get_saved_item(saved_id)

    clean_tags = [re.sub(r"[^a-zA-Z0-9_\-]", "", t.strip().lower()) for t in (tags or []) if t and t.strip()]
    clean_tags = [t for t in clean_tags if t and len(t) <= 50]

    if existing_saved:
        was_inactive = not existing_saved.is_active
        existing_saved.is_active = True
        if user_note and user_note.strip():
            existing_saved.user_note = user_note.strip()[:2000]
        if clean_tags:
            for t in clean_tags:
                if t not in existing_saved.tags:
                    existing_saved.tags.append(t)
        db.save_saved_item(existing_saved)

        if inbox_item_id:
            star_inbox_item(inbox_item_id, db=db)

        msg = "Item reactivated in saved library" if was_inactive else "Item is already saved in library"
        return True, msg, get_saved_item(saved_id, db=db)

    now = datetime.now(timezone.utc)
    assessment = db.get_technology_assessment(cid_clean)
    tech_state = db.get_technology_state(cid_clean)
    claims = db.get_claims_by_cluster(cid_clean, current_only=True)
    claim_scores = [c.verification_score for c in claims if c.verification_score is not None]
    v_snap = float(sum(claim_scores) / len(claim_scores)) if claim_scores else None
    claim_status_snap = aggregate_cluster_claim_status(claims)
    m_snap = assessment.maturity_stage if assessment else None

    ev_count = len(cluster.event_ids) if hasattr(cluster, "event_ids") else 0
    if tech_state:
        if not claims and ev_count == 0:
            r_status_snap = "insufficient_data"
            r_level_snap = None
        else:
            r_status_snap = "assessed"
            r_level_snap = (
                "critical" if tech_state.risk_score >= 0.7
                else ("high" if tech_state.risk_score >= 0.4
                else ("medium" if tech_state.risk_score >= 0.2
                else "low"))
            )
        r_snap = tech_state.risk_score
    else:
        r_status_snap = "not_assessed"
        r_level_snap = None
        r_snap = None

    new_saved = SavedItem(
        id=saved_id,
        entity_type="cluster",
        entity_id=cid_clean,
        story_cluster_id=cid_clean,
        inbox_item_id=inbox_item_id.strip() if inbox_item_id else None,
        title_snapshot=cluster.canonical_title,
        saved_at=now,
        verification_snapshot=v_snap,
        maturity_snapshot=m_snap,
        risk_snapshot=r_snap,
        claim_status_snapshot=claim_status_snap,
        risk_status_snapshot=r_status_snap,
        risk_level_snapshot=r_level_snap,
        user_note=user_note.strip()[:2000] if user_note else None,
        tags=clean_tags if clean_tags else ["saved"],
        project_ids=[],
        is_active=True,
        link_status="resolved",
        event_ids_snapshot=list(cluster.event_ids) if hasattr(cluster, "event_ids") else [],
    )
    db.save_saved_item(new_saved)

    if inbox_item_id:
        star_inbox_item(inbox_item_id, db=db)

    return True, "Story saved successfully", get_saved_item(saved_id, db=db)


def delete_saved_item(
    saved_id: str,
    db: Optional[Database] = None,
) -> Tuple[bool, str]:
    """
    Deactivates a SavedItem by its canonical SavedItem ID.
    Preserves historical retention in the database while removing it from active lists.
    """
    if db is None:
        db = Database()

    if not saved_id or not isinstance(saved_id, str) or not saved_id.strip():
        return False, "saved_id must be provided and non-empty"

    sid_clean = saved_id.strip()
    s = db.get_saved_item(sid_clean)
    if not s or not s.is_active:
        return False, f"Saved item '{sid_clean}' not found"

    db.deactivate_saved_item(s.id)
    if s.inbox_item_id:
        unstar_inbox_item(s.inbox_item_id, db=db)

    return True, f"Saved item '{sid_clean}' removed successfully"


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
