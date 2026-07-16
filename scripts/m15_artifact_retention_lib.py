#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_artifact_retention.json"
NEW_YORK = ZoneInfo("America/New_York")


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_date_from_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return parse_utc_datetime(text).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else ""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def write_gzip_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with gzip.open(tmp_path, "wt", encoding="utf-8") as handle:
        handle.write(text)
    tmp_path.replace(path)


@dataclass(frozen=True, slots=True)
class JsonlCompactionRule:
    name: str
    paths: tuple[Path, ...]
    archive_dir_name: str
    active_trading_dates: tuple[str, ...]
    active_test_ids: tuple[str, ...]
    row_time_fields: tuple[str, ...]
    row_trading_date_fields: tuple[str, ...]
    row_test_id_fields: tuple[str, ...]
    group_priority: tuple[str, ...]
    min_bytes: int
    keep_active_file: bool


@dataclass(frozen=True, slots=True)
class SnapshotRetentionRule:
    name: str
    paths: tuple[Path, ...]
    keep_latest: int


@dataclass(frozen=True, slots=True)
class RetentionConfig:
    stage: str
    title: str
    jsonl_rules: tuple[JsonlCompactionRule, ...]
    snapshot_rules: tuple[SnapshotRetentionRule, ...]
    audit_exempt_paths: tuple[Path, ...]
    dry_run_default: bool
    archived_file_globs: tuple[str, ...] = ()


def _tupled_paths(values: Any) -> tuple[Path, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(resolve_repo_path(item) for item in values)


def _tupled_strings(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(str(item).strip() for item in values if str(item).strip())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RetentionConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    rules = payload.get("jsonl_rules", [])
    snapshot_rules = payload.get("snapshot_rules", [])
    config = RetentionConfig(
        stage=str(payload.get("stage", "M15.artifact_retention")),
        title=str(payload.get("title", "M15 artifact retention")),
        jsonl_rules=tuple(
            JsonlCompactionRule(
                name=str(rule.get("name", "unnamed_jsonl_rule")),
                paths=_tupled_paths(rule.get("paths", [])),
                archive_dir_name=str(rule.get("archive_dir_name", "archive")),
                active_trading_dates=_tupled_strings(rule.get("active_trading_dates", []))
                or (datetime.now(NEW_YORK).date().isoformat(),),
                active_test_ids=_tupled_strings(rule.get("active_test_ids", [])),
                row_time_fields=_tupled_strings(rule.get("row_time_fields", [])),
                row_trading_date_fields=_tupled_strings(rule.get("row_trading_date_fields", [])),
                row_test_id_fields=_tupled_strings(rule.get("row_test_id_fields", [])),
                group_priority=_tupled_strings(rule.get("group_priority", ["trading_date", "test_id"])),
                min_bytes=int(rule.get("min_bytes", 1)),
                keep_active_file=bool(rule.get("keep_active_file", True)),
            )
            for rule in rules
        ),
        snapshot_rules=tuple(
            SnapshotRetentionRule(
                name=str(rule.get("name", "unnamed_snapshot_rule")),
                paths=_tupled_paths(rule.get("paths", [])),
                keep_latest=max(1, int(rule.get("keep_latest", 1))),
            )
            for rule in snapshot_rules
        ),
        audit_exempt_paths=_tupled_paths(payload.get("audit_exempt_paths", [])),
        archived_file_globs=_tupled_strings(payload.get("archived_file_globs", [])),
        dry_run_default=bool(payload.get("dry_run_default", True)),
    )
    validate_config(config)
    return config


def validate_config(config: RetentionConfig) -> None:
    if config.stage != "M15.artifact_retention":
        raise ValueError("M15 artifact retention stage drift")
    for rule in config.jsonl_rules:
        if rule.min_bytes < 0:
            raise ValueError(f"{rule.name} min_bytes cannot be negative")
        if not rule.paths:
            raise ValueError(f"{rule.name} must declare at least one path")
    for rule in config.snapshot_rules:
        if not rule.paths:
            raise ValueError(f"{rule.name} must declare at least one snapshot path")
        if rule.keep_latest <= 0:
            raise ValueError(f"{rule.name} keep_latest must be positive")


def _matches_exempt_path(path: Path, exempt_paths: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved == exempt.resolve() for exempt in exempt_paths)


def _row_test_ids(row: dict[str, Any], fields: tuple[str, ...]) -> set[str]:
    identifiers: set[str] = set()
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            identifiers.add(value)
    return identifiers


def _row_trading_dates(
    row: dict[str, Any],
    *,
    date_fields: tuple[str, ...],
    time_fields: tuple[str, ...],
) -> set[str]:
    dates: set[str] = set()
    for field in date_fields:
        value = str(row.get(field) or "").strip()
        if value:
            dates.add(value)
    for field in time_fields:
        value = iso_date_from_timestamp(row.get(field))
        if value:
            dates.add(value)
    return dates


def _is_active_row(row: dict[str, Any], rule: JsonlCompactionRule) -> bool:
    row_dates = _row_trading_dates(
        row,
        date_fields=rule.row_trading_date_fields,
        time_fields=rule.row_time_fields,
    )
    if row_dates.intersection(rule.active_trading_dates):
        return True
    if _row_test_ids(row, rule.row_test_id_fields).intersection(rule.active_test_ids):
        return True
    return False


def _group_key(row: dict[str, Any], rule: JsonlCompactionRule) -> str:
    row_dates = _row_trading_dates(
        row,
        date_fields=rule.row_trading_date_fields,
        time_fields=rule.row_time_fields,
    )
    row_ids = _row_test_ids(row, rule.row_test_id_fields)
    for key_type in rule.group_priority:
        if key_type == "trading_date":
            for value in sorted(row_dates):
                return value
        if key_type == "test_id":
            for value in sorted(row_ids):
                return sanitize_group_token(value)
    return "unclassified"


def sanitize_group_token(value: str) -> str:
    token = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value.strip())
    return token or "unclassified"


def build_grouped_archive_name(source_path: Path, group_key: str) -> str:
    return f"{source_path.stem}.{sanitize_group_token(group_key)}.archived.jsonl.gz"


def gzip_replace_path(source_path: Path, *, archive_name: str, execute: bool) -> dict[str, Any]:
    archive_dir = source_path.parent / "archive"
    archive_path = archive_dir / archive_name
    result = {
        "source_path": project_path(source_path),
        "archive_path": project_path(archive_path),
        "action": "gzip_replace",
        "execute": execute,
    }
    if not source_path.exists():
        result["status"] = "missing"
        return result
    result["bytes_before"] = source_path.stat().st_size
    if execute:
        payload = source_path.read_text(encoding="utf-8", errors="replace")
        write_gzip_text_atomic(archive_path, payload + ("" if payload.endswith("\n") or not payload else "\n"))
        source_path.unlink()
        result["status"] = "executed"
        result["bytes_after"] = archive_path.stat().st_size
    else:
        result["status"] = "planned"
    return result


def plan_jsonl_compaction(
    source_path: Path,
    rule: JsonlCompactionRule,
    *,
    execute: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rule": rule.name,
        "path": project_path(source_path),
        "execute": execute,
        "skipped": False,
        "archives": [],
    }
    if not source_path.exists():
        result.update({"skipped": True, "reason": "missing"})
        return result
    if source_path.suffix == ".gz":
        result.update({"skipped": True, "reason": "already_gzipped"})
        return result
    size_bytes = source_path.stat().st_size
    result["size_bytes"] = size_bytes
    if size_bytes < rule.min_bytes:
        result.update({"skipped": True, "reason": "below_threshold"})
        return result

    retained_lines: list[str] = []
    archive_groups: dict[str, list[str]] = {}
    malformed_lines: list[str] = []
    original_lines = read_jsonl_lines(source_path)
    for line in original_lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line)
            continue
        if _is_active_row(row, rule):
            retained_lines.append(line)
            continue
        archive_groups.setdefault(_group_key(row, rule), []).append(line)

    if not archive_groups and not malformed_lines:
        result.update({"skipped": True, "reason": "all_rows_active", "retained_rows": len(retained_lines)})
        return result

    archive_dir = source_path.parent / rule.archive_dir_name
    planned_archives: list[dict[str, Any]] = []
    for group_key, lines in sorted(archive_groups.items()):
        archive_path = archive_dir / build_grouped_archive_name(source_path, group_key)
        planned_archives.append(
            {
                "group_key": group_key,
                "archive_path": project_path(archive_path),
                "row_count": len(lines),
            }
        )
        if execute:
            payload = "\n".join(lines) + "\n"
            write_gzip_text_atomic(archive_path, payload)

    if malformed_lines:
        malformed_path = archive_dir / build_grouped_archive_name(source_path, "malformed")
        planned_archives.append(
            {
                "group_key": "malformed",
                "archive_path": project_path(malformed_path),
                "row_count": len(malformed_lines),
            }
        )
        if execute:
            write_gzip_text_atomic(malformed_path, "\n".join(malformed_lines) + "\n")

    all_rows_archived = not retained_lines
    if execute:
        if all_rows_archived and not rule.keep_active_file:
            source_path.unlink()
        else:
            write_text_atomic(source_path, "\n".join(retained_lines) + ("\n" if retained_lines else ""))

    result.update(
        {
            "archives": planned_archives,
            "retained_rows": len(retained_lines),
            "archived_rows": sum(item["row_count"] for item in planned_archives if item["group_key"] != "malformed"),
            "malformed_rows": len(malformed_lines),
            "all_rows_archived": all_rows_archived,
            "rewrote_source": not all_rows_archived or rule.keep_active_file,
            "reason": "inactive_rows_compacted",
        }
    )
    return result


def _snapshot_sort_key(path: Path) -> tuple[float, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    generated_at = str(payload.get("generated_at") or "")
    if generated_at:
        try:
            return (parse_utc_datetime(generated_at).timestamp(), path.name)
        except ValueError:
            pass
    return (path.stat().st_mtime, path.name)


def plan_snapshot_retention(rule: SnapshotRetentionRule, *, execute: bool) -> dict[str, Any]:
    candidates = [path for path in rule.paths if path.exists() and path.suffix != ".gz"]
    ordered = sorted(candidates, key=_snapshot_sort_key, reverse=True)
    keep = ordered[: rule.keep_latest]
    archive = ordered[rule.keep_latest :]
    result = {
        "rule": rule.name,
        "execute": execute,
        "kept_paths": [project_path(path) for path in keep],
        "archived_paths": [],
    }
    for path in archive:
        archive_result = gzip_replace_path(path, archive_name=f"{path.stem}.archived.json.gz", execute=execute)
        result["archived_paths"].append(archive_result)
    return result


def throttle_equity_curve_rows(
    rows: list[dict[str, Any]],
    *,
    value_field: str = "account_total_equity_estimate",
) -> list[dict[str, Any]]:
    if not rows:
        return []
    retained = [rows[0]]
    for index in range(1, len(rows) - 1):
        row = rows[index]
        prev_value = str(rows[index - 1].get(value_field))
        value = str(row.get(value_field))
        if value != prev_value:
            retained.append(row)
    if rows[-1] is not retained[-1]:
        retained.append(rows[-1])
    return retained


def should_emit_watchdog_log(
    *,
    previous_status: str,
    current_status: str,
    previous_emitted_at: str | None,
    now: str,
    throttle_seconds: int = 300,
) -> bool:
    if current_status != previous_status:
        return True
    if not previous_emitted_at:
        return True
    return (parse_utc_datetime(now) - parse_utc_datetime(previous_emitted_at)).total_seconds() >= throttle_seconds


def run_artifact_retention(
    config: RetentionConfig | None = None,
    *,
    execute: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc_iso()
    jsonl_results: list[dict[str, Any]] = []
    for rule in config.jsonl_rules:
        for path in rule.paths:
            if _matches_exempt_path(path, config.audit_exempt_paths):
                jsonl_results.append(
                    {
                        "rule": rule.name,
                        "path": project_path(path),
                        "execute": execute,
                        "skipped": True,
                        "reason": "audit_exempt",
                        "archives": [],
                    }
                )
                continue
            jsonl_results.append(plan_jsonl_compaction(path, rule, execute=execute))

    snapshot_results = [plan_snapshot_retention(rule, execute=execute) for rule in config.snapshot_rules]
    archived_file_results: list[dict[str, Any]] = []
    for pattern in config.archived_file_globs:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file() or path.suffix == ".gz":
                continue
            target = path.with_suffix(path.suffix + ".gz")
            result = {
                "source_path": project_path(path),
                "archive_path": project_path(target),
                "execute": execute,
                "status": "planned",
                "bytes_before": path.stat().st_size,
            }
            if execute:
                write_gzip_text_atomic(target, path.read_text(encoding="utf-8", errors="replace"))
                path.unlink()
                result.update({"status": "executed", "bytes_after": target.stat().st_size})
            archived_file_results.append(result)
    archived_file_count = sum(len(item.get("archives", [])) for item in jsonl_results if not item.get("skipped"))
    archived_file_count += sum(len(item.get("archived_paths", [])) for item in snapshot_results)
    archived_file_count += len(archived_file_results)
    return {
        "schema_version": "m15.artifact-retention.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "dry_run": not execute,
        "jsonl_rule_count": len(config.jsonl_rules),
        "snapshot_rule_count": len(config.snapshot_rules),
        "archived_file_count": archived_file_count,
        "jsonl_results": jsonl_results,
        "snapshot_results": snapshot_results,
        "archived_file_results": archived_file_results,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compact stale M14/M15 artifacts without deleting audit evidence.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to retention config JSON.")
    parser.add_argument("--execute", action="store_true", help="Execute gzip replacement. Default is dry-run.")
    parser.add_argument("--generated-at", default=None, help="UTC timestamp used in the summary payload.")
    return parser.parse_args(argv)
