# M12.3 Visual Gate Recommendation

- M12.3 does not close manual review.
- M10-PA-008 / M10-PA-009 remain the priority visual-review candidates.
- M10-PA-004 / M10-PA-007 remain definition-fix support, not ready queue items.
- M10-PA-013 is a pre-existing Wave B candidate without visual pack.

| strategy | recommendation | reason |
|---|---|---|
| M10-PA-008 | `prepare_user_visual_review` | major trend reversal can be approximated with prior trend, trend break, test, and reversal confirmation. |
| M10-PA-009 | `prepare_user_visual_review` | wedge can be approximated by three pushes using swing pivots, but drawn wedge quality remains a review risk. |
| M10-PA-003 | `watchlist_after_priority_cases` | tight channel can be approximated with consecutive directional closes, small pullbacks, and channel-break disqualifiers. |
| M10-PA-011 | `watchlist_after_priority_cases` | opening reversal can be approximated with session open anchors, gap/opening context, and early reversal confirmation. |
| M10-PA-013 | `keep_pre_existing_wave_b_candidate_separate` | M10.10 carried this strategy as an existing Wave B candidate without a visual pack. |
| M10-PA-004 | `use_cases_for_definition_fix_only` | broad channel boundary depends on drawn channel line quality and boundary tests that are not yet encoded. |
| M10-PA-007 | `use_cases_for_definition_fix_only` | second-leg trap needs range edge, first leg, second leg, and trap confirmation fields before reliable backtest. |

## Boundary

- paper_trading_approval=false
- broker_connection=false
- real_orders=false
- live_execution=false
