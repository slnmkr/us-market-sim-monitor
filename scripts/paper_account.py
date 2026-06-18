"""Paper-account accounting and guardrails.

All functions in this module operate on local synthetic records only. They do
not connect to a broker and cannot place orders.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {"planned", "filled", "canceled", "no_trade"}
ALLOWED_SIDES = {"buy", "sell", "hold"}
REQUIRED_FIELDS = {
    "trade_date",
    "time_et",
    "symbol",
    "side",
    "quantity",
    "price",
    "status",
    "notional_usd",
    "reason",
    "sources",
    "notes",
}


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    cost_basis: float = 0.0


def load_trades(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_portfolio(trades: list[dict[str, Any]], starting_cash: float) -> dict[str, Any]:
    cash = float(starting_cash)
    positions: dict[str, Position] = {}
    realized_pnl = 0.0

    for trade in trades:
        if trade.get("status") != "filled":
            continue
        symbol = trade["symbol"].strip().upper()
        if symbol == "CASH":
            continue
        side = trade["side"].strip().lower()
        qty = parse_float(trade, "quantity")
        price = parse_float(trade, "price")
        notional = parse_float(trade, "notional_usd") or qty * price
        pos = positions.setdefault(symbol, Position(symbol=symbol))
        if side == "buy":
            pos.quantity += qty
            pos.cost_basis += notional
            cash -= notional
        elif side == "sell":
            if pos.quantity <= 0:
                cash += notional
                realized_pnl += notional
                continue
            closed_qty = min(qty, pos.quantity)
            avg_cost = pos.cost_basis / pos.quantity if pos.quantity else 0.0
            removed_cost = avg_cost * closed_qty
            pos.quantity -= closed_qty
            pos.cost_basis -= removed_cost
            realized_pnl += notional - removed_cost
            cash += notional
        else:
            raise ValueError(f"Unsupported filled trade side: {side}")

    positions = {symbol: pos for symbol, pos in positions.items() if abs(pos.quantity) > 1e-12}
    return {"cash": cash, "positions": positions, "realized_pnl": realized_pnl}


def mark_to_market(
    portfolio: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    starting_cash: float,
) -> dict[str, Any]:
    rows = []
    positions_value = 0.0
    unrealized_pnl = 0.0
    missing_quotes: list[str] = []

    for symbol, pos in sorted(portfolio["positions"].items()):
        close = quotes.get(symbol, {}).get("close")
        market_value = pos.quantity * close if close is not None else None
        unrealized = market_value - pos.cost_basis if market_value is not None else None
        if market_value is None:
            missing_quotes.append(symbol)
        else:
            positions_value += market_value
            unrealized_pnl += unrealized or 0.0
        rows.append(
            {
                "symbol": symbol,
                "quantity": pos.quantity,
                "cost_basis": pos.cost_basis,
                "close": close,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
            }
        )

    total = portfolio["cash"] + positions_value
    return_pct = ((total - starting_cash) / starting_cash * 100.0) if starting_cash else 0.0
    return {
        "cash": portfolio["cash"],
        "positions": rows,
        "positions_value": positions_value,
        "realized_pnl": portfolio.get("realized_pnl", 0.0),
        "unrealized_pnl": unrealized_pnl,
        "total_equity": total,
        "return_pct": return_pct,
        "missing_quotes": missing_quotes,
    }


def planned_orders(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filled_keys = {
        _planned_fill_key(row)
        for row in trades
        if row.get("status") == "filled"
    }
    return [
        {
            "trade_date": row["trade_date"],
            "time_et": row["time_et"],
            "symbol": row["symbol"].strip().upper(),
            "side": row["side"].strip().lower(),
            "quantity": parse_float(row, "quantity"),
            "price": parse_float(row, "price"),
            "notional_usd": parse_float(row, "notional_usd"),
            "reason": row.get("reason", ""),
            "sources": row.get("sources", ""),
        }
        for row in trades
        if row.get("status") == "planned"
        and _planned_fill_key(row) not in filled_keys
    ]


def _planned_fill_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        row.get("trade_date", "").strip(),
        row.get("symbol", "").strip().upper(),
        row.get("side", "").strip().lower(),
        _numeric_key(row.get("quantity", "")),
    )


def _numeric_key(value: Any) -> str:
    try:
        return f"{float(value):.8f}"
    except (TypeError, ValueError):
        return str(value)


def validate_trades(
    trades: list[dict[str, Any]],
    starting_cash: float,
    *,
    max_planned_gross: float = 0.90,
    max_single_planned: float = 0.40,
) -> list[str]:
    errors: list[str] = []
    planned_gross = 0.0
    planned_by_symbol: dict[str, float] = {}
    cash = float(starting_cash)
    positions: dict[str, float] = {}

    for idx, row in enumerate(trades, start=2):
        missing = sorted(REQUIRED_FIELDS - set(row))
        if missing:
            errors.append(f"row {idx}: missing fields {', '.join(missing)}")
            continue

        symbol = row["symbol"].strip().upper()
        status = row["status"].strip().lower()
        side = row["side"].strip().lower()
        if status not in ALLOWED_STATUSES:
            errors.append(f"row {idx} {symbol}: invalid status {status!r}")
        if side not in ALLOWED_SIDES:
            errors.append(f"row {idx} {symbol}: invalid side {side!r}")

        qty = parse_float(row, "quantity", row_number=idx, errors=errors)
        price = parse_float(row, "price", row_number=idx, errors=errors)
        notional = parse_float(row, "notional_usd", row_number=idx, errors=errors)
        if qty < 0:
            errors.append(f"row {idx} {symbol}: quantity must be non-negative")
        if price < 0:
            errors.append(f"row {idx} {symbol}: price must be non-negative")
        if notional < 0:
            errors.append(f"row {idx} {symbol}: notional_usd must be non-negative")
        if status in {"planned", "filled"} and symbol != "CASH" and not row.get("sources", "").strip():
            errors.append(f"row {idx} {symbol}: planned/filled rows need source URLs")
        if status in {"planned", "filled"} and symbol != "CASH" and not row.get("reason", "").strip():
            errors.append(f"row {idx} {symbol}: planned/filled rows need a reason")

        if status == "planned" and side == "buy":
            planned_gross += notional
            planned_by_symbol[symbol] = planned_by_symbol.get(symbol, 0.0) + notional
        if status == "filled" and symbol != "CASH":
            if side == "buy":
                cash -= notional
                positions[symbol] = positions.get(symbol, 0.0) + qty
            elif side == "sell":
                held = positions.get(symbol, 0.0)
                if qty > held + 1e-9:
                    errors.append(f"row {idx} {symbol}: sell quantity exceeds synthetic holdings")
                positions[symbol] = held - qty
                cash += notional

    if planned_gross > starting_cash * max_planned_gross + 1e-9:
        errors.append(
            "planned gross exposure "
            f"{planned_gross:.2f} exceeds {max_planned_gross:.0%} limit "
            f"({starting_cash * max_planned_gross:.2f})"
        )
    for symbol, notional in sorted(planned_by_symbol.items()):
        if notional > starting_cash * max_single_planned + 1e-9:
            errors.append(
                f"{symbol} planned exposure {notional:.2f} exceeds "
                f"{max_single_planned:.0%} single-symbol limit "
                f"({starting_cash * max_single_planned:.2f})"
            )
    if cash < -1e-9:
        errors.append(f"filled trades overdraw synthetic cash by {-cash:.2f}")

    return errors


def upsert_equity_curve(path: Path, as_of: str, collected_at: str, mtm: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "date",
        "collected_at",
        "cash",
        "positions_value",
        "total_equity",
        "realized_pnl",
        "unrealized_pnl",
        "return_pct",
        "missing_quotes",
    ]
    rows: list[dict[str, Any]] = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as fh:
            rows = [row for row in csv.DictReader(fh) if row.get("date") != as_of]

    rows.append(
        {
            "date": as_of,
            "collected_at": collected_at,
            "cash": f"{mtm['cash']:.2f}",
            "positions_value": f"{mtm['positions_value']:.2f}",
            "total_equity": f"{mtm['total_equity']:.2f}",
            "realized_pnl": f"{mtm['realized_pnl']:.2f}",
            "unrealized_pnl": f"{mtm['unrealized_pnl']:.2f}",
            "return_pct": f"{mtm['return_pct']:.4f}",
            "missing_quotes": ";".join(mtm.get("missing_quotes", [])),
        }
    )
    rows.sort(key=lambda row: row["date"])

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_float(
    row: dict[str, Any],
    field: str,
    *,
    row_number: int | None = None,
    errors: list[str] | None = None,
) -> float:
    raw = row.get(field, "")
    try:
        if raw in (None, ""):
            return 0.0
        return float(raw)
    except (TypeError, ValueError):
        location = f"row {row_number}: " if row_number is not None else ""
        message = f"{location}{field} must be numeric, got {raw!r}"
        if errors is not None:
            errors.append(message)
            return 0.0
        raise ValueError(message) from None
