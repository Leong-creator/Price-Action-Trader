from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_m15_sdk_dns_override import (
    HOSTS,
    doh_ipv4_addresses,
    read_cached_overrides,
    tls_reachable_address,
    valid_ipv4,
    write_shell_environment,
)


class Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class M15SdkDnsOverrideTest(unittest.TestCase):
    def test_tls_probe_skips_an_address_that_cannot_finish_handshake(self) -> None:
        closed: list[str] = []

        class Connection:
            def __init__(self, address: str) -> None:
                self.address = address

            def close(self) -> None:
                closed.append(self.address)

        class Context:
            def wrap_socket(self, connection: Connection, *, server_hostname: str) -> Connection:
                self.server_hostname = server_hostname
                if connection.address == "1.1.1.1":
                    raise TimeoutError("tls timeout")
                return connection

        selected = tls_reachable_address(
            "openapi.longbridge.cn",
            ["invalid", "1.1.1.1", "8.8.8.8"],
            connector=lambda target, timeout: Connection(target[0]),
            ssl_context_factory=Context,
        )

        self.assertEqual(selected, "8.8.8.8")
        self.assertEqual(closed, ["1.1.1.1", "8.8.8.8"])

    def test_doh_parser_accepts_only_unique_ipv4_answers(self) -> None:
        rows = doh_ipv4_addresses(
            HOSTS[0],
            opener=lambda *_args, **_kwargs: Response({
                "Status": 0,
                "Answer": [
                    {"type": 5, "data": "alias.example"},
                    {"type": 1, "data": "139.196.35.5"},
                    {"type": 1, "data": "139.196.35.5"},
                    {"type": 28, "data": "::1"},
                ],
            }),
        )
        self.assertEqual(rows, ["139.196.35.5"])
        self.assertTrue(valid_ipv4(rows[0]))

    def test_cache_and_environment_are_project_process_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache.json"
            overrides = {host: f"203.0.113.{index + 1}" for index, host in enumerate(HOSTS)}
            cache.write_text(json.dumps({"overrides": overrides}), encoding="utf-8")
            self.assertEqual(read_cached_overrides(cache), overrides)
            env_file = root / "override.env"
            write_shell_environment(env_file, root / "override.so", overrides)
            text = env_file.read_text(encoding="utf-8")
            self.assertIn("M15_LONGBRIDGE_DNS_OVERRIDES", text)
            self.assertIn("LD_PRELOAD", text)
            self.assertIn("NO_PROXY", text)
            self.assertIn("openapi-quote.longbridge.cn", text)
            self.assertNotIn("unset HTTP_PROXY", text)
