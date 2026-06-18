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
FILL_REVIEWS = ROOT / "journal" / "fill_reviews"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def review_plans(
    as_of: str,
    *,
    trades_path: Path = TRADES,
    snapshot_path: Path | None = None,
    max_gap_pct: float = 1.5,
) -> dict[str, Any]:
    snapshot_path = snapshot_path or (SNAPSHOTS / f"{as_of}.json")
    snapshot = load_json(snapshot_path)
    quotes = quote_summary(snapshot)
    reviews = [
        _review_order(as_of, order, quotes.get(order["symbol"]), max_gap_pct)
        for order in planned_orders(load_trades(trades_path))
    ]
    return {
        "as_of": as_of,
        "snapshot": str(snapshot_path),
        "data_boundary": "Synthetic paper-fill review only; no broker order, account access, or live execution.",
        "max_gap_pct": max_gap_pct,
        "summary": _summary(reviews),
        "reviews": reviews,
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

