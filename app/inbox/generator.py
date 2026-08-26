import hashlib
import json
import re
from collections import defaultdict
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
from app.runtime.timezone import runtime_date_string, runtime_day_bounds_utc
from app.runtime.state import load_runtime_config




def load_inbox_config() -> Dict[str, Any]:
    default_cfg = {
        "ttl_hours": 24,
        "discovery_lookback_hours": 36,
        "change_lookback_hours": 36,
        "initial_history_max_days": 7,
        "max_daily_items": 30,
        "min_inbox_score": 0.45,
        "max_must_know": 5,
        "max_project_items_per_project": 6,
        "max_section_items": 6,
        "briefing": {
            "target_items": 15,
            "max_items": 20,
            "min_briefing_score": 0.55,
            "max_must_know": 5,
            "max_project_relevant": 6,
            "max_research": 4,
            "max_systems": 4,
            "max_storage": 4,
            "max_ai_ml": 5,
            "max_developer_tooling": 3,
            "max_corrections": 4,
            "max_watch": 4,
        },
    }
    cfg_path = Path("config/inbox.yaml")
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    if "inbox" in data and isinstance(data["inbox"], dict):
                        default_cfg.update(data["inbox"])
                    if "briefing" in data and isinstance(data["briefing"], dict):
                        default_cfg["briefing"].update(data["briefing"])
        except Exception:
            pass
    return default_cfg


def is_user_facing_change(
    change: IntelligenceChange,
    lookback_cutoff: Optional[datetime] = None,
) -> bool:
    """
    Deterministically determines if an IntelligenceChange is user-facing.
    Initialization/backfill changes and stale changes are rejected.
    """
    origin = getattr(change, "origin", "live_update") or "live_update"
    if origin in ("backfill_initialization", "migration", "recompute", "manual_rebuild"):
        return False

    if lookback_cutoff and change.created_at < lookback_cutoff:
        return False

    meaningful_types = {
        "contradiction_detected",
        "claim_retracted",
        "claim_strengthened",
        "claim_weakened",
        "maturity_increased",
        "maturity_decreased",
        "status_changed",
        "risk_increased",
        "risk_decreased",
        "new_release",
        "story_update",
    }
    return change.change_type in meaningful_types


def extract_repository_identity(events: List[Event]) -> Optional[str]:
    """Extracts lowercase github owner/repo identity if available."""
    for e in events:
        if e.url:
            match = re.search(r"github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", e.url, re.IGNORECASE)
            if match:
                repo = match.group(1).lower().rstrip("/").rstrip(".git")
                # Exclude non-repo paths
                if not repo.startswith("topics/") and not repo.startswith("explore/"):
                    return repo
        if e.id.startswith("github:"):
            parts = e.id.split(":")
            if len(parts) >= 4 and parts[1] in ("release", "repo"):
                return f"{parts[2]}/{parts[3]}".lower()
    return None


def classify_inbox_section(
    cluster: StoryCluster,
    events: List[Event],
    claims: List[Claim],
    matches: List[ProjectMatch],
    inbox_score: float,
    item_type: str,
    assessment: Optional[TechnologyAssessment],
    tech_state: Optional[TechnologyState],
    has_user_facing_change: bool = False,
) -> str:
    """Classifies an item into a briefing section deterministically with strict precedence."""
    # 1. Corrections / Updates (Only for actual user-facing changes)
    if has_user_facing_change or item_type in ("contradiction_detected", "claim_retracted", "claim_weakened"):
        return "corrections_updates"

    # 2. Must Know
    has_release = any(e.source == "github" and e.event_type == "release" for e in events)
    has_contra = any(c.status in ("contradicted", "mixed") for c in claims)
    has_direct_dep = any(m.match_type == "direct_dependency" for m in matches)
    strongest_claim = claims[0] if claims else None
    v_score = strongest_claim.verification_score if strongest_claim else 0.50

    if (inbox_score >= 0.82 and (has_release or has_direct_dep)) or (has_direct_dep and has_release and v_score >= 0.60) or (has_contra and has_direct_dep):
        return "must_know"

    # 3. Project Relevant
    if matches and (has_direct_dep or any(m.impact_score >= 0.70 for m in matches)):
        return "project_relevant"

    # 4. Domain / Topic Analysis
    text_corpus = f"{cluster.canonical_title} " + " ".join(e.title + " " + (e.text or "") for e in events)
    lower = text_corpus.lower()

    if any(k in lower for k in ["llvm", "compiler", "cuda", "kernel", "gpu", "c++", "rust", "triton"]):
        return "systems_compilers"
    if any(k in lower for k in ["database", "vector search", "vector database", "chroma", "qdrant", "milvus", "postgres", "sqlite", "redis", "rocksdb", "duckdb", "kv-cache"]):
        return "storage_databases"
    if any(e.source in ("arxiv", "openalex", "crossref") for e in events) or "benchmark" in lower or "paper" in lower:
        return "research"
    if any(k in lower for k in ["cli", "toolkit", "extension", "plugin", "vscode", "dev tool", "profiler", "debugger"]):
        return "developer_tooling"
    if any(k in lower for k in ["llm", "rag", "pytorch", "transformer", "model", "inference", "hugging face", "agent"]):
        return "ai_ml"

    stage = assessment.maturity_stage if assessment else "concept"
    risk_score = tech_state.risk_score if tech_state else 0.25
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
    is_duplicate_repo: bool = False,
) -> Tuple[float, List[str], str, Dict[str, float]]:
    """
    Computes a transparent inbox score, reason codes, item type, and score breakdown.
    """
    reasons = []
    breakdown = {}

    # 1. Cluster Score
    cluster_score = cluster.cluster_score or 0.50
    breakdown["cluster_score"] = cluster_score

    # 2. Novelty (Calculated from true event discovery / publication recency)
    latest_dt = None
    for ev in events:
        ev_time = ev.published_at or getattr(ev, "discovered_at", None)
        if ev_time:
            if latest_dt is None or ev_time > latest_dt:
                latest_dt = ev_time
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
    breakdown["novelty"] = novelty

    # 3. Project Relevance & Impact
    max_project_impact = 0.0
    has_direct_dep = False
    if matches:
        top_m = max(matches, key=lambda m: (m.impact_score, m.relevance_score))
        max_project_impact = top_m.impact_score
        if top_m.match_type == "direct_dependency":
            has_direct_dep = True
            # Auditable dependency match reason
            dep_reasons = [r for r in top_m.reason_codes if r.startswith("dependency_match:")]
            if dep_reasons:
                reasons.append(dep_reasons[0])
            else:
                reasons.append(f"direct_dependency:{top_m.project_id}")
        else:
            reasons.append(f"project_match:{top_m.match_type}")
    breakdown["project_impact"] = max_project_impact

    # 4. Verification Factor
    strongest_claim = claims[0] if claims else None
    v_score = strongest_claim.verification_score if strongest_claim else 0.50
    claim_status = strongest_claim.status if strongest_claim else "unverified"
    if strongest_claim and v_score >= 0.60:
        reasons.append(f"verified_claim:{v_score:.2f}")
    breakdown["verification"] = v_score

    # 5. User-Facing Intelligence Change Importance
    change_importance = 0.0
    item_type = "new_story"
    user_facing_changes = [c for c in recent_changes if is_user_facing_change(c)]

    if user_facing_changes:
        top_change = max(user_facing_changes, key=lambda c: c.importance)
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
        elif "contradiction" in top_change.change_type:
            item_type = "contradiction_detected"
        elif "retract" in top_change.change_type:
            item_type = "claim_retracted"
        else:
            item_type = "correction"
    elif any(e.source == "github" and e.event_type == "release" for e in events):
        item_type = "new_release"
        reasons.append("official_release")
        change_importance = 0.40

    breakdown["change_importance"] = change_importance

    # 6. Source Diversity
    src_div = min(1.0, len(cluster.sources) / 3.0)
    if len(cluster.sources) > 1:
        reasons.append(f"multi_source:{len(cluster.sources)}")
    breakdown["source_diversity"] = src_div

    # 7. Base Formula Calculation
    raw_inbox_score = (
        0.25 * cluster_score
        + 0.20 * novelty
        + 0.20 * max_project_impact
        + 0.15 * v_score
        + 0.10 * change_importance
        + 0.10 * src_div
    )

    # 8. Adjustments & Penalties
    risk_score = tech_state.risk_score if tech_state else 0.20
    breakdown["risk_penalty"] = 0.0
    breakdown["diversity_penalty"] = 0.0

    if has_direct_dep:
        raw_inbox_score += 0.10  # Priority boost for real project dependencies

    if claim_status in ("contradicted", "mixed"):
        if has_direct_dep:
            raw_inbox_score += 0.15  # High priority risk alert for user project
            reasons.append(f"risk_alert:{claim_status}")
            item_type = "new_risk"
        else:
            raw_inbox_score -= 0.15  # Downgrade generic contradicted claims
            breakdown["risk_penalty"] = -0.15

    if risk_score >= 0.60:
        if has_direct_dep:
            reasons.append(f"high_risk:{risk_score:.2f}")
        else:
            raw_inbox_score -= 0.10
            breakdown["risk_penalty"] = -0.10

    if is_duplicate_repo:
        raw_inbox_score -= 0.10
        breakdown["diversity_penalty"] = -0.10
        reasons.append("same_repo_penalty")

    inbox_score = round(min(1.0, max(0.0, raw_inbox_score)), 4)
    breakdown["final_inbox_score"] = inbox_score
    return inbox_score, reasons, item_type, breakdown


def generate_daily_inbox(
    db: Database,
    lookback_hours: Optional[int] = None,
    ttl_hours: Optional[int] = None,
    now: Optional[datetime] = None,
    rebuild_today: bool = False,
    preview: bool = False,
    surface_date: Optional[str] = None,
    daily_run_id: Optional[str] = None,
    data_cutoff_at: Optional[datetime] = None,
) -> Any:
    """
    Evaluates current intelligence, project matches, and changes to construct
    or update Today's Intelligence Inbox with hard daily active cap and suppressed state.
    """
    cfg = load_inbox_config()
    if lookback_hours is None:
        lookback_hours = cfg.get("discovery_lookback_hours", 36)
    if ttl_hours is None:
        ttl_hours = cfg.get("ttl_hours", 24)
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    expires_at = now + timedelta(hours=ttl_hours)
    min_score = cfg.get("min_inbox_score", 0.45)
    max_items = cfg.get("max_daily_items", 30)
    change_lookback = cfg.get("change_lookback_hours", 36)
    change_cutoff = now - timedelta(hours=change_lookback)

    # Section caps
    section_caps = {
        "corrections_updates": cfg.get("max_corrections", 4),
        "must_know": cfg.get("max_must_know", 5),
        "project_relevant": cfg.get("max_project_items_per_project", 6),
        "research": 4,
        "systems_compilers": 4,
        "storage_databases": 4,
        "ai_ml": 5,
        "developer_tooling": 3,
        "watchlist": 4,
    }

    runtime_config = load_runtime_config()
    today_local_date = surface_date or runtime_date_string(now, runtime_config)
    today_local_date_clean = today_local_date.replace("-", "")

    if not preview:
        if rebuild_today:
            db.conn.execute("UPDATE inbox_items SET state = 'suppressed' WHERE state IN ('unseen', 'seen', 'opened')")
            db.conn.commit()
        db.conn.execute("UPDATE inbox_items SET state = 'expired' WHERE expires_at < ? AND is_starred = 0 AND state NOT IN ('expired', 'archived')", (now.isoformat(),))
        db.conn.commit()

    all_clusters = db.get_all_clusters()
    candidate_records: List[Dict[str, Any]] = []
    seen_repos: Set[str] = set()

    # Archived projects must not influence inbox candidate scoring or
    # classification; restrict project matches to active projects only.
    active_project_ids = {p.id for p in db.get_all_projects(active_only=True)}
    all_project_matches = [
        m for m in db.get_all_project_matches() if m.project_id in active_project_ids
    ]

    for cluster in all_clusters:
        events = db.get_cluster_events(cluster.id)
        claims = db.get_claims_by_cluster(cluster.id)
        assessment = db.get_technology_assessment(cluster.id)
        tech_state = db.get_technology_state(cluster.id)
        matches = [m for m in all_project_matches if m.entity_id == cluster.id]

        all_changes = [c for c in db.get_all_intelligence_changes() if c.entity_id in [cl.id for cl in claims] or c.entity_id == cluster.id]
        user_facing_changes = [c for c in all_changes if is_user_facing_change(c, change_cutoff)]

        # Determine age of latest source event
        latest_event_dt = None
        for ev in events:
            ev_time = ev.published_at or getattr(ev, "discovered_at", None)
            if ev_time:
                if ev_time.tzinfo is None:
                    ev_time = ev_time.replace(tzinfo=timezone.utc)
                if latest_event_dt is None or ev_time > latest_event_dt:
                    latest_event_dt = ev_time
        if latest_event_dt is None:
            latest_event_dt = cluster.created_at
        if latest_event_dt.tzinfo is None:
            latest_event_dt = latest_event_dt.replace(tzinfo=timezone.utc)

        age_hours = max(0.0, (now - latest_event_dt).total_seconds() / 3600.0)
        repo_id = extract_repository_identity(events)
        is_dup_repo = bool(repo_id and repo_id in seen_repos)

        score, reasons, item_type, breakdown = calculate_inbox_score(
            cluster=cluster,
            events=events,
            claims=claims,
            assessment=assessment,
            tech_state=tech_state,
            matches=matches,
            recent_changes=user_facing_changes,
            now=now,
            is_duplicate_repo=is_dup_repo,
        )

        has_direct_dep = any(m.match_type == "direct_dependency" for m in matches)
        max_proj_impact = max([m.impact_score for m in matches], default=0.0)
        has_release = any(e.source == "github" and e.event_type == "release" for e in events)
        strongest_claim = claims[0] if claims else None
        v_score = strongest_claim.verification_score if strongest_claim else 0.50

        # Section classification
        section = classify_inbox_section(
            cluster=cluster,
            events=events,
            claims=claims,
            matches=matches,
            inbox_score=score,
            item_type=item_type,
            assessment=assessment,
            tech_state=tech_state,
            has_user_facing_change=bool(user_facing_changes),
        )

        saved_item = db.get_saved_item_by_cluster(cluster.id)
        existing_inbox = db.get_inbox_item_by_cluster(cluster.id)

        # Rejection & Quality Gate checks
        rejection_reason = None
        if existing_inbox and existing_inbox.state in ("expired", "archived") and not user_facing_changes and not rebuild_today:
            rejection_reason = "already_processed"
        elif age_hours > lookback_hours and not user_facing_changes:
            rejection_reason = "historical"
        elif score < min_score:
            rejection_reason = "below_quality_floor"
        elif not (
            has_direct_dep
            or max_proj_impact >= 0.50
            or (has_release and v_score >= 0.50)
            or (len(cluster.sources) >= 2 and score >= 0.45)
            or user_facing_changes
            or cluster.cluster_score >= 0.65
            or score >= 0.50
        ):
            rejection_reason = "weak_signals"

        if repo_id and not is_dup_repo and not rejection_reason:
            seen_repos.add(repo_id)

        match_type_str = matches[0].match_type if matches else "none"

        candidate_records.append({
            "cluster": cluster,
            "events": events,
            "claims": claims,
            "assessment": assessment,
            "tech_state": tech_state,
            "matches": matches,
            "score": score,
            "reasons": reasons,
            "item_type": item_type,
            "section": section,
            "breakdown": breakdown,
            "rejection_reason": rejection_reason,
            "saved_item": saved_item,
            "existing_inbox": existing_inbox,
            "match_type": match_type_str,
            "repo_id": repo_id,
            "latest_event_dt": latest_event_dt,
            "user_facing_changes": user_facing_changes,
        })

    # Sort eligible candidates by score DESC, project impact DESC
    eligible_candidates = [c for c in candidate_records if not c["rejection_reason"]]
    eligible_candidates.sort(key=lambda c: (c["score"], c["breakdown"]["project_impact"]), reverse=True)

    # Active vs Suppressed selection with section caps
    section_counts: Dict[str, int] = defaultdict(int)
    active_count = 0
    active_items: List[InboxItem] = []

    for c in eligible_candidates:
        sec = c["section"]
        cluster = c["cluster"]
        existing_inbox = c["existing_inbox"]
        saved_item = c["saved_item"]
        latest_event_dt = c["latest_event_dt"]
        user_facing_changes = c["user_facing_changes"]

        # Check section cap and daily cap
        cap_for_sec = section_caps.get(sec, 5)
        is_starred = bool(saved_item and saved_item.is_active)

        if (section_counts[sec] < cap_for_sec and active_count < max_items) or is_starred:
            if is_starred:
                state = "starred"
            elif existing_inbox and existing_inbox.state in ("seen", "opened"):
                state = existing_inbox.state
            else:
                state = "unseen"

            section_counts[sec] += 1
            active_count += 1
            c["selected"] = True
            c["final_state"] = state
        else:
            state = "suppressed"
            c["selected"] = False
            c["final_state"] = state
            c["rejection_reason"] = "section_cap" if section_counts[sec] >= cap_for_sec else "daily_cap"

        inbox_item_id = f"inbox:{cluster.id}:{today_local_date_clean}"
        matched_pids = [m.project_id for m in c["matches"]]

        first_seen_dt = existing_inbox.first_seen_at if (existing_inbox and existing_inbox.first_seen_at) else now
        if first_seen_dt.tzinfo is None:
            first_seen_dt = first_seen_dt.replace(tzinfo=timezone.utc)

        start_utc, end_utc = runtime_day_bounds_utc(today_local_date, runtime_config)
        is_first_seen_today = (start_utc <= first_seen_dt <= end_utc)

        has_new_event_today = False
        for ev in c["events"]:
            ev_pub = ev.published_at or getattr(ev, "discovered_at", None)
            if ev_pub:
                if ev_pub.tzinfo is None:
                    ev_pub = ev_pub.replace(tzinfo=timezone.utc)
                if start_utc <= ev_pub <= end_utc:
                    has_new_event_today = True
                    break

        has_change_today = False
        last_changed_dt = None
        for ch in user_facing_changes:
            ch_created = ch.created_at
            if ch_created.tzinfo is None:
                ch_created = ch_created.replace(tzinfo=timezone.utc)
            if last_changed_dt is None or ch_created > last_changed_dt:
                last_changed_dt = ch_created
            if start_utc <= ch_created <= end_utc:
                has_change_today = True

        if is_first_seen_today:
            freshness_kind = "new"
        elif has_new_event_today or has_change_today:
            freshness_kind = "updated"
        else:
            freshness_kind = "carried_forward"

        item = InboxItem(
            id=inbox_item_id,
            entity_type="cluster",
            entity_id=cluster.id,
            story_cluster_id=cluster.id,
            title=cluster.canonical_title,
            section=sec,
            inbox_score=c["score"],
            rank_score=c["score"],
            project_impact_score=c["breakdown"]["project_impact"],
            state=state,
            item_type=c["item_type"],
            created_at=existing_inbox.created_at if existing_inbox and not rebuild_today else now,
            first_seen_at=first_seen_dt,
            last_seen_at=now,
            expires_at=expires_at,
            seen_at=existing_inbox.seen_at if existing_inbox else None,
            opened_at=existing_inbox.opened_at if existing_inbox else None,
            is_starred=is_starred,
            saved_item_id=saved_item.id if saved_item else None,
            matched_project_ids=matched_pids,
            reason_codes=c["reasons"],
            surface_date=today_local_date,
            latest_event_at=latest_event_dt.isoformat() if latest_event_dt else None,
            last_materialized_at=now.isoformat(),
            data_cutoff_at=(data_cutoff_at or now).isoformat(),
            freshness_kind=freshness_kind,
            daily_run_id=daily_run_id or f"daily-run:{today_local_date}",
            # Provenance: source timestamps come from the newest SOURCE event
            # (published_at or discovered_at), never internal bookkeeping times.
            source_published_at=latest_event_dt,
            source_updated_at=latest_event_dt,
            last_changed_at=last_changed_dt,
            last_evaluated_at=now,
            surfaced_at=now,
            snapshot_date=today_local_date,
        )

        c["inbox_item"] = item
        active_items.append(item)

        if not preview:
            db.save_inbox_item(item)

    if preview:
        return candidate_records

    # Return only active items (unseen, seen, opened, starred)
    return [it for it in active_items if it.state in ("unseen", "seen", "opened", "starred")]

