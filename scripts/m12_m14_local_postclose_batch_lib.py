#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_29_current_day_scan_dashboard_lib import (  # noqa: E402
    load_config as load_m12_29_config,
    market_session_status,
    project_path,
    run_m12_29_current_day_scan_dashboard,
)
from scripts.m12_12_daily_observation_loop_lib import load_config as load_m12_12_config  # noqa: E402
from scripts.m12_liquid_universe_scanner_lib import (  # noqa: E402
    build_universe_snapshot,
    diff_universe_membership_and_order,
)
from scripts.m13_daily_strategy_test_runner_lib import (  # noqa: E402
    load_config as load_m13_config,
    load_registry,
    run_m13_daily_strategy_test_runner,
)
from scripts.m14_strategy_challenge_gate_lib import (  # noqa: E402
    load_config as load_m14_config,
    run_m14_strategy_challenge_gate,
)


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_m14_local_postclose_batch.json"


@dataclass(frozen=True, slots=True)
class FetchReplayConfig:
    execute_fetch: bool
    refresh_quotes: bool
    max_native_fetches: int


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int


@dataclass(frozen=True, slots=True)
class ReferenceConfig:
    m12_12_config_path: Path
    m12_29_config_path: Path
    m13_config_path: Path
    m14_config_path: Path
    runtime_registry_path: Path
    universe_reference_path: Path


@dataclass(frozen=True, slots=True)
class LocalRepairConfig:
    output_dir: Path
    repaired_universe_snapshot_path: Path


@dataclass(frozen=True, slots=True)
class ClassificationConfig:
    longbridge_nightly_reference_runtime_ids: tuple[str, ...]
    local_full_repair_runtime_ids: tuple[str, ...]
    longbridge_nightly_reference_lanes: tuple[str, ...]
    local_repair_lanes: tuple[str, ...]
    auxiliary_module_roles: tuple[str, ...]
    source_only_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


@dataclass(frozen=True, slots=True)
class LocalPostcloseBatchConfig:
    title: str
    run_id: str
    stage: str
    market_timezone: str
    fetch_replay: FetchReplayConfig
    retry: RetryConfig
    references: ReferenceConfig
    local_repair: LocalRepairConfig
    classification: ClassificationConfig
    boundary: BoundaryConfig


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_local_postclose_batch_config(path: str | Path = DEFAULT_CONFIG_PATH) -> LocalPostcloseBatchConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    config = LocalPostcloseBatchConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_m14_local_postclose_batch"),
        stage=payload["stage"],
        market_timezone=payload["market_timezone"],
        fetch_replay=FetchReplayConfig(
            execute_fetch=bool(payload["fetch_replay"]["execute_fetch"]),
            refresh_quotes=bool(payload["fetch_replay"]["refresh_quotes"]),
            max_native_fetches=int(payload["fetch_replay"]["max_native_fetches"]),
        ),
        retry=RetryConfig(max_attempts=int(payload["retry"]["max_attempts"])),
        references=ReferenceConfig(
            m12_12_config_path=resolve_repo_path(payload["references"]["m12_12_config_path"]),
            m12_29_config_path=resolve_repo_path(payload["references"]["m12_29_config_path"]),
            m13_config_path=resolve_repo_path(payload["references"]["m13_config_path"]),
            m14_config_path=resolve_repo_path(payload["references"]["m14_config_path"]),
            runtime_registry_path=resolve_repo_path(payload["references"]["runtime_registry_path"]),
            universe_reference_path=resolve_repo_path(payload["references"]["universe_reference_path"]),
        ),
        local_repair=LocalRepairConfig(
            output_dir=resolve_repo_path(payload["local_repair"]["output_dir"]),
            repaired_universe_snapshot_path=resolve_repo_path(payload["local_repair"]["repaired_universe_snapshot_path"]),
        ),
        classification=ClassificationConfig(
            longbridge_nightly_reference_runtime_ids=tuple(payload["classification"].get("longbridge_nightly_reference_runtime_ids", [])),
            local_full_repair_runtime_ids=tuple(payload["classification"].get("local_full_repair_runtime_ids", [])),
            longbridge_nightly_reference_lanes=tuple(payload["classification"]["longbridge_nightly_reference_lanes"]),
            local_repair_lanes=tuple(payload["classification"]["local_repair_lanes"]),
            auxiliary_module_roles=tuple(payload["classification"]["auxiliary_module_roles"]),
            source_only_roles=tuple(payload["classification"]["source_only_roles"]),
        ),
        boundary=BoundaryConfig(
            paper_simulated_only=bool(payload["boundary"]["paper_simulated_only"]),
            trading_connection=bool(payload["boundary"]["trading_connection"]),
            real_money_actions=bool(payload["boundary"]["real_money_actions"]),
            live_execution=bool(payload["boundary"]["live_execution"]),
            paper_trading_approval=bool(payload["boundary"]["paper_trading_approval"]),
        ),
    )
    validate_local_postclose_batch_config(config)
    return config


def validate_local_postclose_batch_config(config: LocalPostcloseBatchConfig) -> None:
    if config.stage != "M12-M14.local_postclose_batch":
        raise ValueError("Local postclose batch stage drift")
    if config.retry.max_attempts < 1 or config.retry.max_attempts > 3:
        raise ValueError("Local postclose batch max_attempts must stay within 1..3")
    if config.fetch_replay.max_native_fetches <= 0:
        raise ValueError("Local postclose batch max_native_fetches must be positive")
    if not config.boundary.paper_simulated_only:
        raise ValueError("Local postclose batch must stay paper/simulated only")
    if (
        config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
    ):
        raise ValueError("Local postclose batch cannot enable trading, live execution, or approval")
    if set(config.classification.longbridge_nightly_reference_lanes) & set(config.classification.local_repair_lanes):
        raise ValueError("Classification lanes must not overlap")
    if set(config.classification.auxiliary_module_roles) & set(config.classification.source_only_roles):
        raise ValueError("Auxiliary/source-only roles must not overlap")
    if set(config.classification.longbridge_nightly_reference_runtime_ids) & set(config.classification.local_full_repair_runtime_ids):
        raise ValueError("Longbridge nightly reference and local full repair runtime ids must not overlap")


def read_universe_symbols(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols", [])
    if not isinstance(symbols, list) or not symbols:
        raise ValueError(f"Universe snapshot missing symbols: {path}")
    return [str(symbol) for symbol in symbols]


def write_generated_local_configs(
    config: LocalPostcloseBatchConfig,
    *,
    generated_at: str,
) -> dict[str, Path]:
    generated_dir = config.local_repair.output_dir / "_generated_configs"
    generated_dir.mkdir(parents=True, exist_ok=True)

    reference_m12_12 = json.loads(config.references.m12_12_config_path.read_text(encoding="utf-8"))
    reference_m12_12["output_dir"] = (
        config.local_repair.output_dir / "m12_29_current_day_scan_dashboard" / "m12_12_current_day_source"
    ).as_posix()
    reference_m12_12["universe_definition_path"] = config.local_repair.repaired_universe_snapshot_path.as_posix()
    local_m12_12_path = generated_dir / "m12_12_local_postclose_batch.json"
    write_json(local_m12_12_path, reference_m12_12)

    reference_m12_29 = json.loads(config.references.m12_29_config_path.read_text(encoding="utf-8"))
    reference_m12_29["output_dir"] = (config.local_repair.output_dir / "m12_29_current_day_scan_dashboard").as_posix()
    reference_m12_29["source_m12_12_config_path"] = local_m12_12_path.as_posix()
    local_m12_29_path = generated_dir / "m12_29_local_postclose_batch.json"
    write_json(local_m12_29_path, reference_m12_29)

    manifest = {
        "schema_version": "m12-m14.local-postclose-generated-configs.v1",
        "generated_at": generated_at,
        "m12_12_config_path": project_path(local_m12_12_path),
        "m12_29_config_path": project_path(local_m12_29_path),
        "repaired_universe_snapshot_path": project_path(config.local_repair.repaired_universe_snapshot_path),
    }
    write_json(generated_dir / "generated_config_manifest.json", manifest)
    return {
        "m12_12": local_m12_12_path,
        "m12_29": local_m12_29_path,
        "manifest": generated_dir / "generated_config_manifest.json",
    }


def build_classification_summary(
    *,
    registry_path: Path,
    classification: ClassificationConfig,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    declared_runtime_ids = {
        str(account.get("runtime_id") or "")
        for strategy in registry["strategies"]
        for account in strategy.get("runtime_accounts", [])
    }
    configured_longbridge = set(classification.longbridge_nightly_reference_runtime_ids)
    configured_repair = set(classification.local_full_repair_runtime_ids)
    # Short runtimes are generated only by M15 and intentionally do not exist
    # in the local registry. They remain valid nightly reference identities.
    unknown_longbridge = sorted(
        runtime_id for runtime_id in configured_longbridge
        if runtime_id not in declared_runtime_ids and not runtime_id.endswith("-short")
    )
    unknown_repair = sorted(configured_repair - declared_runtime_ids)
    auxiliary: list[str] = []
    source_only: list[str] = []
    for strategy in registry["strategies"]:
        strategy_id = str(strategy["strategy_id"])
        role = str(strategy["module_role"])
        if role in classification.auxiliary_module_roles:
            auxiliary.append(strategy_id)
        if role in classification.source_only_roles:
            source_only.append(strategy_id)
    return {
        "longbridge_nightly_reference_runtime_ids": sorted(configured_longbridge),
        "local_full_repair_runtime_ids": sorted(configured_repair),
        "longbridge_nightly_reference_strategy_ids": sorted({runtime_id.rsplit("-", 1)[0] for runtime_id in configured_longbridge}),
        "local_repair_strategy_ids": sorted({runtime_id.rsplit("-", 1)[0] for runtime_id in configured_repair}),
        "auxiliary_strategy_ids": sorted(auxiliary),
        "source_only_strategy_ids": sorted(source_only),
        "unknown_longbridge_runtime_ids": unknown_longbridge,
        "unknown_local_repair_runtime_ids": unknown_repair,
    }


def build_local_universe_diff(
    *,
    repaired_universe_path: Path,
    reference_universe_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    repaired_symbols = read_universe_symbols(repaired_universe_path)
    reference_symbols = read_universe_symbols(reference_universe_path)
    repaired_snapshot = build_universe_snapshot(
        repaired_symbols,
        snapshot_id="m12_local_repair_fixed_147",
        generated_at=generated_at,
        source_label="local_repair_fixed_147",
    )
    reference_snapshot = build_universe_snapshot(
        reference_symbols,
        snapshot_id="m12_reference_universe",
        generated_at=generated_at,
        source_label="longbridge_nightly_reference",
    )
    diff = diff_universe_membership_and_order(reference_symbols, repaired_symbols)
    payload = {
        "schema_version": "m12.local-universe-diff.v1",
        "generated_at": generated_at,
        "repaired_snapshot_ref": project_path(repaired_universe_path),
        "reference_snapshot_ref": project_path(reference_universe_path),
        "repaired_snapshot": repaired_snapshot,
        "reference_snapshot": reference_snapshot,
        "diff": diff,
    }
    return payload


def build_local_batch_summary(
    *,
    config: LocalPostcloseBatchConfig,
    generated_at: str,
    market_status: str,
    attempts: list[dict[str, Any]],
    generated_configs: dict[str, Path],
    m12_result: dict[str, Any],
    m13_result: dict[str, Any],
    m14_result: dict[str, Any],
    universe_diff: dict[str, Any],
    classification_summary: dict[str, Any],
) -> dict[str, Any]:
    m12_summary = m12_result["summary"]
    m13_summary = m13_result["summary"]
    m14_summary = m14_result["summary"]
    last_attempt = attempts[-1]
    diff_counts = universe_diff["diff"]
    return {
        "schema_version": "m12-m14.local-postclose-batch-summary.v1",
        "title": config.title,
        "run_id": config.run_id,
        "stage": config.stage,
        "generated_at": generated_at,
        "market_status": market_status,
        "attempt_count": len(attempts),
        "max_attempts": config.retry.max_attempts,
        "completed": True,
        "attempts": attempts,
        "generated_config_manifest_ref": project_path(generated_configs["manifest"]),
        "m12_29_output_dir": project_path(config.local_repair.output_dir / "m12_29_current_day_scan_dashboard"),
        "m13_output_dir": project_path(config.local_repair.output_dir / "m13_real_daily_strategy_testing"),
        "m14_output_dir": project_path(config.local_repair.output_dir / "m14_strategy_challenge"),
        "m12": {
            "scan_date": m12_summary.get("scan_date", ""),
            "quote_source": m12_summary.get("quote_source", ""),
            "current_day_runtime_ready": bool(m12_summary.get("current_day_runtime_ready", False)),
            "current_day_scan_complete": bool(m12_summary.get("current_day_scan_complete", False)),
        },
        "m13": {
            "goal_complete": bool(m13_result["goal_status"]["goal_complete"]),
            "ready_for_complete_reliable_testing": bool(m13_summary.get("ready_for_complete_reliable_testing", False)),
            "blocked_strategy_ids": list(m13_summary.get("blocked_strategy_ids", [])),
        },
        "m14": {
            "goal_complete": bool(m14_result["goal_status"]["goal_complete"]),
            "challenge_progress_label": str(m14_summary.get("challenge_progress_label", "")),
            "paper_candidate_count": int(m14_summary.get("paper_candidate_count", 0)),
        },
        "classification": classification_summary,
        "local_universe_repair": {
            "repaired_snapshot_ref": universe_diff["repaired_snapshot_ref"],
            "reference_snapshot_ref": universe_diff["reference_snapshot_ref"],
            "added_symbols": diff_counts["added_symbols"],
            "removed_symbols": diff_counts["removed_symbols"],
            "order_mismatch_count": len(diff_counts["order_mismatches"]),
            "membership_match": bool(diff_counts["membership_match"]),
            "order_match": bool(diff_counts["order_match"]),
        },
        "plain_language_result": (
            f"本地研究与修复系统第 {last_attempt['attempt']} 次完成："
            f"交易日期={m12_summary.get('scan_date', '')}，"
            f"本地账本完成={bool(m13_result['goal_status']['goal_complete'])}，"
            f"策略修复评估完成={bool(m14_result['goal_status']['goal_complete'])}；"
            f"本地 147 修复快照相对参考池新增 {len(diff_counts['added_symbols'])}、"
            f"移除 {len(diff_counts['removed_symbols'])}、顺序差异 {len(diff_counts['order_mismatches'])}。"
        ),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_summary_md(summary: dict[str, Any]) -> str:
    repair = summary["local_universe_repair"]
    classification = summary["classification"]
    return "\n".join(
        [
            "# 本地研究与修复系统",
            "",
            f"- Generated at: `{summary['generated_at']}`",
            f"- Market status: `{summary['market_status']}`",
            f"- Attempts: `{summary['attempt_count']}/{summary['max_attempts']}`",
            f"- 本地行情来源: `{summary['m12']['quote_source']}`",
            f"- 本地模拟账本完成: `{summary['m13']['goal_complete']}`",
            f"- 策略修复评估完成: `{summary['m14']['goal_complete']}`",
            f"- Local universe diff: `+{len(repair['added_symbols'])} / -{len(repair['removed_symbols'])} / order {repair['order_mismatch_count']}`",
            f"- 长桥策略盘后轻量对照运行单元: `{len(classification['longbridge_nightly_reference_runtime_ids'])}`",
            f"- 本地完整修复运行单元: `{len(classification['local_full_repair_runtime_ids'])}`",
            f"- 按需辅助模块: `{len(classification['auxiliary_strategy_ids'])}`",
            f"- 资料来源模块: `{len(classification['source_only_strategy_ids'])}`",
            "",
            summary["plain_language_result"],
            "",
        ]
    )


def run_local_postclose_batch(
    config: LocalPostcloseBatchConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_local_postclose_batch_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config.local_repair.output_dir.mkdir(parents=True, exist_ok=True)

    market = market_session_status(generated_at)
    if market["status"] != "盘后":
        raise ValueError("Local postclose batch only supports postclose execution")

    generated_configs = write_generated_local_configs(config, generated_at=generated_at)
    classification_summary = build_classification_summary(
        registry_path=config.references.runtime_registry_path,
        classification=config.classification,
    )
    universe_diff = build_local_universe_diff(
        repaired_universe_path=config.local_repair.repaired_universe_snapshot_path,
        reference_universe_path=config.references.universe_reference_path,
        generated_at=generated_at,
    )
    write_json(config.local_repair.output_dir / "local_universe_diff.json", universe_diff)

    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for attempt in range(1, config.retry.max_attempts + 1):
        try:
            local_m12_29_config = load_m12_29_config(generated_configs["m12_29"])
            m12_result = run_m12_29_current_day_scan_dashboard(
                local_m12_29_config,
                generated_at=generated_at,
                execute_fetch=config.fetch_replay.execute_fetch,
                max_native_fetches=config.fetch_replay.max_native_fetches,
                refresh_quotes=config.fetch_replay.refresh_quotes,
                force_refresh_current_intraday=False,
            )
            trading_date = str(m12_result["summary"].get("scan_date") or "")
            local_m13_config = replace(
                load_m13_config(config.references.m13_config_path),
                output_dir=config.local_repair.output_dir / "m13_real_daily_strategy_testing",
                m12_29_output_dir=local_m12_29_config.output_dir,
            )
            m13_result = run_m13_daily_strategy_test_runner(
                local_m13_config,
                generated_at=generated_at,
                trading_date=trading_date,
            )
            local_m14_config = replace(
                load_m14_config(config.references.m14_config_path),
                output_dir=config.local_repair.output_dir / "m14_strategy_challenge",
                m13_output_dir=local_m13_config.output_dir,
                m12_29_output_dir=local_m12_29_config.output_dir,
            )
            m14_result = run_m14_strategy_challenge_gate(
                local_m14_config,
                generated_at=generated_at,
                trading_date=trading_date,
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "success",
                    "scan_date": trading_date,
                }
            )
            summary = build_local_batch_summary(
                config=config,
                generated_at=generated_at,
                market_status=market["status"],
                attempts=attempts,
                generated_configs=generated_configs,
                m12_result=m12_result,
                m13_result=m13_result,
                m14_result=m14_result,
                universe_diff=universe_diff,
                classification_summary=classification_summary,
            )
            write_json(config.local_repair.output_dir / "local_postclose_batch_summary.json", summary)
            (config.local_repair.output_dir / "local_postclose_batch_summary.md").write_text(
                build_summary_md(summary),
                encoding="utf-8",
            )
            return {
                "summary": summary,
                "m12_result": m12_result,
                "m13_result": m13_result,
                "m14_result": m14_result,
                "universe_diff": universe_diff,
            }
        except Exception as exc:  # pragma: no cover - covered by retry tests
            last_error = exc
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            )

    failure_payload = {
        "schema_version": "m12-m14.local-postclose-batch-summary.v1",
        "title": config.title,
        "run_id": config.run_id,
        "stage": config.stage,
        "generated_at": generated_at,
        "market_status": market["status"],
        "attempt_count": len(attempts),
        "max_attempts": config.retry.max_attempts,
        "completed": False,
        "attempts": attempts,
        "plain_language_result": "盘后本地 batch 在最大重试次数内仍未完成。",
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_json(config.local_repair.output_dir / "local_postclose_batch_summary.json", failure_payload)
    (config.local_repair.output_dir / "local_postclose_batch_summary.md").write_text(
        build_summary_md(failure_payload | {"m12": {"quote_source": ""}, "m13": {"goal_complete": False}, "m14": {"goal_complete": False}, "local_universe_repair": {"added_symbols": [], "removed_symbols": [], "order_mismatch_count": 0}, "classification": {"longbridge_nightly_reference_strategy_ids": [], "local_repair_strategy_ids": [], "auxiliary_strategy_ids": [], "source_only_strategy_ids": []}}),
        encoding="utf-8",
    )
    if last_error is not None:
        raise last_error
    raise RuntimeError("Local postclose batch failed without an explicit error")
