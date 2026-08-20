import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml

from app.models.schemas import (
    Claim,
    Event,
    InboxItem,
    IntelligenceChange,
    ProjectMatch,
    StoryCluster,
    TechnologyAssessment,
    TechnologyState,
)
from app.storage.db import Database


def load_inbox_config() -> Dict[str, Any]:
    default_cfg = {
        "ttl_hours": 24,
        "discovery_lookback_hours": 36,
        "max_daily_items": 40,
        "max_must_know": 5,
        "max_project_items_per_project": 8,
        "max_section_items": 10,
        "min_inbox_score": 0.40,
    }
    cfg_path = Path("config/inbox.yaml")
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "inbox" in data:
                    default_cfg.update(data["inbox"])
        except Exception:
            pass
    return default_cfg


def classify_inbox_section(
    cluster: StoryCluster,
    events: List[Event],
    claims: List[Claim],
    matches: List[ProjectMatch],
    inbox_score: float,
    item_type: str,
    assessment: Optional[TechnologyAssessment],
    tech_state: Optional[TechnologyState],
) -> str:
    """Classifies an item into a briefing section deterministically."""
    # 1. Corrections / Updates
    if item_type in ("claim_strengthened", "claim_weakened", "correction", "maturity_change", "new_risk"):
        return "corrections_updates"

    # 2. Must Know
    has_release = any(e.source == "github" and e.event_type == "release" for e in events)
    has_contra = any(c.status in ("contradicted", "mixed") for c in claims)
    has_direct_dep = any(m.match_type == "direct_dependency" for m in matches)
    risk_score = tech_state.risk_score if tech_state else 0.0

    if (inbox_score >= 0.82) or (has_direct_dep and has_release) or (has_contra and has_direct_dep):
        return "must_know"

    # 3. Project Relevant
    if matches and (has_direct_dep or any(m.impact_score >= 0.70 for m in matches)):
        return "project_relevant"

    # 4. Domain / Topic Analysis
    text_corpus = f"{cluster.canonical_title} " + " ".join(e.title + " " + (e.text or "") for e in events)
    lower = text_corpus.lower()

    if any(k in lower for k in ["llvm", "compiler", "cuda", "kernel", "gpu", "c++", "rust", "triton"]):
        return "systems_compilers"
    if any(k in lower for k in ["database", "vector search", "chroma", "qdrant", "postgres", "sqlite", "redis", "kv-cache"]):
        return "storage_databases"
    if any(e.source in ("arxiv", "openalex", "crossref") for e in events) or "benchmark" in lower or "paper" in lower:
        return "research"
    if any(k in lower for k in ["cli", "toolkit", "extension", "plugin", "vscode", "dev tool"]):
        return "developer_tooling"
    if any(k in lower for k in ["llm", "rag", "pytorch", "transformer", "model", "inference", "hugging face", "agent"]):
        return "ai_ml"

    stage = assessment.maturity_stage if assessment else "concept"
    if stage in ("prototype", "concept") or risk_score >= 0.60:
        return "watchlist"

    return "ai_ml"


def calculate_inbox_score(
    cluster: StoryCluster,
    events: List[Event],
    claims: List[Claim],
    assessment: Optional[TechnologyAssessment],
    tech_state: Optional[TechnologyState],
    matches: List[ProjectMatch],
    recent_changes: List[IntelligenceChange],
    now: datetime,
) -> Tuple[float, List[str], str]:
    """
    Computes a transparent inbox score, reason codes, and item type.
    """
    reasons = []

    # 1. Cluster Score
    cluster_score = cluster.cluster_score or 0.50

    # 2. Novelty
    # Determine age of latest event
    latest_dt = None
    for ev in events:
        if ev.published_at:
            if latest_dt is None or ev.published_at > latest_dt:
                latest_dt = ev.published_at
    if latest_dt is None:
        latest_dt = cluster.created_at

    age_hours = max(0.0, (now - latest_dt).total_seconds() / 3600.0)
    if age_hours <= 24:
        novelty = 1.0
        reasons.append("recent_discovery")
    elif age_hours <= 48:
        novelty = 0.75
    elif age_hours <= 96:
        novelty = 0.50
    else:
        novelty = 0.25

    # 3. Project Relevance & Impact
    max_project_impact = 0.0
    has_direct_dep = False
    if matches:
        # Sort matches by impact
        top_m = max(matches, key=lambda m: (m.impact_score, m.relevance_score))
        max_project_impact = top_m.impact_score
        if top_m.match_type == "direct_dependency":
            has_direct_dep = True
            reasons.append(f"direct_dependency_match:{top_m.project_id}")
        else:
            reasons.append(f"project_relevant:{top_m.project_id}")

    # 4. Verification Factor
    strongest_claim = claims[0] if claims else None
    v_score = strongest_claim.verification_score if strongest_claim else 0.50
    claim_status = strongest_claim.status if strongest_claim else "unverified"
    if strongest_claim and v_score >= 0.60:
        reasons.append(f"verified_claim:{v_score:.2f}")

    # 5. Intelligence Change Importance
    change_importance = 0.0
    item_type = "new_story"
    if recent_changes:
        top_change = max(recent_changes, key=lambda c: c.importance)
        change_importance = top_change.importance
        reasons.append(f"intel_change:{top_change.change_type}")

        if "strengthen" in top_change.change_type:
            item_type = "claim_strengthened"
        elif "weaken" in top_change.change_type:
            item_type = "claim_weakened"
        elif "supersede" in top_change.change_type:
            item_type = "new_release"
        elif "risk" in top_change.change_type:
            item_type = "new_risk"
        elif "maturity" in top_change.change_type:
            item_type = "maturity_change"
        else:
            item_type = "correction"
    elif any(e.source == "github" and e.event_type == "release" for e in events):
        item_type = "new_release"
        reasons.append("official_release")

    # 6. Source Diversity
    src_div = min(1.0, len(cluster.sources) / 3.0)
    if len(cluster.sources) > 1:
        reasons.append(f"multi_source:{len(cluster.sources)}")

    # 7. Base Formula Calculation
    raw_inbox_score = (
        0.25 * cluster_score
        + 0.20 * novelty
        + 0.20 * max_project_impact
        + 0.15 * v_score
        + 0.10 * change_importance
        + 0.10 * src_div
    )

    # 8. Adjustments
    risk_score = tech_state.risk_score if tech_state else 0.20
    if has_direct_dep:
        raw_inbox_score += 0.10  # Priority boost for project dependencies

    if claim_status in ("contradicted", "mixed"):
        if has_direct_dep:
            raw_inbox_score += 0.15  # High priority risk alert for user project
            reasons.append(f"risk_alert:{claim_status}")
            item_type = "new_risk"
        else:
            raw_inbox_score -= 0.15  # Downgrade generic contradicted claims

    if risk_score >= 0.60:
        if has_direct_dep:
            reasons.append(f"high_risk:{risk_score:.2f}")
        else:
            raw_inbox_score -= 0.10

    inbox_score = round(min(1.0, max(0.0, raw_inbox_score)), 4)
    return inbox_score, reasons, item_type


def generate_daily_inbox(
    db: Database,
    lookback_hours: Optional[int] = None,
    ttl_hours: Optional[int] = None,
    now: Optional[datetime] = None,
) -> List[InboxItem]:
    """
    Evaluates current intelligence, project matches, and changes to construct
    or update Today's Intelligence Inbox.
    """
    cfg = load_inbox_config()
    if lookback_hours is None:
        lookback_hours = cfg["discovery_lookback_hours"]
    if ttl_hours is None:
        ttl_hours = cfg["ttl_hours"]
    if now is None:
        now = datetime.now(timezone.utc)

    expires_at = now + timedelta(hours=ttl_hours)
    min_score = cfg["min_inbox_score"]
    max_items = cfg["max_daily_items"]

    all_clusters = db.get_all_clusters()
    candidate_items: List[InboxItem] = []

    for cluster in all_clusters:
        events = db.get_cluster_events(cluster.id)
        claims = db.get_claims_by_cluster(cluster.id)
        assessment = db.get_technology_assessment(cluster.id)
        tech_state = db.get_technology_state(cluster.id)
        matches = [m for m in db.get_all_project_matches() if m.entity_id == cluster.id]
        changes = [c for c in db.get_all_intelligence_changes() if c.entity_id in [cl.id for cl in claims] or c.entity_id == cluster.id]

        score, reasons, item_type = calculate_inbox_score(
            cluster=cluster,
            events=events,
            claims=claims,
            assessment=assessment,
            tech_state=tech_state,
            matches=matches,
            recent_changes=changes,
            now=now,
        )

        if score < min_score:
            continue

        # Check existing inbox item for this cluster
        existing_inbox = db.get_inbox_item_by_cluster(cluster.id)
        saved_item = db.get_saved_item_by_cluster(cluster.id)

        # Determine if we should create or reinbox
        if existing_inbox:
            # If already active/starred today
            if existing_inbox.state in ("unseen", "seen", "opened", "starred"):
                # Update scores and reasons without resetting state or seen/opened timestamps
                existing_inbox.inbox_score = score
                existing_inbox.rank_score = score
                existing_inbox.project_impact_score = max([m.impact_score for m in matches], default=0.0)
                existing_inbox.reason_codes = list(set(existing_inbox.reason_codes + reasons))
                existing_inbox.last_seen_at = now
                if saved_item and saved_item.is_active:
                    existing_inbox.is_starred = True
                    existing_inbox.saved_item_id = saved_item.id
                db.save_inbox_item(existing_inbox)
                candidate_items.append(existing_inbox)
                continue
            elif existing_inbox.state == "expired":
                # Only reinbox if there is a meaningful new intelligence change
                if not changes:
                    continue
                # Reinbox with new item
                item_type = item_type if item_type != "new_story" else "story_update"

        section = classify_inbox_section(
            cluster=cluster,
            events=events,
            claims=claims,
            matches=matches,
            inbox_score=score,
            item_type=item_type,
            assessment=assessment,
            tech_state=tech_state,
        )

        inbox_item_id = f"inbox:{cluster.id}:{now.strftime('%Y%m%d')}"
        is_starred = bool(saved_item and saved_item.is_active)
        state = "starred" if is_starred else "unseen"

        matched_pids = [m.project_id for m in matches]

        item = InboxItem(
            id=inbox_item_id,
            entity_type="cluster",
            entity_id=cluster.id,
            story_cluster_id=cluster.id,
            title=cluster.canonical_title,
            section=section,
            inbox_score=score,
            rank_score=score,
            project_impact_score=max([m.impact_score for m in matches], default=0.0),
            state=state,
            item_type=item_type,
            created_at=now,
            first_seen_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            is_starred=is_starred,
            saved_item_id=saved_item.id if saved_item else None,
            matched_project_ids=matched_pids,
            reason_codes=reasons,
        )

        db.save_inbox_item(item)
        candidate_items.append(item)

    # Sort items by inbox score DESC
    candidate_items.sort(key=lambda it: (it.inbox_score, it.project_impact_score), reverse=True)

    # Enforce global and section limits
    final_items = candidate_items[:max_items]
    return final_items
