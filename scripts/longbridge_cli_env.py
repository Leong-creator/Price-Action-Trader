#!/usr/bin/env python3
from __future__ import annotations

import os


DEFAULT_LONGBRIDGE_REGION = "global"
DEFAULT_LONGBRIDGE_HTTP_URL = "https://openapi.longbridge.com"
DEFAULT_LONGBRIDGE_QUOTE_WS_URL = "wss://openapi-quote.longbridge.com/v2"
CN_LONGBRIDGE_HTTP_URL = "https://openapi.longbridge.cn"
CN_LONGBRIDGE_QUOTE_WS_URL = "wss://openapi-quote.longbridge.cn/v2"
DEFAULT_LONGBRIDGE_QUOTE_REGION = "cn"


def build_longbridge_cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("LONGBRIDGE_REGION", DEFAULT_LONGBRIDGE_REGION)
    region = env.get("LONGBRIDGE_REGION", "").lower()
    if region == "cn":
        env.setdefault("LONGBRIDGE_HTTP_URL", CN_LONGBRIDGE_HTTP_URL)
        env.setdefault("LONGBRIDGE_QUOTE_WS_URL", CN_LONGBRIDGE_QUOTE_WS_URL)
    elif region == DEFAULT_LONGBRIDGE_REGION:
        env.setdefault("LONGBRIDGE_HTTP_URL", DEFAULT_LONGBRIDGE_HTTP_URL)
        env.setdefault("LONGBRIDGE_QUOTE_WS_URL", DEFAULT_LONGBRIDGE_QUOTE_WS_URL)
    return env


def build_longbridge_quote_cli_env() -> dict[str, str]:
    """Build the CLI environment for quote/kline commands.

    Account and order commands use the global endpoint on this installation,
    while the quote endpoint is reachable through the CN region. Keep the two
    routes explicit so an account connectivity fix cannot disable market data.
    """
    env = dict(os.environ)
    region = env.get("LONGBRIDGE_QUOTE_REGION", DEFAULT_LONGBRIDGE_QUOTE_REGION).lower()
    env["LONGBRIDGE_REGION"] = region
    if region == "cn":
        env["LONGBRIDGE_HTTP_URL"] = env.get("LONGBRIDGE_QUOTE_HTTP_URL", CN_LONGBRIDGE_HTTP_URL)
        env["LONGBRIDGE_QUOTE_WS_URL"] = env.get("LONGBRIDGE_QUOTE_WS_URL_OVERRIDE", CN_LONGBRIDGE_QUOTE_WS_URL)
    elif region == DEFAULT_LONGBRIDGE_REGION:
        env["LONGBRIDGE_HTTP_URL"] = env.get("LONGBRIDGE_QUOTE_HTTP_URL", DEFAULT_LONGBRIDGE_HTTP_URL)
        env["LONGBRIDGE_QUOTE_WS_URL"] = env.get("LONGBRIDGE_QUOTE_WS_URL_OVERRIDE", DEFAULT_LONGBRIDGE_QUOTE_WS_URL)
    else:
        env.pop("LONGBRIDGE_HTTP_URL", None)
        env.pop("LONGBRIDGE_QUOTE_WS_URL", None)
    return env
