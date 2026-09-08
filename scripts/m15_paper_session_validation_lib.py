"""Date-scoped paper validation authorization, separate from full-session proof."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def paper_validation_authorized(config, now=None):
    now = now or datetime.now(UTC)
    if isinstance(now, str):
        try:
            now = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except ValueError:
            return False
    if now.tzinfo is None:
        return False
    local = now.astimezone(ZoneInfo("America/New_York"))
    return bool(
        getattr(config, "paper_validation_approved", False) is True
        and getattr(config, "paper_validation_market_date", "") == local.date().isoformat()
        and local.weekday() < 5
        and local.date().isoformat() not in getattr(config, "market_holidays", ())
        and getattr(config, "paper_trading_only", False) is True
        and not getattr(config, "live_execution", True)
        and not getattr(config, "real_money_actions", True)
        and getattr(config, "market_data_transport", "") == "official_sdk_persistent_websocket"
    )


def entry_session_authorized(config, complete_session_passed, now=None):
    return bool(
        not config.complete_session_gate_enabled
        or complete_session_passed
        or paper_validation_authorized(config, now)
    )


def validation_status_current(status, now=None):
    """A cached approval is not valid across dates or beyond status freshness."""
    try:
        current = now or datetime.now(UTC)
        if isinstance(current, str):
            current = datetime.fromisoformat(current.replace("Z", "+00:00"))
        generated = datetime.fromisoformat(str(status.get("generated_at") or "").replace("Z", "+00:00"))
        if current.tzinfo is None or generated.tzinfo is None:
            return False
        return bool(status.get("paper_validation_authorized") is True
                    and status.get("paper_validation_market_date") == current.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                    and 0 <= (current - generated).total_seconds() <= 45)
    except (ValueError, TypeError):
        return False
