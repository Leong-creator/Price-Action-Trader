# 2026-05-06（美东）收盘/盘后新闻与财报回顾（M12）

> 说明：本报告只使用本项目**只读**扫描/模拟结果 + 公开新闻/财报信息做交叉核对；不接账户、不下单、不构成实盘建议。若信息不确定，会标注「待确认」。

## 1）今天模拟测试结果（一句话）

主线模拟当日合计约 **-288.27**（experimental 为 **0.00**），盘后仍处于 **paper_trading_approval=false / trading_connection=false** 的只读观察状态。

## 2）盘后财报/新闻大波动（优先策略相关与第一批 50 / 大盘 ETF）

### 大盘/宏观主线（收盘）

- 市场情绪偏 risk-on：公开报道指出 **S&P 500 与纳指创纪录**，与 AI 情绪、以及中东局势相关的“缓和预期/油价下行”叙事共同驱动。参考：Reuters 转述稿（MarketScreener 聚合页）  
  - [S&P 500, Nasdaq hit record highs on AI optimism, Middle East peace hopes（Reuters）](https://www.marketscreener.com/news/s-p-500-nasdaq-hit-record-highs-on-ai-optimism-middle-east-peace-hopes-ce7f58d2d881fe21)

### 盘后/延长交易主要异动（快照，可能随时间变化）

- **AMD**：盘后/延长交易显著上行（公开报道普遍指向财报与指引带动；具体幅度以各数据源为准）。参考：Reuters/Investing.com 聚合与盘后报价页  
  - [After Hours Stock Quotes（SPY/QQQ/IWM 盘后报价 + 个股盘后活跃）](https://www.investing.com/equities/after-hours)
  - [After-hours movers: FTNT, DASH, ARM, SNAP, ...（Investing.com）](https://www.investing.com/news/stock-market-news/afterhours-movers-ftnt-dash-arm-snap-bros-cohr-fsly-aosl-app-432SI-4665446)
- **ARM / FTNT / DASH / SNAP / APP / BROS / COHR / FSLY / AOSL**：上述 Investing.com 盘后异动列表里给出了幅度与触发点（多为盘后财报与指引）。  
  - 这批里多数不在「第一批 50」核心池内，因此更可能被当前日常扫描漏掉（见第 4 部分）。

## 3）这些股票是否被今天策略候选检测到（基于只读候选文件）

以 `m12_29_today_candidates.csv` 为准（本次候选：93 行，48 个唯一 ticker）：

- **命中（在今日候选中出现）**：`AMD`、`GOOG`、`GOOGL`、`SPY`、`IWM`、`SOXX`、`SMH`、`QCOM`
- **未命中（今日候选未出现）**：`QQQ`、`ARM`、`FTNT`、`DASH`、`SNAP`、`APP`、`BROS`、`COHR`、`FSLY`、`AOSL`

## 4）哪些机会漏掉了，以及可能原因（只做机制归因，不做交易建议）

- **盘后财报异动股（ARM/FTNT/DASH/...）未命中**：更大概率是“**不在当前第一批 50 核心池/日常关注池**”导致（属于 coverage 缺口，而非信号逻辑错误）。  
- **QQQ 未命中**：属于“**今日信号条件未触发/或被过滤**”类漏报（待确认：需要回看 `m12_29_today_candidates.csv` 的过滤链路与各策略 lane 的信号统计）。
- **数据不齐提醒**：只读看板提示“第一批 50 当日数据未全部齐”，这可能导致部分标的被动缺失或降级为低置信（待确认具体缺失列表）。

## 5）明天盘前需要重点盯的股票（只读观察清单）

结合只读看板告警 + 今日候选覆盖，盘前优先级建议（仅用于“观察/复核信号”，不构成交易动作）：

- **必看交叉检查**：`GOOG` / `GOOGL`；`SPY` / `IWM`（以及 `QQQ` 的“为什么缺席”）
- **财报驱动波动核心**：`AMD`（并联 `SOXX` / `SMH` / `QCOM` 做板块强弱对照）
- **候选高频出现（行数较多）**：`EEM`、`ORCL`（用于检查是否出现“事件驱动 + 技术形态”叠加的假信号）

## 6）对策略测试的影响（只读结论）

- **事件驱动波动日**会放大滑点/跳空风险：对 5m lane（如 `M10-PA-012`）与财报相关标的更敏感；应在回放/模拟里重点标注“财报窗口”与“盘后缺口”的风险标签（待确认：是否已有自动标注字段）。
- **coverage 缺口**需要显式管理：若目标是“盘后财报异动跟踪”，需要单独定义“盘后异动 watchlist”输入，而不是依赖第一批 50/日线扫描自然覆盖（避免把策略能力误判为扫描覆盖不足）。

---

### 本次使用的本地只读产物（可复核）

- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_38_codex_observer_latest.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_today_candidates.csv`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_32_strategy_scorecard.csv`

