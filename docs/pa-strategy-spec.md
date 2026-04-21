# PA 策略结构规范

## 1. 总原则

- PA context 优先，技术指标只能辅助。
- 所有信号必须可解释，并能追溯到知识库来源或规则版本。
- 早期信号只用于研究、回测和模拟验证，不直接进入实盘。

## 2. Setup 页面应记录的核心字段

- `pa_context`
- `market_cycle`
- `higher_timeframe_context`
- `bar_by_bar_notes`
- `signal_bar`
- `entry_trigger`
- `entry_bar`
- `stop_rule`
- `target_rule`
- `trade_management`
- `measured_move`
- `invalidation`
- `risk_reward_min`

## 3. 结构化信号最小字段

- `signal_id`
- `symbol`
- `market`
- `timeframe`
- `direction`
- `setup_type`
- `pa_context`
- `entry_trigger`
- `stop_rule`
- `target_rule`
- `invalidation`
- `confidence`
- `source_refs`
- `explanation`
- `risk_notes`

## 4. 验证要求

- 新增 setup 必须注明适用市场、周期、方向、入场、止损、目标和失效条件。
- 新增策略逻辑必须配测试、回测样本或模拟验证路径。
- 未经验证的规则不得写成稳定盈利结论。

## 5. Strategy Card 补充要求

位于 `knowledge/wiki/strategy_cards/` 的页面继续使用 wiki frontmatter，但需补齐：

- `strategy_id`
- `source_family`
- `setup_family`
- `market_context`
- `evidence_quality`
- `chart_dependency`
- `needs_visual_review`
- `test_priority`
- `last_updated`

策略卡正文至少包含：

1. 来源依据
2. 核心交易思想
3. 适用市场环境
4. 入场前提
5. 入场触发
6. 止损规则
7. 止盈 / 出场规则
8. 失效条件
9. 禁止交易条件
10. 可量化规则草案
11. 参数范围
12. 回测假设
13. 测试计划
14. 预期失败模式
15. 当前结论

说明：

- 若图表依赖强或证据不足，必须显式保留 `needs_visual_review`、`open_questions` 或 `contradictions`。
- `PA-SC-009`、`PA-SC-010` 这类过滤卡只允许作为 `rule` 类型，不得单独接成 trigger。
