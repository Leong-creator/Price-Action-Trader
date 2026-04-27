#!/usr/bin/env python3
from __future__ import annotations

import json

from m10_capital_backtest_lib import run_m10_wave_a_capital_backtest


def main() -> int:
    summary = run_m10_wave_a_capital_backtest()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
