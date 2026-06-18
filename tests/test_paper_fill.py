import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.paper_fill import review_plans


class PaperFillReviewTests(unittest.TestCase):
    def test_future_plan_stays_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self._write_trades(root, trade_date="2026-06-22")
            snapshot = self._write_snapshot(root, as_of="2026-06-19", quote_date="2026-06-18", close=100.0)
            payload = review_plans("2026-06-19", trades_path=trades, snapshot_path=snapshot)
            self.assertEqual(payload["summary"]["pending_future"], 1)
            self.assertEqual(payload["reviews"][0]["decision"], "pending_future")

    def test_same_day_stale_quote_blocks_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self._write_trades(root, trade_date="2026-06-22")
            snapshot = self._write_snapshot(root, as_of="2026-06-22", quote_date="2026-06-18", close=100.0)
            payload = review_plans("2026-06-22", trades_path=trades, snapshot_path=snapshot)
            self.assertEqual(payload["reviews"][0]["decision"], "blocked_stale_quote")

    def test_same_day_quote_within_gap_is_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self._write_trades(root, trade_date="2026-06-22", price=100.0, quantity=3)
            snapshot = self._write_snapshot(root, as_of="2026-06-22", quote_date="2026-06-22", close=101.0)
            payload = review_plans("2026-06-22", trades_path=trades, snapshot_path=snapshot, max_gap_pct=1.5)
            review = payload["reviews"][0]
            self.assertEqual(review["decision"], "fill_candidate")
            self.assertEqual(review["suggested_trade_row"]["status"], "filled")
            self.assertEqual(review["suggested_trade_row"]["notional_usd"], "303.00")

    def test_same_day_quote_outside_gap_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self._write_trades(root, trade_date="2026-06-22", price=100.0)
            snapshot = self._write_snapshot(root, as_of="2026-06-22", quote_date="2026-06-22", close=103.0)
            payload = review_plans("2026-06-22", trades_path=trades, snapshot_path=snapshot, max_gap_pct=1.5)
            self.assertEqual(payload["reviews"][0]["decision"], "blocked_gap")

    def _write_trades(self, root: Path, *, trade_date: str, price: float = 100.0, quantity: int = 1) -> Path:
        path = root / "paper_trades.csv"
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
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
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "trade_date": trade_date,
                    "time_et": "09:30",
                    "symbol": "SPY",
                    "side": "buy",
                    "quantity": str(quantity),
                    "price": f"{price:.2f}",
                    "status": "planned",
                    "notional_usd": f"{price * quantity:.2f}",
                    "reason": "test plan",
                    "sources": "https://example.com/plan",
                    "notes": "Synthetic test",
                }
            )
        return path

    def _write_snapshot(self, root: Path, *, as_of: str, quote_date: str, close: float) -> Path:
        path = root / f"{as_of}.json"
        path.write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "quotes": [
                        {
                            "symbol": "SPY",
                            "source": "https://example.com/quote",
                            "bars": [
                                {"date_utc": "2026-06-17", "close": 99.0},
                                {"date_utc": quote_date, "close": close},
                            ],
                        }
                    ],
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()

