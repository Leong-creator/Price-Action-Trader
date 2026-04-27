#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_readonly_auth_preflight_lib import M12_0_DIR, run_m12_readonly_auth_preflight


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.0 Longbridge readonly auth preflight.")
    parser.add_argument("--output-dir", default=str(M12_0_DIR), help="Output directory for M12.0 artifacts.")
    parser.add_argument("--probe-symbol", default="SPY.US", help="Longbridge symbol used for readonly quote/kline probes.")
    args = parser.parse_args()
    artifact = run_m12_readonly_auth_preflight(Path(args.output_dir), probe_symbol=args.probe_symbol)
    print(f"M12.0 readonly auth preflight complete: {artifact['auth_status']} -> {args.output_dir}")


if __name__ == "__main__":
    main()

