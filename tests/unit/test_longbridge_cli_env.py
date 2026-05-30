from __future__ import annotations

import unittest
from unittest import mock

from scripts.longbridge_cli_env import build_longbridge_cli_env


class LongbridgeCliEnvTests(unittest.TestCase):
    def test_defaults_to_cn_region_and_cn_quote_endpoint(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            env = build_longbridge_cli_env()

        self.assertEqual(env["LONGBRIDGE_REGION"], "cn")
        self.assertEqual(env["LONGBRIDGE_HTTP_URL"], "https://openapi.longbridge.cn")
        self.assertEqual(env["LONGBRIDGE_QUOTE_WS_URL"], "wss://openapi-quote.longbridge.cn/v2")

    def test_respects_explicit_user_region(self) -> None:
        with mock.patch.dict("os.environ", {"LONGBRIDGE_REGION": "hk"}, clear=True):
            env = build_longbridge_cli_env()

        self.assertEqual(env["LONGBRIDGE_REGION"], "hk")
        self.assertNotIn("LONGBRIDGE_HTTP_URL", env)


if __name__ == "__main__":
    unittest.main()
