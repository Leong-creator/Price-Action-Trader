#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.kb_atomization_lib import (
    DEFAULT_ATOM_OUTPUT,
    DEFAULT_CALLABLE_OUTPUT,
    DEFAULT_CHUNK_OUTPUT,
    DEFAULT_SOURCE_OUTPUT,
    build_callable_index,
    load_json,
    load_jsonl,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build M8B.2a callable atom index.")
    parser.add_argument("--source-manifest", default=str(DEFAULT_SOURCE_OUTPUT))
    parser.add_argument("--chunk-manifest", default=str(DEFAULT_CHUNK_OUTPUT))
    parser.add_argument("--atoms", default=str(DEFAULT_ATOM_OUTPUT))
    parser.add_argument("--output", default=str(DEFAULT_CALLABLE_OUTPUT))
    args = parser.parse_args()

    source_manifest = load_json(Path(args.source_manifest))
    chunks = load_jsonl(Path(args.chunk_manifest))
    atoms = load_jsonl(Path(args.atoms))
    callable_index = build_callable_index(source_manifest, chunks, atoms)
    write_json(Path(args.output), callable_index)
    print(f"Wrote callable index to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
