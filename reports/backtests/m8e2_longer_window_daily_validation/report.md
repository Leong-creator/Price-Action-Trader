# Public History Longer-Window Daily Validation

本报告仅用于公共历史数据研究演示，仍处于 paper / simulated 边界，不代表实盘能力或未来收益承诺。

## 1. 本次测试范围

- 标的：NVDA, TSLA, SPY
- 时间范围：2018-01-01 ~ 2026-04-17 (1d)
- 数据来源：yfinance
- 本地缓存目录：`local_data/public_history`
- 报告目录：`reports/backtests/m8e2_longer_window_daily_validation`
- 现金口径说明：本次现金口径按 USD demo sizing 统计，因为本轮只选择了 US 标的。
- Walk-forward 切分：In-sample, Validation, Out-of-sample
- Regime 分层：2018 紧缩波动, 2019 修复与再定价, 2020 高波动下跌, 2020H2-2021 上升趋势, 2022 宏观回撤, 2023-2026 恢复、AI 动量与区间切换

## 2. 核心结果

- 总盈亏：389.9846
- 总收益率：1.5599%
- 最大回撤：494.1026 (1.9237%)
- 交易笔数：14
- 胜率：42.8571%
- 盈亏比（profit factor）：1.4914
- 风控拦截信号数：562
- no-trade / wait 结构化记录：6210

## 3. 分标的摘要

| 标的 | 角色 | 数据源 | Bars | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NVDA | 高贝塔成长趋势段 | yfinance | 2083 | 190 | 3 | 183 | 2074 | -0.0856 | 33.3333% | 100.0000% | 100.0000% |
| TSLA | 高波动震荡/反复段 | yfinance | 2083 | 191 | 5 | 183 | 2073 | 100.9702 | 40.0000% | 100.0000% | 100.0000% |
| SPY | 指数基准与相对稳态段 | yfinance | 2083 | 214 | 6 | 196 | 2063 | 289.1000 | 50.0000% | 100.0000% | 100.0000% |

## 4. Walk-forward / Split 摘要

| 名称 | 区间 | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| In-sample | 2018-01-01 ~ 2020-12-31 | 197 | 14 | 183 | 2241 | 389.9846 | 42.8571% | 100.0000% | 100.0000% |
| Validation | 2021-01-01 ~ 2023-12-31 | 222 | 0 | 222 | 2253 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| Out-of-sample | 2024-01-01 ~ 2026-04-17 | 157 | 0 | 157 | 1716 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |

### 样本充分性

- 总体结论：insufficient_sample（验证诚实但样本不足）
- In-sample (in_sample)：executed_trades=14 / minimum_required=5 -> adequate
- Validation (validation)：executed_trades=0 / minimum_required=5 -> insufficient_sample（验证诚实但样本不足）
- Out-of-sample (out_of_sample)：executed_trades=0 / minimum_required=5 -> insufficient_sample（验证诚实但样本不足）

## 5. Regime 分层摘要

| 名称 | 区间 | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2018 紧缩波动 | 2018-01-01 ~ 2018-12-31 | 77 | 14 | 63 | 732 | 389.9846 | 42.8571% | 100.0000% | 100.0000% |
| 2019 修复与再定价 | 2019-01-01 ~ 2019-12-31 | 67 | 0 | 67 | 756 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 2020 高波动下跌 | 2020-02-01 ~ 2020-05-31 | 15 | 0 | 15 | 242 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 2020H2-2021 上升趋势 | 2020-06-01 ~ 2021-12-31 | 101 | 0 | 101 | 1202 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 2022 宏观回撤 | 2022-01-01 ~ 2022-12-31 | 80 | 0 | 80 | 752 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 2023-2026 恢复、AI 动量与区间切换 | 2023-01-01 ~ 2026-04-17 | 231 | 0 | 231 | 2463 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 未落入显式窗口 | 2018-01-01 ~ 2026-04-17 | 5 | 0 | 5 | 63 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |

## 6. Knowledge Trace 覆盖率摘要

- 发出信号总数：595；trace 非空占比：100.0000%
- 含 curated trace 的信号占比：100.0000%；含 statement 补充证据的信号占比：100.0000%
- actual hit family 分布（按 visible trace 的信号存在计数）：curated_concept=595 | curated_rule=595 | curated_setup=595 | fangfangtu_notes=595
- actual evidence family 分布（按 visible trace 命中的证据家族计数）：al_brooks_ppt=595 | fangfangtu_notes=595 | fangfangtu_transcript=595
- bundle support family 分布（按补充来源存在计数）：al_brooks_ppt=595 | curated_rule=595 | fangfangtu_notes=595 | fangfangtu_transcript=595
- curated vs statement 命中占比（按受控 trace item 计）：curated=83.3333%， statement=16.6667%

## 7. no-trade / wait 摘要

- 结构化记录总数：6210
- action 分布：no-trade=562 | wait=5648
- reason 分布：context_not_trend=4578 | duplicate_direction_suppressed=218 | insufficient_evidence=852 | risk_blocked_before_fill=562
- 代表性样本：
  - `NVDA` @ 2018-01-04T16:00:00-05:00: wait / insufficient_evidence (bars did not satisfy the placeholder setup body/range/invalidation requirements)
  - `SPY` @ 2018-01-04T16:00:00-05:00: wait / insufficient_evidence (bars did not satisfy the placeholder setup body/range/invalidation requirements)
  - `TSLA` @ 2018-01-04T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `NVDA` @ 2018-01-05T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `TSLA` @ 2018-01-05T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)

## 8. 最好 5 笔交易

- `TSLA` long | pnl=199.7182 | 2018-01-18T16:00:00-05:00 -> 2018-01-22T16:00:00-05:00 | exit=达到固定 2R 目标
- `NVDA` short | pnl=199.6904 | 2018-02-05T16:00:00-05:00 -> 2018-02-05T16:00:00-05:00 | exit=达到固定 2R 目标
- `TSLA` short | pnl=199.5480 | 2018-03-02T16:00:00-05:00 -> 2018-03-27T16:00:00-04:00 | exit=达到固定 2R 目标
- `SPY` long | pnl=198.5600 | 2018-01-08T16:00:00-05:00 -> 2018-01-11T16:00:00-05:00 | exit=达到固定 2R 目标
- `SPY` long | pnl=196.2000 | 2018-01-16T16:00:00-05:00 -> 2018-01-26T16:00:00-05:00 | exit=达到固定 2R 目标

## 9. 最差 5 笔交易

- `NVDA` long | pnl=-99.9492 | 2018-01-23T16:00:00-05:00 -> 2018-02-05T16:00:00-05:00 | exit=触及保护性止损
- `SPY` long | pnl=-99.9400 | 2018-01-23T16:00:00-05:00 -> 2018-02-02T16:00:00-05:00 | exit=触及保护性止损
- `TSLA` long | pnl=-99.8478 | 2018-02-26T16:00:00-05:00 -> 2018-02-28T16:00:00-05:00 | exit=触及保护性止损
- `NVDA` short | pnl=-99.8268 | 2018-03-02T16:00:00-05:00 -> 2018-03-09T16:00:00-05:00 | exit=触及保护性止损
- `SPY` long | pnl=-99.7500 | 2018-02-27T16:00:00-05:00 -> 2018-02-27T16:00:00-05:00 | exit=触及保护性止损

## 10. 代表性交易解释

- `TSLA` long @ 2018-01-18T16:00:00-05:00 -> 2018-01-22T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 10 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md, wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md | wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` short @ 2018-02-05T16:00:00-05:00 -> 2018-02-05T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 22 closed below the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md, wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md | wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` long @ 2018-01-23T16:00:00-05:00 -> 2018-02-05T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 13 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md, wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：触及保护性止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md | wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `SPY` long @ 2018-01-23T16:00:00-05:00 -> 2018-02-02T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 13 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md, wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：触及保护性止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md | wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low

## 11. 风控与未执行样本

- `NVDA` @ 2018-01-30T16:00:00-05:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill. (reason_codes=max_total_exposure_exceeded)
- `SPY` @ 2018-03-12T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `NVDA` @ 2018-03-13T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `SPY` @ 2018-03-20T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `NVDA` @ 2018-03-26T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)

## 12. 结论与局限

- 结论：这轮 `2018-01-01 ~ 2026-04-17` 的 daily public-history validation 在 `NVDA, TSLA, SPY` 上，按当前 demo 风控和历史回测口径，录得 1.5599% 的总收益率。
- 本报告仅用于公共历史数据研究演示，仍处于 paper / simulated 边界，不代表实盘能力或未来收益承诺。
- 当前演示未接入历史新闻时间线，因此 news filter 不参与本轮回测结果。
- 当前 no-trade / wait 只持久化系统能明确解释的 decision sites，不对所有静默 bar 补造结论。
- 当前仍是 daily public-history validation，不模拟 intraday session reset、真实滑点或真实手续费。
