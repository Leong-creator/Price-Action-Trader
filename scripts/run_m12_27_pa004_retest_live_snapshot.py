#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_27_pa004_retest_live_snapshot_lib import (  # noqa: E402
    M12_27_LIVE_MANIFEST,
    OUTPUT_DIR,
    run_m12_27_pa004_retest_live_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.27 PA004 diagnostic retest and readonly live snapshot summary.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Output directory.")
    parser.add_argument("--live-manifest", default=str(M12_27_LIVE_MANIFEST), help="Readonly feed manifest path.")
    args = parser.parse_args()
    summary = run_m12_27_pa004_retest_live_snapshot(
        output_dir=Path(args.output_dir),
        live_manifest_path=Path(args.live_manifest),
    )
    live = summary["live_readonly_snapshot"]
    print(
        "M12.27 complete: "
        f"PA004 long-only={summary['pa004_long_only_retest']['return_percent']}%, "
        f"live rows={live['row_count']}, deferred={live['deferred_count']} -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
