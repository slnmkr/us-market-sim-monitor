#!/usr/bin/env python3
"""Build paper-account performance metrics from local artifacts only."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EQUITY_CURVE = ROOT / "data" / "equity_curve.csv"
SNAPSHOTS = ROOT / "data" / "market_snapshots"
PERFORMANCE_DIR = ROOT / "data" / "performance"


def build_performance(
    as_of: str,
    *,
    equity_curve_path: Path = EQUITY_CURVE,
    snapshots_dir: Path = SNAPSHOTS,
    benchmark_symbol: str = "SPY",
) -> dict[str, Any]:
    rows = [row for row in _load_equity_curve(equity_curve_path) if row["date"] <= as_of]
    rows.sort(key=lambda row: row["date"])
    if not rows:
        return {
            "as_of": as_of,
            "data_boundary": "Local paper equity curve only; no broker or account data.",
            "status": "missing_equity_curve",
            "errors": [f"no equity curve rows on or before {as_of}"],
        }

    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    starting_equity = rows[0]["total_equity"]
    total_return_pct = _pct(latest["total_equity"], starting_equity)
    one_day_return_pct = _pct(latest["total_equity"], previous["total_equity"]) if previous else 0.0
    max_drawdown_pct = _max_drawdown_pct([row["total_equity"] for row in rows])
    benchmark = _benchmark_summary(rows, snapshots_dir, benchmark_symbol)

    return {
        "as_of": as_of,
        "data_boundary": "Local paper equity curve and public market snapshots only; no broker or account data.",
        "status": "ok",
        "paper": {
            "start_date": rows[0]["date"],
            "latest_date": latest["date"],
            "observations": len(rows),
            "starting_equity": starting_equity,
            "latest_equity": latest["total_equity"],
            "cash": latest["cash"],
            "positions_value": latest["positions_value"],
            "total_return_pct": total_return_pct,
            "one_day_return_pct": one_day_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
        },
        "benchmark": benchmark,
        "comparison": _comparison(total_return_pct, benchmark),
    }


def write_performance(as_of: str, payload: dict[str, Any], output_dir: Path = PERFORMANCE_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{as_of}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def _load_equity_curve(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = []
        for row in csv.DictReader(fh):
            rows.append(
                {
                    "date": row["date"],
                    "cash": float(row["cash"]),
                    "positions_value": float(row["positions_value"]),
                    "total_equity": float(row["total_equity"]),
                    "realized_pnl": float(row["realized_pnl"]),
                    "unrealized_pnl": float(row["unrealized_pnl"]),
                    "return_pct": float(row["return_pct"]),
                }
            )
        return rows


def _benchmark_summary(rows: list[dict[str, Any]], snapshots_dir: Path, symbol: str) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in rows:
        snapshot_path = snapshots_dir / f"{row['date']}.json"
        if not snapshot_path.exists():
            missing.append(row["date"])
            continue
        snapshot = _load_json(snapshot_path)
        quote = next((item for item in snapshot.get("quotes", []) if item.get("symbol") == symbol), None)
        if not quote or not quote.get("bars"):
            missing.append(row["date"])
            continue
        bar = quote["bars"][-1]
        close = bar.get("close")
        if close is None:
            missing.append(row["date"])
            continue
        observations.append(
            {
                "date": row["date"],
                "quote_date_utc": bar.get("date_utc"),
                "close": float(close),
                "source": quote.get("source", ""),
            }
        )

    if not observations:
        return {
            "symbol": symbol,
            "status": "missing",
            "missing_dates": missing,
        }

    start = observations[0]
    latest = observations[-1]
    return {
        "symbol": symbol,
        "status": "ok",
        "start_date": start["date"],
        "latest_date": latest["date"],
        "start_quote_date_utc": start["quote_date_utc"],
        "latest_quote_date_utc": latest["quote_date_utc"],
        "start_close": start["close"],
        "latest_close": latest["close"],
        "total_return_pct": _pct(latest["close"], start["close"]),
        "observations": len(observations),
        "missing_dates": missing,
        "source": latest["source"],
    }


def _comparison(paper_return_pct: float, benchmark: dict[str, Any]) -> dict[str, Any]:
    if benchmark.get("status") != "ok":
        return {"status": "missing_benchmark"}
    benchmark_return = float(benchmark["total_return_pct"])
    return {
        "status": "ok",
        "excess_return_pct": paper_return_pct - benchmark_return,
        "paper_return_pct": paper_return_pct,
        "benchmark_return_pct": benchmark_return,
    }


def _pct(current: float, base: float) -> float:
    if base == 0:
        return 0.0
    return (current - base) / base * 100.0


def _max_drawdown_pct(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak * 100.0)
    return worst


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Performance date YYYY-MM-DD")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark symbol from local snapshots")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = build_performance(args.date, benchmark_symbol=args.benchmark)
    path = write_performance(args.date, payload)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(path)
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

