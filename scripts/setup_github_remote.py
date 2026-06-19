#!/usr/bin/env python3
"""Safely configure a GitHub remote for the local audit trail."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

try:
    from .live_account_gate import evaluate_live_gate, write_live_gate
except ImportError:  # pragma: no cover - script execution path.
    from live_account_gate import evaluate_live_gate, write_live_gate


ROOT = Path(__file__).resolve().parents[1]
Runner = Callable[..., subprocess.CompletedProcess[str]]

HTTPS_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
SSH_RE = re.compile(r"^git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$")


def configure_remote(
    remote_url: str,
    *,
    root: Path = ROOT,
    remote_name: str = "origin",
    replace: bool = False,
    git_name: str | None = None,
    git_email: str | None = None,
    refresh_live_gate_date: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    errors = validate_remote_url(remote_url)
    if git_email is not None:
        errors.extend(_validate_git_email(git_email))
    if errors:
        return {
            "status": "invalid_input",
            "errors": errors,
            "data_boundary": "Local git configuration only; no GitHub token, password, cookie, or browser credential is accepted.",
        }

    current = _git_remote(runner, root, remote_name)
    if current and not replace:
        return {
            "status": "remote_exists",
            "remote_name": remote_name,
            "remote_url": current,
            "message": f"Remote {remote_name!r} already exists; rerun with --replace to change it.",
            "data_boundary": "Local git configuration only; no GitHub token, password, cookie, or browser credential is accepted.",
        }

    commands: list[dict[str, Any]] = []
    if git_name:
        commands.append(_run(runner, ["git", "config", "user.name", git_name], root))
    if git_email:
        commands.append(_run(runner, ["git", "config", "user.email", git_email], root))

    if current and replace:
        commands.append(_run(runner, ["git", "remote", "set-url", remote_name, remote_url], root))
    else:
        commands.append(_run(runner, ["git", "remote", "add", remote_name, remote_url], root))

    failed = [item for item in commands if item["returncode"] != 0]
    payload: dict[str, Any] = {
        "status": "configured" if not failed else "command_failed",
        "remote_name": remote_name,
        "remote_url": remote_url,
        "commands": commands,
        "data_boundary": "Local git configuration only; no GitHub token, password, cookie, or browser credential is accepted.",
        "next_push_command": f"git push -u {remote_name} main",
    }
    if failed:
        return payload

    if refresh_live_gate_date:
        live_gate = evaluate_live_gate(refresh_live_gate_date, root=root)
        path = write_live_gate(refresh_live_gate_date, live_gate, output_dir=root / "data" / "live_gate")
        payload["live_gate_path"] = str(path)
        payload["live_gate_status"] = live_gate["status"]
        payload["live_gate_blocker_codes"] = [item["code"] for item in live_gate.get("blockers", [])]
    return payload


def validate_remote_url(remote_url: str) -> list[str]:
    errors: list[str] = []
    value = remote_url.strip()
    if not value:
        return ["remote URL is required"]
    if any(secret in value.lower() for secret in ["@", "token", "password", "api_key", "apikey"]):
        if not value.startswith("git@github.com:"):
            errors.append("remote URL must not include credentials or token-like text")
    match = HTTPS_RE.match(value) or SSH_RE.match(value)
    if not match:
        errors.append("remote URL must be a GitHub HTTPS or SSH repository URL")
        return errors
    owner, repo = match.groups()
    for label, part in [("owner", owner), ("repo", repo)]:
        if part.startswith(".") or part.endswith(".") or ".." in part:
            errors.append(f"{label} contains invalid dot placement")
    return errors


def _validate_git_email(email: str) -> list[str]:
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return ["git email must look like a real email address"]
    if email.endswith("@local.invalid"):
        return ["git email must not use the local.invalid placeholder"]
    return []


def _git_remote(runner: Runner, root: Path, remote_name: str) -> str:
    proc = runner(
        ["git", "remote", "get-url", remote_name],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _run(runner: Runner, args: list[str], root: Path) -> dict[str, Any]:
    proc = runner(
        args,
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "args": list(args),
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("remote_url", help="GitHub repository URL, for example https://github.com/user/repo.git")
    parser.add_argument("--remote-name", default="origin", help="Git remote name")
    parser.add_argument("--replace", action="store_true", help="Replace an existing remote with the same name")
    parser.add_argument("--git-name", help="Set local git user.name")
    parser.add_argument("--git-email", help="Set local git user.email")
    parser.add_argument("--refresh-live-gate", default=date.today().isoformat(), help="Refresh live gate for this date after configuration")
    parser.add_argument("--no-refresh-live-gate", action="store_true", help="Do not refresh live gate")
    parser.add_argument("--json", action="store_true", help="Print JSON payload")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = configure_remote(
        args.remote_url,
        remote_name=args.remote_name,
        replace=args.replace,
        git_name=args.git_name,
        git_email=args.git_email,
        refresh_live_gate_date=None if args.no_refresh_live_gate else args.refresh_live_gate,
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(payload["status"])
        if payload.get("next_push_command"):
            print(f"next: {payload['next_push_command']}")
        for error in payload.get("errors", []):
            print(f"ERROR: {error}")
    return 0 if payload["status"] in {"configured", "remote_exists"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
