# Intraday Pilot NVDA 15m

本报告仅用于单标的 intraday paper validation，仍处于 `paper / simulated` 边界，不代表 broker/live/real-money 能力。

## 1. 测试范围

- 标的：NVDA (NVIDIA Corporation)
- 市场：US
- 周期：15m
- 时间范围：2026-03-30 ~ 2026-04-16
- 数据来源：yfinance
- 本地缓存：`/home/hgl/projects/Price-Action-Trader/local_data/public_intraday/us_NVDA_15m_2026-03-30_2026-04-16_yfinance.csv`
- 交易时区：America/New_York
- 市场时段：09:30 ~ 16:00
- 交易边界：paper / simulated
- 当前仍未进入期权、broker、live、real-money。

## 2. 核心结果

- 总盈亏：219.8256
- 总收益率：0.8793%
- 最大回撤：0.0000 (0.0000%)
- 交易笔数：2
- 胜率：100.0000%
- 盈亏比（profit factor）：N/A
- 风控拦截信号数：27
- no-trade / wait 结构化记录：310

## 3. Session 质量与重置摘要

- Session 总数：13；用于 pilot：13
- 缺失 bar 总数：0
- 非交易时段 bar 总数：0
- 重复 bar 总数：0

| Session | Bars | Signals | 实际执行 | 风控拦截 | no-trade/wait | reset | 完整 | curated trace | statement trace |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |
| 2026-03-30 | 26/26 | 3 | 1 | 2 | 23 | False | True | 100.0000% | 100.0000% |
| 2026-03-31 | 26/26 | 3 | 1 | 2 | 23 | True | True | 100.0000% | 100.0000% |
| 2026-04-01 | 26/26 | 2 | 0 | 2 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-02 | 26/26 | 1 | 0 | 1 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-06 | 26/26 | 2 | 0 | 2 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-07 | 26/26 | 3 | 0 | 3 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-08 | 26/26 | 3 | 0 | 3 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-09 | 26/26 | 2 | 0 | 2 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-10 | 26/26 | 3 | 0 | 3 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-13 | 26/26 | 3 | 0 | 3 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-14 | 26/26 | 1 | 0 | 1 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-15 | 26/26 | 2 | 0 | 2 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-16 | 26/26 | 1 | 0 | 1 | 24 | True | True | 100.0000% | 100.0000% |

## 4. Knowledge Trace 摘要

- trace 非空占比：100.0000%
- curated trace 覆盖率：100.0000%
- statement 补充覆盖率：100.0000%
- actual hit family 分布：curated_concept=29 | curated_rule=29 | curated_setup=29 | fangfangtu_notes=29
- actual evidence family 分布：al_brooks_ppt=29 | fangfangtu_notes=29 | fangfangtu_transcript=29
- bundle support family 分布：al_brooks_ppt=29 | curated_rule=29 | fangfangtu_notes=29 | fangfangtu_transcript=29
- curated vs statement（按受控 trace item 计）：curated=75.0000%， statement=25.0000%

## 5. no-trade / wait 摘要

- 结构化记录总数：310
- action 分布：no-trade=27 | wait=283
- reason 分布：context_not_trend=242 | duplicate_direction_suppressed=10 | insufficient_evidence=31 | risk_blocked_before_fill=27
- 代表性样本：
  - `NVDA` @ 2026-03-30T10:00:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `NVDA` @ 2026-03-30T10:15:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `NVDA` @ 2026-03-30T10:30:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `NVDA` @ 2026-03-30T10:45:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `NVDA` @ 2026-03-30T11:00:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)

## 6. 代表性交易

- `NVDA` short | 2026-03-30T12:30:00-04:00 -> 2026-03-30T14:45:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 11 closed below the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` long | 2026-03-31T12:45:00-04:00 -> 2026-03-31T15:45:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 12 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：样本结束，按最后收盘价平仓
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` long | 2026-03-31T12:45:00-04:00 -> 2026-03-31T15:45:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar upward progression with rising highs/lows; bar 12 closed above the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：样本结束，按最后收盘价平仓
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `NVDA` short | 2026-03-30T12:30:00-04:00 -> 2026-03-30T14:45:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 11 closed below the prior close with a directional body in a trend context; actual knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md; knowledge trace: concept atom--000c21b0fa567ea4 @ chunk_set[3] | setup atom--339abd6106df72a7 @ chunk_set[4]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  actual refs：wiki:knowledge/wiki/concepts/market-cycle-overview.md | wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md | wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md | wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md
  bundle support：wiki:knowledge/wiki/rules/m3-research-reference-pack.md | wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md | raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf | wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md | raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf | wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md
  trace 摘要：concept atom--000c21b0fa567ea4 @ chunk_set[3] <= fangfangtu_notes@p1b1#f1 / fangfangtu_transcript@p12b1#f2 | setup atom--339abd6106df72a7 @ chunk_set[4] <= fangfangtu_notes@p1b1#f3 / fangfangtu_notes@p3b1#f2 | rule atom--3c72dac9d9d1c67f @ chunk_set[4] <= fangfangtu_notes@p2b1#f2 / fangfangtu_transcript@p12b1#f2
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low

## 7. 风控拦截样本

- `NVDA` @ 2026-03-30T13:30:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.
- `NVDA` @ 2026-03-30T14:30:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.
- `NVDA` @ 2026-03-31T14:00:00-04:00: max_risk_per_order_exceeded。Paper order blocked before simulated fill.
- `NVDA` @ 2026-03-31T14:30:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.
- `NVDA` @ 2026-04-01T13:00:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.

## 8. 结论与局限

- 结论：在 `NVDA 15m`、`2026-03-30 ~ 2026-04-16` 的 regular session pilot 中，系统以 paper/simulated 方式完成了 intraday session、risk reset、duplicate protection、slippage/fee、knowledge trace 的最小验证。
- 当前仍处于 paper / simulated 边界，不代表 broker/live/real-money 能力。
- 当前 intraday pilot 只覆盖 NVDA 15m regular session，不包含期权、不包含多标的并发。
- statement / source_note 仍只进入 knowledge_trace，不参与 trigger。
- 当前滑点/手续费模型是最小可配置研究模型，不是实盘成交真实性证明。
