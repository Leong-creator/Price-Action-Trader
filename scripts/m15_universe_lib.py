from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE_PATH = ROOT / "config/m15_us_liquid_universe_300.json"


def load_m15_universe(path: str | Path = DEFAULT_UNIVERSE_PATH) -> tuple[str, ...]:
    source = Path(path).expanduser()
    if not source.is_absolute():
        source = ROOT / source
    payload = json.loads(source.read_text(encoding="utf-8"))
    symbols = tuple(str(symbol).strip().upper() for symbol in payload.get("symbols", []))
    if not symbols:
        raise ValueError("M15 universe must not be empty")
    if len(symbols) != len(set(symbols)):
        raise ValueError("M15 universe contains duplicate symbols")
    if len(symbols) > 450:
        raise ValueError("M15 universe exceeds the reserved 450-symbol application ceiling")
    return symbols


def validate_expansion(base_symbols: tuple[str, ...], expanded_symbols: tuple[str, ...]) -> dict[str, object]:
    prefix_matches = expanded_symbols[: len(base_symbols)] == base_symbols
    return {
        "base_count": len(base_symbols),
        "expanded_count": len(expanded_symbols),
        "added_count": max(0, len(expanded_symbols) - len(base_symbols)),
        "base_order_preserved": prefix_matches,
        "duplicates": len(expanded_symbols) - len(set(expanded_symbols)),
        "valid": prefix_matches and len(expanded_symbols) == 300 and len(expanded_symbols) == len(set(expanded_symbols)),
    }
