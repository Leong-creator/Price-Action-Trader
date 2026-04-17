# Public History Backtest Demo

本报告仅用于公共历史数据研究演示，仍处于 paper / simulated 边界，不代表实盘能力或未来收益承诺。

## 1. 本次测试范围

- 标的：NVDA, TSLA, SPY
- 时间范围：2024-01-01 ~ 2024-06-30 (1d)
- 数据来源：yfinance
- 本地缓存目录：`/home/hgl/projects/Price-Action-Trader/local_data/public_history`
- 报告目录：`/home/hgl/projects/Price-Action-Trader/reports/backtests/smoke_public_demo_regression`
- 现金口径说明：本次现金口径按 USD demo sizing 统计，因为本轮只选择了 US 标的。
- Walk-forward 切分：完整区间
- Regime 分层：完整区间

## 2. 核心结果

- 总盈亏：498.0720
- 总收益率：1.9923%
- 最大回撤：392.4220 (1.5157%)
- 交易笔数：16
- 胜率：43.7500%
- 盈亏比（profit factor）：1.5678
- 风控拦截信号数：19
- no-trade / wait 结构化记录：350

## 3. 分标的摘要

| 标的 | 角色 | 数据源 | Bars | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NVDA | 明显趋势段 | yfinance | 124 | 13 | 6 | 7 | 116 | 593.1220 | 66.6667% | 100.0000% | 100.0000% |
| TSLA | 高波动震荡/反复段 | yfinance | 124 | 11 | 5 | 6 | 117 | -187.9500 | 20.0000% | 100.0000% | 100.0000% |
| SPY | 指数基准与相对平稳段 | yfinance | 124 | 11 | 5 | 6 | 117 | 92.9000 | 40.0000% | 100.0000% | 100.0000% |

## 4. Walk-forward / Split 摘要

| 名称 | 区间 | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 完整验证区间 | 2024-01-02 ~ 2024-06-28 | 35 | 16 | 19 | 350 | 498.0720 | 43.7500% | 100.0000% | 100.0000% |

## 5. Regime 分层摘要

| 名称 | 区间 | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 完整验证区间 | 2024-01-02 ~ 2024-06-28 | 35 | 16 | 19 | 350 | 498.0720 | 43.7500% | 100.0000% | 100.0000% |

## 6. Knowledge Trace 覆盖率摘要

- 发出信号总数：35；trace 非空占比：100.0000%
- 含 curated trace 的信号占比：100.0000%；含 statement 补充证据的信号占比：100.0000%
- actual hit family 分布（按 visible trace 的信号存在计数）：curated_concept=35 | curated_rule=35 | curated_setup=35 | fangfangtu_notes=35
- actual evidence family 分布（按 visible trace 命中的证据家族计数）：al_brooks_ppt=35 | fangfangtu_notes=35 | fangfangtu_transcript=35
- bundle support family 分布（按补充来源存在计数）：al_brooks_ppt=35 | curated_rule=35 | fangfangtu_notes=35 | fangfangtu_transcript=35
- curated vs statement 命中占比（按受控 trace item 计）：curated=75.0000%， statement=25.0000%

## 7. no-trade / wait 摘要

- 结构化记录总数：350
- action 分布：no-trade=19 | wait=331
- reason 分布：context_not_trend=269 | duplicate_direction_suppressed=9 | insufficient_evidence=53 | risk_blocked_before_fill=19
- 代表性样本：
  - `NVDA` @ 2024-01-04T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `SPY` @ 2024-01-04T16:00:00-05:00: wait / insufficient_evidence (bars did not satisfy the placeholder setup body/range/invalidation requirements)
  - `TSLA` @ 2024-01-04T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `SPY` @ 2024-01-05T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `TSLA` @ 2024-01-05T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)

## 8. 最好 5 笔交易

- `NVDA` long | pnl=199.5400 | 2024-02-05T16:00:00-05:00 -> 2024-02-22T16:00:00-05:00 | exit=达到固定 2R 目标
- `NVDA` long | pnl=197.7840 | 2024-01-08T16:00:00-05:00 -> 2024-01-08T16:00:00-05:00 | exit=达到固定 2R 目标
- `NVDA` long | pnl=197.6800 | 2024-01-22T16:00:00-05:00 -> 2024-02-02T16:00:00-05:00 | exit=达到固定 2R 目标
- `NVDA` long | pnl=197.1900 | 2024-03-04T16:00:00-05:00 -> 2024-03-08T16:00:00-05:00 | exit=达到固定 2R 目标
- `TSLA` short | pnl=195.3000 | 2024-01-12T16:00:00-05:00 -> 2024-01-25T16:00:00-05:00 | exit=达到固定 2R 目标

## 9. 最差 5 笔交易

- `NVDA` long | pnl=-99.6480 | 2024-03-08T16:00:00-05:00 -> 2024-03-08T16:00:00-05:00 | exit=触及保护性止损
- `NVDA` long | pnl=-99.4240 | 2024-03-25T16:00:00-04:00 -> 2024-03-27T16:00:00-04:00 | exit=触及保护性止损
- `TSLA` short | pnl=-99.3600 | 2024-03-14T16:00:00-04:00 -> 2024-03-20T16:00:00-04:00 | exit=触及保护性止损
- `SPY` long | pnl=-99.1600 | 2024-02-12T16:00:00-05:00 -> 2024-02-13T16:00:00-05:00 | exit=触及保护性止损
- `SPY` long | pnl=-98.6000 | 2024-02-16T16:00:00-05:00 -> 2024-02-16T16:00:00-05:00 | exit=触及保护性止损

## 10. 代表性交易解释

- `NVDA` long @ 2024-02-05T16:00:00-05:00 -> 2024-02-22T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 22 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` long @ 2024-01-08T16:00:00-05:00 -> 2024-01-08T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 3 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` long @ 2024-03-08T16:00:00-05:00 -> 2024-03-08T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 45 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：触及保护性止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` long @ 2024-03-25T16:00:00-04:00 -> 2024-03-27T16:00:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 56 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：触及保护性止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low

## 11. 风控与未执行样本

- `TSLA` @ 2024-02-12T16:00:00-05:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill. (reason_codes=max_total_exposure_exceeded)
- `NVDA` @ 2024-03-28T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `TSLA` @ 2024-04-10T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `SPY` @ 2024-04-16T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `TSLA` @ 2024-04-22T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)

## 12. 结论与局限

- 结论：这轮 `2024-01-01 ~ 2024-06-30` 的 daily public-history validation 在 `NVDA, TSLA, SPY` 上，按当前 demo 风控和历史回测口径，录得 1.9923% 的总收益率。
- 本报告仅用于公共历史数据研究演示，仍处于 paper / simulated 边界，不代表实盘能力或未来收益承诺。
- 当前演示未接入历史新闻时间线，因此 news filter 不参与本轮回测结果。
- 当前 no-trade / wait 只持久化系统能明确解释的 decision sites，不对所有静默 bar 补造结论。
- 当前仍是 daily public-history validation，不模拟 intraday session reset、真实滑点或真实手续费。
