#!/usr/bin/env python3
from __future__ import annotations

from m11_5_paper_gate_recheck_lib import load_gate_recheck_config, run_m11_5_paper_gate_recheck


def main() -> int:
    config = load_gate_recheck_config()
    summary = run_m11_5_paper_gate_recheck(config)
    print(
        f"M11.5 paper gate recheck complete: {summary['gate_decision']} -> "
        f"{summary['output_dir']}/m11_5_paper_gate_recheck_report.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
