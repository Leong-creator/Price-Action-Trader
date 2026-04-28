#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_26_cache_scanner_expansion_lib import run_m12_26_cache_scanner_expansion


def main() -> None:
    summary = run_m12_26_cache_scanner_expansion()
    print(
        "M12.26 cache scanner expansion complete: "
        f"first50_daily={summary['first50_daily_ready_symbols']} "
        f"first50_current_5m={summary['first50_current_5m_ready_symbols']} "
        f"candidates={summary['scanner_candidate_count']} "
        f"deferred_expansion={summary['additional_deferred_symbol_count']}"
    )


if __name__ == "__main__":
    main()
