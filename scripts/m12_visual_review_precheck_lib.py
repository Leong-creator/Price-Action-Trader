#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_visual_review_precheck.json"
PRIORITY_VISUAL_IDS = ("M10-PA-008", "M10-PA-009")
WATCHLIST_IDS = ("M10-PA-003", "M10-PA-011", "M10-PA-013")
DEFINITION_ASSIST_IDS = ("M10-PA-004", "M10-PA-007")
M12_3_STRATEGY_IDS = PRIORITY_VISUAL_IDS + WATCHLIST_IDS + DEFINITION_ASSIST_IDS
NO_VISUAL_PACK_IDS = ("M10-PA-013",)
FORBIDDEN_TEXT = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true", "live_execution=true")
FORBIDDEN_KEYS = {"order", "order_id", "fill", "fill_price", "position", "cash", "pnl", "profit_loss"}


@dataclass(frozen=True, slots=True)
class VisualPrecheckConfig:
    title: str
    run_id: str
    visual_case_index_path: Path
    visual_gate_summary_path: Path
    visual_gate_queue_path: Path
    visual_case_dir: Path
    old_m10_worktree_root: Path
    output_dir: Path
    paper_simulated_only: bool
    paper_trading_approval: bool
    broker_connection: bool
    real_orders: bool
    live_execution: bool


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_visual_precheck_config(path: str | Path = DEFAULT_CONFIG_PATH) -> VisualPrecheckConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    return VisualPrecheckConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_3_visual_review_precheck"),
        visual_case_index_path=resolve_repo_path(payload["visual_case_index_path"]),
        visual_gate_summary_path=resolve_repo_path(payload["visual_gate_summary_path"]),
        visual_gate_queue_path=resolve_repo_path(payload["visual_gate_queue_path"]),
        visual_case_dir=resolve_repo_path(payload["visual_case_dir"]),
        old_m10_worktree_root=Path(payload["old_m10_worktree_root"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        paper_simulated_only=bool(payload.get("paper_simulated_only", True)),
        paper_trading_approval=bool(payload.get("paper_trading_approval", False)),
        broker_connection=bool(payload.get("broker_connection", False)),
        real_orders=bool(payload.get("real_orders", False)),
        live_execution=bool(payload.get("live_execution", False)),
    )


def run_m12_visual_precheck(config: VisualPrecheckConfig, *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validate_config_boundaries(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    case_index = load_json(config.visual_case_index_path)
    gate_summary = load_json(config.visual_gate_summary_path)
    gate_queue = load_json(config.visual_gate_queue_path)
    review_rows = {row["strategy_id"]: row for row in gate_summary["review_rows"]}
    queue_entries = {row["strategy_id"]: row for row in gate_queue["entries"]}

    strategy_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    for strategy_id in M12_3_STRATEGY_IDS:
        strategy_row = build_strategy_row(config, strategy_id, review_rows, queue_entries)
        strategy_rows.append(strategy_row)
        if strategy_row["visual_pack_present"]:
            pack = load_json(resolve_repo_path(strategy_row["case_pack_json"]))
            for case in pack["cases"]:
                case_rows.append(build_case_row(config, case))

    case_location_counts = Counter(row["evidence_asset_location"] for row in case_rows)
    checksum_match_count = sum(1 for row in case_rows if row["checksum_match"])
    index = {
        "schema_version": "m12.visual-review-precheck-index.v1",
        "generated_at": generated_at,
        "stage": "M12.3.visual_review_precheck",
        "run_id": config.run_id,
        "paper_simulated_only": True,
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "source_reuse_refs": {
            "m10_2_visual_case_index": project_path(config.visual_case_index_path),
            "m10_10_visual_gate_summary": project_path(config.visual_gate_summary_path),
            "m10_10_visual_gate_queue": project_path(config.visual_gate_queue_path),
        },
        "asset_search_roots": {
            "current_worktree": str(ROOT),
            "old_m10_worktree": str(config.old_m10_worktree_root),
        },
        "strategy_count": len(strategy_rows),
        "case_count": len(case_rows),
        "case_location_counts": dict(sorted(case_location_counts.items())),
        "checksum_match_count": checksum_match_count,
        "strategy_rows": strategy_rows,
        "case_rows": case_rows,
        "excluded_strategy_ids": {
            "visual_only_not_in_m12_3": ["M10-PA-010"],
            "tier_a_auto_observation_only": ["M10-PA-001", "M10-PA-002", "M10-PA-012"],
            "supporting_or_research": ["M10-PA-006", "M10-PA-014", "M10-PA-015", "M10-PA-016"],
        },
        "boundary_note": "M12.3 is agent precheck only. It reduces manual review work but does not replace manual visual judgment or approve paper trading.",
    }
    validate_index(index, case_index)
    write_json(config.output_dir / "m12_3_visual_precheck_index.json", index)
    (config.output_dir / "m12_3_user_review_packet.md").write_text(build_user_review_packet(index), encoding="utf-8")
    (config.output_dir / "m12_3_visual_gate_recommendation.md").write_text(build_gate_recommendation(index), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return index


def validate_config_boundaries(config: VisualPrecheckConfig) -> None:
    if not config.paper_simulated_only:
        raise ValueError("M12.3 requires paper_simulated_only=true")
    if config.paper_trading_approval or config.broker_connection or config.real_orders or config.live_execution:
        raise ValueError("M12.3 must keep paper trading, broker, orders, and live execution disabled")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_strategy_row(
    config: VisualPrecheckConfig,
    strategy_id: str,
    review_rows: dict[str, dict[str, Any]],
    queue_entries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if strategy_id in NO_VISUAL_PACK_IDS:
        queue_entry = queue_entries[strategy_id]
        return {
            "strategy_id": strategy_id,
            "source_type": "pre_existing_candidate",
            "gate_decision": "pre_existing_wave_b_candidate",
            "gate_reason": "M10.10 carried this strategy as an existing Wave B candidate without a visual pack.",
            "priority_bucket": "watchlist_pre_existing_candidate",
            "case_pack_json": None,
            "case_pack_markdown": None,
            "queue_entry_ref": project_path(config.visual_gate_queue_path),
            "visual_pack_present": False,
            "evidence_complete": None,
            "case_counts": {},
            "ohlcv_proxy_quality": queue_entry.get("ohlcv_proxy_quality", "not_applicable"),
            "required_manual_review": False,
            "definition_fix_required": False,
            "notes": "Keep separate from visual-pack strategies; no case-level image review is available in M10.2.",
        }

    row = review_rows[strategy_id]
    priority_bucket = priority_bucket_for(strategy_id, row["decision"])
    case_pack_json = str(M10_DIR / row["case_pack_json"])
    case_pack_markdown = str(M10_DIR / row["case_pack_markdown"])
    return {
        "strategy_id": strategy_id,
        "source_type": "visual_pack",
        "gate_decision": row["decision"],
        "gate_reason": row["gate_reason"],
        "priority_bucket": priority_bucket,
        "case_pack_json": project_path(Path(case_pack_json)),
        "case_pack_markdown": project_path(Path(case_pack_markdown)),
        "queue_entry_ref": project_path(config.visual_gate_summary_path),
        "visual_pack_present": True,
        "evidence_complete": row["evidence_complete"],
        "case_counts": row["case_counts"],
        "ohlcv_proxy_quality": row["ohlcv_proxy_quality"],
        "required_manual_review": strategy_id in PRIORITY_VISUAL_IDS,
        "definition_fix_required": strategy_id in DEFINITION_ASSIST_IDS,
        "notes": row["client_note"],
    }


def priority_bucket_for(strategy_id: str, decision: str) -> str:
    if strategy_id in PRIORITY_VISUAL_IDS:
        return "tier_b_priority_visual_review"
    if strategy_id in DEFINITION_ASSIST_IDS:
        return "definition_fix_support"
    if decision == "ready_for_wave_b_backtest":
        return "watchlist_visual_review"
    return "visual_review_deferred"


def build_case_row(config: VisualPrecheckConfig, case: dict[str, Any]) -> dict[str, Any]:
    logical_path = Path(case["evidence_image_logical_path"])
    expected_checksum = case["evidence_image_checksum"]
    current_path = ROOT / logical_path
    old_path = config.old_m10_worktree_root / logical_path

    evidence_asset_location = "missing"
    resolved_path: str | None = None
    checksum_match = False
    if current_path.exists():
        evidence_asset_location = "current_worktree"
        resolved_path = str(current_path)
        checksum_match = sha256_file(current_path) == expected_checksum
    elif old_path.exists():
        evidence_asset_location = "old_m10_worktree"
        resolved_path = str(old_path)
        checksum_match = sha256_file(old_path) == expected_checksum

    return {
        "case_id": case["case_id"],
        "strategy_id": case["strategy_id"],
        "case_type": case["case_type"],
        "manual_review_status": case["review_status"],
        "reviewer_decision": None,
        "reviewer_notes": None,
        "evidence_image_logical_path": case["evidence_image_logical_path"],
        "evidence_image_checksum": expected_checksum,
        "evidence_asset_location": evidence_asset_location,
        "evidence_resolved_local_path": resolved_path,
        "evidence_exists": resolved_path is not None,
        "checksum_match": checksum_match,
        "brooks_unit_ref": case["brooks_unit_ref"],
        "evidence_video_id": case["evidence_video_id"],
        "evidence_page": case["evidence_page"],
        "pattern_decision_points": case["pattern_decision_points"],
        "disqualifiers": case["disqualifiers"],
        "ohlcv_approximation_risk": case["ohlcv_approximation_risk"],
    }


def validate_index(index: dict[str, Any], case_index: dict[str, Any]) -> None:
    if tuple(row["strategy_id"] for row in index["strategy_rows"]) != M12_3_STRATEGY_IDS:
        raise ValueError("M12.3 strategy order drift")
    if index["paper_trading_approval"] or index["broker_connection"] or index["real_orders"] or index["live_execution"]:
        raise ValueError("M12.3 boundary drift")
    for strategy_id in PRIORITY_VISUAL_IDS:
        row = find_strategy(index, strategy_id)
        if not row["required_manual_review"]:
            raise ValueError(f"{strategy_id} must require manual visual review")
    for strategy_id in DEFINITION_ASSIST_IDS:
        row = find_strategy(index, strategy_id)
        if not row["definition_fix_required"] or row["priority_bucket"] != "definition_fix_support":
            raise ValueError(f"{strategy_id} must stay in definition fix support")
    m10_pa_013 = find_strategy(index, "M10-PA-013")
    if m10_pa_013["visual_pack_present"] or m10_pa_013["source_type"] != "pre_existing_candidate":
        raise ValueError("M10-PA-013 must remain a pre-existing candidate without visual pack")
    expected_visual_ids = set(case_index["visual_strategy_ids"])
    for row in index["strategy_rows"]:
        if row["visual_pack_present"] and row["strategy_id"] not in expected_visual_ids:
            raise ValueError(f"Unexpected visual pack strategy: {row['strategy_id']}")
    forbidden = find_forbidden_keys(index)
    if forbidden:
        raise ValueError(f"M12.3 index contains forbidden execution/account keys: {sorted(forbidden)}")


def find_strategy(index: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    for row in index["strategy_rows"]:
        if row["strategy_id"] == strategy_id:
            return row
    raise KeyError(strategy_id)


def build_user_review_packet(index: dict[str, Any]) -> str:
    lines = [
        "# M12.3 Visual Review User Packet",
        "",
        "## Summary",
        "",
        f"- strategies: `{index['strategy_count']}`",
        f"- case rows: `{index['case_count']}`",
        f"- checksum matches: `{index['checksum_match_count']}`",
        "- 本包是 agent 预审，不替代人工图形判断，也不批准 paper trading。",
        "",
        "## Strategy Queue",
        "",
        "| strategy | bucket | gate | manual review | definition fix | cases |",
        "|---|---|---|---|---|---:|",
    ]
    case_counts = Counter(row["strategy_id"] for row in index["case_rows"])
    for row in index["strategy_rows"]:
        lines.append(
            f"| {row['strategy_id']} | `{row['priority_bucket']}` | `{row['gate_decision']}` | "
            f"`{row['required_manual_review']}` | `{row['definition_fix_required']}` | {case_counts[row['strategy_id']]} |"
        )
    lines.extend(["", "## Priority Review Cases", ""])
    for row in index["case_rows"]:
        if row["strategy_id"] not in PRIORITY_VISUAL_IDS:
            continue
        image_line = f"![{row['case_id']}]({row['evidence_resolved_local_path']})" if row["evidence_resolved_local_path"] else "`image_missing`"
        lines.extend(
            [
                f"### {row['case_id']}",
                "",
                image_line,
                "",
                f"- strategy: `{row['strategy_id']}`",
                f"- type: `{row['case_type']}`",
                f"- asset location: `{row['evidence_asset_location']}`",
                f"- checksum match: `{row['checksum_match']}`",
                f"- manual review status: `{row['manual_review_status']}`",
                f"- risk: {row['ohlcv_approximation_risk']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def build_gate_recommendation(index: dict[str, Any]) -> str:
    rows = [
        "| strategy | recommendation | reason |",
        "|---|---|---|",
    ]
    for row in index["strategy_rows"]:
        recommendation = "prepare_user_visual_review"
        if row["strategy_id"] == "M10-PA-013":
            recommendation = "keep_pre_existing_wave_b_candidate_separate"
        elif row["definition_fix_required"]:
            recommendation = "use_cases_for_definition_fix_only"
        elif row["priority_bucket"] == "watchlist_visual_review":
            recommendation = "watchlist_after_priority_cases"
        rows.append(f"| {row['strategy_id']} | `{recommendation}` | {row['gate_reason']} |")
    return "\n".join(
        [
            "# M12.3 Visual Gate Recommendation",
            "",
            "- M12.3 does not close manual review.",
            "- M10-PA-008 / M10-PA-009 remain the priority visual-review candidates.",
            "- M10-PA-004 / M10-PA-007 remain definition-fix support, not ready queue items.",
            "- M10-PA-013 is a pre-existing Wave B candidate without visual pack.",
            "",
            *rows,
            "",
            "## Boundary",
            "",
            "- paper_trading_approval=false",
            "- broker_connection=false",
            "- real_orders=false",
            "- live_execution=false",
            "",
        ]
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                found.add(key)
            found.update(find_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(find_forbidden_keys(child))
    return found


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output_dir.glob("m12_3_*") if path.is_file())
    lowered = combined.lower()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"M12.3 output contains forbidden text: {forbidden}")


def project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)
