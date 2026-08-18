from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_artifact_retention_lib import (
    JsonlCompactionRule,
    SnapshotRetentionRule,
    RetentionConfig,
    load_config,
    plan_jsonl_compaction,
    plan_snapshot_retention,
    run_artifact_retention,
    should_emit_watchdog_log,
    throttle_equity_curve_rows,
)


class M15ArtifactRetentionTest(unittest.TestCase):
    def test_load_config_defaults_to_dry_run_example(self) -> None:
        config = load_config()
        self.assertTrue(config.dry_run_default)
        self.assertEqual(config.stage, "M15.artifact_retention")
        self.assertGreaterEqual(len(config.jsonl_rules), 2)

    def test_load_config_merges_active_test_ids_from_formal_epoch_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "formal_epoch.json"
            marker.write_text(
                json.dumps(
                    {
                        "test_epoch_id": "current-long",
                        "short_test_epoch_id": "current-short",
                    }
                ),
                encoding="utf-8",
            )
            config_path = root / "retention.json"
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M15.artifact_retention",
                        "active_test_id_sources": [
                            {
                                "path": str(marker),
                                "fields": ["test_epoch_id", "short_test_epoch_id"],
                            }
                        ],
                        "jsonl_rules": [
                            {
                                "name": "events",
                                "paths": [str(root / "events.jsonl")],
                                "active_test_ids": ["static-id"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(
                set(config.jsonl_rules[0].active_test_ids),
                {"static-id", "current-long", "current-short"},
            )

    def test_market_event_compaction_keeps_active_rows_and_buckets_closed_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "m15_realtime_market_events.jsonl"
            self.write_jsonl(
                source,
                [
                    {"event_id": "old-1", "event_time": "2026-07-14T20:00:00Z", "test_epoch_id": "old-epoch"},
                    {"event_id": "old-2", "event_time": "2026-07-15T20:05:00Z", "test_epoch_id": "old-epoch"},
                    {"event_id": "active-1", "event_time": "2026-07-16T20:10:00Z", "test_epoch_id": "m15-sdk-formal-single-strategy-20260716"},
                ],
            )
            rule = JsonlCompactionRule(
                name="market_events",
                paths=(source,),
                archive_dir_name="archive",
                active_trading_dates=("2026-07-16",),
                active_test_ids=("m15-sdk-formal-single-strategy-20260716",),
                row_time_fields=("event_time",),
                row_trading_date_fields=("trading_date",),
                row_test_id_fields=("test_epoch_id",),
                group_priority=("trading_date", "test_id"),
                min_bytes=1,
                keep_active_file=True,
            )

            planned = plan_jsonl_compaction(source, rule, execute=False)

            self.assertFalse(planned["skipped"])
            self.assertEqual(planned["retained_rows"], 1)
            self.assertEqual(planned["archived_rows"], 2)
            self.assertEqual([item["group_key"] for item in planned["archives"]], ["2026-07-14", "2026-07-15"])
            self.assertEqual(len(self.read_jsonl(source)), 3)

    def test_execute_compaction_rewrites_active_file_and_writes_gzip_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "m14_challenge_day_ledger.jsonl"
            self.write_jsonl(
                source,
                [
                    {"runtime_id": "r1", "trading_date": "2026-07-14", "test_id": "closed-a"},
                    {"runtime_id": "r2", "trading_date": "2026-07-15", "test_id": "closed-b"},
                    {"runtime_id": "r3", "trading_date": "2026-07-16", "test_id": "active-id"},
                ],
            )
            rule = JsonlCompactionRule(
                name="m14_ledger",
                paths=(source,),
                archive_dir_name="archive",
                active_trading_dates=("2026-07-16",),
                active_test_ids=("active-id",),
                row_time_fields=(),
                row_trading_date_fields=("trading_date",),
                row_test_id_fields=("test_id",),
                group_priority=("test_id", "trading_date"),
                min_bytes=1,
                keep_active_file=True,
            )

            result = plan_jsonl_compaction(source, rule, execute=True)
            retained = self.read_jsonl(source)

            self.assertEqual([row["runtime_id"] for row in retained], ["r3"])
            archive_dir = root / "archive"
            archives = sorted(archive_dir.glob("*.gz"))
            self.assertEqual(len(archives), 2)
            self.assertEqual(result["archived_rows"], 2)
            self.assertIn('"runtime_id": "r1"', gzip.open(archives[0], "rt", encoding="utf-8").read())

    def test_inactive_non_active_file_can_be_fully_replaced_by_gzip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "m14_internal_paper_execution_ledger.jsonl"
            self.write_jsonl(
                source,
                [
                    {"runtime_id": "old", "trading_date": "2026-07-14", "test_id": "closed"},
                ],
            )
            rule = JsonlCompactionRule(
                name="old_m14_execution",
                paths=(source,),
                archive_dir_name="archive",
                active_trading_dates=("2026-07-16",),
                active_test_ids=("active-id",),
                row_time_fields=(),
                row_trading_date_fields=("trading_date",),
                row_test_id_fields=("test_id",),
                group_priority=("test_id",),
                min_bytes=1,
                keep_active_file=False,
            )

            result = plan_jsonl_compaction(source, rule, execute=True)

            self.assertFalse(source.exists())
            archive = root / "archive" / "m14_internal_paper_execution_ledger.closed.archived.jsonl.gz"
            self.assertTrue(archive.exists())
            self.assertTrue(result["all_rows_archived"])

    def test_snapshot_retention_keeps_latest_and_gzips_older_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "account.previous.json"
            latest = root / "account.current.json"
            older.write_text(json.dumps({"generated_at": "2026-07-15T20:00:00Z"}), encoding="utf-8")
            latest.write_text(json.dumps({"generated_at": "2026-07-16T20:00:00Z"}), encoding="utf-8")
            rule = SnapshotRetentionRule(name="snapshots", paths=(older, latest), keep_latest=1)

            result = plan_snapshot_retention(rule, execute=True)

            self.assertEqual(result["kept_paths"], [str(latest.resolve())])
            self.assertFalse(older.exists())
            self.assertTrue((root / "archive" / "account.previous.archived.json.gz").exists())

    def test_equity_curve_throttle_keeps_edges_and_changes(self) -> None:
        rows = [
            {"generated_at": "t1", "account_total_equity_estimate": "100"},
            {"generated_at": "t2", "account_total_equity_estimate": "100"},
            {"generated_at": "t3", "account_total_equity_estimate": "100"},
            {"generated_at": "t4", "account_total_equity_estimate": "101"},
            {"generated_at": "t5", "account_total_equity_estimate": "101"},
        ]

        throttled = throttle_equity_curve_rows(rows)

        self.assertEqual([row["generated_at"] for row in throttled], ["t1", "t4", "t5"])

    def test_watchdog_status_change_or_five_minute_interval_emits_log(self) -> None:
        self.assertTrue(
            should_emit_watchdog_log(
                previous_status="healthy",
                current_status="needs_attention",
                previous_emitted_at="2026-07-16T10:00:00Z",
                now="2026-07-16T10:01:00Z",
            )
        )
        self.assertFalse(
            should_emit_watchdog_log(
                previous_status="healthy",
                current_status="healthy",
                previous_emitted_at="2026-07-16T10:00:00Z",
                now="2026-07-16T10:04:59Z",
            )
        )
        self.assertTrue(
            should_emit_watchdog_log(
                previous_status="healthy",
                current_status="healthy",
                previous_emitted_at="2026-07-16T10:00:00Z",
                now="2026-07-16T10:05:00Z",
            )
        )

    def test_run_artifact_retention_skips_audit_exempt_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exempt = root / "execution_ledger.jsonl"
            active = root / "market_events.jsonl"
            self.write_jsonl(exempt, [{"id": "keep"}])
            self.write_jsonl(active, [{"event_time": "2026-07-14T10:00:00Z", "test_epoch_id": "old"}])
            config = RetentionConfig(
                stage="M15.artifact_retention",
                title="test",
                jsonl_rules=(
                    JsonlCompactionRule(
                        name="rule",
                        paths=(exempt, active),
                        archive_dir_name="archive",
                        active_trading_dates=("2026-07-16",),
                        active_test_ids=("active",),
                        row_time_fields=("event_time",),
                        row_trading_date_fields=(),
                        row_test_id_fields=("test_epoch_id",),
                        group_priority=("trading_date",),
                        min_bytes=1,
                        keep_active_file=True,
                    ),
                ),
                snapshot_rules=(),
                audit_exempt_paths=(exempt,),
                dry_run_default=True,
            )

            payload = run_artifact_retention(config, execute=False, generated_at="2026-07-16T12:00:00Z")

            skipped = next(item for item in payload["jsonl_results"] if item["path"] == str(exempt.resolve()))
            self.assertEqual(skipped["reason"], "audit_exempt")

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    def read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
