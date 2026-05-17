# 2026-05-11（美股）收盘/盘后新闻与财报回顾（只读）

> 说明：本报告只基于本仓库**只读**扫描产物 + 公开信息快照整理；不接账户、不下单、不构成实盘建议。
> 时区：交易日按纽约日期 `2026-05-11`；本地生成时间约 `2026-05-12 05:15 CST`（盘后）。

## 1）今天模拟测试结果（一句话）

主线模拟：`-126.67`（权益 `153439.88`）；实验模拟：`-166.18`（权益 `179833.82`）；当日数据齐备（First50 日线/5m 均 `50/50`），但**重点关注股命中为 0**。

## 2）盘后财报/新闻大波动（先列“可核对的”，不确定标待确认）

### 2.1 盘前大幅波动（来自本项目只读 extended-session 监控）

阈值：`>= 3%`

- `MU`：盘前 +`5.94%`（存储芯片）
- `QCOM`：盘前 +`6.08%`（高通 / 芯片）
- `SLV`：盘前 +`5.49%`
- `INTC`：盘前 +`3.76%`

> 以上为项目内监控快照，**原因未在本仓库产物中给出**，需在次日盘前结合公司公告/新闻再确认。

### 2.2 盘后/收盘后（公开信息：After-hours movers/quotes 快照）

- Reuters/Investing.com（`2026-05-11 16:35` 发布）列出的盘后异动标的：`HIMS / ACHR / HLIT / ABCL / PLUG / BZH / PSIX / ASTS`（事件多为财报或指引相关，细项以原文为准）。
- Investing.com “After Hours” 页面在同一交易日显示：`GOOGL` 小幅波动、`NVDA` 出现异常级别跌幅打印（**疑似非代表性 after-hours print 或数据源异常**）——此类极端值需要用多源报价或次日开盘验证。

## 3）这些股票是否被今天策略候选检测到（按仓库只读候选）

### 3.1 必看：GOOG/GOOGL；SPY/QQQ/IWM

- `GOOG/GOOGL`：**未出现在**今日候选（`m12_29_today_candidates.csv` 未命中）。
- `SPY`：**未出现在**今日候选（未命中）。
- `QQQ`：在候选内（`M10-PA-001` 日线观察）。
- `IWM`：在候选内（`M10-PA-001` 日线观察）。

### 3.2 扩展时段异动 4 只（QCOM/MU/SLV/INTC）

- `MU`：在候选内（`M10-PA-001` 日线观察）。
- `QCOM / SLV / INTC`：**未出现在**今日候选（未命中）。

### 3.3 Reuters/Investing.com 盘后异动清单（HIMS/ACHR/…）

- `HIMS / ACHR / HLIT / ABCL / PLUG / BZH / PSIX / ASTS`：**均未出现在**今日候选（未命中）。
- 备注：这些标的多数不在 First50；即使在 First50 外，也应按“风险提示/错过机会归因”做降级处理。

## 4）哪些机会漏掉了，以及原因（只给“可验证的原因”，不编造）

### 4.1 “盘后异动标的”未覆盖（结构性原因）

- 本项目当前日常重点覆盖 **First50 股票池**（见看板与缓存），而 Reuters/Investing.com 的盘后异动清单包含大量 First50 以外标的：这类“漏掉”属于**宇宙覆盖范围外**，不是信号漏检。

### 4.2 First50 内仍出现“异动但非候选”（信号层原因，需次日复核）

- `QCOM / SLV / INTC` 在 First50 内，但未成为今日候选：目前只能确定“未满足当日候选规则/阈值或被策略过滤”，具体是哪条过滤或哪段数据形态导致，需要结合次日盘前复盘（bar-by-bar/日线形态）再定位。

### 4.3 数据异常风险（需明确标注）

- 本次交易日 `current_day_runtime_ready=true` 且 `50/50` 数据齐备，但公开 after-hours 报价中出现 `NVDA` 极端打印：此类情况可能导致“盘后大波动”误判，必须多源核对后才可写入策略结论。

## 5）明天盘前需要重点盯的股票（仅“复盘/风险核对清单”，非实盘建议）

优先级按“策略相关 + First50 + 波动/事件风险”：

- **必看大盘**：`SPY / QQQ / IWM`（确认是否出现 gap、以及与候选/信号的一致性）。
- **芯片链条**：`MU`（已入候选 + 盘前异动），以及 `QCOM / INTC`（盘前异动但未入候选，查明原因）。
- **白银/避险**：`SLV`（盘前异动但未入候选，查明原因）。
- **GOOG/GOOGL**：虽然今日未入候选，但仍需做“盘后公告/SEC/IR”例行核对（尤其当大盘/科技权重对指数影响显著时）。
- **盘后异动清单**：`HIMS / ACHR / HLIT / ABCL / PLUG / BZH / PSIX / ASTS`（多数可能不在 First50，作为事件风险雷达即可）。

## 6）对策略测试的影响（只谈测试，不扩展到执行）

- 今日候选对大盘 ETF 的覆盖：`QQQ/IWM` 有候选，但 `SPY` 未入候选；明天可重点观察：是否需要在“观察层”加一条**指数类候选最小覆盖**（仅用于复盘对齐，不改变信号/收益口径）。
- 对扩展时段异动的处理：当前“盘前异动 4 条”能被记录，但缺少“原因标签/公告链路”，建议继续保持“待确认”状态，避免把新闻当作收益解释的主因。
- 公开 after-hours 报价出现疑似异常打印（`NVDA`）：建议把“极端 after-hours print”纳入复盘 checklist（例如：必须次日开盘前用第二来源验证），防止把数据噪音当成事件。

## 附：本次使用的仓库只读产物

- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_report.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_summary.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_today_candidates.csv`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_48_extended_session_monitor.json`

## 附：公开信息（待用户或次日盘前二次核对）

- Investing.com After-hours movers（Reuters）与 After Hours quotes 页面（`2026-05-11`）
