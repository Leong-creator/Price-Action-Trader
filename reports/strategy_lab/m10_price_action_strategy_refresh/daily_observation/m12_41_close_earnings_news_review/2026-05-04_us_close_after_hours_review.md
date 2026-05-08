# 2026-05-04（美股）收盘/盘后：财报与新闻回顾（只读）

> 说明：本报告仅基于本仓库只读扫描与公开信息做“复盘记录”，不接账户、不下单、不构成实盘建议。不确定处会标注“待确认”。

## 1）今天模拟测试结果（一句话）

- 交易日（纽约）：`2026-05-04`；只读报价覆盖后的模拟盈亏：`+12055.92`（`+12.06%`）；今日候选 `78` 条、PA004 做多观察 `19` 条；连续观察进度 `1/10`（未满足进入模拟试运行门槛）。

## 2）盘后财报/新闻大波动（收盘后到盘后早段）

> 口径：仅摘录“盘后显著波动 + 明确触发原因（财报/指引）”的条目；幅度为媒体报道区间，精确幅度以盘后逐笔为准（待确认）。

- `PINS`：盘后上涨（约 +18%），媒体口径为“业绩超预期 + 指引强于预期”。（待确认：公司公告/IR）
- `BLZE`：盘后上涨（约 +22%），媒体口径为“业绩超预期 + 上调指引”。（待确认：公司公告/IR）
- `PLTR`：盘后小涨（约 +1%），媒体口径为 EPS/营收均高于预期。（待确认：公司公告/IR）
- `WGS`：盘后大跌（约 -37%），媒体口径为 Q2 营收指引偏弱。（待确认：公司公告/IR）
- `DUOL`：盘后下跌（约 -13%），媒体口径为“bookings 指引低于预期”。（待确认：公司公告/IR）
- `FN`：盘后下跌（约 -10%），媒体口径为“结果不错但未满足更高预期”。（待确认：公司公告/IR）
- `ON`：盘后下跌（约 -4%），媒体口径为“sell the news（前期涨幅大）”。（待确认：公司公告/IR）

## 3）这些股票是否被今天策略候选检测到

### A. 出现在今日候选（m12_29_today_candidates.csv）

- `PLTR`：是（`M10-PA-012`，`trigger_candidate`）。
- `GOOG/GOOGL`：是（`M10-PA-001`，`watch_candidate`；收盘 bar 标记为 `2026-05-04T16:00:00-04:00`）。
- `SPY/QQQ/IWM`：是（均为 `M10-PA-012`，`trigger_candidate`）。
- `AMD`：是（`M10-PA-012`，`trigger_candidate`；注意：不等同于“当日盘后财报”，仅作为候选记录保留）。

### B. 未出现在今日候选

- `PINS / ON / BLZE / DUOL / FN / WGS / PSKY`：否。

## 4）哪些机会漏掉了，以及原因（最小归因）

- 主要原因：盘后波动的多只标的不在“第一批 50 只股票池 / 今日扫描宇宙”，属于当前阶段的刻意不覆盖。
- 时间窗原因：盘后财报类跳空风险发生在 regular session 之后，不应期望被“当日盘中候选”预测式捕捉；更合适作为次日开盘前风险项与过滤规则回放样本。

## 5）明天盘前需要重点盯的股票（仅风险观察清单，非交易建议）

- 盘后大波动（财报/指引驱动）：`PINS, BLZE, WGS, DUOL, FN, ON, PLTR`（关注：次日跳空、开盘后波动与是否触发高波动过滤）。
- 强制交叉检查：`GOOG, GOOGL, SPY, QQQ, IWM`（关注：是否出现与大盘共振的 gap + 失败突破/突破 follow-through）。
- 今日候选高频出现：`TLT, LQD, HYG`（候选行频次靠前；关注：是否继续给出一致性形态）。

## 6）对策略测试的影响（只谈测试）

- 对不在 First50 的盘后波动标的：主要用于验证“universe 边界是否合理”和“高波动/跳空过滤”在次日开盘的表现，不用于评价当日盘中候选好坏。
- 对已覆盖标的（如 `PLTR`）：盘后财报造成的次日跳空适合作为 `M10-PA-012` 等候选的次日风险回放样本，用于检查 `no-trade / wait` 与高波动规则是否按预期拦截或降权。（待确认：是否已有“财报风险标注”字段/规则）

## 本次使用的本地只读资料（Source of Truth）

- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_report.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_summary.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_today_candidates.csv`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_33_observation_run_status.md`

