# M12.9 User Visual Review Packet

本包只要求用户复核优先级最高的 `M10-PA-008 / M10-PA-009` 关键图例。
Agent 已预审图例存在性、checksum、Brooks source refs 和图形语义，但这些预审不能替代用户视觉确认。

- 需用户复核 case 数：`10`
- 当前不批准 paper trading；所有 case 的 `paper_gate_evidence_now=false`。

| strategy | case | type | agent decision | why review | image logical path |
|---|---|---|---|---|---|
| M10-PA-008 | M10-PA-008-positive-001 | positive | `pass` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_022A/part2_p0478_crop.webp` |
| M10-PA-008 | M10-PA-008-positive-002 | positive | `pass` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_022A/part2_p0467_crop.webp` |
| M10-PA-008 | M10-PA-008-positive-003 | positive | `pass` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_022D/part2_p0517_crop.webp` |
| M10-PA-008 | M10-PA-008-counterexample-001 | counterexample | `pass_as_counterexample` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_021A/part2_p0371_crop.webp` |
| M10-PA-008 | M10-PA-008-boundary-001 | boundary | `ambiguous` | boundary / ambiguous visual context | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_022A/part2_p0465_crop.webp` |
| M10-PA-009 | M10-PA-009-positive-001 | positive | `pass` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_024B/part2_p0583_crop.webp` |
| M10-PA-009 | M10-PA-009-positive-002 | positive | `pass` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_024A/part2_p0576_crop.webp` |
| M10-PA-009 | M10-PA-009-positive-003 | positive | `pass` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_024A/part2_p0567_crop.webp` |
| M10-PA-009 | M10-PA-009-counterexample-001 | counterexample | `pass_as_counterexample` | priority strategy gate confirmation | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_024A/part2_p0575_crop.webp` |
| M10-PA-009 | M10-PA-009-boundary-001 | boundary | `ambiguous` | boundary / ambiguous visual context | `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets/evidence/video_024A/part2_p0573_crop.webp` |

## 用户确认口径

- `pass`：图例确实符合策略关键几何语义。
- `fail`：图例不应支持该策略，后续必须降级或重选图例。
- `ambiguous`：图例需要更多上下文；不得作为 gate evidence。
