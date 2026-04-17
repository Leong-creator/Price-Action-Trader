# Intraday Pilot SPY 15m

本报告仅用于单标的 intraday paper validation，仍处于 `paper / simulated` 边界，不代表 broker/live/real-money 能力。

## 1. 测试范围

- 标的：SPY (SPDR S&P 500 ETF)
- 市场：US
- 周期：15m
- 时间范围：2026-03-30 ~ 2026-04-16
- 数据来源：yfinance
- 本地缓存：`/home/hgl/projects/Price-Action-Trader/local_data/public_intraday/us_SPY_15m_2026-03-30_2026-04-16_yfinance.csv`
- 交易时区：America/New_York
- 市场时段：09:30 ~ 16:00
- 交易边界：paper / simulated
- 当前仍未进入期权、broker、live、real-money。

## 2. 核心结果

- 总盈亏：20.7883
- 总收益率：0.0832%
- 最大回撤：246.7056 (0.9789%)
- 交易笔数：25
- 胜率：48.0000%
- 盈亏比（profit factor）：1.0353
- 风控拦截信号数：8
- no-trade / wait 结构化记录：285

## 3. Session 质量与重置摘要

- Session 总数：13；用于 pilot：13
- 缺失 bar 总数：0
- 非交易时段 bar 总数：0
- 重复 bar 总数：0

| Session | Bars | Signals | 实际执行 | 风控拦截 | no-trade/wait | reset | 完整 | curated trace | statement trace |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |
| 2026-03-30 | 26/26 | 4 | 2 | 1 | 21 | False | True | 100.0000% | 100.0000% |
| 2026-03-31 | 26/26 | 3 | 2 | 1 | 22 | True | True | 100.0000% | 100.0000% |
| 2026-04-01 | 26/26 | 2 | 2 | 0 | 22 | True | True | 100.0000% | 100.0000% |
| 2026-04-02 | 26/26 | 3 | 1 | 2 | 23 | True | True | 100.0000% | 100.0000% |
| 2026-04-06 | 26/26 | 1 | 1 | 0 | 23 | True | True | 100.0000% | 100.0000% |
| 2026-04-07 | 26/26 | 3 | 3 | 0 | 21 | True | True | 100.0000% | 100.0000% |
| 2026-04-08 | 26/26 | 5 | 2 | 2 | 21 | True | True | 100.0000% | 100.0000% |
| 2026-04-09 | 26/26 | 1 | 0 | 1 | 24 | True | True | 100.0000% | 100.0000% |
| 2026-04-10 | 26/26 | 1 | 1 | 0 | 23 | True | True | 100.0000% | 100.0000% |
| 2026-04-13 | 26/26 | 3 | 3 | 0 | 21 | True | True | 100.0000% | 100.0000% |
| 2026-04-14 | 26/26 | 3 | 3 | 0 | 21 | True | True | 100.0000% | 100.0000% |
| 2026-04-15 | 26/26 | 3 | 2 | 1 | 22 | True | True | 100.0000% | 100.0000% |
| 2026-04-16 | 26/26 | 3 | 3 | 0 | 21 | True | True | 100.0000% | 100.0000% |

## 4. Knowledge Trace 摘要

- trace 非空占比：100.0000%
- curated trace 覆盖率：100.0000%
- statement 补充覆盖率：100.0000%
- source family 分布：curated_concept=35 | curated_rule=35 | curated_setup=35 | fangfangtu_notes=35
- curated vs statement（按受控 trace item 计）：curated=75.0000%， statement=25.0000%

## 5. no-trade / wait 摘要

- 结构化记录总数：285
- action 分布：no-trade=8 | wait=277
- reason 分布：context_not_trend=236 | duplicate_direction_suppressed=7 | insufficient_evidence=34 | risk_blocked_before_fill=8
- 代表性样本：
  - `SPY` @ 2026-03-30T10:00:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `SPY` @ 2026-03-30T10:15:00-04:00: wait / context_not_trend (recent closes are compressed into a narrow range)
  - `SPY` @ 2026-03-30T10:30:00-04:00: wait / context_not_trend (recent closes are compressed into a narrow range)
  - `SPY` @ 2026-03-30T10:45:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)
  - `SPY` @ 2026-03-30T11:00:00-04:00: wait / context_not_trend (recent bars do not show a stable trend or tight trading range)

## 6. 代表性交易

- `SPY` short | 2026-03-30T12:30:00-04:00 -> 2026-03-30T14:15:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 11 closed below the prior close with a directional body in a trend context; knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/m3-research-reference-pack.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf, wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md, wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md; knowledge trace: concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  trace 摘要：concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3] | rule atom--74317e517ebf045c @ chunk_set[5472]
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `SPY` short | 2026-03-30T14:30:00-04:00 -> 2026-03-30T15:15:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 19 closed below the prior close with a directional body in a trend context; knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/m3-research-reference-pack.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf, wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md, wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md; knowledge trace: concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3]
  出场原因：达到固定 2R 目标
  setup/context：`signal_bar_entry_placeholder` / `trend`
  trace 摘要：concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3] | rule atom--74317e517ebf045c @ chunk_set[5472]
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `SPY` short | 2026-04-06T13:15:00-04:00 -> 2026-04-06T13:30:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 14 closed below the prior close with a directional body in a trend context; knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/m3-research-reference-pack.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf, wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md, wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md; knowledge trace: concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3]
  出场原因：触及保护性止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  trace 摘要：concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3] | rule atom--74317e517ebf045c @ chunk_set[5472]
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low
- `SPY` short | 2026-03-31T11:00:00-04:00 -> 2026-03-31T11:00:00-04:00
  进场原因：research-only placeholder setup triggered after three-bar downward progression with falling highs/lows; bar 5 closed below the prior close with a directional body in a trend context; knowledge refs: wiki:knowledge/wiki/concepts/market-cycle-overview.md, wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md, wiki:knowledge/wiki/rules/m3-research-reference-pack.md, wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf, wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md, raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf, wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md, wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md; knowledge trace: concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3]
  出场原因：触及保护性止损
  setup/context：`signal_bar_entry_placeholder` / `trend`
  trace 摘要：concept atom--261e09f9bda3f305 @ chunk_set[3] | setup atom--6b61cdba4d56f0ff @ chunk_set[3] | rule atom--74317e517ebf045c @ chunk_set[5472]
  risk_notes：research-only placeholder setup; not validated for live trading | knowledge page is draft/placeholder, so confidence is intentionally low

## 7. 风控拦截样本

- `SPY` @ 2026-03-30T15:15:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.
- `SPY` @ 2026-03-31T12:45:00-04:00: max_risk_per_order_exceeded。Paper order blocked before simulated fill.
- `SPY` @ 2026-04-02T12:30:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.
- `SPY` @ 2026-04-02T14:00:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.
- `SPY` @ 2026-04-08T13:00:00-04:00: 总曝险超过 demo 风控上限。Paper order blocked before simulated fill.

## 8. 结论与局限

- 结论：在 `SPY 15m`、`2026-03-30 ~ 2026-04-16` 的 regular session pilot 中，系统以 paper/simulated 方式完成了 intraday session、risk reset、duplicate protection、slippage/fee、knowledge trace 的最小验证。
- 当前仍处于 paper / simulated 边界，不代表 broker/live/real-money 能力。
- 当前 intraday pilot 只覆盖 SPY 15m regular session，不包含期权、不包含多标的并发。
- statement / source_note 仍只进入 knowledge_trace，不参与 trigger。
- 当前滑点/手续费模型是最小可配置研究模型，不是实盘成交真实性证明。
