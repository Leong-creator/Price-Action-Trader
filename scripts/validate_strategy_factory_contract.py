#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


CONTRACT_MARKER_PATTERN = re.compile(
    r"<!--\s*strategy_factory_provider_contract=(\{.*?\})\s*-->",
    re.DOTALL,
)
DEFAULT_DOC_PATHS = (
    "plans/active-plan.md",
    "docs/status.md",
    "docs/acceptance.md",
    "docs/data-sources.md",
    "docs/strategy-factory.md",
)
DEFAULT_RUN_STATE_PATH = "reports/strategy_lab/strategy_factory/run_state.json"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_contract_marker(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = CONTRACT_MARKER_PATTERN.search(text)
    if not match:
        raise ValueError(f"{path}: missing strategy_factory_provider_contract marker")
    marker = json.loads(match.group(1))
    if not isinstance(marker, dict):
        raise ValueError(f"{path}: contract marker must decode to an object")
    return {
        "active_provider_config_path": str(marker.get("active_provider_config_path", "")),
        "primary_provider_runtime_source": str(marker.get("primary_provider_runtime_source", "")),
    }


def load_primary_provider(config_path: Path) -> str:
    payload = load_json(config_path)
    if not isinstance(payload, dict):
        raise ValueError(f"{config_path}: provider config must be a JSON object")
    source_order = payload.get("source_order")
    if not isinstance(source_order, list) or not source_order or not isinstance(source_order[0], str):
        raise ValueError(f"{config_path}: source_order[0] must be a non-empty string")
    return source_order[0]


def validate_provider_contract(
    *,
    doc_paths: list[Path],
    run_state_path: Path,
) -> list[str]:
    errors: list[str] = []
    markers: dict[Path, dict[str, str]] = {}

    for doc_path in doc_paths:
        try:
            markers[doc_path] = extract_contract_marker(doc_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))

    if errors:
        return errors

    first_marker = next(iter(markers.values()))
    for doc_path, marker in markers.items():
        if marker != first_marker:
            errors.append(
                f"{doc_path}: contract marker {marker!r} does not match canonical marker {first_marker!r}"
            )

    if errors:
        return errors

    config_path = Path(first_marker["active_provider_config_path"])
    runtime_source = first_marker["primary_provider_runtime_source"]
    if runtime_source != "source_order[0]":
        errors.append(
            f"unsupported primary_provider_runtime_source '{runtime_source}', expected 'source_order[0]'"
        )
        return errors

    try:
        primary_provider = load_primary_provider(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return errors

    try:
        run_state = load_json(run_state_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return errors

    if not isinstance(run_state, dict):
        errors.append(f"{run_state_path}: run_state must be a JSON object")
        return errors

    expected_path = config_path.as_posix()
    if run_state.get("active_provider_config_path") != expected_path:
        errors.append(
            f"{run_state_path}: active_provider_config_path must equal '{expected_path}'"
        )
    if run_state.get("primary_provider") != primary_provider:
        errors.append(
            f"{run_state_path}: primary_provider must equal '{primary_provider}'"
        )

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the Strategy Factory provider contract across docs, config, and run state."
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        default=list(DEFAULT_DOC_PATHS),
        help="Markdown files that must carry the same provider contract marker.",
    )
    parser.add_argument(
        "--run-state",
        default=DEFAULT_RUN_STATE_PATH,
        help="Path to the strategy factory run_state.json template.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    doc_paths = [Path(path) for path in args.docs]
    run_state_path = Path(args.run_state)
    errors = validate_provider_contract(
        doc_paths=doc_paths,
        run_state_path=run_state_path,
    )
    if errors:
        print("Strategy factory contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    marker = extract_contract_marker(doc_paths[0])
    primary_provider = load_primary_provider(Path(marker["active_provider_config_path"]))
    print(
        "Strategy factory contract validation passed: "
        f"config={marker['active_provider_config_path']} "
        f"primary_provider={primary_provider} "
        f"docs={len(doc_paths)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
