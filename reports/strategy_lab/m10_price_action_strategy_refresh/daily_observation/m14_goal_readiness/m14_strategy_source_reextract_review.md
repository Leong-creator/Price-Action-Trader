# M14 Strategy Source Reextract Review

- Generated at: `2026-05-26T14:27:54Z`
- Current stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Challenge: `10/10`
- Review rows: `2`
- Source-backed atoms / answers: `10/6`
- Markdown refs existing / total: `6/6`
- Non-markdown refs pending visual review: `7`
- Future spec draftable / visual-review required: `2/2`
- Create/close/promote/discard/mutate allowed now: `0/0/0/0/0`
- Boundary: source review/spec packet only; no strategy creation, gap closure, broker/live, real orders, paper approval, parameter mutation, or manual M12.37 once-mode.

## Plain Result

Source reextract review produced 2 candidate review packets with 10 source-backed atoms and 6 review answers. 2 future specs are draftable after visual alignment, while 2 still require visual review before any strategy-state decision. The review cannot create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live.

## Review Rows

### M10-PA-003 Tight Channel Trend Continuation

- Review state: `source_review_packet_ready`
- Setup hypothesis: `tight_channel_small_pullback_trend_continuation`
- Future spec readiness: `draftable_after_visual_case_alignment`
- OHLCV proxy state: `partially_ohlcv_approximable`
- Visual review required: `True`
- Visual review reason: PDF/notes refs are present and must be visually checked before future source-reextract spec promotion.

#### Source-Backed Atoms

- `context` from `part1 p987-p992`
  - Rule: Tight channels are treated like higher-timeframe breakouts; when unclear, trade only with the trend.
  - Implementation hint: Use higher-timeframe breakout context and block counter-trend entries in tight-channel state.
- `setup_definition` from `part1 p1398-p1406`
  - Rule: A tight/small-pullback trend has shallow pullbacks, often 1-3 bars, and pullbacks smaller than about two average bars or two to three minimum scalps.
  - Implementation hint: Approximate with pullback depth, pullback bar count, average bar size, and trend-direction persistence.
- `entry_trigger` from `part1 p1006-p1007`
  - Rule: After 20 or more bars above the moving average, the first pullback to the average or first close below it can become a trend-continuation reversal entry.
  - Implementation hint: Model as first MA test or first opposite-side close after a sustained trend gap-bar run.
- `risk_management` from `part1 p1004-p1005`
  - Rule: Correct stops can be far in strong trends; strong traders use wider stops below the last trend leg and trail after new extremes.
  - Implementation hint: Keep position sizing tied to stop distance instead of tightening stops to fit a fixed quantity.
- `invalidation` from `part1 p1000-p1001`
  - Rule: A strong trend can reverse, but it needs stronger contrary evidence such as wedge/MAG failure, all trend-continuation setups failing, and opposite breakout with follow-through.
  - Implementation hint: Require explicit opposite breakout/follow-through before treating tight-channel continuation as failed.

#### Review Answers

- `tight_channel_vs_ordinary_channel`: Tightness is defined by tradeability and pullback size: higher-timeframe breakout behavior, pullbacks around 1-3/1-4 bars, smaller than about two average bars or two to three minimum scalps, and poor counter-trend profitability.
- `minimum_pullback_or_failure_condition`: Continuation weakens when gaps close, pullbacks overlap breakout points, the market shifts toward broad-channel/TR behavior, or opposite breakout/follow-through appears after failed continuation setups.
- `ohlcv_approximation_boundary`: Pullback depth/count, average bar size, MA tests, gap bars, and opposite breakout/follow-through are OHLCV-approximable; channel-quality and example matching still require visual review.

### M10-PA-010 Final Flag or Climax TBTL Reversal

- Review state: `source_review_packet_ready`
- Setup hypothesis: `climax_exhaustion_gap_tbtl_reversal`
- Future spec readiness: `draftable_as_visual_first_dual_route_spec`
- OHLCV proxy state: `visual_first_with_ohlcv_support`
- Visual review required: `True`
- Visual review reason: Climax/final-flag/TBTL reversal needs chart-shape confirmation, and PDF/notes refs remain visual-review inputs.

#### Source-Backed Atoms

- `context` from `part2 p802-p810`
  - Rule: A climax is a late move-ending breakout; most climaxes lead first to a 3-10 bar trading range, not automatically to a new opposite trend.
  - Implementation hint: Mark late-trend acceleration as decision-zone context, not immediate reversal permission.
- `setup_definition` from `part2 p842-p847`
  - Rule: After about 10-20 or 20+ bars, a large trend bar near support/resistance can be either measuring gap or exhaustion gap; follow-through and gap closure decide the label.
  - Implementation hint: Track late trend age, large-body rank, gap/overlap state, and next-bar follow-through before assigning reversal state.
- `entry_trigger` from `part2 p848-p853`
  - Rule: After exhaustion, early counter-trend entries have better reward/risk but lower probability; waiting for strong opposite breakout raises probability with worse reward/risk.
  - Implementation hint: Split future spec into early visual-review entry and confirmed opposite-breakout entry; do not merge them into one trigger.
- `target_management` from `part2 p879-p883`
  - Rule: Consecutive sell climaxes often imply TBTL or trading range, but a final 5-10 bar sell vacuum can still appear before the larger correction.
  - Implementation hint: Require TBTL tracking and allow a final-climax exception before promoting reversal evidence.
- `invalidation` from `part2 p884-p886`
  - Rule: Strong micro-channel pressure means the first reversal can fail; final buy climax can still resolve roughly 50/50 between reversal and trend resumption.
  - Implementation hint: Block promotion unless visual review confirms failed breakout/exhaustion rather than measuring-gap trend continuation.

#### Review Answers

- `climax_final_flag_failed_breakout_boundary`: The reviewed sources support late-trend acceleration, exhaustion gap, failed breakout, TBTL, support/resistance, and final-flag language, but final-flag classification remains visual-first.
- `required_reversal_confirmation`: A climax alone is not enough. Confirmation needs follow-through failure, gap closure or negative gap, support/resistance reaction, or a strong opposite breakout depending on early-versus-confirmed entry route.
- `visual_vs_ohlcv_boundary`: Late trend age, bar count, large-body rank, gaps, follow-through, and TBTL tracking are OHLCV-approximable; wedge/final flag, exhaustion versus measuring-gap interpretation, and failed-breakout quality require visual review.
