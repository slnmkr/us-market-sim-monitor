#!/usr/bin/env python3
"""Evaluate whether the project is eligible for manual live-account review.

This is a local safety gate. It never connects to a broker, never reads secrets,
and never places orders.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "live_gate_policy.json"
PERFORMANCE_DIR = ROOT / "data" / "performance"
LIVE_GATE_DIR = ROOT / "data" / "live_gate"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def evaluate_live_gate(
    as_of: str,
    *,
    root: Path = ROOT,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    policy_path = policy_path or (root / "config" / "live_gate_policy.json")
    policy = load_json(policy_path)
    blockers: list[dict[str, str]] = []
    warnings: list[str] = []

    performance_path = root / "data" / "performance" / f"{as_of}.json"
    performance = _optional_json(performance_path)
    if performance is None:
        blockers.append(_blocker("missing_performance", f"Missing {performance_path}"))
    elif performance.get("status") != "ok":
        blockers.append(_blocker("performance_not_ok", f"Performance status is {performance.get('status')!r}"))
    else:
        paper = performance.get("paper", {})
        observations = int(paper.get("observations", 0))
        total_return = float(paper.get("total_return_pct", 0.0))
        max_drawdown = float(paper.get("max_drawdown_pct", 0.0))
        if observations < int(policy["min_paper_observations"]):
            blockers.append(
                _blocker(
                    "insufficient_paper_observations",
                    f"Paper observations {observations} < required {policy['min_paper_observations']}",
                )
            )
        if total_return < float(policy["min_paper_total_return_pct"]):
            blockers.append(
                _blocker(
                    "paper_return_below_threshold",
                    f"Paper total return {total_return:.4f}% < required {policy['min_paper_total_return_pct']:.4f}%",
                )
            )
        if max_drawdown < float(policy["max_allowed_drawdown_pct"]):
            blockers.append(
                _blocker(
                    "drawdown_too_large",
                    f"Paper max drawdown {max_drawdown:.4f}% < allowed {policy['max_allowed_drawdown_pct']:.4f}%",
                )
            )

    for item in policy.get("required_files", []):
        required_path = root / item["path"]
        if not required_path.exists():
            blockers.append(_blocker("missing_required_file", f"Missing {item['path']}: {item['description']}"))

    remote_info = _git_remote_info(root)
    if policy.get("require_git_remote") and not remote_info["has_remote"]:
        blockers.append(_blocker("missing_git_remote", "No git remote is configured for off-machine audit trail."))

    identity = _git_identity(root)
    if identity.get("email", "").endswith("@local.invalid"):
        warnings.append("Git user.email is a local placeholder, not a verified GitHub email.")

    status = policy["blocked_status"] if blockers else policy["eligible_status"]
    return {
        "as_of": as_of,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "data_boundary": "Local live-account preflight only; no broker connection, no secrets, no account access, no live orders.",
        "blockers": blockers,
        "warnings": warnings,
        "policy": {
            "min_paper_observations": policy["min_paper_observations"],
            "min_paper_total_return_pct": policy["min_paper_total_return_pct"],
            "max_allowed_drawdown_pct": policy["max_allowed_drawdown_pct"],
            "require_git_remote": policy["require_git_remote"],
        },
        "git": {
            **remote_info,
            "identity": identity,
        },
    }


def write_live_gate(as_of: str, payload: dict[str, Any], output_dir: Path = LIVE_GATE_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{as_of}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def _optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return load_json(path)


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _git_remote_info(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "remote", "-v"],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    remotes = sorted(set(line.strip() for line in proc.stdout.splitlines() if line.strip()))
    return {"has_remote": bool(remotes), "remotes": remotes}


def _git_identity(root: Path) -> dict[str, str]:
    return {
        "name": _git_config(root, "user.name"),
        "email": _git_config(root, "user.email"),
    }


def _git_config(root: Path, key: str) -> str:
    proc = subprocess.run(
        ["git", "config", "--local", "--get", key],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.strip()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Gate date YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = evaluate_live_gate(args.date)
    path = write_live_gate(args.date, payload)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

