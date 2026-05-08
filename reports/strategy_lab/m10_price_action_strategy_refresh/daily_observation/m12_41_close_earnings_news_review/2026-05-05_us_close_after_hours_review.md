# 2026-05-05（美股）收盘/盘后：财报与新闻回顾（只读）

> 说明：本报告仅基于本仓库只读扫描与公开信息做“复盘记录”，不接账户、不下单、不构成实盘建议。不确定处会标注“待确认”。

## 1）今天模拟测试结果（一句话）

- 交易日（纽约）：`2026-05-05`；主线正式账户当前权益 `155244.65`，今日盈亏 `-4755.35`（`-2.97%`）；实验账户当前权益 `180000.00`，今日盈亏 `0.00`；今日候选 `77` 条（只读候选≠成交/执行）。

## 2）盘后财报/新闻大波动（收盘后到盘后早段）

> 口径：优先覆盖“本项目正在每日测试/观察的策略相关标的 + First50 股票池 + GOOG/GOOGL + SPY/QQQ/IWM”。幅度以公开盘后报价为准，精确幅度以盘后逐笔为准（待确认）。

### A. 大盘 ETF（盘后）

- `SPY` / `QQQ` / `IWM`：盘后小幅波动（分别约 `+0.16% / +0.33% / -0.11%`，以公开盘后报价为准；待确认：盘后收盘价与成交量分布）。

### B. 财报与公司公告（盘后为主）

- `AMD`：盘后发布 `Q1 2026` 财报新闻稿（官方 IR/Newsroom）。待确认项：盘后实际涨跌幅、财报细节（如指引/分部增速）与次日跳空幅度。
- `SHOP`：`2026-05-05` 公布截至 `2026-03-31` 季度财务结果（公司投资者关系）。注：不在 First50 股票池，本项目今日扫描未覆盖（因此不会被今日候选检测到）。
- `PYPL`：`2026-05-05` 发布 `Q1 2026` 季度财报（公司 Newsroom）。注：不在 First50 股票池，本项目今日扫描未覆盖（因此不会被今日候选检测到）。

## 3）这些股票是否被今天策略候选检测到

### A. 出现在今日候选（`m12_29_today_candidates.csv`）

- `SPY/QQQ/IWM`：是（`M10-PA-012` 为主；含 `1d` 与 `5m`）。
- `GOOG/GOOGL`：是（`M10-PA-001`，`watch_candidate`，`1d`）。
- `AMD`：是（`M10-PA-012`，`trigger_candidate`，`5m`；注意：候选不等于“盘后财报波动已捕捉/可预测”）。
- `PLTR`：是（`M10-PA-001` 的 `1d` + `M10-PA-012` 的 `5m`；更多属于“财报后波动延续/回吐”的风险观察对象）。

### B. 未出现在今日候选

- `SHOP / PYPL`：否（原因：当前 First50 股票池未覆盖）。

## 4）哪些机会漏掉了，以及原因（最小归因）

- 覆盖边界：`SHOP / PYPL` 等不在第一批 `50` 只股票池内，属于当前阶段的刻意不覆盖。
- 时间窗差异：财报新闻多在 regular session 之后发布；当日盘中候选不应被期待“预测盘后跳空”，更合理用法是把它们加入“次日开盘风险项/过滤回放样本”。

## 5）明天盘前需要重点盯的股票（仅风险观察清单，非交易建议）

- 强制交叉检查：`GOOG, GOOGL, SPY, QQQ, IWM`（关注：是否出现 gap、follow-through 是否失败、是否触发高波动过滤）。
- 财报/公告风险：`AMD`（关注：财报后次日跳空、波动扩张是否影响 `M10-PA-012` 的误报率）。
- 今日也在候选内：`PLTR`（关注：财报后波动是否继续造成“候选频繁但不可执行”的噪声；只做样本回放）。

## 6）对策略测试的影响（只谈测试）

- `AMD`：建议把“财报后次日开盘”作为 `M10-PA-012（开盘区间突破）` 的 stress sample：检查是否需要更明确的“财报日/跳空/波动扩张”降权或 `no-trade/wait` 规则（待确认：现有规则包是否已有财报风险标注字段）。
- 对未覆盖标的（`SHOP/PYPL`）：仅作为“universe 扩展候选”的价值评估输入；不应反向用来否定当前 First50 的只读检测质量。

## 本次使用的本地只读资料（Source of Truth）

- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_summary.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_today_candidates.csv`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_12_loop/m12_12_first50_cache_summary.json`

