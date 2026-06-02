# M15 Monday Refresh Acceptance

- Status: `pretrade_preparation_ready_waiting_for_monday`
- Session should run: `False`
- Child running: `False`
- Quote source: `longbridge_quote_readonly`
- Pass / waiting / fail: `8/2/0`
- Boundary: preview only, no account connection, no orders, no manual M12.37 once.

| Check | Status | Actual |
|---|---|---|
| m12_47_alive | pass | True |
| regular_us_market_window | waiting_for_monday_refresh | 等待下一交易日 |
| m12_37_child_running_when_required | waiting_for_monday_refresh | child_running=false, failure_state=, failure_reason= |
| quote_source_longbridge | pass | longbridge_quote_readonly |
| first50_daily_and_5m_complete | pass | daily=50/50, 5m=50/50 |
| m13_current_day_ledger | pass | scan_date=2026-06-01, m13=2026-06-01 |
| m14_recomputed_for_current_day | pass | scan_date=2026-06-01, m14=2026-06-01 |
| no_fallback_or_old_snapshot | pass | fresh_or_clean |
| longbridge_paper_preflight_preview_only | pass | ready_for_user_paper_credential_approval |
| m12_37_supervisor_owned | pass | M12.37.intraday_auto_loop |
