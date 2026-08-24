import argparse
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add repository root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import Event
from app.pipeline.filter import filter_event
from app.pipeline.rank import score_event
from app.runtime.jobs import _get_adapter_factories
from app.runtime.sanitization import sanitize_error
from app.runtime.state import load_runtime_config

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run_source_diagnosis(
    source_filter: str = "all",
    limit: int = 2,
    no_persist: bool = True,
) -> List[Dict[str, Any]]:
    """
    Executes a non-mutating diagnostic pass across configured source adapters:
    construct -> fetch -> validate_fetch_shape -> normalize -> validate_event_schema -> filter -> score.
    
    Guarantees:
      - Zero database writes or mutations.
      - Zero checkpoint updates.
      - Zero metric increments.
      - Zero heartbeat or lock file touches.
    """
    config = load_runtime_config()
    sources_cfg = {}
    sources_file = Path("config/sources.yaml")
    if sources_file.exists():
        try:
            import yaml
            with open(sources_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    sources_cfg = data.get("sources", {})
        except Exception:
            pass

    interests_cfg = {}
    interests_file = Path("config/interests.yaml")
    if interests_file.exists():
        try:
            import yaml
            with open(interests_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    interests_cfg = data.get("interests", {})
        except Exception:
            pass

    factories = _get_adapter_factories(sources_cfg)
    target_sources = list(factories.keys()) if source_filter == "all" else [source_filter]

    diagnostic_results = []

    for src_name in target_sources:
        if src_name not in factories:
            diagnostic_results.append({
                "source": src_name,
                "status": "error",
                "stage": "lookup",
                "error_category": "unknown_source",
                "error": f"Unknown source adapter '{src_name}'",
            })
            continue

        factory_fn, default_max = factories[src_name]
        fetch_limit = min(limit, default_max)

        src_res = {
            "source": src_name,
            "status": "pending",
            "failing_stage": None,
            "error_category": None,
            "error": None,
            "raw_item_type": None,
            "items_fetched": 0,
            "items_normalized": 0,
            "items_rejected": 0,
            "items_failed": 0,
            "scored_events": 0,
        }

        # Stage 1: Construct
        current_stage = "construct"
        try:
            adapter = factory_fn()
        except Exception as e:
            cat, san_err = sanitize_error(e)
            src_res.update({
                "status": "failed",
                "failing_stage": current_stage,
                "error_category": cat,
                "error": san_err,
                "exception_type": type(e).__name__,
            })
            diagnostic_results.append(src_res)
            continue

        # Stage 2: Fetch
        current_stage = "fetch"
        try:
            raw_items = adapter.fetch(limit=fetch_limit)
        except Exception as e:
            cat, san_err = sanitize_error(e)
            src_res.update({
                "status": "failed",
                "failing_stage": current_stage,
                "error_category": cat,
                "error": san_err,
                "exception_type": type(e).__name__,
            })
            diagnostic_results.append(src_res)
            continue

        # Stage 3: Validate Fetch Shape
        current_stage = "validate_fetch_shape"
        if not isinstance(raw_items, list):
            src_res.update({
                "status": "failed",
                "failing_stage": current_stage,
                "error_category": "schema_error",
                "error": f"fetch() returned {type(raw_items).__name__} instead of list",
                "raw_item_type": type(raw_items).__name__,
            })
            diagnostic_results.append(src_res)
            continue

        src_res["items_fetched"] = len(raw_items)

        # Stage 4: Normalize & Validate Schema
        current_stage = "normalize"
        events = []
        for idx, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                src_res["items_failed"] += 1
                src_res["raw_item_type"] = type(raw_item).__name__
                continue

            try:
                event = adapter.normalize(raw_item)
            except Exception as e:
                cat, san_err = sanitize_error(e)
                src_res["items_failed"] += 1
                src_res["failing_stage"] = "normalize"
                src_res["error_category"] = cat
                src_res["error"] = san_err
                src_res["exception_type"] = type(e).__name__
                continue

            # Validate Event contract
            if not isinstance(event, Event):
                src_res["items_failed"] += 1
                src_res["failing_stage"] = "validate_event_schema"
                src_res["error_category"] = "schema_error"
                src_res["error"] = f"normalize() returned {type(event).__name__} instead of Event"
                continue

            if not event.id or not isinstance(event.id, str):
                src_res["items_failed"] += 1
                src_res["failing_stage"] = "validate_event_schema"
                src_res["error_category"] = "schema_error"
                src_res["error"] = "Event.id must be a non-empty string"
                continue

            if event.published_at is not None and not isinstance(event.published_at, datetime):
                src_res["items_failed"] += 1
                src_res["failing_stage"] = "validate_event_schema"
                src_res["error_category"] = "schema_error"
                src_res["error"] = f"Event.published_at is {type(event.published_at).__name__} (expected datetime)"
                continue

            if not isinstance(event.discovered_at, datetime) or event.discovered_at.tzinfo is None:
                src_res["items_failed"] += 1
                src_res["failing_stage"] = "validate_event_schema"
                src_res["error_category"] = "schema_error"
                src_res["error"] = "Event.discovered_at must be a timezone-aware datetime"
                continue

            if not isinstance(event.metadata, dict) or not isinstance(event.raw_payload, dict):
                src_res["items_failed"] += 1
                src_res["failing_stage"] = "validate_event_schema"
                src_res["error_category"] = "schema_error"
                src_res["error"] = "Event.metadata and Event.raw_payload must be dicts"
                continue

            if not isinstance(event.authors, list) or not isinstance(event.topics, list):
                src_res["items_failed"] += 1
                src_res["failing_stage"] = "validate_event_schema"
                src_res["error_category"] = "schema_error"
                src_res["error"] = "Event.authors and Event.topics must be lists"
                continue

            src_res["items_normalized"] += 1
            events.append(event)

        # Stage 5: Filter & Score
        current_stage = "filter_and_score"
        for ev in events:
            try:
                passed = filter_event(ev, interests_cfg)
                if not passed:
                    src_res["items_rejected"] += 1
                    continue
                scored = score_event(ev, interests_cfg)
                if scored:
                    src_res["scored_events"] += 1
            except Exception as e:
                cat, san_err = sanitize_error(e)
                src_res["failing_stage"] = "score"
                src_res["error_category"] = cat
                src_res["error"] = san_err
                src_res["exception_type"] = type(e).__name__

        # Compute status
        if src_res["items_failed"] > 0 and src_res["items_normalized"] > 0:
            src_res["status"] = "partial"
        elif src_res["items_failed"] > 0 and src_res["items_normalized"] == 0:
            src_res["status"] = "failed"
        elif src_res["error"]:
            src_res["status"] = "failed"
        else:
            src_res["status"] = "completed"

        diagnostic_results.append(src_res)

    return diagnostic_results


def main():
    parser = argparse.ArgumentParser(description="HERMES Read-Only Source Adapter Diagnostic Tool")
    parser.add_argument("--source", type=str, default="all", help="Source adapter name or 'all'")
    parser.add_argument("--limit", type=int, default=2, help="Max items to fetch per source (default: 2)")
    parser.add_argument("--no-persist", action="store_true", default=True, help="Enforce non-mutating inspection (default: True)")
    args = parser.parse_args()

    results = run_source_diagnosis(
        source_filter=args.source,
        limit=args.limit,
        no_persist=args.no_persist,
    )

    out_lines = [
        "=" * 70,
        f"HERMES SOURCE ADAPTER DIAGNOSTIC REPORT ({datetime.now(timezone.utc).isoformat()})",
        f"MODE: NON-MUTATING INSPECTION (no-persist={args.no_persist})",
        "=" * 70,
        "",
    ]

    for r in results:
        status_tag = f"[{r['status'].upper()}]"
        out_lines.append(f"Source: {r['source']:<18} Status: {status_tag:<12} Fetched: {r.get('items_fetched', 0)} | Normalized: {r.get('items_normalized', 0)} | Failed: {r.get('items_failed', 0)} | Scored: {r.get('scored_events', 0)}")
        if r.get("failing_stage"):
            out_lines.append(f"  -> Failing Stage:     {r['failing_stage']}")
            out_lines.append(f"  -> Error Category:    {r.get('error_category')}")
            out_lines.append(f"  -> Exception Type:    {r.get('exception_type')}")
            out_lines.append(f"  -> Sanitized Error:   {r.get('error')}")
            if r.get("raw_item_type"):
                out_lines.append(f"  -> Raw Item Type:     {r['raw_item_type']}")
        out_lines.append("-" * 70)

    report_text = "\n".join(out_lines) + "\n"
    print(report_text)

    # Save to evidence/phase16/source_diagnostic.txt
    evidence_dir = Path("evidence/phase16")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out_file = evidence_dir / "source_diagnostic.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"Saved diagnostic report to {out_file}")


if __name__ == "__main__":
    main()
