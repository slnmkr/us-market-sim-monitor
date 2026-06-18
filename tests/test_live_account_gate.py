import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from scripts.live_account_gate import evaluate_live_gate


class LiveAccountGateTests(unittest.TestCase):
    def test_blocks_without_required_files_remote_and_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo(root)
            self._write_policy(root)
            self._write_performance(root, observations=1, total_return=0.0, max_drawdown=0.0)

            payload = evaluate_live_gate("2026-06-19", root=root)

            codes = {item["code"] for item in payload["blockers"]}
            self.assertEqual(payload["status"], "blocked")
            self.assertIn("insufficient_paper_observations", codes)
            self.assertIn("missing_required_file", codes)
            self.assertIn("missing_git_remote", codes)

    def test_eligible_when_policy_conditions_are_met(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo(root)
            subprocess.run(["git", "remote", "add", "origin", "https://example.com/repo.git"], cwd=root, check=True)
            self._write_policy(root)
            self._write_performance(root, observations=5, total_return=1.2, max_drawdown=-1.0)
            self._write_live_mandate(root)
            self._write_broker_manifest(root)

            payload = evaluate_live_gate("2026-06-19", root=root)

            self.assertEqual(payload["status"], "eligible_for_manual_review")
            self.assertEqual(payload["blockers"], [])

    def test_blocks_empty_required_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo(root)
            subprocess.run(["git", "remote", "add", "origin", "https://example.com/repo.git"], cwd=root, check=True)
            self._write_policy(root)
            self._write_performance(root, observations=5, total_return=1.2, max_drawdown=-1.0)
            (root / "config/live_mandate.json").write_text("{}", encoding="utf-8")
            (root / "config/broker_connection.json").write_text("{}", encoding="utf-8")

            payload = evaluate_live_gate("2026-06-19", root=root)

            codes = {item["code"] for item in payload["blockers"]}
            self.assertEqual(payload["status"], "blocked")
            self.assertIn("invalid_required_file", codes)

    def test_blocks_expired_mandate_and_secret_like_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo(root)
            subprocess.run(["git", "remote", "add", "origin", "https://example.com/repo.git"], cwd=root, check=True)
            self._write_policy(root)
            self._write_performance(root, observations=5, total_return=1.2, max_drawdown=-1.0)
            self._write_live_mandate(root, expires_on="2026-06-18")
            self._write_broker_manifest(root, extra={"api_key": "do-not-commit"})

            payload = evaluate_live_gate("2026-06-19", root=root)

            messages = " ".join(item["message"] for item in payload["blockers"])
            self.assertIn("expires_on", messages)
            self.assertIn("api_key", messages)

    def _init_repo(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        (root / "data/performance").mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "tester"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=root, check=True)

    def _write_policy(self, root: Path) -> None:
        (root / "config/live_gate_policy.json").write_text(
            json.dumps(
                {
                    "min_paper_observations": 5,
                    "min_paper_total_return_pct": 0.0,
                    "max_allowed_drawdown_pct": -5.0,
                    "require_git_remote": True,
                    "required_files": [
                        {"path": "config/live_mandate.json", "description": "mandate"},
                        {"path": "config/broker_connection.json", "description": "broker manifest"},
                    ],
                    "blocked_status": "blocked",
                    "eligible_status": "eligible_for_manual_review",
                }
            ),
            encoding="utf-8",
        )

    def _write_performance(self, root: Path, *, observations: int, total_return: float, max_drawdown: float) -> None:
        (root / "data/performance/2026-06-19.json").write_text(
            json.dumps(
                {
                    "status": "ok",
                    "paper": {
                        "observations": observations,
                        "total_return_pct": total_return,
                        "max_drawdown_pct": max_drawdown,
                    },
                }
            ),
            encoding="utf-8",
        )

    def _write_live_mandate(self, root: Path, *, expires_on: str = "2026-07-19") -> None:
        (root / "config/live_mandate.json").write_text(
            json.dumps(
                {
                    "user_written": True,
                    "authorized_by": "tester",
                    "created_on": "2026-06-19",
                    "expires_on": expires_on,
                    "broker": "Example Broker",
                    "account_scope": ["paper-review-account"],
                    "instrument_scope": ["US listed ETFs only"],
                    "max_order_notional_usd": 1000,
                    "max_gross_exposure_pct": 0.25,
                    "max_daily_loss_pct": 0.01,
                    "allowed_order_types": ["market", "limit"],
                    "no_automatic_live_orders": True,
                }
            ),
            encoding="utf-8",
        )

    def _write_broker_manifest(self, root: Path, *, extra: Optional[dict] = None) -> None:
        payload = {
            "broker_name": "Example Broker",
            "environment": "paper",
            "account_type": "individual",
            "capabilities": ["quotes", "paper_trading"],
            "credentials_included": False,
            "credential_storage": "external_only",
        }
        payload.update(extra or {})
        (root / "config/broker_connection.json").write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
