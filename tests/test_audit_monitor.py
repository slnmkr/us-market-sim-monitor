import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_monitor import audit_date


class AuditMonitorTests(unittest.TestCase):
    def test_audit_passes_for_minimal_valid_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_valid_tree(root, "2026-06-19")
            result = audit_date("2026-06-19", root=root)
            self.assertTrue(result.ok, result.errors)

    def test_audit_fails_without_source_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_valid_tree(root, "2026-06-19")
            (root / "data/source_checks/2026-06-19.json").unlink()
            result = audit_date("2026-06-19", root=root)
            self.assertFalse(result.ok)
            self.assertTrue(any("missing JSON artifact" in item for item in result.errors))

    def test_audit_fails_on_forbidden_report_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_valid_tree(root, "2026-06-19")
            report = root / "reports/2026-06-19.md"
            report.write_text(report.read_text(encoding="utf-8") + "\nguaranteed return\n", encoding="utf-8")
            result = audit_date("2026-06-19", root=root)
            self.assertFalse(result.ok)
            self.assertTrue(any("forbidden claim" in item for item in result.errors))

    def _write_valid_tree(self, root: Path, as_of: str):
        for rel in [
            "config",
            "journal",
            "journal/fill_reviews",
            "journal/apply_logs",
            "data/event_risk",
            "data/performance",
            "data/live_gate",
            "data/run_cards",
            "data/market_snapshots",
            "data/source_checks",
            "reports",
        ]:
            (root / rel).mkdir(parents=True, exist_ok=True)

        (root / "config/watchlist.json").write_text(
            json.dumps({"paper_account": {"starting_cash": 100000.0}}),
            encoding="utf-8",
        )
        (root / "journal/paper_trades.csv").write_text(
            "trade_date,time_et,symbol,side,quantity,price,status,notional_usd,reason,sources,notes\n"
            f"{as_of},all_day,CASH,hold,0,0,no_trade,0,closed,https://example.com,Synthetic\n",
            encoding="utf-8",
        )
        (root / f"data/market_snapshots/{as_of}.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "data_boundary": "Public Yahoo Finance chart endpoint; no broker or account data.",
                    "quotes": [
                        {
                            "symbol": "SPY",
                            "source": "https://example.com/spy",
                            "bars": [{"date_utc": as_of, "close": 100.0}],
                        }
                    ],
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )
        (root / f"data/source_checks/{as_of}.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "data_boundary": "Real public web sources only.",
                    "checks": [
                        self._check("market_holiday"),
                        self._check("latest_us_equity_close"),
                        self._check("fomc"),
                        self._check("nonfarm_payroll_next"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "data/equity_curve.csv").write_text(
            "date,collected_at,cash,positions_value,total_equity,realized_pnl,unrealized_pnl,return_pct,missing_quotes\n"
            f"{as_of},now,100000.00,0.00,100000.00,0.00,0.00,0.0000,\n",
            encoding="utf-8",
        )
        (root / f"data/event_risk/{as_of}.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "data_boundary": "Deterministic risk-window assessment from source-backed local event config; no broker or account data.",
                    "current_risk": {
                        "risk_level": "normal",
                        "max_new_gross_exposure_pct": 0.9,
                        "reasons": ["No active window."],
                        "actions": [],
                    },
                    "next_events": [],
                    "active_events": [],
                }
            ),
            encoding="utf-8",
        )
        (root / f"data/performance/{as_of}.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "data_boundary": "Local paper equity curve and public market snapshots only; no broker or account data.",
                    "status": "ok",
                    "paper": {
                        "observations": 1,
                        "latest_equity": 100000.0,
                        "total_return_pct": 0.0,
                        "one_day_return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                    },
                    "benchmark": {"status": "ok", "symbol": "SPY", "total_return_pct": 0.0},
                    "comparison": {"status": "ok", "excess_return_pct": 0.0},
                }
            ),
            encoding="utf-8",
        )
        (root / f"data/live_gate/{as_of}.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "status": "blocked",
                    "data_boundary": "Local live-account preflight only; no broker connection, no secrets, no account access, no live orders.",
                    "blockers": [{"code": "test", "message": "blocked"}],
                    "warnings": [],
                    "git": {"has_remote": False, "remotes": [], "identity": {}},
                }
            ),
            encoding="utf-8",
        )
        (root / f"data/run_cards/{as_of}.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "overall_status": "market_closed_no_trade",
                    "data_boundary": "Local run card from public-source paper-monitor artifacts only; no broker connection, no secrets, no account access, no live orders.",
                    "market": {},
                    "paper_account": {},
                    "paper_execution": {},
                    "live_gate": {},
                    "source_check": {},
                    "next_actions": ["No paper fills."],
                }
            ),
            encoding="utf-8",
        )
        (root / f"journal/fill_reviews/{as_of}.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "data_boundary": "Synthetic paper-fill review only; no broker order, account access, or live execution.",
                    "reviews": [],
                    "summary": {"total": 0},
                }
            ),
            encoding="utf-8",
        )
        (root / f"journal/apply_logs/{as_of}.dry_run.json").write_text(
            json.dumps(
                {
                    "as_of": as_of,
                    "mode": "dry_run",
                    "data_boundary": "Synthetic paper ledger update only; no broker order, account access, or live execution.",
                    "candidate_count": 0,
                    "applied_count": 0,
                    "dry_run_append_count": 0,
                    "skipped_existing_count": 0,
                    "rows": [],
                }
            ),
            encoding="utf-8",
        )
        for suffix in [".md", ".generated.md"]:
            (root / f"reports/{as_of}{suffix}").write_text(
                f"# Report {as_of}\n\nNo broker access. Paper account only. source: https://example.com\n",
                encoding="utf-8",
            )

    def _check(self, topic: str) -> dict:
        return {
            "topic": topic,
            "source_url": f"https://example.com/{topic}",
            "facts": ["fact"],
            "paper_account_impact": "impact",
        }


if __name__ == "__main__":
    unittest.main()
