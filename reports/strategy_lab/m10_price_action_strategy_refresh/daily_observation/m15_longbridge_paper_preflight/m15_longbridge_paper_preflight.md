# M15 Longbridge Paper Preflight

- Status: `ready_for_user_paper_credential_approval`
- Quote source: `longbridge_quote_readonly`
- Scan date / M14 trading date: `2026-06-01` / `2026-06-01`
- Candidate runtimes: `11`
- First paper order candidates: `11`
- CLI: `/home/hgl/.local/bin/longbridge` `longbridge 0.22.1`
- Boundary: paper token only, live token forbidden, no credential injection, no broker connection, no order submission.
- Paper account model: `6000` USD equity, max exposure `3600`, max symbol exposure `600`.
- Fractional shares: disabled. Short selling: disabled. Options: disabled.
- Allowed order types: `limit, trigger_limit`.
- US paper path uses regular trading hours only; pre-market and post-market paper orders stay disabled.
- First paper order whitelist: ``
- Policy blockers: `none`
- Quote source blockers: `none`
- Current-day blockers: `none`

| Runtime | Strategy | Action | Size | Order | First paper order |
|---|---|---|---:|---|---|
| M10-PA-002-1d | M10-PA-002 | risk_limited_advance | 0.25 | limit | True |
| M10-PA-004-MBF-1d | M10-PA-004-MBF | risk_limited_advance | 0.5 | limit | True |
| M10-PA-004-MBF-QC-m14-modify-20260522-1d | M10-PA-004-MBF-QC-m14-modify-20260522 | risk_limited_advance | 0.5 | limit | True |
| M10-PA-004-long-1d | M10-PA-004 | advance_internal_sim | 1 | limit | True |
| M10-PA-005-1d | M10-PA-005 | risk_limited_advance | 0.25 | limit | True |
| M10-PA-005-5m | M10-PA-005 | risk_limited_advance | 0.25 | limit | True |
| M10-PA-008-1d | M10-PA-008 | risk_limited_advance | 0.25 | limit | True |
| M10-PA-012-5m | M10-PA-012 | risk_limited_advance | 0.5 | limit | True |
| M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m | M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow | risk_limited_advance | 0.5 | limit | True |
| M10-PA-013-1d | M10-PA-013 | advance_internal_sim | 1 | limit | True |
| M10-PA-013-5m | M10-PA-013 | risk_limited_advance | 0.5 | limit | True |
