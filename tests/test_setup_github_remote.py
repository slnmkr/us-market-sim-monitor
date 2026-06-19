import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from scripts.setup_github_remote import configure_remote, validate_remote_url


class SetupGithubRemoteTests(unittest.TestCase):
    def test_rejects_non_github_or_credential_url(self):
        self.assertTrue(validate_remote_url("https://example.com/user/repo.git"))
        self.assertTrue(validate_remote_url("https://token@github.com/user/repo.git"))
        self.assertFalse(validate_remote_url("https://github.com/user/repo.git"))
        self.assertFalse(validate_remote_url("git@github.com:user/repo.git"))

    def test_configures_remote_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo(root)

            payload = configure_remote(
                "https://github.com/example/us-market-sim-monitor.git",
                root=root,
                git_name="Example User",
                git_email="example@example.com",
                refresh_live_gate_date=None,
            )

            self.assertEqual(payload["status"], "configured")
            self.assertEqual(self._git(root, "remote", "get-url", "origin"), "https://github.com/example/us-market-sim-monitor.git")
            self.assertEqual(self._git(root, "config", "--local", "--get", "user.email"), "example@example.com")

    def test_existing_remote_requires_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo(root)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/a/old.git"], cwd=root, check=True)

            payload = configure_remote("https://github.com/a/new.git", root=root, refresh_live_gate_date=None)
            replaced = configure_remote("https://github.com/a/new.git", root=root, replace=True, refresh_live_gate_date=None)

            self.assertEqual(payload["status"], "remote_exists")
            self.assertEqual(replaced["status"], "configured")
            self.assertEqual(self._git(root, "remote", "get-url", "origin"), "https://github.com/a/new.git")

    def test_rejects_placeholder_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo(root)

            payload = configure_remote(
                "https://github.com/example/repo.git",
                root=root,
                git_email="zhangta@local.invalid",
                refresh_live_gate_date=None,
            )

            self.assertEqual(payload["status"], "invalid_input")
            self.assertIn("local.invalid", " ".join(payload["errors"]))

    def _init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "tester"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=root, check=True)

    def _git(self, root: Path, *args: str, default: Optional[str] = None) -> str:
        proc = subprocess.run(["git", *args], cwd=root, check=False, text=True, stdout=subprocess.PIPE)
        return proc.stdout.strip() if proc.returncode == 0 else (default or "")


if __name__ == "__main__":
    unittest.main()
