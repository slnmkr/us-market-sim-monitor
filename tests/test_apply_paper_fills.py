import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.apply_paper_fills import apply_fill_candidates
from scripts.paper_account import load_trades


class ApplyPaperFillsTests(unittest.TestCase):
    def test_dry_run_does_not_mutate_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self._write_trades(root)
            review = self._write_review(root)

            payload = apply_fill_candidates("2026-06-22", review_path=review, trades_path=trades, apply=False)

            self.assertEqual(payload["mode"], "dry_run")
            self.assertEqual(payload["dry_run_append_count"], 1)
            self.assertEqual(len(load_trades(trades)), 1)

    def test_apply_appends_candidate_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self._write_trades(root)
            review = self._write_review(root)

            first = apply_fill_candidates("2026-06-22", review_path=review, trades_path=trades, apply=True)
            second = apply_fill_candidates("2026-06-22", review_path=review, trades_path=trades, apply=True)

            rows = load_trades(trades)
            self.assertEqual(first["applied_count"], 1)
            self.assertEqual(second["applied_count"], 0)
            self.assertEqual(second["skipped_existing_count"], 1)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["status"], "filled")
            self.assertIn("not a broker execution", rows[-1]["notes"])

    def test_non_candidate_rows_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades = self._write_trades(root)
            review = root / "review.json"
            review.write_text(
                json.dumps(
                    {
                        "as_of": "2026-06-22",
                        "reviews": [{"decision": "blocked_gap", "symbol": "SPY"}],
                    }
                ),
                encoding="utf-8",
            )

            payload = apply_fill_candidates("2026-06-22", review_path=review, trades_path=trades, apply=True)

            self.assertEqual(payload["candidate_count"], 0)
            self.assertEqual(len(load_trades(trades)), 1)

    def _write_trades(self, root: Path) -> Path:
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
                    "trade_date": "2026-06-22",
                    "time_et": "09:30",
                    "symbol": "SPY",
                    "side": "buy",
                    "quantity": "1",
                    "price": "100",
                    "status": "planned",
                    "notional_usd": "100",
                    "reason": "plan",
                    "sources": "https://example.com/plan",
                    "notes": "Synthetic plan; not a broker order.",
                }
            )
        return path

    def _write_review(self, root: Path) -> Path:
        path = root / "review.json"
        path.write_text(
            json.dumps(
                {
                    "as_of": "2026-06-22",
                    "reviews": [
                        {
                            "decision": "fill_candidate",
                            "symbol": "SPY",
                            "suggested_trade_row": {
                                "trade_date": "2026-06-22",
                                "time_et": "close",
                                "symbol": "SPY",
                                "side": "buy",
                                "quantity": "1",
                                "price": "101.0000",
                                "status": "filled",
                                "notional_usd": "101.00",
                                "reason": "Paper fill candidate.",
                                "sources": "https://example.com/quote",
                                "notes": "Synthetic fill candidate only; not a broker execution.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()

