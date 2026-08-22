#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.m15_deployment_governance_lib import (
    DEFAULT_MANIFEST_PATH,
    branch_allowed_for_development,
    git_workspace_state,
    issue_manifest,
    verify_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue or verify the local M15 deployment manifest.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--issue", action="store_true")
    parser.add_argument("--check-development", action="store_true")
    args = parser.parse_args()
    if args.check_development:
        state = git_workspace_state()
        payload = {
            "allowed": state.available and branch_allowed_for_development(state.branch),
            "branch": state.branch,
            "head_sha": state.head_sha,
            "dirty": state.dirty,
            "issues": ([] if branch_allowed_for_development(state.branch) else ["development_branch_not_allowed"]),
        }
    elif args.issue:
        payload = issue_manifest(args.config, manifest_path=args.manifest)
        payload = {"issued": True, "manifest": payload}
    else:
        payload = verify_manifest(args.config, manifest_path=args.manifest)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("allowed", payload.get("issued", payload.get("verified", False))) else 3


if __name__ == "__main__":
    raise SystemExit(main())
