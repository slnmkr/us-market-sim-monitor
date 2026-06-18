#!/usr/bin/env python3
"""Generate a source-aware market snapshot and paper-account report.

The script only handles public market data and local paper trades. It never
connects to a broker and never sends orders.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .paper_account import (
        build_portfolio,
        load_trades,
        mark_to_market,
        planned_orders,
        upsert_equity_curve,
        validate_trades,
    )
except ImportError:  # pragma: no cover - used when executed as a script.
    from paper_account import (
        build_portfolio,
        load_trades,
        mark_to_market,
        planned_orders,
        upsert_equity_curve,
        validate_trades,
    )


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "config" / "watchlist.json"
EVENTS = ROOT / "config" / "economic_events.json"
TRADES = ROOT / "journal" / "paper_trades.csv"
SNAPSHOTS = ROOT / "data" / "market_snapshots"
REPORTS = ROOT / "reports"
EQUITY_CURVE = ROOT / "data" / "equity_curve.csv"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def fetch_yahoo_chart(symbol: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=10d&interval=1d"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "us-market-sim-monitor/0.1 (+local paper trading research)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo chart error for {symbol}: {error}")

    result = payload["chart"]["result"][0]
    meta = result.get("meta", {})
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        close = closes[idx] if idx < len(closes) else None
        if close is None or (isinstance(close, float) and math.isnan(close)):
            continue
        bars.append(
            {
                "date_utc": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                "open": _safe_number(opens, idx),
                "high": _safe_number(highs, idx),
                "low": _safe_number(lows, idx),
                "close": float(close),
                "volume": _safe_number(volumes, idx),
            }
        )

    if not bars:
        raise RuntimeError(f"No usable bars returned for {symbol}")

    return {
        "symbol": symbol,
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
        "regular_market_price": meta.get("regularMarketPrice"),
        "source": url,
        "bars": bars,
    }


def _safe_number(values: list[Any], idx: int) -> float | int | None:
    if idx >= len(values):
        return None
    value = values[idx]
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def quote_summary(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in snapshot.get("quotes", []):
        bars = item.get("bars", [])
        if not bars:
            continue
        latest = bars[-1]
        prev = bars[-2] if len(bars) > 1 else None
        close = latest["close"]
        prev_close = prev["close"] if prev else None
        change = close - prev_close if prev_close else None
        pct = (change / prev_close * 100.0) if prev_close else None
        out[item["symbol"]] = {
            "date_utc": latest["date_utc"],
            "close": close,
            "previous_close": prev_close,
            "change": change,
            "change_pct": pct,
            "source": item.get("source"),
        }
    return out


def write_snapshot(as_of: str, watchlist: dict[str, Any]) -> dict[str, Any]:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "as_of": as_of,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "data_boundary": "Public Yahoo Finance chart endpoint; no broker or account data.",
        "quotes": [],
        "errors": [],
    }
    for entry in watchlist["symbols"]:
        symbol = entry["symbol"]
        try:
            quote = fetch_yahoo_chart(symbol)
            quote["name"] = entry.get("name")
            quote["role"] = entry.get("role")
            snapshot["quotes"].append(quote)
        except Exception as exc:  # noqa: BLE001 - report data gaps explicitly.
            snapshot["errors"].append({"symbol": symbol, "error": str(exc)})

    path = SNAPSHOTS / f"{as_of}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return snapshot


def render_report(as_of: str, snapshot: dict[str, Any], watchlist: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    quotes = quote_summary(snapshot)
    trades = load_trades(TRADES)
    account = watchlist["paper_account"]
    starting_cash = float(account["starting_cash"])
    rule_errors = validate_trades(trades, starting_cash)
    mtm = mark_to_market(build_portfolio(trades, starting_cash), quotes, starting_cash)
    upsert_equity_curve(EQUITY_CURVE, as_of, snapshot.get("collected_at", ""), mtm)
    plans = planned_orders(trades)
    events = load_json(EVENTS).get("events", [])

    lines = [
        f"# Generated US Market Monitor - {as_of}",
        "",
        f"Collected at: `{snapshot.get('collected_at')}`",
        "",
        "Data boundary: public market data only; no broker credentials, no live orders.",
        "",
        "## Quote Snapshot",
        "",
        "| Symbol | Date UTC | Close | Change | Change % |",
        "|---|---:|---:|---:|---:|",
    ]
    for symbol in [item["symbol"] for item in watchlist["symbols"]]:
        row = quotes.get(symbol)
        if not row:
            lines.append(f"| {symbol} | n/a | n/a | n/a | n/a |")
            continue
        lines.append(
            "| {symbol} | {date} | {close:.2f} | {change} | {pct} |".format(
                symbol=symbol,
                date=row["date_utc"],
                close=row["close"],
                change=_fmt(row["change"]),
                pct=_fmt(row["change_pct"], suffix="%"),
            )
        )

    lines.extend(
        [
            "",
            "## Paper Account Mark-to-Market",
            "",
            f"Starting cash: `${starting_cash:,.2f}`",
            f"Current cash from filled trades: `${mtm['cash']:,.2f}`",
            f"Positions value from filled trades: `${mtm['positions_value']:,.2f}`",
            f"Total equity from filled trades: `${mtm['total_equity']:,.2f}`",
            f"Total return from filled trades: `{mtm['return_pct']:,.4f}%`",
            "",
            "| Symbol | Quantity | Cost Basis | Close | Market Value | Unrealized PnL |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    if not mtm["positions"]:
        lines.append("| none | 0 | 0.00 | n/a | 0.00 | 0.00 |")
    for row in mtm["positions"]:
        lines.append(
            "| {symbol} | {qty:.4f} | {cost:.2f} | {close} | {mv} | {pnl} |".format(
                symbol=row["symbol"],
                qty=row["quantity"],
                cost=row["cost_basis"],
                close=_fmt(row["close"]),
                mv=_fmt(row["market_value"]),
                pnl=_fmt(row["unrealized_pnl"]),
            )
        )

    lines.extend(
        [
            "",
            "## Planned Paper Orders",
            "",
            "| Date | Time ET | Symbol | Side | Quantity | Reference Price | Notional |",
            "|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    if not plans:
        lines.append("| none | n/a | n/a | n/a | 0 | n/a | 0.00 |")
    for row in plans:
        lines.append(
            "| {date} | {time} | {symbol} | {side} | {qty:.4f} | {price} | {notional} |".format(
                date=row["trade_date"],
                time=row["time_et"],
                symbol=row["symbol"],
                side=row["side"],
                qty=row["quantity"],
                price=_fmt(row["price"]),
                notional=_fmt(row["notional_usd"]),
            )
        )

    lines.extend(["", "## Rule Check", ""])
    if rule_errors:
        lines.append("Status: `FAIL`")
        for err in rule_errors:
            lines.append(f"- {err}")
    else:
        lines.append("Status: `PASS`")
        lines.append("- Synthetic-only paper ledger passed status, source, cash, and exposure checks.")

    lines.extend(["", "## Event Register", ""])
    for event in events:
        lines.append(
            f"- {event['date']} {event.get('time_et', '')} ET | {event['status']} | "
            f"{event['event']} | source: {event['source']}"
        )

    if snapshot.get("errors"):
        lines.extend(["", "## Data Gaps", ""])
        for err in snapshot["errors"]:
            lines.append(f"- {err['symbol']}: {err['error']}")

    path = REPORTS / f"{as_of}.generated.md"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    return path


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.2f}{suffix}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now().date().isoformat(), help="Report date YYYY-MM-DD")
    parser.add_argument("--snapshot-only", action="store_true", help="Write raw snapshot without generated report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    watchlist = load_json(WATCHLIST)
    snapshot = write_snapshot(args.date, watchlist)
    if args.snapshot_only:
        print(SNAPSHOTS / f"{args.date}.json")
    else:
        report = render_report(args.date, snapshot, watchlist)
        print(report)
    return 0 if not snapshot.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
