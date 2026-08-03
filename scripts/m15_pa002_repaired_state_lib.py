#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


RUNTIME_ID = "M10-PA-002-5m-repaired-v1"


def sync_repaired_state(
    fill_attribution_path: Path,
    state_path: Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    state = _read_json(state_path)
    processed = set(str(item) for item in state.get("processed_completed_trade_ids", []) if str(item))
    consecutive_losses = int(state.get("consecutive_losses") or 0)
    pending_skip_count = int(state.get("pending_skip_count") or 0)
    attribution = _read_json(fill_attribution_path)
    trades = sorted(
        (
            row
            for row in attribution.get("completed_trades", [])
            if isinstance(row, dict) and str(row.get("runtime_id") or "") == RUNTIME_ID
        ),
        key=lambda row: (str(row.get("closed_at") or ""), str(row.get("batch_id") or "")),
    )
    newly_processed = 0
    for trade in trades:
        trade_id = str(trade.get("batch_id") or "")
        if not trade_id or trade_id in processed:
            continue
        processed.add(trade_id)
        newly_processed += 1
        net_pnl = _decimal(trade.get("estimated_net_pnl", trade.get("gross_realized_pnl")))
        if net_pnl < 0:
            consecutive_losses += 1
            if consecutive_losses >= 2:
                pending_skip_count += 1
                consecutive_losses = 0
        else:
            consecutive_losses = 0
    state.update(
        {
            "schema_version": "m15-pa002-repaired-state-v1",
            "runtime_id": RUNTIME_ID,
            "generated_at": generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "consecutive_losses": consecutive_losses,
            "pending_skip_count": pending_skip_count,
            "processed_completed_trade_ids": sorted(processed),
            "completed_trade_count": len(processed),
            "newly_processed_trade_count": newly_processed,
            "source": "longbridge_actual_filled_completed_trades",
            "local_simulation_used": False,
        }
    )
    _write_json(state_path, state)
    return state


def consume_next_eligible_signal(
    state: dict[str, Any],
    state_path: Path,
    *,
    signal_id: str,
    consumed_at: str,
) -> bool:
    pending = int(state.get("pending_skip_count") or 0)
    if pending <= 0:
        return False
    state["pending_skip_count"] = pending - 1
    state["last_skipped_signal_id"] = signal_id
    state["last_skipped_signal_at"] = consumed_at
    state["generated_at"] = consumed_at
    _write_json(state_path, state)
    return True


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
