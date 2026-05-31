# M15 Monday Refresh Acceptance

- Status: `pretrade_preparation_ready_waiting_for_monday`
- Session should run: `False`
- Child running: `False`
- Quote source: `fallback_quotes_only`
- Pass / waiting / fail: `6/4/0`
- Boundary: preview only, no account connection, no orders, no manual M12.37 once.

| Check | Status | Actual |
|---|---|---|
| m12_47_alive | pass | True |
| regular_us_market_window | waiting_for_monday_refresh | 非交易日等待 |
| m12_37_child_running_when_required | waiting_for_monday_refresh | child_running=false, failure_state=, failure_reason= |
| quote_source_longbridge | waiting_for_monday_refresh | fallback_quotes_only |
| first50_daily_and_5m_complete | pass | daily=50/50, 5m=50/50 |
| m13_current_day_ledger | pass | scan_date=2026-05-22, m13=2026-05-22 |
| m14_recomputed_for_current_day | pass | scan_date=2026-05-22, m14=2026-05-22 |
| no_fallback_or_old_snapshot | waiting_for_monday_refresh | fallback_or_no_fetch |
| longbridge_paper_preflight_preview_only | pass | blocked_fallback_or_no_fetch_data |
| m12_37_supervisor_owned | pass | M12.37.intraday_auto_loop |
