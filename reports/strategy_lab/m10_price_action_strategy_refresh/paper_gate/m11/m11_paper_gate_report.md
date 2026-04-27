# M11 Paper Gate Report

## Gate Decision

- decision: `not_approved`
- paper trading 继续关闭。
- broker connection、real account、live execution 和 real orders 继续禁用。
- 当前没有任何候选策略可作为 paper trading approval evidence。

## 候选分级

- Tier A 核心观察候选：`M10-PA-001 / M10-PA-002 / M10-PA-012`。
- Tier B 视觉条件候选：`M10-PA-008 / M10-PA-009`，必须先完成人工图形语境复核。
- Tier C/D/E 策略只保留在 watchlist、definition-fix、supporting 或 research-only 路径。

## 候选策略

| Strategy | Timeframes | Client Tier | Evidence Status | Blockers |
|---|---|---|---|---|
| M10-PA-001 | `1d / 15m / 5m` | tier_a_core_after_read_only_observation | not_evidence_until_real_read_only_observation_is_reviewed | `no_completed_real_read_only_observation_window / no_human_business_approval_for_paper_trading` |
| M10-PA-002 | `1d / 1h / 15m` | tier_a_core_after_read_only_observation | not_evidence_until_real_read_only_observation_is_reviewed | `no_completed_real_read_only_observation_window / no_human_business_approval_for_paper_trading` |
| M10-PA-012 | `15m / 5m` | tier_a_core_after_read_only_observation | not_evidence_until_real_read_only_observation_is_reviewed | `no_completed_real_read_only_observation_window / no_human_business_approval_for_paper_trading` |
| M10-PA-008 | `1h / 15m / 5m` | tier_b_conditional_visual_after_review | not_evidence_until_read_only_observation_and_manual_visual_review_are_closed | `no_completed_real_read_only_observation_window / no_human_business_approval_for_paper_trading / manual_visual_context_review_required` |
| M10-PA-009 | `1h / 15m` | tier_b_conditional_visual_after_review | not_evidence_until_read_only_observation_and_manual_visual_review_are_closed | `no_completed_real_read_only_observation_window / no_human_business_approval_for_paper_trading / manual_visual_context_review_required` |

## 候选风险点

- `M10-PA-001`: 历史模拟收益为正，但回撤金额较高，且 1h reserve 为负；进入任何后续 gate 前必须先观察回撤和连续亏损。
- `M10-PA-002`: 历史模拟优势较薄，且 5m reserve 为负；只适合作为观察候选，不可直接批准 paper trading。
- `M10-PA-012`: 只覆盖 15m / 5m 开盘区间场景；15m 仍保留 derived_from_5m lineage，需要按 bar-close 节奏复核。
- `M10-PA-008`: 视觉语境策略，必须完成人工图形复核；1d reserve 为负，不能把 OHLCV proxy 结果直接当作 gate evidence。
- `M10-PA-009`: 正收益幅度最弱，reserve 负周期为 1d / 5m；必须先完成视觉复核和只读观察。

## 为什么不批准

- `no_completed_real_read_only_observation_window`
- `no_human_business_approval_for_paper_trading`
- `visual_context_review_still_required_for_visual_candidates`
- `broker_connection_and_order_path_must_remain_disabled`

## 后续 Gate 条件

- 先按 M10.13 runbook 完成至少一个真实只读观察复核窗口。
- 对视觉候选策略完成人工图形语境复核。
- 逐条检查暂停红线，任何 pause condition 命中都继续关闭 gate。
- 确认候选策略没有因暂停条件被降级。
- 在任何 paper trading 设置前取得明确人工业务审批。

## 边界

本报告只准备 gate review，不批准 paper trading，也不授权任何订单路径。
