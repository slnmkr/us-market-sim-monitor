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

    required_file_checks: list[dict[str, Any]] = []
    for item in policy.get("required_files", []):
        required_path = root / item["path"]
        if not required_path.exists():
            blockers.append(_blocker("missing_required_file", f"Missing {item['path']}: {item['description']}"))
            required_file_checks.append({"path": item["path"], "status": "missing"})
            continue
        file_errors, file_warnings = _validate_required_file(item["path"], required_path, as_of)
        required_file_checks.append(
            {
                "path": item["path"],
                "status": "ok" if not file_errors else "invalid",
                "errors": file_errors,
                "warnings": file_warnings,
            }
        )
        blockers.extend(_blocker("invalid_required_file", f"{item['path']}: {error}") for error in file_errors)
        warnings.extend(f"{item['path']}: {warning}" for warning in file_warnings)

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
        "required_file_checks": required_file_checks,
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


def _validate_required_file(rel_path: str, path: Path, as_of: str) -> tuple[list[str], list[str]]:
    if rel_path == "config/live_mandate.json":
        return _validate_live_mandate(path, as_of)
    if rel_path == "config/broker_connection.json":
        return _validate_broker_manifest(path)
    return [], []


def _validate_live_mandate(path: Path, as_of: str) -> tuple[list[str], list[str]]:
    data, errors = _load_gate_json(path)
    warnings: list[str] = []
    if data is None:
        return errors, warnings

    required = {
        "user_written",
        "authorized_by",
        "created_on",
        "expires_on",
        "broker",
        "account_scope",
        "instrument_scope",
        "max_order_notional_usd",
        "max_gross_exposure_pct",
        "max_daily_loss_pct",
        "allowed_order_types",
        "no_automatic_live_orders",
    }
    errors.extend(_missing_fields(data, required))
    if errors:
        return errors, warnings

    if data.get("user_written") is not True:
        errors.append("user_written must be true")
    if data.get("no_automatic_live_orders") is not True:
        errors.append("no_automatic_live_orders must be true for manual live review")
    for field in ["authorized_by", "broker"]:
        if not str(data.get(field, "")).strip():
            errors.append(f"{field} must be non-empty")
    for field in ["account_scope", "instrument_scope", "allowed_order_types"]:
        if not isinstance(data.get(field), list) or not data[field] or not all(str(item).strip() for item in data[field]):
            errors.append(f"{field} must be a non-empty list of strings")
    for field in ["max_order_notional_usd", "max_gross_exposure_pct", "max_daily_loss_pct"]:
        value = _to_float(data.get(field))
        if value is None or value <= 0:
            errors.append(f"{field} must be a positive number")
    gross = _to_float(data.get("max_gross_exposure_pct"))
    daily_loss = _to_float(data.get("max_daily_loss_pct"))
    if gross is not None and gross > 1.0:
        errors.append("max_gross_exposure_pct must be <= 1.0")
    if daily_loss is not None and daily_loss > 0.1:
        warnings.append("max_daily_loss_pct is above 10%; review before live use")

    created = _parse_date(data.get("created_on"))
    expires = _parse_date(data.get("expires_on"))
    current = _parse_date(as_of)
    if created is None:
        errors.append("created_on must be an ISO date YYYY-MM-DD")
    if expires is None:
        errors.append("expires_on must be an ISO date YYYY-MM-DD")
    if expires is not None and current is not None and expires < current:
        errors.append(f"expires_on {data.get('expires_on')} is before gate date {as_of}")
    if created is not None and expires is not None and created > expires:
        errors.append("created_on must be on or before expires_on")

    secret_paths = _secret_like_paths(data)
    if secret_paths:
        errors.append("live mandate must not contain secret-like keys: " + ", ".join(secret_paths))
    return errors, warnings


def _validate_broker_manifest(path: Path) -> tuple[list[str], list[str]]:
    data, errors = _load_gate_json(path)
    warnings: list[str] = []
    if data is None:
        return errors, warnings

    required = {
        "broker_name",
        "environment",
        "account_type",
        "capabilities",
        "credentials_included",
        "credential_storage",
    }
    errors.extend(_missing_fields(data, required))
    if errors:
        return errors, warnings

    for field in ["broker_name", "account_type", "credential_storage"]:
        if not str(data.get(field, "")).strip():
            errors.append(f"{field} must be non-empty")
    if data.get("environment") not in {"paper", "live", "unknown"}:
        errors.append("environment must be one of: paper, live, unknown")
    if not isinstance(data.get("capabilities"), list) or not data["capabilities"] or not all(str(item).strip() for item in data["capabilities"]):
        errors.append("capabilities must be a non-empty list of strings")
    if data.get("credentials_included") is not False:
        errors.append("credentials_included must be false")
    if str(data.get("credential_storage", "")).strip() != "external_only":
        errors.append("credential_storage must be external_only")
    secret_paths = _secret_like_paths(data)
    if secret_paths:
        errors.append("broker manifest must not contain secret-like keys: " + ", ".join(secret_paths))
    return errors, warnings


def _load_gate_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = load_json(path)
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, ["must be a JSON object"]
    if data.get("template") is True:
        return None, ["template examples are not accepted as live gate inputs"]
    return data, []


def _missing_fields(data: dict[str, Any], fields: set[str]) -> list[str]:
    return [f"missing field {field}" for field in sorted(fields) if field not in data]


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _secret_like_paths(value: Any, prefix: str = "") -> list[str]:
    forbidden = ("api_key", "apikey", "access_token", "token", "password", "cookie", "secret")
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).lower()
            if any(item in lowered for item in forbidden):
                paths.append(path)
            paths.extend(_secret_like_paths(child, path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            paths.extend(_secret_like_paths(child, f"{prefix}[{idx}]"))
    return paths


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
