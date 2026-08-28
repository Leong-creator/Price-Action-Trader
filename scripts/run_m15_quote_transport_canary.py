#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_quote_transport_canary_lib import load_symbols, run_sdk_canary


def endpoint_overrides(region: str) -> dict[str, str]:
    suffix = "cn" if region.lower() == "cn" else "com"
    return {
        "http_url": f"https://openapi.longbridge.{suffix}",
        "quote_ws_url": f"wss://openapi-quote.longbridge.{suffix}/v2",
        "trade_ws_url": f"wss://openapi-trade.longbridge.{suffix}/v2",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated read-only Longbridge quote transport canary.")
    parser.add_argument("--transport", choices=("sdk",), default="sdk")
    parser.add_argument("--universe", default=str(ROOT / "config" / "m15_us_liquid_universe_300.json"))
    parser.add_argument("--limit", type=int, choices=(3, 147), required=True)
    parser.add_argument("--fields", choices=("quote", "trade", "quote,trade"), required=True)
    parser.add_argument("--duration-seconds", type=float, default=1800)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--client-id-file", default="~/.config/price-action-trader/longbridge_sdk_client_id")
    parser.add_argument("--region", choices=("cn", "global"), default="cn")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    symbols = load_symbols(args.universe, args.limit)
    fields = tuple(args.fields.split(","))
    import longbridge.openapi as sdk

    client_id = Path(args.client_id_file).expanduser().read_text(encoding="utf-8").strip()
    oauth = sdk.OAuthBuilder(client_id).build(lambda url: print(f"authorization_required:{url}"))
    config = sdk.Config.from_oauth(oauth, **endpoint_overrides(args.region))
    payload = run_sdk_canary(
        sdk=sdk,
        sdk_config=config,
        symbols=symbols,
        fields=fields,
        duration_seconds=args.duration_seconds,
        batch_size=args.batch_size if args.batch_size is not None else 50,
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not payload.get("missing_subscriptions") else 3


if __name__ == "__main__":
    raise SystemExit(main())
