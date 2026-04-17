#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.kb_atomization_lib import (
    DEFAULT_CHUNK_OUTPUT,
    DEFAULT_SOURCE_OUTPUT,
    build_chunk_manifest,
    load_json,
    write_jsonl,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build M8B.2a chunk registry.")
    parser.add_argument("--source-manifest", default=str(DEFAULT_SOURCE_OUTPUT))
    parser.add_argument("--output", default=str(DEFAULT_CHUNK_OUTPUT))
    args = parser.parse_args()

    source_manifest = load_json(Path(args.source_manifest))
    chunks = build_chunk_manifest(source_manifest)
    write_jsonl(Path(args.output), chunks)
    print(f"Wrote {len(chunks)} chunk record(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
