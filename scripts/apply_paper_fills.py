#!/usr/bin/env python3
"""Apply approved synthetic fill candidates to the local paper ledger.

Default mode is dry-run. Passing ``--apply`` appends only synthetic
``fill_candidate`` rows from a fill-review artifact. This never calls a broker
and never changes planned rows in place.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .paper_account import REQUIRED_FIELDS, load_trades
except ImportError:  # pragma: no cover - used when executed as a script.
    from paper_account import REQUIRED_FIELDS, load_trades


ROOT = Path(__file__).resolve().parents[1]
TRADES = ROOT / "journal" / "paper_trades.csv"
FILL_REVIEWS = ROOT / "journal" / "fill_reviews"
APPLY_LOGS = ROOT / "journal" / "apply_logs"

FIELDNAMES = [
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
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def apply_fill_candidates(
    as_of: str,
    *,
    review_path: Path | None = None,
    trades_path: Path = TRADES,
    apply: bool = False,
) -> dict[str, Any]:
    review_path = review_path or (FILL_REVIEWS / f"{as_of}.json")
    review = load_json(review_path)
    if review.get("as_of") != as_of:
        raise ValueError(f"fill review as_of {review.get('as_of')!r} does not match {as_of}")

    existing = load_trades(trades_path)
    existing_keys = {_filled_key(row) for row in existing if row.get("status") == "filled"}
    candidates = [_normalize_candidate(item) for item in review.get("reviews", []) if item.get("decision") == "fill_candidate"]
    to_append = [row for row in candidates if _filled_key(row) not in existing_keys]
    skipped = [row for row in candidates if _filled_key(row) in existing_keys]

    if apply and to_append:
        _write_trades(trades_path, existing + to_append)

    payload = {
        "as_of": as_of,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "apply" if apply else "dry_run",
        "data_boundary": "Synthetic paper ledger update only; no broker order, account access, or live execution.",
        "review_path": str(review_path),
        "trades_path": str(trades_path),
        "candidate_count": len(candidates),
        "applied_count": len(to_append) if apply else 0,
        "dry_run_append_count": len(to_append) if not apply else 0,
        "skipped_existing_count": len(skipped),
        "rows": to_append,
    }
    return payload


def write_apply_log(as_of: str, payload: dict[str, Any], output_dir: Path = APPLY_LOGS) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "apply" if payload.get("mode") == "apply" else "dry_run"
    path = output_dir / f"{as_of}.{suffix}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def _normalize_candidate(review: dict[str, Any]) -> dict[str, str]:
    row = review.get("suggested_trade_row")
    if not isinstance(row, dict):
        raise ValueError(f"fill_candidate for {review.get('symbol')} is missing suggested_trade_row")
    missing = sorted(REQUIRED_FIELDS - set(row))
    if missing:
        raise ValueError(f"suggested_trade_row missing fields: {', '.join(missing)}")
    normalized = {field: str(row.get(field, "")) for field in FIELDNAMES}
    if normalized["status"] != "filled":
        raise ValueError("suggested_trade_row status must be filled")
    notes = normalized["notes"].lower()
    if "not a broker execution" not in notes:
        raise ValueError("suggested_trade_row must state not a broker execution")
    return normalized


def _write_trades(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def _filled_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        row.get("trade_date", "").strip(),
        row.get("symbol", "").strip().upper(),
        row.get("side", "").strip().lower(),
        _num(row.get("quantity", "")),
        _num(row.get("price", "")),
    )


def _num(value: Any) -> str:
    try:
        return f"{float(value):.8f}"
    except (TypeError, ValueError):
        return str(value)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Fill review date YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true", help="Append candidates to the paper ledger")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of the log path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = apply_fill_candidates(args.date, apply=args.apply)
    path = write_apply_log(args.date, payload)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

