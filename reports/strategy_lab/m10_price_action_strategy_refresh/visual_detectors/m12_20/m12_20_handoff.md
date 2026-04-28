```yaml
task_id: M12.20-visual-detector-implementation
role: main-agent
branch_or_worktree: feature/m12-20-visual-detector-implementation
objective: 实现 M10-PA-004/007 机器识别检测器，并把 M10/M12 策略合并成统一队列
status: success
files_changed:
  - scripts/m12_20_visual_detector_implementation_lib.py
  - scripts/run_m12_20_visual_detector_implementation.py
  - tests/unit/test_m12_20_visual_detector_implementation.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_20/*
interfaces_changed: []
commands_run:
  - python scripts/run_m12_20_visual_detector_implementation.py
tests_run: []
assumptions:
  - 第一版检测器先使用 1d 长窗口缓存，不把当前单日5m伪装成长历史日内测试。
risks:
  - 检测器事件只是候选图形，不是交易信号，也不是盈利结论。
qa_focus:
  - 检查 M10-PA-004/007 是否只输出候选图形，不输出真实交易字段。
rollback_notes:
  - 回滚本阶段提交即可撤回检测器实现和 m12_20 产物。
next_recommended_action: 抽样检查候选图形稳定性，稳定后再决定是否做历史回测。
needs_user_decision: false
user_decision_needed: ''
```

本次检测器事件数：4801。
