import json
import tempfile
import unittest
from pathlib import Path

from scripts.performance import build_performance


class PerformanceTests(unittest.TestCase):
    def test_build_performance_computes_returns_and_drawdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            equity = root / "equity.csv"
            snapshots = root / "snapshots"
            snapshots.mkdir()
            equity.write_text(
                "date,collected_at,cash,positions_value,total_equity,realized_pnl,unrealized_pnl,return_pct,missing_quotes\n"
                "2026-06-19,now,100000,0,100000,0,0,0,\n"
                "2026-06-22,now,1000,98000,99000,0,-1000,-1,\n"
                "2026-06-23,now,1000,101000,102000,0,2000,2,\n",
                encoding="utf-8",
            )
            self._snapshot(snapshots, "2026-06-19", 100.0)
            self._snapshot(snapshots, "2026-06-22", 101.0)
            self._snapshot(snapshots, "2026-06-23", 103.0)

            payload = build_performance("2026-06-23", equity_curve_path=equity, snapshots_dir=snapshots)

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["paper"]["observations"], 3)
            self.assertEqual(payload["paper"]["total_return_pct"], 2.0)
            self.assertEqual(payload["paper"]["one_day_return_pct"], 3.0303030303030303)
            self.assertEqual(payload["paper"]["max_drawdown_pct"], -1.0)
            self.assertEqual(payload["benchmark"]["total_return_pct"], 3.0)
            self.assertEqual(payload["comparison"]["excess_return_pct"], -1.0)

    def test_missing_equity_curve_rows_returns_error_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            equity = root / "equity.csv"
            snapshots = root / "snapshots"
            snapshots.mkdir()
            equity.write_text(
                "date,collected_at,cash,positions_value,total_equity,realized_pnl,unrealized_pnl,return_pct,missing_quotes\n",
                encoding="utf-8",
            )
            payload = build_performance("2026-06-23", equity_curve_path=equity, snapshots_dir=snapshots)
            self.assertEqual(payload["status"], "missing_equity_curve")

    def _snapshot(self, root: Path, as_of: str, close: float) -> None:
        (root / f"{as_of}.json").write_text(
            json.dumps(
                {
                    "quotes": [
                        {
                            "symbol": "SPY",
                            "source": "https://example.com/spy",
                            "bars": [{"date_utc": as_of, "close": close}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()

