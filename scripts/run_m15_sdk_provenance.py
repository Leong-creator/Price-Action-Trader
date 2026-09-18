#!/usr/bin/env python3
"""Offline: issue/verify environment receipt against committed official digest."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_sdk_provenance_lib import issue_environment_receipt, verify_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--wheel", type=Path, help="Issue receipt from independently pinned official wheel")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify_environment(ROOT)
    else:
        try:
            result = {"verified": True, "environment": issue_environment_receipt(args.wheel, ROOT)}
        except Exception as exc:
            result = {"verified": False, "issues": [str(exc)]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verified"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
