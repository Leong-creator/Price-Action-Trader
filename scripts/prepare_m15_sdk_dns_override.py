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
import sys
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
QUOTE_HOST = "openapi-quote.longbridge.cn"
DEFAULT_RUNTIME_CONFIG = ROOT / "config/examples/m15_longbridge_sdk_runtime.contract_v1.json"

SDK_QUOTE_PROBE = """
import sys
import longbridge.openapi as sdk
from scripts.m15_longbridge_sdk_runtime_lib import (
    load_config,
    read_client_id,
    sdk_config_from_oauth,
)

config = load_config(sys.argv[1])
oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
quote = sdk.QuoteContext(sdk_config_from_oauth(sdk, oauth, config.quote_region))
rows = quote.quote(["SPY.US"])
raise SystemExit(0 if rows and str(rows[0].symbol) == "SPY.US" else 2)
"""


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


def recently_sdk_validated_quote_address(
    path: Path,
    *,
    now: datetime | None = None,
    ttl_seconds: int = 300,
) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if payload.get("quote_sdk_validated") is not True:
        return ""
    try:
        generated_at = datetime.fromisoformat(
            str(
                payload.get("quote_sdk_validated_at")
                or payload.get("generated_at")
                or ""
            ).replace("Z", "+00:00")
        ).astimezone(UTC)
    except ValueError:
        return ""
    current = now or datetime.now(UTC)
    if (current - generated_at).total_seconds() > ttl_seconds:
        return ""
    address = str((payload.get("overrides") or {}).get(QUOTE_HOST) or "")
    return address if valid_ipv4(address) else ""


def resolve_overrides(
    cache_path: Path,
    *,
    quote_validator: Callable[[str, dict[str, str]], bool] | None = None,
    required_hosts: set[str] | None = None,
) -> tuple[dict[str, str], str]:
    cached = read_cached_overrides(cache_path)
    required = set(HOSTS if required_hosts is None else required_hosts)
    overrides: dict[str, str] = {}
    sources: set[str] = set()
    # Resolve the generic and trade endpoints first so the quote SDK probe can
    # use a complete process-local mapping without touching system DNS.
    resolution_order = (HOSTS[0], HOSTS[2], HOSTS[1])
    for host in resolution_order:
        if host not in required:
            address = cached.get(host, "")
            if not address:
                try:
                    address = next(iter(doh_ipv4_addresses(host)), "")
                except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                    address = ""
            if not valid_ipv4(address):
                raise RuntimeError(f"longbridge_dns_override_unavailable:{host}")
            overrides[host] = address
            sources.add("unused_endpoint_cache")
            continue
        # A cached endpoint may already have passed a real SDK request.  A new
        # DNS answer that merely completes TLS is weaker evidence, so do not
        # replace a reachable cache entry on every boot.
        address = ""
        cached_address = cached.get(host, "")
        reachable_cached = tls_reachable_address(host, [cached_address])
        if reachable_cached:
            candidate_overrides = {**cached, **overrides, host: reachable_cached}
            if (
                host != QUOTE_HOST
                or quote_validator is None
                or quote_validator(reachable_cached, candidate_overrides)
            ):
                address = reachable_cached
                sources.add("sdk_validated_cache" if host == QUOTE_HOST and quote_validator else "reachable_cache")
        if not address:
            dns_candidates: list[str] = []
            for attempt in range(3):
                try:
                    for candidate in doh_ipv4_addresses(host):
                        if candidate not in dns_candidates:
                            dns_candidates.append(candidate)
                except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                    pass
                if dns_candidates:
                    break
                if attempt < 2:
                    time.sleep(0.25)
            for candidate in dns_candidates:
                if candidate == cached_address:
                    continue
                reachable = tls_reachable_address(host, [candidate])
                if not reachable:
                    continue
                candidate_overrides = {**cached, **overrides, host: reachable}
                if (
                    host == QUOTE_HOST
                    and quote_validator is not None
                    and not quote_validator(reachable, candidate_overrides)
                ):
                    continue
                address = reachable
                sources.add("sdk_validated_dns" if host == QUOTE_HOST and quote_validator else "dns_over_https")
                break
        if not address:
            raise RuntimeError(f"longbridge_dns_override_unavailable:{host}")
        overrides[host] = address
    source = "reachable_cache" if sources == {"reachable_cache"} else "+".join(sorted(sources))
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


def write_system_dns_environment(path: Path, library: Path) -> None:
    """Remove only this project's shim and preserve the user's network route."""
    library_text = str(library)
    if any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./_-"
        for character in library_text
    ):
        raise ValueError("unsafe_longbridge_dns_override_library")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'unset M15_LONGBRIDGE_DNS_OVERRIDES\n'
        'IFS=\':\' read -r -a _m15_preload_parts <<< "${LD_PRELOAD:-}"\n'
        '_m15_clean_preload=""\n'
        'for _m15_preload_part in "${_m15_preload_parts[@]}"; do\n'
        '  if [[ -z "$_m15_preload_part" || "${_m15_preload_part##*/}" == "libm15_sdk_dns_override.so" ]]; then\n'
        '    continue\n'
        '  fi\n'
        '  _m15_clean_preload="${_m15_clean_preload:+$_m15_clean_preload:}$_m15_preload_part"\n'
        'done\n'
        'if [[ -n "$_m15_clean_preload" ]]; then\n'
        '  export LD_PRELOAD="$_m15_clean_preload"\n'
        'else\n'
        '  unset LD_PRELOAD\n'
        'fi\n'
        'unset _m15_preload_parts _m15_preload_part _m15_clean_preload\n',
        encoding="utf-8",
    )


def process_local_environment(
    payload: dict[str, Any],
    *,
    base_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the child-only environment represented by a validated override."""
    environment = dict(base_environment if base_environment is not None else os.environ)
    if payload.get("override_enabled") is False:
        return environment_without_m15_dns_override(environment)
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


def environment_without_m15_dns_override(
    base_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Remove only this project's optional resolver shim from a child env."""
    environment = dict(base_environment if base_environment is not None else os.environ)
    project_override_was_active = bool(
        environment.get("M15_LONGBRIDGE_DNS_OVERRIDES")
    )
    environment.pop("M15_LONGBRIDGE_DNS_OVERRIDES", None)
    preload_parts = [
        part
        for part in str(environment.get("LD_PRELOAD") or "").split(":")
        if part and Path(part).name != "libm15_sdk_dns_override.so"
    ]
    if preload_parts:
        environment["LD_PRELOAD"] = ":".join(preload_parts)
    else:
        environment.pop("LD_PRELOAD", None)
    if project_override_was_active:
        for key in ("NO_PROXY", "no_proxy"):
            if key not in environment:
                continue
            retained = [
                part
                for part in str(environment.get(key) or "").split(",")
                if part and part not in HOSTS
            ]
            if retained:
                environment[key] = ",".join(retained)
            else:
                environment.pop(key, None)
    return environment


def sdk_quote_system_dns_reachable(
    runtime_config_path: Path,
    *,
    timeout_seconds: float = 4,
    runner: Callable[..., Any] = subprocess.run,
    base_environment: dict[str, str] | None = None,
) -> bool:
    """Prefer normal DNS when a harmless real SDK quote already succeeds."""
    environment = environment_without_m15_dns_override(base_environment)
    try:
        result = runner(
            [sys.executable, "-c", SDK_QUOTE_PROBE, str(runtime_config_path)],
            cwd=str(ROOT),
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return False
    return int(result.returncode) == 0


def sdk_quote_endpoint_reachable(
    address: str,
    overrides: dict[str, str],
    *,
    library: Path,
    runtime_config_path: Path,
    timeout_seconds: float = 4,
    runner: Callable[..., Any] = subprocess.run,
) -> bool:
    """Validate a candidate with a harmless real SDK quote request."""
    candidate_overrides = dict(overrides)
    candidate_overrides[QUOTE_HOST] = address
    if any(not valid_ipv4(str(candidate_overrides.get(host) or "")) for host in HOSTS):
        return False
    environment = process_local_environment(
        {"library": str(library), "overrides": candidate_overrides},
    )
    try:
        result = runner(
            [sys.executable, "-c", SDK_QUOTE_PROBE, str(runtime_config_path)],
            cwd=str(ROOT),
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return False
    return int(result.returncode) == 0


def prepare(
    cache_dir: Path,
    env_file: Path,
    *,
    runtime_config_path: Path | None = None,
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    library = cache_dir / "libm15_sdk_dns_override.so"
    cache_path = cache_dir / "m15_sdk_dns_override.json"
    cached_overrides = read_cached_overrides(cache_path)
    if runtime_config_path is not None and sdk_quote_system_dns_reachable(
        runtime_config_path,
    ):
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        write_system_dns_environment(env_file, library)
        return {
            "schema_version": "m15.sdk-dns-override.v2",
            "generated_at": generated_at,
            "scope": "m15_processes_only",
            "proxy_settings_modified": False,
            "process_local_proxy_bypass": [],
            "process_local_proxy_variables_cleared": False,
            "system_dns_modified": False,
            "hosts_file_modified": False,
            "source": "normal_sdk_route_validated",
            "override_enabled": False,
            "quote_sdk_validated": True,
            "quote_sdk_validated_at": generated_at,
            "overrides": {},
            "library": "",
            "environment_file": str(env_file),
        }
    if (
        runtime_config_path is not None
        and library.exists()
        and len(cached_overrides) == len(HOSTS)
        and recently_sdk_validated_quote_address(
            cache_path,
            ttl_seconds=24 * 60 * 60,
        )
        and sdk_quote_endpoint_reachable(
            cached_overrides[QUOTE_HOST],
            cached_overrides,
            library=library,
            runtime_config_path=runtime_config_path,
        )
    ):
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "schema_version": "m15.sdk-dns-override.v2",
            "generated_at": generated_at,
            "scope": "m15_processes_only",
            "proxy_settings_modified": False,
            "process_local_proxy_bypass": list(HOSTS),
            "process_local_proxy_variables_cleared": False,
            "system_dns_modified": False,
            "hosts_file_modified": False,
            "source": "sdk_validated_cache",
            "override_enabled": True,
            "quote_sdk_validated": True,
            "quote_sdk_validated_at": generated_at,
            "overrides": cached_overrides,
            "library": str(library),
            "environment_file": str(env_file),
        }
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_shell_environment(env_file, library, cached_overrides)
        return payload
    compile_override(SOURCE, library)
    validator = None
    trusted_quote_address = ""
    trusted_quote_validated_at = ""
    quote_probe_succeeded = False
    required_hosts = set(HOSTS)
    if runtime_config_path is not None:
        try:
            runtime_payload = json.loads(runtime_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runtime_payload = {}
        oauth_payload = runtime_payload.get("oauth", {}) if isinstance(runtime_payload, dict) else {}
        required_hosts = set()
        if str(oauth_payload.get("quote_region") or "cn").lower() == "cn":
            # The harmless real SDK quote request below validates the quote
            # endpoint together with its generic HTTP dependency.
            required_hosts.add(QUOTE_HOST)
        if str(oauth_payload.get("trade_region") or "cn").lower() == "cn":
            required_hosts.update(
                {"openapi.longbridge.cn", "openapi-trade.longbridge.cn"}
            )
        trusted_quote_address = recently_sdk_validated_quote_address(cache_path)
        try:
            cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_payload = {}
        trusted_quote_validated_at = str(
            cached_payload.get("quote_sdk_validated_at")
            or cached_payload.get("generated_at")
            or ""
        )

        def validate_quote(address: str, rows: dict[str, str]) -> bool:
            nonlocal quote_probe_succeeded
            if address == trusted_quote_address:
                return True
            quote_probe_succeeded = sdk_quote_endpoint_reachable(
                address,
                rows,
                library=library,
                runtime_config_path=runtime_config_path,
            )
            return quote_probe_succeeded

        validator = validate_quote
    overrides, source = resolve_overrides(
        cache_path,
        quote_validator=validator,
        required_hosts=required_hosts,
    )
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": "m15.sdk-dns-override.v2",
        "generated_at": generated_at,
        "scope": "m15_processes_only",
        "proxy_settings_modified": False,
        "process_local_proxy_bypass": list(HOSTS),
        "process_local_proxy_variables_cleared": False,
        "system_dns_modified": False,
        "hosts_file_modified": False,
        "source": source,
        "override_enabled": True,
        "quote_sdk_validated": validator is not None,
        "quote_sdk_validated_at": (
            generated_at
            if quote_probe_succeeded or overrides.get(QUOTE_HOST) != trusted_quote_address
            else trusted_quote_validated_at
        ),
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
    parser.add_argument(
        "--runtime-config",
        default=str(DEFAULT_RUNTIME_CONFIG),
        help="Runtime config used by the harmless SPY SDK endpoint probe.",
    )
    args = parser.parse_args()
    payload = prepare(
        Path(args.cache_dir).expanduser(),
        Path(args.env_file).expanduser(),
        runtime_config_path=Path(args.runtime_config).expanduser(),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
