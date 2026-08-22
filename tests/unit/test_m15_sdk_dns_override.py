from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_m15_sdk_dns_override import (
    HOSTS,
    QUOTE_HOST,
    doh_ipv4_addresses,
    resolve_overrides,
    read_cached_overrides,
    recently_sdk_validated_quote_address,
    tls_reachable_address,
    valid_ipv4,
    process_local_environment,
    sdk_quote_endpoint_reachable,
    sdk_quote_system_dns_reachable,
    environment_without_m15_dns_override,
    prepare,
    write_shell_environment,
    write_system_dns_environment,
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

    @patch("scripts.prepare_m15_sdk_dns_override.doh_ipv4_addresses")
    @patch("scripts.prepare_m15_sdk_dns_override.tls_reachable_address")
    def test_reachable_cached_endpoints_are_preserved_on_boot(
        self,
        tls_probe,
        doh_probe,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            overrides = {
                host: f"203.0.113.{index + 1}"
                for index, host in enumerate(HOSTS)
            }
            cache.write_text(json.dumps({"overrides": overrides}), encoding="utf-8")
            tls_probe.side_effect = lambda _host, addresses: next(iter(addresses), "")

            selected, source = resolve_overrides(cache)

            self.assertEqual(selected, overrides)
            self.assertEqual(source, "reachable_cache")
            doh_probe.assert_not_called()

    def test_process_environment_preserves_proxy_and_adds_child_only_override(self) -> None:
        overrides = {host: f"203.0.113.{index + 1}" for index, host in enumerate(HOSTS)}
        environment = process_local_environment(
            {"library": "/tmp/liboverride.so", "overrides": overrides},
            base_environment={
                "HTTP_PROXY": "http://127.0.0.1:10808",
                "LD_PRELOAD": "/tmp/existing.so",
                "NO_PROXY": "localhost",
            },
        )

        self.assertEqual(environment["HTTP_PROXY"], "http://127.0.0.1:10808")
        self.assertEqual(
            environment["LD_PRELOAD"],
            "/tmp/liboverride.so:/tmp/existing.so",
        )
        self.assertTrue(all(host in environment["NO_PROXY"] for host in HOSTS))
        self.assertEqual(environment["NO_PROXY"], environment["no_proxy"])

    def test_process_environment_accepts_system_dns_payload_without_override(self) -> None:
        environment = process_local_environment(
            {"override_enabled": False},
            base_environment={
                "HTTP_PROXY": "http://127.0.0.1:10808",
                "LD_PRELOAD": "/tmp/libm15_sdk_dns_override.so:/tmp/other.so",
                "M15_LONGBRIDGE_DNS_OVERRIDES": "stale",
            },
        )

        self.assertEqual(
            environment["HTTP_PROXY"],
            "http://127.0.0.1:10808",
        )
        self.assertEqual(environment["LD_PRELOAD"], "/tmp/other.so")
        self.assertNotIn("M15_LONGBRIDGE_DNS_OVERRIDES", environment)
        self.assertNotIn("NO_PROXY", environment)
        self.assertNotIn("no_proxy", environment)

    def test_system_dns_probe_removes_only_project_override(self) -> None:
        captured: dict[str, object] = {}

        class Result:
            returncode = 0

        def runner(command, **kwargs):
            captured["command"] = command
            captured.update(kwargs)
            return Result()

        base = {
            "HTTP_PROXY": "http://127.0.0.1:10808",
            "LD_PRELOAD": "/tmp/libm15_sdk_dns_override.so:/tmp/other.so",
            "M15_LONGBRIDGE_DNS_OVERRIDES": "quote=203.0.113.1",
        }
        self.assertTrue(
            sdk_quote_system_dns_reachable(
                Path("/tmp/runtime.json"),
                runner=runner,
                base_environment=base,
            )
        )
        environment = captured["env"]
        self.assertEqual(environment["HTTP_PROXY"], base["HTTP_PROXY"])
        self.assertEqual(environment["LD_PRELOAD"], "/tmp/other.so")
        self.assertNotIn("M15_LONGBRIDGE_DNS_OVERRIDES", environment)
        self.assertNotIn("NO_PROXY", environment)
        self.assertNotIn("no_proxy", environment)
        self.assertIn("/tmp/runtime.json", captured["command"])

    def test_clean_environment_drops_empty_project_preload(self) -> None:
        environment = environment_without_m15_dns_override(
            {
                "LD_PRELOAD": "/tmp/libm15_sdk_dns_override.so",
                "M15_LONGBRIDGE_DNS_OVERRIDES": "quote=203.0.113.1",
            }
        )
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertNotIn("M15_LONGBRIDGE_DNS_OVERRIDES", environment)
        self.assertNotIn("NO_PROXY", environment)
        self.assertNotIn("no_proxy", environment)

    def test_clean_environment_removes_only_project_proxy_bypass_hosts(self) -> None:
        environment = environment_without_m15_dns_override(
            {
                "HTTP_PROXY": "http://127.0.0.1:10808",
                "M15_LONGBRIDGE_DNS_OVERRIDES": "quote=203.0.113.1",
                "NO_PROXY": "localhost,openapi.longbridge.cn,internal.example",
                "no_proxy": "localhost,openapi.longbridge.cn,internal.example",
            }
        )

        self.assertEqual(environment["HTTP_PROXY"], "http://127.0.0.1:10808")
        self.assertEqual(environment["NO_PROXY"], "localhost,internal.example")
        self.assertEqual(environment["no_proxy"], "localhost,internal.example")

    def test_system_dns_environment_removes_only_project_preload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "system.env"
            library = Path(tmp) / "libm15_sdk_dns_override.so"
            write_system_dns_environment(path, library)
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        f'export LD_PRELOAD="{library}:/tmp/other.so"; '
                        'export M15_LONGBRIDGE_DNS_OVERRIDES="stale"; '
                        f'source "{path}"; '
                        'printf "%s|%s|%s" "${LD_PRELOAD:-}" "${M15_LONGBRIDGE_DNS_OVERRIDES:-}" "${NO_PROXY:-}"'
                    ),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            preload, mapping, no_proxy = result.stdout.split("|", 2)
            self.assertEqual(preload, "/tmp/other.so")
            self.assertEqual(mapping, "")
            self.assertEqual(no_proxy, "")

    @patch(
        "scripts.prepare_m15_sdk_dns_override.sdk_quote_system_dns_reachable",
        return_value=True,
    )
    @patch("scripts.prepare_m15_sdk_dns_override.compile_override")
    @patch("scripts.prepare_m15_sdk_dns_override.resolve_overrides")
    def test_prepare_prefers_validated_system_dns_without_compiling_fallback(
        self,
        resolve,
        compile_fallback,
        system_probe,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_config = root / "runtime.json"
            runtime_config.write_text("{}", encoding="utf-8")
            env_file = root / "runtime.env"

            payload = prepare(
                root / "cache",
                env_file,
                runtime_config_path=runtime_config,
            )

            system_probe.assert_called_once_with(runtime_config)
            compile_fallback.assert_not_called()
            resolve.assert_not_called()
            self.assertFalse(payload["override_enabled"])
            self.assertEqual(payload["source"], "normal_sdk_route_validated")
            self.assertNotIn(
                "export LD_PRELOAD=\"/",
                env_file.read_text(encoding="utf-8"),
            )

    @patch(
        "scripts.prepare_m15_sdk_dns_override.sdk_quote_endpoint_reachable",
        return_value=True,
    )
    @patch(
        "scripts.prepare_m15_sdk_dns_override.sdk_quote_system_dns_reachable",
        return_value=False,
    )
    def test_prepare_uses_recent_validated_process_cache_when_normal_route_fails(
        self,
        system_probe,
        cached_probe,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_config = root / "runtime.json"
            runtime_config.write_text("{}", encoding="utf-8")
            cache_dir = root / "cache"
            cache_dir.mkdir()
            library = cache_dir / "libm15_sdk_dns_override.so"
            library.touch()
            overrides = {
                host: f"203.0.113.{index + 1}"
                for index, host in enumerate(HOSTS)
            }
            (cache_dir / "m15_sdk_dns_override.json").write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now(UTC).isoformat(),
                        "quote_sdk_validated": True,
                        "overrides": overrides,
                    }
                ),
                encoding="utf-8",
            )
            env_file = root / "runtime.env"

            payload = prepare(
                cache_dir,
                env_file,
                runtime_config_path=runtime_config,
            )

            self.assertTrue(payload["override_enabled"])
            self.assertEqual(payload["source"], "sdk_validated_cache")
            self.assertEqual(payload["overrides"], overrides)
            cached_probe.assert_called_once()
            system_probe.assert_called_once_with(runtime_config)
            self.assertIn(
                "M15_LONGBRIDGE_DNS_OVERRIDES",
                env_file.read_text(encoding="utf-8"),
            )

    @patch("scripts.prepare_m15_sdk_dns_override.doh_ipv4_addresses")
    @patch("scripts.prepare_m15_sdk_dns_override.tls_reachable_address")
    def test_quote_validator_rejects_tls_only_cache_and_selects_sdk_endpoint(
        self,
        tls_probe,
        doh_probe,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            overrides = {
                host: f"203.0.113.{index + 1}"
                for index, host in enumerate(HOSTS)
            }
            cache.write_text(json.dumps({"overrides": overrides}), encoding="utf-8")
            tls_probe.side_effect = lambda _host, addresses: next(iter(addresses), "")
            doh_probe.return_value = ["203.0.113.20", "203.0.113.21"]

            selected, source = resolve_overrides(
                cache,
                quote_validator=lambda address, _rows: address == "203.0.113.21",
            )

            self.assertEqual(selected["openapi-quote.longbridge.cn"], "203.0.113.21")
            self.assertIn("sdk_validated_dns", source)

    def test_sdk_quote_probe_uses_process_local_override(self) -> None:
        captured: dict[str, object] = {}

        class Result:
            returncode = 0

        def runner(command, **kwargs):
            captured["command"] = command
            captured.update(kwargs)
            return Result()

        overrides = {host: f"203.0.113.{index + 1}" for index, host in enumerate(HOSTS)}
        self.assertTrue(
            sdk_quote_endpoint_reachable(
                overrides["openapi-quote.longbridge.cn"],
                overrides,
                library=Path("/tmp/liboverride.so"),
                runtime_config_path=Path("/tmp/runtime.json"),
                runner=runner,
            )
        )
        environment = captured["env"]
        self.assertIn("M15_LONGBRIDGE_DNS_OVERRIDES", environment)
        self.assertIn("/tmp/runtime.json", captured["command"])

    def test_unused_trade_endpoint_does_not_block_cn_quote_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            overrides = {
                host: f"203.0.113.{index + 1}"
                for index, host in enumerate(HOSTS)
            }
            cache.write_text(json.dumps({"overrides": overrides}), encoding="utf-8")
            with patch(
                "scripts.prepare_m15_sdk_dns_override.tls_reachable_address",
                side_effect=lambda host, addresses: "" if host == "openapi-trade.longbridge.cn" else next(iter(addresses), ""),
            ):
                selected, source = resolve_overrides(
                    cache,
                    required_hosts={"openapi.longbridge.cn", "openapi-quote.longbridge.cn"},
                )

            self.assertEqual(
                selected["openapi-trade.longbridge.cn"],
                overrides["openapi-trade.longbridge.cn"],
            )
            self.assertIn("unused_endpoint_cache", source)

    def test_recent_sdk_validated_quote_cache_has_bounded_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-08-18T19:00:00Z",
                        "quote_sdk_validated": True,
                        "overrides": {QUOTE_HOST: "203.0.113.20"},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                recently_sdk_validated_quote_address(
                    cache,
                    now=datetime(
                        2026, 8, 18, 19, 4, 59,
                        tzinfo=UTC,
                    ),
                ),
                "203.0.113.20",
            )
            self.assertEqual(
                recently_sdk_validated_quote_address(
                    cache,
                    now=datetime(
                        2026, 8, 18, 19, 5, 1,
                        tzinfo=UTC,
                    ),
                ),
                "",
            )
