#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACTS_DIR = ROOT / "config" / "m15_strategy_contracts"

CONTRACT_STAGE_ZH = {
    "contract-draft-v1": "规则草案",
    "shadow-v1": "实时影子",
    "paper-v1": "模拟交易",
    "full-v1": "完整执行版",
}
REQUIRED_FIELDS = (
    "schema_version",
    "runtime_id",
    "strategy_id",
    "display_name_zh",
    "stage",
    "direction",
    "timeframe",
    "setup",
    "entry_rules",
    "exit_rules",
    "risk_controls",
    "data_requirements",
    "visual_acceptance",
    "execution_boundaries",
    "source_refs",
)
REQUIRED_OBJECT_FIELDS = (
    "setup",
    "entry_rules",
    "exit_rules",
    "risk_controls",
    "data_requirements",
    "visual_acceptance",
    "execution_boundaries",
)
_RUNTIME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HASH_EXCLUDED_FIELDS = frozenset({"contract_hash", "stage_zh"})


class StrategyContractError(ValueError):
    """Raised when an M15 strategy contract is invalid or ambiguous."""


def _source_label(source: str | Path | None) -> str:
    return f" ({source})" if source is not None else ""


def validate_contract(contract: Mapping[str, Any], *, source: str | Path | None = None) -> None:
    if not isinstance(contract, Mapping):
        raise StrategyContractError(f"strategy contract must be a JSON object{_source_label(source)}")

    missing = [field for field in REQUIRED_FIELDS if field not in contract]
    if missing:
        raise StrategyContractError(
            f"missing required contract fields: {', '.join(missing)}{_source_label(source)}"
        )

    for field in ("schema_version", "runtime_id", "strategy_id", "display_name_zh", "timeframe"):
        if not isinstance(contract[field], str) or not contract[field].strip():
            raise StrategyContractError(f"{field} must be a non-empty string{_source_label(source)}")

    runtime_id = contract["runtime_id"]
    if not _RUNTIME_ID_PATTERN.fullmatch(runtime_id):
        raise StrategyContractError(f"invalid runtime_id: {runtime_id!r}{_source_label(source)}")
    if contract["schema_version"] != "m15-strategy-contract-v1":
        raise StrategyContractError(f"unsupported schema_version{_source_label(source)}")
    if contract["stage"] not in CONTRACT_STAGE_ZH:
        raise StrategyContractError(f"unsupported contract stage: {contract['stage']!r}{_source_label(source)}")
    if contract["direction"] not in {"long", "short"}:
        raise StrategyContractError(f"direction must be long or short{_source_label(source)}")
    if contract["timeframe"] not in {"1d", "5m"}:
        raise StrategyContractError(f"unsupported timeframe: {contract['timeframe']!r}{_source_label(source)}")

    for field in REQUIRED_OBJECT_FIELDS:
        if not isinstance(contract[field], Mapping) or not contract[field]:
            raise StrategyContractError(f"{field} must be a non-empty object{_source_label(source)}")
    if not isinstance(contract["source_refs"], list) or not contract["source_refs"]:
        raise StrategyContractError(f"source_refs must be a non-empty list{_source_label(source)}")
    if any(not isinstance(item, str) or not item.strip() for item in contract["source_refs"]):
        raise StrategyContractError(f"source_refs entries must be non-empty strings{_source_label(source)}")

    visual = contract["visual_acceptance"]
    if not isinstance(visual.get("required"), bool) or not isinstance(visual.get("status"), str):
        raise StrategyContractError(
            f"visual_acceptance requires boolean required and string status{_source_label(source)}"
        )
    if contract["stage"] in {"contract-draft-v1", "shadow-v1"} and visual.get("required") is not True:
        raise StrategyContractError(
            f"draft/shadow contract requires explicit visual acceptance{_source_label(source)}"
        )

    boundaries = contract["execution_boundaries"]
    required_boundaries = {
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "local_simulation_as_signal_source": False,
    }
    for key, expected in required_boundaries.items():
        if boundaries.get(key) is not expected:
            raise StrategyContractError(
                f"execution_boundaries.{key} must be {str(expected).lower()}{_source_label(source)}"
            )


def _hash_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in contract.items() if key not in _HASH_EXCLUDED_FIELDS}


def stable_contract_hash(contract: Mapping[str, Any]) -> str:
    validate_contract(contract)
    canonical = json.dumps(
        _hash_payload(contract),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyContractError(f"cannot load strategy contract ({contract_path}): {exc}") from exc
    validate_contract(payload, source=contract_path)
    loaded = dict(payload)
    loaded["stage_zh"] = CONTRACT_STAGE_ZH[loaded["stage"]]
    loaded["contract_hash"] = stable_contract_hash(payload)
    return loaded


def load_contracts(contracts_dir: str | Path = DEFAULT_CONTRACTS_DIR) -> dict[str, dict[str, Any]]:
    directory = Path(contracts_dir)
    if not directory.is_dir():
        raise StrategyContractError(f"strategy contracts directory does not exist: {directory}")

    contracts: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.rglob("*.json")):
        contract = load_contract(path)
        runtime_id = contract["runtime_id"]
        if runtime_id in contracts:
            raise StrategyContractError(f"duplicate runtime_id in strategy contracts: {runtime_id}")
        contracts[runtime_id] = contract
    if not contracts:
        raise StrategyContractError(f"no strategy contracts found: {directory}")
    return contracts


@lru_cache(maxsize=8)
def load_contracts_cached(contracts_dir: str = str(DEFAULT_CONTRACTS_DIR)) -> dict[str, dict[str, Any]]:
    """Load immutable-at-runtime contracts once; a process restart accepts revisions."""
    return load_contracts(contracts_dir)


def get_contract_for_runtime(
    runtime_id: str,
    *,
    contracts: Mapping[str, Mapping[str, Any]] | None = None,
    contracts_dir: str | Path = DEFAULT_CONTRACTS_DIR,
) -> dict[str, Any]:
    loaded = contracts if contracts is not None else load_contracts(contracts_dir)
    try:
        return dict(loaded[runtime_id])
    except KeyError as exc:
        raise StrategyContractError(f"strategy contract not found for runtime: {runtime_id}") from exc


def write_state_atomic(path: str | Path, state: Mapping[str, Any]) -> Path:
    if not isinstance(state, Mapping):
        raise StrategyContractError("contract state must be a JSON object")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def persist_runtime_state(runtime_id: str, state: Mapping[str, Any], state_dir: str | Path) -> Path:
    if not _RUNTIME_ID_PATTERN.fullmatch(runtime_id):
        raise StrategyContractError(f"invalid runtime_id: {runtime_id!r}")
    return write_state_atomic(Path(state_dir) / f"{runtime_id}.json", state)
