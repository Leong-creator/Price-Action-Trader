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
