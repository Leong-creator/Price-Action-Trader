#!/usr/bin/env python3
from __future__ import annotations

import os


DEFAULT_LONGBRIDGE_REGION = "cn"
DEFAULT_LONGBRIDGE_HTTP_URL = "https://openapi.longbridge.cn"
DEFAULT_LONGBRIDGE_QUOTE_WS_URL = "wss://openapi-quote.longbridge.cn/v2"


def build_longbridge_cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("LONGBRIDGE_REGION", DEFAULT_LONGBRIDGE_REGION)
    if env.get("LONGBRIDGE_REGION", "").lower() == DEFAULT_LONGBRIDGE_REGION:
        env.setdefault("LONGBRIDGE_HTTP_URL", DEFAULT_LONGBRIDGE_HTTP_URL)
        env.setdefault("LONGBRIDGE_QUOTE_WS_URL", DEFAULT_LONGBRIDGE_QUOTE_WS_URL)
    return env
