# M14 Strategy Source Reextract Plan

- Generated at: `2026-05-26T13:25:00Z`
- Current stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Challenge: `10/10`
- Source reextract plan rows: `7`
- Future source-reextract candidates: `2`
- Research/support/external holds: `2/2/1`
- Source-review tasks/questions: `16/16`
- Create/close/promote/discard/mutate allowed now: `0/0/0/0/0`
- Boundary: source reextract planning only; no strategy creation, gap closure, broker/live, real orders, paper approval, parameter mutation, or manual M12.37 once-mode.

## Plain Result

Source reextract plan tracks 7 source-triage rows. 2 rows are future source-reextract candidates, 2 remain research-only holds, 2 are supporting-only attachments, and 1 are external-reference holds. The plan has 16 source-review tasks and 16 review questions. It cannot create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live.

## Plan Rows

### P2 M10-PA-003

- State: `future_source_reextract_candidate`
- Route: `original_source_and_visual_packet_review`
- Catalog title: `Tight Channel Trend Continuation`
- Source families: `brooks_v2_manual_transcript, fangfangtu_youtube_transcript, fangfangtu_notes`
- Future source-reextract spec allowed to draft: `True`
- Can create/close/promote/discard/mutate now: `False/False/False/False/False`
- Tasks:
  - Re-read Brooks tight-channel and small-pullback trend units for independent setup context, signal bar, entry, stop, and target candidates.
  - Recheck Fangfangtu channel refs and notes for visual examples; keep missing charts explicit when unavailable.
  - Decide whether a future source-reextract spec can separate this setup from generic trend filter or ranking logic.
- Questions:
  - Which bars define a tight channel versus an ordinary channel in the source material?
  - What minimum pullback size or failure condition invalidates the trend-continuation read?
  - Which visual examples can be approximated from OHLCV without chart-image confirmation?

### P2 M10-PA-010

- State: `future_source_reextract_candidate`
- Route: `original_source_and_visual_packet_review`
- Catalog title: `Final Flag or Climax TBTL Reversal`
- Source families: `brooks_v2_manual_transcript, fangfangtu_youtube_transcript, fangfangtu_notes`
- Future source-reextract spec allowed to draft: `True`
- Can create/close/promote/discard/mutate now: `False/False/False/False/False`
- Tasks:
  - Re-read Brooks climax, final-flag, and TBTL refs for reversal trigger versus failed-breakout boundaries.
  - Recheck Fangfangtu climax/exhaustion refs and notes for visual examples; separate final flag from generic exhaustion language.
  - Decide whether a future source-reextract spec can be OHLCV-proxied or must remain visual-review first.
- Questions:
  - Where do the sources separate climax, final flag, failed breakout, and TBTL reversal language?
  - What confirmation must appear before any reversal entry is considered?
  - Which examples require visual confirmation rather than OHLCV-only approximation?

### P2 M10-PA-006

- State: `research_only_hold_no_reextract`
- Route: `research_definition_hold`
- Catalog title: `Trading Range BLSHS Limit-Order Framework`
- Source families: `brooks_v2_manual_transcript, fangfangtu_youtube_transcript, fangfangtu_notes`
- Future source-reextract spec allowed to draft: `False`
- Can create/close/promote/discard/mutate now: `False/False/False/False/False`
- Tasks:
  - Keep as research-only until bounded-risk, range maturity, and cost/slippage definitions are frozen.
  - Do not draft a standalone source-reextract spec from risk framework language alone.
- Questions:
  - What concrete setup trigger is missing beyond risk or position-management language?
  - What fresh evidence would make this more than a research-only framework?

### P2 M10-PA-016

- State: `research_only_hold_no_reextract`
- Route: `research_definition_hold`
- Catalog title: `Trading Range Scaling-In Research`
- Source families: `brooks_v2_manual_transcript, fangfangtu_youtube_transcript, fangfangtu_notes`
- Future source-reextract spec allowed to draft: `False`
- Can create/close/promote/discard/mutate now: `False/False/False/False/False`
- Tasks:
  - Keep as research-only until bounded-risk, range maturity, and cost/slippage definitions are frozen.
  - Do not draft a standalone source-reextract spec from risk framework language alone.
- Questions:
  - What concrete setup trigger is missing beyond risk or position-management language?
  - What fresh evidence would make this more than a research-only framework?

### P2 M10-PA-014

- State: `supporting_rule_no_standalone_reextract`
- Route: `attach_to_parent_setup_only`
- Catalog title: `Measured Move Target Engine`
- Source families: `brooks_v2_manual_transcript`
- Future source-reextract spec allowed to draft: `False`
- Can create/close/promote/discard/mutate now: `False/False/False/False/False`
- Tasks:
  - Attach as target, stop, or sizing support to parent setups during future source review.
  - Do not draft a standalone strategy spec unless a separate source-backed setup emerges later.
- Questions:
  - Which parent setup should consume this target, stop, or sizing rule?
  - Can the supporting rule be tested only as an attachment rather than a standalone strategy?

### P2 M10-PA-015

- State: `supporting_rule_no_standalone_reextract`
- Route: `attach_to_parent_setup_only`
- Catalog title: `Protective Stops and Position Sizing`
- Source families: `brooks_v2_manual_transcript, fangfangtu_youtube_transcript, fangfangtu_notes`
- Future source-reextract spec allowed to draft: `False`
- Can create/close/promote/discard/mutate now: `False/False/False/False/False`
- Tasks:
  - Attach as target, stop, or sizing support to parent setups during future source review.
  - Do not draft a standalone strategy spec unless a separate source-backed setup emerges later.
- Questions:
  - Which parent setup should consume this target, stop, or sizing rule?
  - Can the supporting rule be tested only as an attachment rather than a standalone strategy?

### P2 AI-TRADER-EXTERNAL

- State: `external_reference_hold`
- Route: `local_source_required_before_reextract`
- Catalog title: ``
- Source families: ``
- Future source-reextract spec allowed to draft: `False`
- Can create/close/promote/discard/mutate now: `False/False/False/False/False`
- Tasks:
  - Keep as external architecture/reference input only.
  - Require local source refs before any local source-reextract task can be opened.
- Questions:
  - Which local Brooks or Fangfangtu source refs would be required before this becomes a local task?
  - Which parts are architecture inspiration only and must not override local evidence gates?
