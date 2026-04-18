# Public History Long-Horizon Daily Validation

本报告仅用于公共历史数据研究演示，仍处于 paper / simulated 边界，不代表实盘能力或未来收益承诺。

## 1. 本次测试范围

- 标的：NVDA, TSLA, SPY
- 时间范围：2020-01-01 ~ 2025-12-31 (1d)
- 数据来源：yfinance
- 本地缓存目录：`/home/hgl/projects/Price-Action-Trader-m8d1-artifact-trace-unification/local_data/public_history`
- 报告目录：`/home/hgl/projects/Price-Action-Trader-m8d1-artifact-trace-unification/reports/backtests/m8c1_long_horizon_daily_validation`
- 现金口径说明：本次现金口径按 USD demo sizing 统计，因为本轮只选择了 US 标的。
- Walk-forward 切分：In-sample, Validation, Out-of-sample
- Regime 分层：2020 高波动下跌, 2020H2-2021 上升趋势, 2022 宏观回撤, 2023 恢复与轮动, 2024-2025 AI 动量与区间切换

## 2. 核心结果

- 总盈亏：-22.8695
- 总收益率：-0.0915%
- 最大回撤：398.3296 (1.5697%)
- 交易笔数：12
- 胜率：33.3333%
- 盈亏比（profit factor）：0.9712
- 风控拦截信号数：396
- no-trade / wait 结构化记录：4486

## 3. 分标的摘要

| 标的 | 角色 | 数据源 | Bars | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NVDA | 高贝塔成长趋势段 | yfinance | 1507 | 138 | 4 | 131 | 1498 | -99.8257 | 25.0000% | 100.0000% | 100.0000% |
| TSLA | 高波动震荡/反复段 | yfinance | 1507 | 130 | 4 | 123 | 1498 | 197.6562 | 50.0000% | 100.0000% | 100.0000% |
| SPY | 指数基准与相对稳态段 | yfinance | 1507 | 157 | 4 | 142 | 1490 | -120.7000 | 25.0000% | 100.0000% | 100.0000% |

## 4. Walk-forward / Split 摘要

| 名称 | 区间 | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| In-sample | 2020-01-01 ~ 2021-12-31 | 121 | 12 | 109 | 1489 | -22.8695 | 33.3333% | 100.0000% | 100.0000% |
| Validation | 2022-01-01 ~ 2023-12-31 | 154 | 0 | 154 | 1499 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| Out-of-sample | 2024-01-01 ~ 2025-12-31 | 133 | 0 | 133 | 1498 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |

## 5. Regime 分层摘要

| 名称 | 区间 | Signals | 实际执行 | 风控拦截 | no-trade/wait | 累计盈亏 | 胜率 | curated trace | statement trace |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020 高波动下跌 | 2020-02-01 ~ 2020-05-31 | 15 | 8 | 7 | 234 | 78.8475 | 37.5000% | 100.0000% | 100.0000% |
| 2020H2-2021 上升趋势 | 2020-06-01 ~ 2021-12-31 | 101 | 0 | 101 | 1202 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 2022 宏观回撤 | 2022-01-01 ~ 2022-12-31 | 80 | 0 | 80 | 752 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 2023 恢复与轮动 | 2023-01-01 ~ 2023-12-31 | 74 | 0 | 74 | 747 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 2024-2025 AI 动量与区间切换 | 2024-01-01 ~ 2025-12-31 | 133 | 0 | 133 | 1498 | 0.0000 | 0.0000% | 100.0000% | 100.0000% |
| 未落入显式窗口 | 2020-02-01 ~ 2025-12-31 | 5 | 4 | 1 | 53 | -101.7170 | 25.0000% | 100.0000% | 100.0000% |

## 6. Knowledge Trace 覆盖率摘要

- 发出信号总数：425；trace 非空占比：100.0000%
- 含 curated trace 的信号占比：100.0000%；含 statement 补充证据的信号占比：100.0000%
- actual hit family 分布（按 visible trace 的信号存在计数）：curated_concept=425 | curated_rule=425 | curated_setup=425 | fangfangtu_notes=425
- actual evidence family 分布（按 visible trace 命中的证据家族计数）：al_brooks_ppt=425 | fangfangtu_notes=425 | fangfangtu_transcript=425
- bundle support family 分布（按补充来源存在计数）：al_brooks_ppt=425 | curated_rule=425 | fangfangtu_notes=425 | fangfangtu_transcript=425
- curated vs statement 命中占比（按受控 trace item 计）：curated=75.0000%， statement=25.0000%

## 7. no-trade / wait 摘要

- 结构化记录总数：4486
- action 分布：no-trade=396 | wait=4090
- reason 分布：context_not_trend=3297 | duplicate_direction_suppressed=170 | insufficient_evidence=623 | risk_blocked_before_fill=396
- 代表性样本：
  - `NVDA` @ 2020-01-06T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `SPY` @ 2020-01-06T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `TSLA` @ 2020-01-06T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `NVDA` @ 2020-01-07T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `SPY` @ 2020-01-07T16:00:00-05:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)

## 8. 最好 5 笔交易

- `NVDA` long | pnl=199.9360 | 2020-02-13T16:00:00-05:00 -> 2020-02-14T16:00:00-05:00 | exit=达到固定 2R 目标
- `TSLA` short | pnl=197.6000 | 2020-02-26T16:00:00-05:00 -> 2020-02-28T16:00:00-05:00 | exit=达到固定 2R 目标
- `TSLA` long | pnl=196.3194 | 2020-01-09T16:00:00-05:00 -> 2020-01-22T16:00:00-05:00 | exit=达到固定 2R 目标
- `SPY` short | pnl=177.3800 | 2020-02-24T16:00:00-05:00 -> 2020-02-27T16:00:00-05:00 | exit=达到固定 2R 目标
- `TSLA` long | pnl=-97.7389 | 2020-02-04T16:00:00-05:00 -> 2020-02-27T16:00:00-05:00 | exit=触及保护性止损

## 9. 最差 5 笔交易

- `SPY` short | pnl=-99.9600 | 2020-03-13T16:00:00-04:00 -> 2020-03-13T16:00:00-04:00 | exit=同一根 bar 内先触发止损
- `NVDA` short | pnl=-99.9498 | 2020-02-26T16:00:00-05:00 -> 2020-03-03T16:00:00-05:00 | exit=触及保护性止损
- `NVDA` long | pnl=-99.9164 | 2020-01-14T16:00:00-05:00 -> 2020-01-14T16:00:00-05:00 | exit=触及保护性止损
- `NVDA` short | pnl=-99.8955 | 2020-03-13T16:00:00-04:00 -> 2020-03-13T16:00:00-04:00 | exit=触及保护性止损
- `SPY` long | pnl=-99.1200 | 2020-01-10T16:00:00-05:00 -> 2020-01-10T16:00:00-05:00 | exit=触及保护性止损

## 10. 代表性交易解释

- `NVDA` long @ 2020-02-13T16:00:00-05:00 -> 2020-02-14T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 28 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `TSLA` short @ 2020-02-26T16:00:00-05:00 -> 2020-02-28T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 36 closed below the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `SPY` short @ 2020-03-13T16:00:00-04:00 -> 2020-03-13T16:00:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 48 closed below the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：同一根 bar 内先触发止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` short @ 2020-02-26T16:00:00-05:00 -> 2020-03-03T16:00:00-05:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 36 closed below the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：触及保护性止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low

## 11. 风控与未执行样本

- `NVDA` @ 2020-01-16T16:00:00-05:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill. (reason_codes=max_total_exposure_exceeded)
- `SPY` @ 2020-03-27T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `TSLA` @ 2020-04-14T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `NVDA` @ 2020-04-22T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)
- `TSLA` @ 2020-04-22T16:00:00-04:00: 连续亏损达到 demo 风控暂停阈值。Paper order blocked before simulated fill. (reason_codes=consecutive_losses_limit)

## 12. 结论与局限

- 结论：这轮 `2020-01-01 ~ 2025-12-31` 的 daily public-history validation 在 `NVDA, TSLA, SPY` 上，按当前 demo 风控和历史回测口径，录得 -0.0915% 的总收益率。
- 本报告仅用于公共历史数据研究演示，仍处于 paper / simulated 边界，不代表实盘能力或未来收益承诺。
- 当前演示未接入历史新闻时间线，因此 news filter 不参与本轮回测结果。
- 当前 no-trade / wait 只持久化系统能明确解释的 decision sites，不对所有静默 bar 补造结论。
- 当前仍是 daily public-history validation，不模拟 intraday session reset、真实滑点或真实手续费。
