#!/usr/bin/env python3
"""Create a compact daily run card from local monitor artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_CARDS = ROOT / "data" / "run_cards"


def build_run_card(as_of: str, *, root: Path = ROOT) -> dict[str, Any]:
    event_risk = _load_json(root / "data" / "event_risk" / f"{as_of}.json")
    performance = _load_json(root / "data" / "performance" / f"{as_of}.json")
    fill_review = _load_json(root / "journal" / "fill_reviews" / f"{as_of}.json")
    apply_log = _load_apply_log(root, as_of)
    live_gate = _load_json(root / "data" / "live_gate" / f"{as_of}.json")
    source_check = _load_json(root / "data" / "source_checks" / f"{as_of}.json")

    decisions = _fill_decisions(fill_review)
    overall = _overall_status(event_risk, performance, apply_log, live_gate)
    return {
        "as_of": as_of,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "data_boundary": "Local run card from public-source paper-monitor artifacts only; no broker connection, no secrets, no account access, no live orders.",
        "overall_status": overall,
        "market": {
            "risk_level": event_risk["current_risk"]["risk_level"],
            "max_new_gross_exposure_pct": event_risk["current_risk"]["max_new_gross_exposure_pct"],
            "active_events": [
                {
                    "event": item["event"],
                    "date": item["date"],
                    "risk_level": item["risk_level"],
                    "source": item["source"],
                }
                for item in event_risk.get("active_events", [])
            ],
            "next_events": [
                {
                    "event": item["event"],
                    "date": item["date"],
                    "time_et": item.get("time_et", ""),
                    "days_until": item["days_until"],
                    "risk_level": item["risk_level"],
                    "source": item["source"],
                }
                for item in event_risk.get("next_events", [])
            ],
        },
        "paper_account": {
            "performance_status": performance["status"],
            "observations": performance.get("paper", {}).get("observations", 0),
            "latest_equity": performance.get("paper", {}).get("latest_equity"),
            "total_return_pct": performance.get("paper", {}).get("total_return_pct"),
            "max_drawdown_pct": performance.get("paper", {}).get("max_drawdown_pct"),
            "benchmark": performance.get("benchmark", {}),
            "comparison": performance.get("comparison", {}),
        },
        "paper_execution": {
            "fill_decisions": decisions,
            "risk_gate": fill_review.get("risk_gate", {}),
            "apply_mode": apply_log.get("mode"),
            "applied_count": apply_log.get("applied_count"),
            "dry_run_append_count": apply_log.get("dry_run_append_count"),
            "candidate_count": apply_log.get("candidate_count"),
        },
        "live_gate": {
            "status": live_gate["status"],
            "blocker_codes": [item["code"] for item in live_gate.get("blockers", [])],
            "required_file_statuses": {
                item.get("path", f"required_file_{idx}"): item.get("status")
                for idx, item in enumerate(live_gate.get("required_file_checks", []), start=1)
            },
            "warnings": live_gate.get("warnings", []),
        },
        "source_check": {
            "check_count": len(source_check.get("checks", [])),
            "topics": [item.get("topic") for item in source_check.get("checks", [])],
        },
        "next_actions": _next_actions(event_risk, fill_review, live_gate),
    }


def write_run_card(as_of: str, payload: dict[str, Any], output_dir: Path = RUN_CARDS) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{as_of}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def _overall_status(event_risk: dict[str, Any], performance: dict[str, Any], apply_log: dict[str, Any], live_gate: dict[str, Any]) -> str:
    if performance.get("status") != "ok":
        return "needs_data_repair"
    if event_risk.get("current_risk", {}).get("risk_level") == "closed":
        return "market_closed_no_trade"
    if apply_log.get("applied_count", 0):
        return "paper_fills_applied"
    if apply_log.get("dry_run_append_count", 0):
        return "paper_fill_candidates_pending_apply"
    if live_gate.get("status") == "blocked":
        return "paper_monitoring_live_blocked"
    return "paper_monitoring_live_review_possible"


def _fill_decisions(fill_review: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in fill_review.get("reviews", []):
        decision = item.get("decision", "unknown")
        out[decision] = out.get(decision, 0) + 1
    out["total"] = len(fill_review.get("reviews", []))
    return out


def _next_actions(event_risk: dict[str, Any], fill_review: dict[str, Any], live_gate: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if event_risk.get("current_risk", {}).get("risk_level") == "closed":
        actions.append("No paper fills or new paper entries while the market is closed.")
    if any(item.get("decision") == "fill_candidate" for item in fill_review.get("reviews", [])):
        actions.append("Review fill candidates and only apply source-backed synthetic fills deliberately.")
    if live_gate.get("status") == "blocked":
        actions.append("Keep live trading disabled; resolve live gate blockers before any broker review.")
    if not actions:
        actions.append("Continue paper monitoring and source-backed reporting.")
    return actions


def _load_apply_log(root: Path, as_of: str) -> dict[str, Any]:
    dry_run = root / "journal" / "apply_logs" / f"{as_of}.dry_run.json"
    applied = root / "journal" / "apply_logs" / f"{as_of}.apply.json"
    if applied.exists():
        return _load_json(applied)
    return _load_json(dry_run)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Run-card date YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = build_run_card(args.date)
    path = write_run_card(args.date, payload)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
