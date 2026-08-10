#!/usr/bin/env python3
"""Prepare a process-local DNS override for Longbridge SDK endpoints."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/m15_sdk_dns_override.c"
DEFAULT_CACHE_DIR = Path("~/.cache/price-action-trader").expanduser()
DEFAULT_ENV_FILE = ROOT / "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_startup/m15_sdk_dns_override.env"
HOSTS = (
    "openapi.longbridge.cn",
    "openapi-quote.longbridge.cn",
    "openapi-trade.longbridge.cn",
)


def valid_ipv4(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def doh_ipv4_addresses(
    host: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[str]:
    query = urllib.parse.urlencode({"name": host, "type": "A"})
    request = urllib.request.Request(
        f"https://dns.google/resolve?{query}",
        headers={"Accept": "application/dns-json"},
    )
    with opener(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if int(payload.get("Status", -1)) != 0:
        return []
    addresses: list[str] = []
    for row in payload.get("Answer", []) or []:
        value = str(row.get("data") or "") if isinstance(row, dict) else ""
        if valid_ipv4(value) and value not in addresses:
            addresses.append(value)
    return addresses


def tls_reachable_address(
    host: str,
    addresses: Iterable[str],
    *,
    connector: Callable[..., Any] = socket.create_connection,
    ssl_context_factory: Callable[[], Any] = ssl.create_default_context,
) -> str:
    for address in addresses:
        if not valid_ipv4(address):
            continue
        connection = None
        secure_connection = None
        try:
            connection = connector((address, 443), timeout=3)
            context = ssl_context_factory()
            secure_connection = context.wrap_socket(connection, server_hostname=host)
        except (OSError, ssl.SSLError, TimeoutError):
            if connection is not None:
                connection.close()
            continue
        try:
            return address
        finally:
            if secure_connection is not None:
                secure_connection.close()
            elif connection is not None:
                connection.close()
    return ""


def read_cached_overrides(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("overrides", {}) if isinstance(payload, dict) else {}
    return {
        host: str(rows.get(host) or "")
        for host in HOSTS
        if valid_ipv4(str(rows.get(host) or ""))
    }


def resolve_overrides(cache_path: Path) -> tuple[dict[str, str], str]:
    cached = read_cached_overrides(cache_path)
    overrides: dict[str, str] = {}
    source = "dns_over_https"
    for host in HOSTS:
        address = ""
        for attempt in range(3):
            try:
                address = tls_reachable_address(host, doh_ipv4_addresses(host))
            except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                address = ""
            if address:
                break
            if attempt < 2:
                time.sleep(0.25)
        if not address:
            address = tls_reachable_address(host, [cached.get(host, "")])
            source = "reachable_cache"
        if not address:
            raise RuntimeError(f"longbridge_dns_override_unavailable:{host}")
        overrides[host] = address
    return overrides, source


def compile_override(source: Path, output: Path) -> None:
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        raise RuntimeError("longbridge_dns_override_compiler_missing")
    if output.exists() and output.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.so")
    subprocess.run(
        [compiler, "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-o", str(temporary), str(source), "-ldl"],
        check=True,
        capture_output=True,
        text=True,
    )
    temporary.replace(output)


def write_shell_environment(path: Path, library: Path, overrides: dict[str, str]) -> None:
    mapping = ";".join(f"{host}={overrides[host]}" for host in HOSTS)
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./_-=;" for character in mapping):
        raise ValueError("unsafe_longbridge_dns_override_mapping")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'export LD_PRELOAD="{library}${{LD_PRELOAD:+:$LD_PRELOAD}}"\n'
        f'export M15_LONGBRIDGE_DNS_OVERRIDES="{mapping}"\n'
        f'export NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}{",".join(HOSTS)}"\n'
        'export no_proxy="$NO_PROXY"\n',
        encoding="utf-8",
    )


def process_local_environment(
    payload: dict[str, Any],
    *,
    base_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the child-only environment represented by a validated override."""
    environment = dict(base_environment if base_environment is not None else os.environ)
    library = str(payload.get("library") or "")
    overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
    if not library or any(not valid_ipv4(str(overrides.get(host) or "")) for host in HOSTS):
        raise RuntimeError("longbridge_dns_override_payload_incomplete")
    mapping = ";".join(f"{host}={overrides[host]}" for host in HOSTS)
    existing_preload = str(environment.get("LD_PRELOAD") or "")
    preload_parts = [part for part in existing_preload.split(":") if part and part != library]
    environment["LD_PRELOAD"] = ":".join([library, *preload_parts])
    environment["M15_LONGBRIDGE_DNS_OVERRIDES"] = mapping
    existing_no_proxy = str(environment.get("NO_PROXY") or environment.get("no_proxy") or "")
    no_proxy_parts = [part for part in existing_no_proxy.split(",") if part]
    for host in HOSTS:
        if host not in no_proxy_parts:
            no_proxy_parts.append(host)
    environment["NO_PROXY"] = ",".join(no_proxy_parts)
    environment["no_proxy"] = environment["NO_PROXY"]
    return environment


def prepare(cache_dir: Path, env_file: Path) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    library = cache_dir / "libm15_sdk_dns_override.so"
    cache_path = cache_dir / "m15_sdk_dns_override.json"
    compile_override(SOURCE, library)
    overrides, source = resolve_overrides(cache_path)
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": "m15.sdk-dns-override.v1",
        "generated_at": generated_at,
        "scope": "m15_processes_only",
        "proxy_settings_modified": False,
        "process_local_proxy_bypass": list(HOSTS),
        "process_local_proxy_variables_cleared": False,
        "system_dns_modified": False,
        "hosts_file_modified": False,
        "source": source,
        "overrides": overrides,
        "library": str(library),
        "environment_file": str(env_file),
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_shell_environment(env_file, library, overrides)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
    )
    args = parser.parse_args()
    payload = prepare(Path(args.cache_dir).expanduser(), Path(args.env_file).expanduser())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
