#!/usr/bin/env python3
from __future__ import annotations

from m12_universe_kline_cache_lib import load_universe_kline_cache_config, run_m12_universe_kline_cache


def main() -> int:
    config = load_universe_kline_cache_config()
    summary = run_m12_universe_kline_cache(config)
    print(
        "M12.8 universe kline cache inventory complete: "
        f"symbols={summary['universe_symbol_count']} / "
        f"cache_present={summary['cache_present_symbol_count']} / "
        f"target_complete={summary['target_complete_symbol_count']} / "
        f"deferred={summary['deferred_item_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
