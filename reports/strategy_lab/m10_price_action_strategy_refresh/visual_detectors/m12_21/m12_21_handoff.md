```yaml
task_id: M12.21-detector-quality-review
role: main-agent
branch_or_worktree: feature/m12-21-detector-quality-review
objective: 全量复核 M12.20 机器识别候选，并生成抽样图形复核包
status: success
files_changed:
  - scripts/m12_21_detector_quality_review_lib.py
  - scripts/run_m12_21_detector_quality_review.py
  - tests/unit/test_m12_21_detector_quality_review.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_21/*
interfaces_changed: []
commands_run:
  - python scripts/run_m12_21_detector_quality_review.py
tests_run: []
assumptions:
  - 本阶段只复核图形候选结构，不输出策略表现或盈利。
risks:
  - 自动结构复核不等于人工视觉准确率；仍需抽样看图。
qa_focus:
  - 检查全量 ledger 覆盖 M12.20 所有事件，且无真实交易字段。
rollback_notes:
  - 回滚本阶段提交即可撤回 M12.21 复核产物。
next_recommended_action: 查看抽样图形包，决定是否收紧检测器或进入小范围历史回测。
needs_user_decision: false
user_decision_needed: ''
```
