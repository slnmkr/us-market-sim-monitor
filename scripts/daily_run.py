#!/usr/bin/env python3
"""Run the daily paper-monitor workflow and optionally commit daily artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Any


ROOT = Path(__file__).resolve().parents[1]

Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_daily(
    as_of: str,
    *,
    root: Path = ROOT,
    commit: bool = False,
    message: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    validate = _run(runner, ["make", "validate", f"DATE={as_of}"], root)
    payload: dict[str, Any] = {
        "as_of": as_of,
        "root": str(root),
        "data_boundary": "Local paper-monitor workflow only; no broker connection, no secrets, no account access, no live orders.",
        "validate": _summary(validate),
        "commit_requested": commit,
    }
    if validate.returncode != 0:
        payload["status"] = "validation_failed"
        return payload

    status_before = _run(runner, ["git", "status", "--short"], root)
    payload["git_status_before"] = status_before.stdout.splitlines()
    if status_before.returncode != 0:
        payload["status"] = "git_status_failed"
        payload["git_status_error"] = status_before.stderr.strip()
        return payload

    if not commit:
        payload["status"] = "validated"
        payload["commit_status"] = "dry_run"
        payload["next_command"] = f"python3 scripts/daily_run.py --date {as_of} --commit"
        return payload

    staged_paths = _existing_daily_paths(as_of, root)
    if staged_paths:
        add_result = _run(runner, ["git", "add", *[str(path.relative_to(root)) for path in staged_paths]], root)
    else:
        add_result = subprocess.CompletedProcess(["git", "add"], 0, "", "")
    payload["git_add"] = _summary(add_result)
    if add_result.returncode != 0:
        payload["status"] = "git_add_failed"
        return payload

    diff_result = _run(runner, ["git", "diff", "--cached", "--quiet"], root)
    if diff_result.returncode == 0:
        payload["status"] = "validated"
        payload["commit_status"] = "no_daily_changes"
        payload["staged_paths"] = []
        return payload
    if diff_result.returncode not in {0, 1}:
        payload["status"] = "git_diff_failed"
        payload["git_diff"] = _summary(diff_result)
        return payload

    commit_message = message or f"daily: {as_of} us market simulation"
    commit_result = _run(runner, ["git", "commit", "-m", commit_message], root)
    payload["git_commit"] = _summary(commit_result)
    payload["staged_paths"] = [str(path.relative_to(root)) for path in staged_paths]
    if commit_result.returncode != 0:
        payload["status"] = "git_commit_failed"
        return payload

    status_after = _run(runner, ["git", "status", "--short"], root)
    payload["git_status_after"] = status_after.stdout.splitlines()
    payload["status"] = "committed"
    payload["commit_status"] = "committed"
    return payload


def _existing_daily_paths(as_of: str, root: Path) -> list[Path]:
    candidates = [
        root / "data" / "market_snapshots" / f"{as_of}.json",
        root / "data" / "event_risk" / f"{as_of}.json",
        root / "data" / "performance" / f"{as_of}.json",
        root / "data" / "live_gate" / f"{as_of}.json",
        root / "data" / "run_cards" / f"{as_of}.json",
        root / "data" / "source_checks" / f"{as_of}.json",
        root / "data" / "equity_curve.csv",
        root / "journal" / "fill_reviews" / f"{as_of}.json",
        root / "journal" / "apply_logs" / f"{as_of}.dry_run.json",
        root / "journal" / "apply_logs" / f"{as_of}.apply.json",
        root / "journal" / "paper_trades.csv",
        root / "reports" / f"{as_of}.generated.md",
        root / "reports" / f"{as_of}.md",
    ]
    return [path for path in candidates if path.exists()]


def _run(runner: Runner, args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return runner(args, cwd=root, text=True, capture_output=True)


def _summary(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "args": list(proc.args) if isinstance(proc.args, (list, tuple)) else proc.args,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout.splitlines()[-20:] if proc.stdout else [],
        "stderr_tail": proc.stderr.splitlines()[-20:] if proc.stderr else [],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Workflow date YYYY-MM-DD")
    parser.add_argument("--commit", action="store_true", help="Commit daily generated artifacts after validation passes")
    parser.add_argument("--message", help="Override the git commit message")
    parser.add_argument("--json", action="store_true", help="Print full JSON payload")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = run_daily(args.date, commit=args.commit, message=args.message)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(payload["status"])
        if payload.get("commit_status"):
            print(f"commit_status: {payload['commit_status']}")
        if payload.get("next_command"):
            print(f"next: {payload['next_command']}")
    return 0 if payload["status"] in {"validated", "committed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
