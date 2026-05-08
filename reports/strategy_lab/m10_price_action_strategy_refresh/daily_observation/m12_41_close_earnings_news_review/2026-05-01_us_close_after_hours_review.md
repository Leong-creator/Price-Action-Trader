# M12 收盘/盘后新闻与财报回顾（美股）

- New York trading date：`2026-05-01`（Fri）
- 生成时间：`2026-05-01T21:22:58Z`（≈ 17:22:58 EDT；盘后时段）
- 范围说明：只读看板 + 新闻/财报复盘；不接账户、不下单、不提供实盘建议；不确定信息标注“待确认”。

## 0）本次使用的本地只读产物（Source of Truth）

- `/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_report.md`
- `/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_summary.json`
- `/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_today_candidates.csv`
- `/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_32_strategy_scorecard.csv`

## 1）今天模拟测试结果（一句话）

`2026-05-01` 的只读扫描里，累计模拟盈亏 `+16562.79`（`+16.56%`），但主线合计为 `-7819.12`，主要正贡献来自 `M10-PA-004` 做多观察 `+24381.91`（仅模拟观察，不代表已通过准入）。

## 2）盘后财报/新闻大波动（只列与关注池高度相关的）

### 2.1 本周最相关的“盘后财报集中段”（用于解释近两天波动）

说明：这些财报发生在 `2026-04-29`（盘后）与 `2026-04-30`（盘后），市场在 `2026-05-01` 继续消化/延续其影响；属于“离今天最近的盘后事件回放”。

- `GOOG/GOOGL`：Alphabet `2026-04-29` 盘后发布 Q1 2026 财报/材料（官方 PDF）。
  - 参考：Alphabet Q1 2026 earnings release（官方 PDF）https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf
  - 参考：Alphabet Q1 2026 earnings slides（官方 PDF）https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-slides.pdf
- `AMZN`：Amazon `2026-04-29` 盘后发布 Q1 2026 财报（官方 PDF）。
  - 参考：Amazon Q1 2026 earnings release（官方 PDF）https://s2.q4cdn.com/299287126/files/doc_earnings/2026/q1/earnings-result/AMZN-Q1-2026-Earnings-Release.pdf
- `MSFT / META / QCOM`：同一时间窗的盘后异动在媒体汇总里经常与上述同框出现（幅度与解读随口径不同而不同；细节建议二次核对）。
  - 参考（媒体汇总）：https://www.investing.com/news/stock-market-news/afterhours-movers-meta-googl-amzn-msft-qcom-f-cmg-cvna-432SI-4646900

### 2.2 “今天”自身的盘前/盘中财报（与盘后风险提示相关）

- `XOM / CVX`：`2026-05-01` 为盘前财报日（这两只不在本次 50 只池里，但会影响大盘风险偏好与能源板块波动；本项目仅做风险标签，不做交易建议）。
  - 参考（财报日历）：https://www.investing.com/equities/after-hours（页面含 `2026-05-01` Earnings Calendar）

## 3）这些股票是否被“今天策略候选”检测到（只读结果）

### 3.1 必看：GOOG/GOOGL + 大盘 ETF

- `GOOG`：命中（`M10-PA-012`，`5m`，`long`，`trigger_candidate`，需收盘复核）
- `GOOGL`：命中（`M10-PA-012`，`5m`，`long`，`trigger_candidate`，需收盘复核）
- `SPY`：命中（`M10-PA-002` `1d long`；`M10-PA-012` `5m long`；`M12-FTD-001` `1d long`）
- `QQQ`：命中（`M10-PA-002` `1d long`；`M10-PA-012` `5m long`；`M12-FTD-001` `1d long`）
- `IWM`：命中（`M10-PA-012`，`5m`，`long`）

### 3.2 盘后财报集中段里与本项目相关的 Mega-cap（采样）

- `AAPL`：命中（`M10-PA-002 1d long trigger_candidate`；另有 `M10-PA-012 5m long` 等）
- `MSFT`：命中（`M10-PA-012 5m long trigger_candidate`；另有 `M10-PA-001 1d watch_candidate`）
- `AMZN`：命中（`M10-PA-012 5m long trigger_candidate`）
- `META`：命中（`M10-PA-012 5m short trigger_candidate`）
- `QCOM`：命中（`M10-PA-012 5m short trigger_candidate`）

> 备注：上述命中只表示“形态/规则代理信号被检测到”，不代表与财报方向一致，更不代表可交易或已通过 paper gate。

## 4）哪些机会漏掉了？以及原因（只按可验证信息写）

- `F / CMG / CVNA` 等盘后异动在媒体汇总中出现，但**本次 50 只股票池扫描未覆盖**，因此不会在 `m12_29_today_candidates.csv` 里出现（不是“漏扫”，是“universe 不含”）。
- 本地扫描报告明确提示存在 `old_candidate_count=1`：今天候选里夹杂旧日期候选的风险仍在，因此“盘后回顾”里所有候选都应以 `needs_read_only_bar_close_review` 的复核状态为准，避免把盘中快照误当作收盘确认。

## 5）明天盘前需要重点盯的股票（只给观察清单，不给交易建议）

优先级按“本项目每日测试/观察策略 + 50 只池 + 财报/盘后波动关联度”排序：

1. `GOOG / GOOGL`：本周盘后财报样本核心；且今日候选已命中，需要观察次日延续/回撤的风险标签（待确认：财报后次日是否出现方向相反信号）。
2. `SPY / QQQ / IWM`：大盘风险偏好载体；今日多策略命中，适合作为“候选密度/误报率”的基准面板。
3. `AAPL / MSFT / AMZN / META / QCOM`：盘后财报集中段的核心波动来源；今日候选均有命中，但方向分歧明显（尤其 `META/QCOM` 的 `short` 候选）。

## 6）对策略测试的影响（只谈测试，不谈实盘）

- 近两天属于“财报密集周”的尾声阶段：候选数量与波动共振时，`M10-PA-012`（开盘区间）更容易出现高风险级别候选；建议在后续复盘里把“财报日/次日”作为高风险标签样本，沉淀到新闻 sidecar 的误报/冲突案例库。
- `M10-PA-004` 目前是收益主要来源，但它在本项目里仍是“做多观察”，不进入 paper gate evidence；因此这类收益更多用于“观察样本、检验风控标签”，不用于推进准入结论。

