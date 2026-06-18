import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.daily_run import _existing_daily_paths, run_daily


class DailyRunTests(unittest.TestCase):
    def test_validation_failure_stops_before_git(self):
        calls: list[list[str]] = []

        def runner(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 2, "", "validate failed")

        payload = run_daily("2026-06-19", root=Path("."), runner=runner)

        self.assertEqual(payload["status"], "validation_failed")
        self.assertEqual(calls, [["make", "validate", "DATE=2026-06-19"]])

    def test_dry_run_reports_next_commit_command(self):
        calls: list[list[str]] = []

        def runner(args, **kwargs):
            calls.append(args)
            if args[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(args, 0, " M data/run_cards/2026-06-19.json\n", "")
            return subprocess.CompletedProcess(args, 0, "ok\n", "")

        payload = run_daily("2026-06-19", root=Path("."), runner=runner)

        self.assertEqual(payload["status"], "validated")
        self.assertEqual(payload["commit_status"], "dry_run")
        self.assertIn("--commit", payload["next_command"])
        self.assertNotIn(["git", "commit", "-m", "daily: 2026-06-19 us market simulation"], calls)

    def test_commit_stages_daily_artifacts_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/run_cards").mkdir(parents=True)
            (root / "reports").mkdir(parents=True)
            (root / "data/run_cards/2026-06-19.json").write_text("{}", encoding="utf-8")
            (root / "reports/2026-06-19.generated.md").write_text("report", encoding="utf-8")
            calls: list[list[str]] = []

            def runner(args, **kwargs):
                calls.append(args)
                if args[:3] == ["git", "diff", "--cached"]:
                    return subprocess.CompletedProcess(args, 1, "", "")
                return subprocess.CompletedProcess(args, 0, "ok\n", "")

            payload = run_daily("2026-06-19", root=root, commit=True, runner=runner)

            self.assertEqual(payload["status"], "committed")
            self.assertIn("data/run_cards/2026-06-19.json", payload["staged_paths"])
            self.assertTrue(any(call[:2] == ["git", "add"] for call in calls))
            self.assertTrue(any(call[:2] == ["git", "commit"] for call in calls))

    def test_daily_paths_are_limited_to_date_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/run_cards").mkdir(parents=True)
            (root / "scripts").mkdir()
            wanted = root / "data/run_cards/2026-06-19.json"
            ignored = root / "scripts/unrelated.py"
            wanted.write_text("{}", encoding="utf-8")
            ignored.write_text("print('no')\n", encoding="utf-8")

            paths = _existing_daily_paths("2026-06-19", root)

            self.assertIn(wanted, paths)
            self.assertNotIn(ignored, paths)


if __name__ == "__main__":
    unittest.main()
