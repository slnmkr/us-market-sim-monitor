import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_card import build_run_card


class RunCardTests(unittest.TestCase):
    def test_market_closed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_tree(root, risk_level="closed", dry_run_append_count=0, live_status="blocked")
            card = build_run_card("2026-06-19", root=root)
            self.assertEqual(card["overall_status"], "market_closed_no_trade")
            self.assertEqual(card["market"]["risk_level"], "closed")
            self.assertIn("Keep live trading disabled", " ".join(card["next_actions"]))

    def test_fill_candidates_pending_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_tree(root, risk_level="normal", dry_run_append_count=1, live_status="blocked")
            card = build_run_card("2026-06-19", root=root)
            self.assertEqual(card["overall_status"], "paper_fill_candidates_pending_apply")
            self.assertEqual(card["paper_execution"]["dry_run_append_count"], 1)

    def _write_tree(self, root: Path, *, risk_level: str, dry_run_append_count: int, live_status: str) -> None:
        for rel in [
            "data/event_risk",
            "data/performance",
            "data/live_gate",
            "data/source_checks",
            "journal/fill_reviews",
            "journal/apply_logs",
        ]:
            (root / rel).mkdir(parents=True, exist_ok=True)
        as_of = "2026-06-19"
        (root / f"data/event_risk/{as_of}.json").write_text(
            json.dumps(
                {
                    "current_risk": {"risk_level": risk_level, "max_new_gross_exposure_pct": 0.0},
                    "active_events": [],
                    "next_events": [],
                }
            ),
            encoding="utf-8",
        )
        (root / f"data/performance/{as_of}.json").write_text(
            json.dumps(
                {
                    "status": "ok",
                    "paper": {
                        "observations": 1,
                        "latest_equity": 100000.0,
                        "total_return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                    },
                    "benchmark": {"status": "ok", "symbol": "SPY"},
                    "comparison": {"status": "ok"},
                }
            ),
            encoding="utf-8",
        )
        (root / f"journal/fill_reviews/{as_of}.json").write_text(
            json.dumps(
                {
                    "risk_gate": {"status": "ok", "risk_level": risk_level},
                    "reviews": [{"decision": "fill_candidate"}] if dry_run_append_count else [],
                }
            ),
            encoding="utf-8",
        )
        (root / f"journal/apply_logs/{as_of}.dry_run.json").write_text(
            json.dumps(
                {
                    "mode": "dry_run",
                    "applied_count": 0,
                    "dry_run_append_count": dry_run_append_count,
                    "candidate_count": dry_run_append_count,
                }
            ),
            encoding="utf-8",
        )
        (root / f"data/live_gate/{as_of}.json").write_text(
            json.dumps(
                {
                    "status": live_status,
                    "blockers": [{"code": "missing_git_remote"}] if live_status == "blocked" else [],
                    "required_file_checks": [{"path": "config/live_mandate.json", "status": "missing"}],
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        (root / f"data/source_checks/{as_of}.json").write_text(
            json.dumps({"checks": [{"topic": "market_holiday"}]}),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
