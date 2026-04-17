#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.kb_atomization_lib import DEFAULT_SOURCE_OUTPUT, load_json, validate_source_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate M8B.2a source registry coverage.")
    parser.add_argument("--source-manifest", default=str(DEFAULT_SOURCE_OUTPUT))
    args = parser.parse_args()

    manifest = load_json(Path(args.source_manifest))
    errors = validate_source_manifest(manifest)
    if errors:
        print("KB coverage validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    counts = manifest["coverage_summary"]["parse_status_counts"]
    print(
        "KB coverage validation passed: "
        f"registered={manifest['coverage_summary']['total_registered']} "
        f"parsed={counts['parsed']} partial={counts['partial']} blocked={counts['blocked']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
