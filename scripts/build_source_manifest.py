#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.kb_atomization_lib import DEFAULT_SOURCE_OUTPUT, build_source_manifest, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Build M8B.2a source registry manifest.")
    parser.add_argument("--output", default=str(DEFAULT_SOURCE_OUTPUT))
    args = parser.parse_args()

    manifest = build_source_manifest()
    write_json(Path(args.output), manifest)
    print(f"Wrote source manifest to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
