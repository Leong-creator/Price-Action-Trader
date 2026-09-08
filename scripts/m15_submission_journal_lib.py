"""Append-only paper submit intents, not a fill ledger or profit input.

An intent is fsynced before SDK invocation. An absent/unknown result blocks all
new writes, including after restart. Only a unique exact transmitted remark and
broker order ID can reconcile it; empty account reads are never negative proof.
Malformed/torn records fail closed, without automatic truncation or repair.
Durability assumes a local filesystem honoring fsync and preservation of this
file. All instances use a nonblocking file lock and reread under that lock.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any


class SubmissionJournalError(RuntimeError):
    """Storage or identity evidence is insufficient to authorize a write."""


class SubmissionJournalBlocked(SubmissionJournalError):
    """An earlier intent still requires broker reconciliation."""


PAYLOAD_FIELDS = (
    "client_request_id", "signal_id", "runtime_id", "strategy_id", "symbol",
    "side", "order_type", "quantity", "limit_price", "trigger_price",
    "position_action", "test_epoch_id", "capital_bucket",
)
UNRESOLVED = {"intent", "unknown"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _safe_payload(payload: dict[str, Any]) -> dict[str, str]:
    # No SDK configuration, response bodies, exceptions, tokens or nested data.
    return {key: str(payload[key]) for key in PAYLOAD_FIELDS if key in payload}


class SubmissionJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.failure = ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot()

    @contextmanager
    def _locked(self):
        if self.failure:
            raise SubmissionJournalError(self.failure)
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "r+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield handle
        except (OSError, ValueError, TypeError) as exc:
            self.failure = f"submission_journal_storage_failed:{type(exc).__name__}"
            raise SubmissionJournalError(self.failure) from exc
        except SubmissionJournalBlocked:
            raise
        except SubmissionJournalError:
            self.failure = "submission_journal_invalid_evidence"
            raise

    def _load(self, handle) -> tuple[dict[str, dict[str, Any]], int]:
        handle.seek(0)
        entries: dict[str, dict[str, Any]] = {}
        sequence = 0
        for line in handle:
            if not line.endswith(b"\n"):
                raise SubmissionJournalError("submission_journal_torn_record")
            try:
                envelope = json.loads(line)
                row = envelope["record"]
                checksum = envelope["sha256"]
            except (ValueError, KeyError, TypeError) as exc:
                raise SubmissionJournalError("submission_journal_invalid_record") from exc
            if not isinstance(row, dict) or hashlib.sha256(_canonical(row)).hexdigest() != checksum:
                raise SubmissionJournalError("submission_journal_checksum_mismatch")
            sequence += 1
            key = row.get("key")
            outcome = row.get("outcome")
            if (row.get("version") != 1 or row.get("sequence") != sequence
                    or not isinstance(key, str) or not key
                    or not isinstance(row.get("payload"), dict)
                    or row["payload"].get("client_request_id") != key
                    or not isinstance(row.get("remark"), str) or not row["remark"]
                    or outcome not in {"intent", "unknown", "acknowledged", "not_sent"}
                    or not isinstance(row.get("order_id"), str)
                    or bool(row["order_id"]) != (outcome == "acknowledged")):
                raise SubmissionJournalError("submission_journal_invalid_schema")
            previous = entries.get(key)
            if outcome == "intent":
                if previous is not None:
                    raise SubmissionJournalError("submission_journal_duplicate_intent")
            elif (previous is None or previous["outcome"] not in UNRESOLVED
                  or previous["remark"] != row["remark"] or previous["payload"] != row["payload"]):
                raise SubmissionJournalError("submission_journal_invalid_transition")
            entries[key] = row
        return entries, sequence

    def _append(self, handle, row: dict[str, Any]) -> None:
        data = _canonical({"record": row, "sha256": hashlib.sha256(_canonical(row)).hexdigest()}) + b"\n"
        handle.seek(0, os.SEEK_END)
        if handle.write(data) != len(data):
            raise OSError("short journal write")
        handle.flush()
        os.fsync(handle.fileno())
        # Also persist the directory entry when the journal was newly created.
        directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _record(entry: dict[str, Any], sequence: int, outcome: str, order_id: str = "") -> dict[str, Any]:
        return {**entry, "version": 1, "sequence": sequence, "outcome": outcome,
                "order_id": order_id, "recorded_at": datetime.now(UTC).isoformat()}

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._locked() as handle:
            entries, _ = self._load(handle)
            return entries

    def begin(self, payload: dict[str, Any], remark: str) -> tuple[bool, dict[str, Any]]:
        key = payload.get("client_request_id")
        signal_id = payload.get("signal_id")
        if any(not isinstance(value, str) or not value or any(char.isspace() for char in value)
               for value in (key, signal_id)):
            raise SubmissionJournalError("submission_journal_stable_key_and_signal_required")
        if not remark or len(remark) > 64 or not remark.startswith(f"PAT-RT {signal_id} "):
            raise SubmissionJournalError("submission_journal_unreconcilable_remark")
        safe = _safe_payload(payload)
        with self._locked() as handle:
            entries, sequence = self._load(handle)
            previous = entries.get(key)
            if previous is not None:
                if previous["payload"] != safe or previous["remark"] != remark:
                    raise SubmissionJournalError("submission_journal_key_payload_conflict")
                return False, previous
            if any(row["outcome"] in UNRESOLVED for row in entries.values()):
                raise SubmissionJournalBlocked("submission_journal_pending_reconciliation")
            if any(row["remark"] == remark for row in entries.values()):
                raise SubmissionJournalError("submission_journal_remark_collision")
            entry = self._record({"key": key, "remark": remark, "payload": safe}, sequence + 1, "intent")
            self._append(handle, entry)
            return True, entry

    def finish(self, key: str, *, outcome: str, order_id: str = "") -> dict[str, Any]:
        if outcome not in {"unknown", "acknowledged", "not_sent"} or bool(order_id) != (outcome == "acknowledged"):
            raise SubmissionJournalError("submission_journal_invalid_outcome")
        with self._locked() as handle:
            entries, sequence = self._load(handle)
            previous = entries.get(key)
            if previous is None or previous["outcome"] not in UNRESOLVED:
                raise SubmissionJournalError("submission_journal_intent_required")
            entry = self._record(previous, sequence + 1, outcome, order_id)
            self._append(handle, entry)
            return entry

    def reconcile(self, account_state: dict[str, Any]) -> list[dict[str, Any]]:
        """Caller supplies a verified fresh paper snapshot; status is not a fill."""
        orders_by_remark: dict[str, set[str]] = {}
        for field in ("orders", "open_orders", "historical_orders"):
            for order in account_state.get(field, []):
                if not isinstance(order, dict):
                    continue
                remark, order_id = order.get("remark"), order.get("order_id") or order.get("id")
                if isinstance(remark, str) and isinstance(order_id, str) and order_id.strip():
                    orders_by_remark.setdefault(remark, set()).add(order_id)
        reconciled = []
        with self._locked() as handle:
            entries, sequence = self._load(handle)
            for entry in entries.values():
                if entry["outcome"] not in UNRESOLVED:
                    continue
                ids = orders_by_remark.get(entry["remark"], set())
                if len(ids) != 1:
                    continue
                sequence += 1
                confirmed = self._record(entry, sequence, "acknowledged", next(iter(ids)))
                self._append(handle, confirmed)
                reconciled.append(confirmed)
        return reconciled

    @staticmethod
    def response(entry: dict[str, Any]) -> dict[str, Any]:
        acknowledged = entry["outcome"] == "acknowledged"
        not_sent = entry["outcome"] == "not_sent"
        return {
            "submitted": acknowledged,
            "status": ("submitted" if acknowledged else "submit_blocked_trade_admission" if not_sent
                       else "submit_unconfirmed_missing_order_id"),
            "order_id": entry["order_id"] if acknowledged else "",
            "explicit_reject": False,
            "confirmation_required": not acknowledged and not not_sent,
            "response": {"order_id": entry["order_id"] if acknowledged else ""},
            "submission_journal_outcome": entry["outcome"],
            "sdk_request_sent": False,
            "submission_journal_reused": True,
            "recovered_order": acknowledged,
            "submission_confirmation_source": "durable_journal",
        }
