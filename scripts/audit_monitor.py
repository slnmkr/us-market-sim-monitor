#!/usr/bin/env python3
"""Audit local market-monitor artifacts for a given date.

This script is deliberately offline. It checks whether the local paper-account
records, source checks, reports, snapshots, and equity curve are internally
consistent before a daily git commit is considered usable.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .paper_account import load_trades, validate_trades
except ImportError:  # pragma: no cover - used when executed as a script.
    from paper_account import load_trades, validate_trades


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "config" / "watchlist.json"
TRADES = ROOT / "journal" / "paper_trades.csv"
EQUITY_CURVE = ROOT / "data" / "equity_curve.csv"
SNAPSHOTS = ROOT / "data" / "market_snapshots"
SOURCE_CHECKS = ROOT / "data" / "source_checks"
REPORTS = ROOT / "reports"


@dataclass
class AuditResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def audit_date(as_of: str, *, root: Path = ROOT) -> AuditResult:
    errors: list[str] = []
    warnings: list[str] = []
    watchlist_path = root / "config" / "watchlist.json"
    trades_path = root / "journal" / "paper_trades.csv"
    equity_path = root / "data" / "equity_curve.csv"
    snapshot_path = root / "data" / "market_snapshots" / f"{as_of}.json"
    source_path = root / "data" / "source_checks" / f"{as_of}.json"
    event_risk_path = root / "data" / "event_risk" / f"{as_of}.json"
    fill_review_path = root / "journal" / "fill_reviews" / f"{as_of}.json"
    manual_report_path = root / "reports" / f"{as_of}.md"
    generated_report_path = root / "reports" / f"{as_of}.generated.md"

    watchlist = _required_json(watchlist_path, errors)
    if watchlist:
        starting_cash = float(watchlist.get("paper_account", {}).get("starting_cash", 0.0))
        if starting_cash <= 0:
            errors.append("watchlist paper_account.starting_cash must be positive")
    else:
        starting_cash = 0.0

    if trades_path.exists():
        trade_errors = validate_trades(load_trades(trades_path), starting_cash)
        errors.extend(f"trade ledger: {item}" for item in trade_errors)
    else:
        errors.append(f"missing trade ledger {trades_path}")

    snapshot = _required_json(snapshot_path, errors)
    if snapshot:
        _audit_snapshot(snapshot, as_of, errors, warnings)

    source_check = _required_json(source_path, errors)
    if source_check:
        _audit_source_check(source_check, as_of, errors)

    event_risk = _required_json(event_risk_path, errors)
    if event_risk:
        _audit_event_risk(event_risk, as_of, errors)

    fill_review = _required_json(fill_review_path, errors)
    if fill_review:
        _audit_fill_review(fill_review, as_of, errors)

    _audit_equity_curve(equity_path, as_of, starting_cash, errors)
    _audit_report(manual_report_path, as_of, errors, warnings)
    _audit_report(generated_report_path, as_of, errors, warnings)

    return AuditResult(errors=errors, warnings=warnings)


def _required_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.exists():
        errors.append(f"missing JSON artifact {path}")
        return None
    try:
        return load_json(path)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return None


def _audit_snapshot(
    snapshot: dict[str, Any],
    as_of: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if snapshot.get("as_of") != as_of:
        errors.append(f"snapshot as_of {snapshot.get('as_of')!r} does not match {as_of}")
    if "broker" in snapshot.get("data_boundary", "").lower():
        if "no broker" not in snapshot.get("data_boundary", "").lower():
            errors.append("snapshot data boundary must not imply broker access")
    quotes = snapshot.get("quotes")
    if not isinstance(quotes, list) or not quotes:
        errors.append("snapshot must contain at least one quote")
    for idx, quote in enumerate(quotes or [], start=1):
        symbol = quote.get("symbol", f"quote#{idx}")
        bars = quote.get("bars")
        if not isinstance(bars, list) or not bars:
            errors.append(f"snapshot {symbol}: missing bars")
            continue
        latest = bars[-1]
        if not latest.get("date_utc"):
            errors.append(f"snapshot {symbol}: latest bar missing date_utc")
        if latest.get("close") is None:
            errors.append(f"snapshot {symbol}: latest bar missing close")
        if not quote.get("source", "").startswith("https://"):
            errors.append(f"snapshot {symbol}: source must be an https URL")
    if snapshot.get("errors"):
        warnings.append(f"snapshot has data gaps: {len(snapshot['errors'])}")


def _audit_source_check(source_check: dict[str, Any], as_of: str, errors: list[str]) -> None:
    if source_check.get("as_of") != as_of:
        errors.append(f"source check as_of {source_check.get('as_of')!r} does not match {as_of}")
    boundary = source_check.get("data_boundary", "")
    if "Real public web sources only" not in boundary:
        errors.append("source check must state public-source-only data boundary")
    checks = source_check.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("source check must contain at least one check")
        return
    topics = {item.get("topic") for item in checks}
    for required in {"market_holiday", "latest_us_equity_close", "fomc", "nonfarm_payroll_next"}:
        if required not in topics:
            errors.append(f"source check missing required topic {required}")
    for idx, item in enumerate(checks, start=1):
        topic = item.get("topic", f"check#{idx}")
        if not item.get("source_url", "").startswith("https://"):
            errors.append(f"source check {topic}: source_url must be an https URL")
        facts = item.get("facts")
        if not isinstance(facts, list) or not facts:
            errors.append(f"source check {topic}: facts must be a non-empty list")
        if not item.get("paper_account_impact", "").strip():
            errors.append(f"source check {topic}: missing paper_account_impact")


def _audit_equity_curve(path: Path, as_of: str, starting_cash: float, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"missing equity curve {path}")
        return
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    row = next((item for item in rows if item.get("date") == as_of), None)
    if row is None:
        errors.append(f"equity curve missing row for {as_of}")
        return
    for field in ["cash", "positions_value", "total_equity", "realized_pnl", "unrealized_pnl", "return_pct"]:
        try:
            float(row.get(field, ""))
        except ValueError:
            errors.append(f"equity curve {as_of}: {field} must be numeric")
    total = _to_float(row.get("total_equity"))
    if total is not None and starting_cash > 0:
        expected = (total - starting_cash) / starting_cash * 100.0
        actual = _to_float(row.get("return_pct"))
        if actual is not None and abs(expected - actual) > 0.01:
            errors.append(f"equity curve {as_of}: return_pct is inconsistent with total_equity")


def _audit_fill_review(fill_review: dict[str, Any], as_of: str, errors: list[str]) -> None:
    if fill_review.get("as_of") != as_of:
        errors.append(f"fill review as_of {fill_review.get('as_of')!r} does not match {as_of}")
    boundary = fill_review.get("data_boundary", "").lower()
    if "synthetic paper-fill review only" not in boundary:
        errors.append("fill review must state synthetic paper-fill-only data boundary")
    reviews = fill_review.get("reviews")
    if not isinstance(reviews, list):
        errors.append("fill review reviews must be a list")
        return
    allowed = {
        "pending_future",
        "stale_unfilled",
        "blocked_missing_quote",
        "blocked_stale_quote",
        "blocked_missing_price",
        "blocked_gap",
        "fill_candidate",
    }
    for idx, review in enumerate(reviews, start=1):
        decision = review.get("decision")
        if decision not in allowed:
            errors.append(f"fill review row {idx}: invalid decision {decision!r}")
        if decision == "fill_candidate":
            row = review.get("suggested_trade_row")
            if not isinstance(row, dict):
                errors.append(f"fill review row {idx}: fill_candidate missing suggested_trade_row")
            elif row.get("status") != "filled":
                errors.append(f"fill review row {idx}: suggested_trade_row status must be filled")
            notes = (row or {}).get("notes", "").lower()
            if "not a broker execution" not in notes:
                errors.append(f"fill review row {idx}: suggested_trade_row must state not a broker execution")


def _audit_event_risk(event_risk: dict[str, Any], as_of: str, errors: list[str]) -> None:
    if event_risk.get("as_of") != as_of:
        errors.append(f"event risk as_of {event_risk.get('as_of')!r} does not match {as_of}")
    boundary = event_risk.get("data_boundary", "").lower()
    if "no broker" not in boundary or "source-backed local event config" not in boundary:
        errors.append("event risk must state local source-backed/no-broker data boundary")
    current = event_risk.get("current_risk")
    if not isinstance(current, dict):
        errors.append("event risk current_risk must be an object")
        return
    if current.get("risk_level") not in {"normal", "medium", "high", "closed"}:
        errors.append(f"event risk has invalid risk_level {current.get('risk_level')!r}")
    try:
        cap = float(current.get("max_new_gross_exposure_pct"))
    except (TypeError, ValueError):
        errors.append("event risk max_new_gross_exposure_pct must be numeric")
        return
    if not 0.0 <= cap <= 1.0:
        errors.append("event risk max_new_gross_exposure_pct must be between 0 and 1")
    if not isinstance(event_risk.get("next_events"), list):
        errors.append("event risk next_events must be a list")


def _audit_report(path: Path, as_of: str, errors: list[str], warnings: list[str]) -> None:
    if not path.exists():
        errors.append(f"missing report {path}")
        return
    text = path.read_text(encoding="utf-8")
    if as_of not in text:
        errors.append(f"report {path.name}: missing as_of date {as_of}")
    for required in ["no broker", "Paper", "source"]:
        if required.lower() not in text.lower():
            warnings.append(f"report {path.name}: does not mention {required!r}")
    forbidden = ["guaranteed return", "stable return guaranteed", "live order placed"]
    for phrase in forbidden:
        if phrase in text.lower():
            errors.append(f"report {path.name}: forbidden claim {phrase!r}")


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Audit date YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = audit_date(args.date)
    payload = {"ok": result.ok, "errors": result.errors, "warnings": result.warnings}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print("OK" if result.ok else "FAIL")
        for warning in result.warnings:
            print(f"WARN: {warning}")
        for error in result.errors:
            print(f"ERROR: {error}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
