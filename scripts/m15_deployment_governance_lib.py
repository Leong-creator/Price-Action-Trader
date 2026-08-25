#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = ROOT / "reports" / "runtime" / "m15_deployment_manifest.json"
ALLOWED_DEVELOPMENT_BRANCH = re.compile(
    r"^(?:(?:codex/)?(?:feature|fix|chore|refactor|test|docs|integration)/[A-Za-z0-9._-]+"
    r"|codex/(?:feature|fix|chore|refactor|test|docs|integration)-[A-Za-z0-9._-]+)$"
)
DEFAULT_RUNTIME_FILES = (
    "scripts/run_m15_longbridge_sdk_runtime.py",
    "scripts/m15_longbridge_serve_transport_lib.py",
    "scripts/m15_longbridge_sdk_runtime_lib.py",
    "scripts/m15_longbridge_sdk_account_lib.py",
    "scripts/m15_longbridge_realtime_signal_router_lib.py",
    "scripts/m15_longbridge_realtime_execution_lib.py",
    "scripts/m15_opening_trade_readiness_lib.py",
)


@dataclass(frozen=True, slots=True)
class GitWorkspaceState:
    available: bool
    branch: str
    head_sha: str
    detached: bool
    dirty: bool
    dirty_paths: tuple[str, ...]
    remote_contains_head: bool
    error: str = ""


def _git(*args: str, root: Path = ROOT, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"git exited {result.returncode}")
    return result.stdout.strip()


def git_workspace_state(root: Path = ROOT) -> GitWorkspaceState:
    try:
        head_sha = _git("rev-parse", "HEAD", root=root)
        branch = _git("branch", "--show-current", root=root)
        porcelain = _git("status", "--porcelain=v1", "--untracked-files=normal", root=root)
        remote_rows = _git("branch", "-r", "--contains", head_sha, root=root, check=False)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return GitWorkspaceState(False, "", "", False, True, (), False, str(exc))
    dirty_paths = tuple(
        row[3:].strip() if len(row) > 3 else row.strip()
        for row in porcelain.splitlines()
        if row.strip()
    )
    return GitWorkspaceState(
        available=True,
        branch=branch,
        head_sha=head_sha,
        detached=not bool(branch),
        dirty=bool(dirty_paths),
        dirty_paths=dirty_paths,
        remote_contains_head=any(row.strip() for row in remote_rows.splitlines()),
    )


def branch_allowed_for_development(branch: str) -> bool:
    return bool(ALLOWED_DEVELOPMENT_BRANCH.fullmatch(branch)) and branch not in {"main", "master"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_repo_path(value: str | Path, root: Path = ROOT) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def relative_path(path: Path, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def issue_manifest(
    config_path: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    runtime_files: Iterable[str | Path] = DEFAULT_RUNTIME_FILES,
    root: Path = ROOT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    state = git_workspace_state(root)
    errors: list[str] = []
    if not state.available:
        errors.append(f"git_unavailable:{state.error}")
    if state.detached:
        errors.append("detached_head")
    if state.dirty:
        errors.append("dirty_worktree")
    if not state.remote_contains_head:
        errors.append("head_not_present_on_remote")
    config = resolve_repo_path(config_path, root)
    if not config.is_file():
        errors.append("config_missing")
    source_paths = [resolve_repo_path(path, root) for path in runtime_files]
    missing_sources = [relative_path(path, root) for path in source_paths if not path.is_file()]
    if missing_sources:
        errors.append("runtime_source_missing")
    if errors:
        raise ValueError(",".join(errors))
    payload = {
        "schema_version": "m15.deployment-manifest.v1",
        "issued_at": generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repo_root": str(root.resolve()),
        "branch": state.branch,
        "head_sha": state.head_sha,
        "remote_verified_at_issue": True,
        "config_path": relative_path(config, root),
        "config_sha256": sha256_file(config),
        "runtime_files": {
            relative_path(path, root): sha256_file(path)
            for path in source_paths
        },
    }
    destination = resolve_repo_path(manifest_path, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def verify_manifest(
    config_path: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    root: Path = ROOT,
) -> dict[str, Any]:
    manifest = resolve_repo_path(manifest_path, root)
    state = git_workspace_state(root)
    try:
        manifest_repo_path = relative_path(manifest, root)
    except ValueError:
        manifest_repo_path = ""
    dirty_paths = tuple(path for path in state.dirty_paths if path != manifest_repo_path)
    issues: list[str] = []
    payload: dict[str, Any] = {}
    if not manifest.is_file():
        issues.append("deployment_manifest_missing")
    else:
        try:
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            issues.append("deployment_manifest_invalid")
    if not state.available:
        issues.append("git_workspace_unavailable")
    else:
        if state.detached:
            issues.append("detached_head")
        if dirty_paths:
            issues.append("dirty_worktree")
        if payload and payload.get("head_sha") != state.head_sha:
            issues.append("deployment_commit_drift")
    config = resolve_repo_path(config_path, root)
    if not config.is_file():
        issues.append("deployment_config_missing")
    elif payload and payload.get("config_sha256") != sha256_file(config):
        issues.append("deployment_config_drift")
    runtime_files = payload.get("runtime_files", {}) if payload else {}
    if payload and not isinstance(runtime_files, dict):
        issues.append("deployment_runtime_files_invalid")
        runtime_files = {}
    for name, expected_hash in runtime_files.items():
        path = resolve_repo_path(str(name), root)
        if not path.is_file():
            issues.append(f"deployment_source_missing:{name}")
        elif sha256_file(path) != str(expected_hash):
            issues.append(f"deployment_source_drift:{name}")
    return {
        "schema_version": "m15.deployment-governance.v1",
        "verified": not issues,
        "issues": issues,
        "manifest_path": str(manifest.resolve()),
        "branch": state.branch,
        "head_sha": state.head_sha,
        "worktree_clean": state.available and not dirty_paths,
        "dirty_paths": list(dirty_paths[:20]),
        "manifest": payload,
    }
