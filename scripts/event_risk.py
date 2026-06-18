#!/usr/bin/env python3
"""Generate deterministic macro-event risk windows for the paper account."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "config" / "economic_events.json"
RISK_POLICY = ROOT / "config" / "risk_policy.json"
EVENT_RISK_DIR = ROOT / "data" / "event_risk"

SEVERITY = {"normal": 0, "medium": 1, "high": 2, "closed": 3}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def assess_event_risk(
    as_of: str,
    *,
    events_path: Path = EVENTS,
    policy_path: Path = RISK_POLICY,
) -> dict[str, Any]:
    events = load_json(events_path).get("events", [])
    policy = load_json(policy_path)
    as_of_date = date.fromisoformat(as_of)
    active: list[dict[str, Any]] = []
    next_events: list[dict[str, Any]] = []

    for event in events:
        event_date = date.fromisoformat(event["date"])
        days_until = (event_date - as_of_date).days
        matched = _matching_policy(event, policy.get("policies", []))
        if event_date >= as_of_date:
            next_events.append(_event_summary(event, matched, days_until))
        if matched and -int(matched["post_days"]) <= days_until <= int(matched["pre_days"]):
            active.append(_event_summary(event, matched, days_until))

    next_events.sort(key=lambda item: (item["days_until"], item["event"]))
    current = _current_risk(policy.get("default", {}), active)
    return {
        "as_of": as_of,
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "data_boundary": "Deterministic risk-window assessment from source-backed local event config; no broker or account data.",
        "current_risk": current,
        "active_events": active,
        "next_events": next_events[:8],
    }


def write_event_risk(as_of: str, payload: dict[str, Any], output_dir: Path = EVENT_RISK_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{as_of}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def _matching_policy(event: dict[str, Any], policies: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in policies:
        match = item.get("match", {})
        status = match.get("status")
        contains = match.get("event_contains")
        if status and event.get("status") != status:
            continue
        if contains and contains.lower() not in event.get("event", "").lower():
            continue
        return item
    return None


def _event_summary(event: dict[str, Any], policy: dict[str, Any] | None, days_until: int) -> dict[str, Any]:
    return {
        "date": event["date"],
        "time_et": event.get("time_et", ""),
        "event": event["event"],
        "status": event["status"],
        "days_until": days_until,
        "source": event.get("source", ""),
        "risk_label": policy.get("label", "none") if policy else "none",
        "risk_level": policy.get("risk_level", "normal") if policy else "normal",
        "max_new_gross_exposure_pct": policy.get("max_new_gross_exposure_pct") if policy else None,
        "action": policy.get("action", "") if policy else "",
    }


def _current_risk(default: dict[str, Any], active: list[dict[str, Any]]) -> dict[str, Any]:
    level = default.get("risk_level", "normal")
    max_exposure = float(default.get("max_new_gross_exposure_pct", 0.9))
    reasons: list[str] = []
    actions: list[str] = []
    for event in active:
        event_level = event.get("risk_level", "normal")
        if SEVERITY.get(event_level, 0) > SEVERITY.get(level, 0):
            level = event_level
        cap = event.get("max_new_gross_exposure_pct")
        if cap is not None:
            max_exposure = min(max_exposure, float(cap))
        reasons.append(f"{event['event']} ({event['date']}, days_until={event['days_until']})")
        if event.get("action"):
            actions.append(event["action"])
    return {
        "risk_level": level,
        "max_new_gross_exposure_pct": max_exposure,
        "reasons": reasons or [default.get("note", "No active macro risk window.")],
        "actions": sorted(set(actions)) if actions else [],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Assessment date YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of the output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = assess_event_risk(args.date)
    path = write_event_risk(args.date, payload)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
