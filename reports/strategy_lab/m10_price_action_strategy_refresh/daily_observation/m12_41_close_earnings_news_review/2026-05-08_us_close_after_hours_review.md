# 2026-05-08（周五）美股收盘/盘后：财报与新闻回顾（只读）

> 范围声明：本报告只使用本项目的只读看板/模拟结果 + 公开可得的盘后行情页面信息；**不接账户、不下单、不提供实盘建议**。
> 覆盖交易日口径：**纽约交易日 2026-05-08（Fri）**；本地看板生成时间：`2026-05-08T16:52:49Z`（见当日扫描报告）。

## 1）今天模拟测试结果一句话

- **主线模拟**：`-852.44`，权益 `153564.49`；**实验账户**：`-52.86`，权益 `159947.14`（当日扫描报告口径，均为模拟/只读）。

## 2）盘后财报/新闻大波动（只列“确认到的盘后波动/日历”，其余待确认）

### 2.1 本项目盘前/盘后异动监控（阈值 3%）

- 扩展时段监控显示：**盘前 0、盘后 0（>=3%）**；“当前没有超过 3% 的盘前/盘后异动。”（仅对本项目监控范围与阈值成立）。

### 2.2 公开盘后行情页（用于交叉核对）

- 盘后 ETF 轻微波动（盘后快照）：`SPY -0.02%`，`QQQ -0.03%`，`IWM +0.01%`，`DIA -0.02%`（盘后行情页口径，时间为页面抓取时刻，可能随时变动）。
- 盘后榜单示例（盘后快照）：`WAT -7.39%`、`LVS +5.28%` 等不在 First50；因此**不会被“First50 日内/日线”覆盖**（属于“范围外”而非“漏检”）。

### 2.3 盘后财报日历（用于“次日风险”提示，不等于价格必然波动）

- 日历显示 2026-05-08（Fri）披露的公司包含 `PPL`、`FIS`（是否盘后/盘前，以各公司 IR/新闻稿时间为准；此处只做“有财报事件”的提醒）。

> 待确认：本交易日盘后是否存在“First50 内”个股因财报/公告出现 >3% 的波动但未被本地监控捕捉；目前本地监控结论为“无”。

## 3）这些股票是否被今天策略候选检测到（重点：First50 + GOOG/GOOGL + 大盘 ETF）

### 3.1 今日候选（m12_29_today_candidates.csv）

- 候选共 `26` 行、`22` 个去重标的；**全部都在 First50**（没有范围外候选）。
- 重点交叉检查：
  - `GOOG`：命中候选（`1`）
  - `GOOGL`：命中候选（`1`）
  - `IWM`：命中候选（`1`）
  - `SPY`：未命中候选（`0`）
  - `QQQ`：未命中候选（`0`）

### 3.2 关于“盘后大波动 vs 候选”

- 在“>=3% 扩展时段异动”这个口径下：本地监控为 `0`，因此**不存在“盘后大波动被候选漏掉”的同口径事件**。

## 4）哪些机会漏掉了以及原因（只基于只读看板能确认的原因）

- **数据可用性为 0**：当日扫描报告显示 “50 只股票日线可用 0、当日 5m 可用 0”，并且 First50 cache summary 显示 `stale_cache`（缓存陈旧）。这会导致：
  - “盘后/盘前异动监控”只能报告为 0（因为没有可用的当日数据链路去支撑筛选）。
  - 候选列表可能**偏向“可生成但未必是当日新鲜数据”的信号队列**（需要结合 `candidate_status` / `bar_timestamp` 逐条复核）。
- **旧日期候选残留**：当日扫描报告提示仍有 `26` 条旧日期候选留在观察信号里，不能当作今日新开仓；因此“候选命中”不等于“今日新机会”。

## 5）明天盘前需要重点盯的股票（只列“范围内 + 有理由”的清单）

> 这里只给“观察清单”，不做实盘建议。

- `GOOG / GOOGL`：项目强制交叉检查标的，且今日均在候选中；盘前需关注是否有新增公告/SEC/IR 更新（待确认）。
- `IWM`：今日在候选中；同时是风格/小盘风险的体感温度计。
- `PANW / ORCL / META / NVDA / MSFT / AAPL / AVGO`：均在 First50 且出现在今日候选中；盘前只需做“是否有突发公告/财报时间变更/监管消息”的一致性检查。
- `SPY / QQQ`：作为大盘 ETF 依然建议盘前看一眼（尽管今日候选未命中）。

## 6）对策略测试的影响（只读口径）

- 本交易日的核心信号：**数据链路“ready_symbols=0 + stale_cache”是首要风险**；在此条件下，“候选命中/不命中”对策略质量的解释力会显著下降。
- 对 M12.33 连续观察的影响：当前只累计到 `4/10` 个交易日；在数据可用性不稳定时，建议把本日标记为“数据质量异常日”（仅做记录，不做结论推广）。

## 附：本次回顾使用的本地只读材料

- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_current_day_scan_report.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_29_today_candidates.csv`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_48_extended_session_monitor.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_12_current_day_source/m12_12_first50_cache_summary.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/m12_12_current_day_source/m12_12_first50_universe.json`
