import json
import subprocess
import tempfile
import unittest
from pathlib import Path

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
            (root / "config/live_mandate.json").write_text("{}", encoding="utf-8")
            (root / "config/broker_connection.json").write_text("{}", encoding="utf-8")

            payload = evaluate_live_gate("2026-06-19", root=root)

            self.assertEqual(payload["status"], "eligible_for_manual_review")
            self.assertEqual(payload["blockers"], [])

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


if __name__ == "__main__":
    unittest.main()

