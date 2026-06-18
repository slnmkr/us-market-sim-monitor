#!/usr/bin/env python3
"""Review planned paper orders against the latest local market snapshot.

The output is a recommendation file only. This script never edits the trade
ledger unless a future explicit workflow adds a separate apply step.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .market_monitor import quote_summary
    from .paper_account import load_trades, planned_orders
except ImportError:  # pragma: no cover - used when executed as a script.
    from market_monitor import quote_summary
    from paper_account import load_trades, planned_orders


ROOT = Path(__file__).resolve().parents[1]
TRADES = ROOT / "journal" / "paper_trades.csv"
SNAPSHOTS = ROOT / "data" / "market_snapshots"
EVENT_RISK = ROOT / "data" / "event_risk"
FILL_REVIEWS = ROOT / "journal" / "fill_reviews"
WATCHLIST = ROOT / "config" / "watchlist.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def review_plans(
    as_of: str,
    *,
    trades_path: Path = TRADES,
    snapshot_path: Path | None = None,
    event_risk_path: Path | None = None,
    watchlist_path: Path = WATCHLIST,
    max_gap_pct: float = 1.5,
) -> dict[str, Any]:
    snapshot_path = snapshot_path or (SNAPSHOTS / f"{as_of}.json")
    event_risk_path = event_risk_path or (EVENT_RISK / f"{as_of}.json")
    snapshot = load_json(snapshot_path)
    quotes = quote_summary(snapshot)
    risk_gate = _load_risk_gate(as_of, event_risk_path, watchlist_path)
    reviews = _apply_risk_gate(
        [
            _review_order(as_of, order, quotes.get(order["symbol"]), max_gap_pct)
            for order in planned_orders(load_trades(trades_path))
        ],
        risk_gate,
    )
    return {
        "as_of": as_of,
        "snapshot": str(snapshot_path),
        "event_risk": str(event_risk_path),
        "data_boundary": "Synthetic paper-fill review only; no broker order, account access, or live execution.",
        "max_gap_pct": max_gap_pct,
        "risk_gate": risk_gate,
        "summary": _summary(reviews),
        "reviews": reviews,
    }


def _load_risk_gate(as_of: str, event_risk_path: Path, watchlist_path: Path) -> dict[str, Any]:
    if not event_risk_path.exists():
        return {
            "status": "missing_event_risk",
            "event_risk_path": str(event_risk_path),
            "risk_level": "unknown",
            "max_new_gross_exposure_pct": None,
            "starting_cash": None,
            "max_new_gross_exposure_usd": None,
            "reason": "event risk artifact is required before same-day synthetic fills can be considered",
        }
    event_risk = load_json(event_risk_path)
    current = event_risk.get("current_risk", {})
    cap = current.get("max_new_gross_exposure_pct")
    starting_cash = _starting_cash(watchlist_path)
    try:
        max_exposure = float(cap) * starting_cash if cap is not None and starting_cash is not None else None
    except (TypeError, ValueError):
        max_exposure = None
    return {
        "status": "ok" if event_risk.get("as_of") == as_of else "event_risk_date_mismatch",
        "event_risk_path": str(event_risk_path),
        "risk_level": current.get("risk_level", "unknown"),
        "max_new_gross_exposure_pct": cap,
        "starting_cash": starting_cash,
        "max_new_gross_exposure_usd": max_exposure,
        "reasons": current.get("reasons", []),
        "actions": current.get("actions", []),
    }


def _starting_cash(watchlist_path: Path) -> float | None:
    if not watchlist_path.exists():
        return None
    try:
        return float(load_json(watchlist_path).get("paper_account", {}).get("starting_cash"))
    except (TypeError, ValueError):
        return None


def _apply_risk_gate(reviews: list[dict[str, Any]], risk_gate: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [item for item in reviews if item.get("decision") == "fill_candidate"]
    if not candidates:
        return reviews

    if risk_gate.get("status") != "ok":
        return [
            _block_candidate(item, "blocked_missing_event_risk", risk_gate.get("reason") or risk_gate.get("status", "event risk unavailable"))
            if item.get("decision") == "fill_candidate"
            else item
            for item in reviews
        ]

    risk_level = risk_gate.get("risk_level")
    if risk_level == "closed":
        return [
            _block_candidate(item, "blocked_event_risk", "event risk level is closed; no synthetic fills are allowed")
            if item.get("decision") == "fill_candidate"
            else item
            for item in reviews
        ]

    cap_usd = risk_gate.get("max_new_gross_exposure_usd")
    if cap_usd is None:
        return [
            _block_candidate(item, "blocked_event_risk", "event risk cap could not be computed from watchlist starting cash")
            if item.get("decision") == "fill_candidate"
            else item
            for item in reviews
        ]

    candidate_new_gross = sum(
        float(item.get("fill_notional_usd", 0.0))
        for item in candidates
        if item.get("side") == "buy"
    )
    if candidate_new_gross > float(cap_usd) + 1e-9:
        reason = f"candidate new gross {candidate_new_gross:.2f} exceeds event-risk cap {float(cap_usd):.2f}"
        return [
            _block_candidate(
                item,
                "blocked_event_risk",
                reason,
                candidate_new_gross_usd=candidate_new_gross,
                max_new_gross_exposure_usd=float(cap_usd),
            )
            if item.get("decision") == "fill_candidate"
            else item
            for item in reviews
        ]

    return [
        {
            **item,
            "risk_gate_decision": "passed_event_risk_cap",
            "risk_level": risk_level,
            "candidate_new_gross_usd": candidate_new_gross,
            "max_new_gross_exposure_usd": float(cap_usd),
        }
        if item.get("decision") == "fill_candidate"
        else item
        for item in reviews
    ]


def _block_candidate(
    review: dict[str, Any],
    decision: str,
    reason: str,
    **extra: Any,
) -> dict[str, Any]:
    out = {key: value for key, value in review.items() if key != "suggested_trade_row"}
    return {
        **out,
        **extra,
        "decision": decision,
        "prior_decision": review.get("decision"),
        "reason": reason,
    }


def write_review(as_of: str, payload: dict[str, Any], output_dir: Path = FILL_REVIEWS) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{as_of}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def _review_order(
    as_of: str,
    order: dict[str, Any],
    quote: dict[str, Any] | None,
    max_gap_pct: float,
) -> dict[str, Any]:
    trade_date = order["trade_date"]
    base = {
        "planned_trade_date": trade_date,
        "as_of": as_of,
        "symbol": order["symbol"],
        "side": order["side"],
        "quantity": order["quantity"],
        "reference_price": order["price"],
        "reference_notional": order["notional_usd"],
        "source": order["sources"],
    }
    if trade_date > as_of:
        return {
            **base,
            "decision": "pending_future",
            "reason": f"planned trade date {trade_date} is after review date {as_of}",
        }
    if trade_date < as_of:
        return {
            **base,
            "decision": "stale_unfilled",
            "reason": f"planned trade date {trade_date} is before review date {as_of}; manual review required",
        }
    if quote is None:
        return {
            **base,
            "decision": "blocked_missing_quote",
            "reason": "no quote found in local snapshot",
        }

    latest_date = quote.get("date_utc")
    close = quote.get("close")
    if latest_date != as_of:
        return {
            **base,
            "decision": "blocked_stale_quote",
            "latest_quote_date": latest_date,
            "latest_close": close,
            "reason": f"latest quote date {latest_date} does not match planned trade date {as_of}",
        }
    if close is None:
        return {
            **base,
            "decision": "blocked_missing_price",
            "latest_quote_date": latest_date,
            "reason": "latest quote has no close price",
        }

    gap_pct = abs(float(close) - order["price"]) / order["price"] * 100.0 if order["price"] else 0.0
    if gap_pct > max_gap_pct:
        return {
            **base,
            "decision": "blocked_gap",
            "latest_quote_date": latest_date,
            "latest_close": close,
            "gap_pct": gap_pct,
            "reason": f"gap {gap_pct:.2f}% exceeds {max_gap_pct:.2f}% limit",
        }

    notional = float(close) * order["quantity"]
    return {
        **base,
        "decision": "fill_candidate",
        "latest_quote_date": latest_date,
        "fill_price": close,
        "fill_notional_usd": notional,
        "gap_pct": gap_pct,
        "suggested_trade_row": {
            "trade_date": as_of,
            "time_et": "close",
            "symbol": order["symbol"],
            "side": order["side"],
            "quantity": f"{order['quantity']:.8g}",
            "price": f"{float(close):.4f}",
            "status": "filled",
            "notional_usd": f"{notional:.2f}",
            "reason": f"Paper fill candidate generated from local snapshot on {as_of}.",
            "sources": quote.get("source") or order["sources"],
            "notes": "Synthetic fill candidate only; not a broker execution.",
        },
        "reason": "latest quote matches planned date and is within gap limit",
    }


def _summary(reviews: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in reviews:
        decision = item["decision"]
        counts[decision] = counts.get(decision, 0) + 1
    counts["total"] = len(reviews)
    return counts


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Review date YYYY-MM-DD")
    parser.add_argument("--max-gap-pct", type=float, default=1.5, help="Max reference-price gap for fill candidates")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of the output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = review_plans(args.date, max_gap_pct=args.max_gap_pct)
    path = write_review(args.date, payload)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
