# M12.4 Handoff

```yaml
task_id: m12-4-definition-fix-and-retest
role: main_agent
branch_or_worktree: codex/m12-4-definition-fix-and-retest
objective: 复用 M10.9 的 M10-PA-005 before/after 复测结果，并把 M10-PA-004/007 的图形证据转成可执行定义字段缺口，不伪造交易结果。
status: success
files_changed:
  - config/examples/m12_definition_fix_and_retest.json
  - scripts/m12_definition_fix_and_retest_lib.py
  - scripts/run_m12_definition_fix_and_retest.py
  - tests/unit/test_m12_definition_fix_and_retest.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_definition_fix_summary.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_before_after_metrics.csv
  - reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_definition_fix_report.md
  - reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_retest_client_summary.md
  - reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_handoff.md
  - docs/status.md
  - plans/active-plan.md
  - reports/strategy_lab/README.md
interfaces_changed: []
commands_run:
  - python scripts/run_m12_definition_fix_and_retest.py
  - python scripts/validate_kb.py
  - python scripts/validate_kb_coverage.py
  - python scripts/validate_knowledge_atoms.py
  - python -m unittest tests/unit/test_m12_definition_fix_and_retest.py tests/unit/test_m12_visual_review_precheck.py tests/unit/test_m12_core_daily_observation.py -v
  - python -m unittest discover -s tests/unit -v
  - python -m unittest discover -s tests/reliability -v
  - git diff --check
tests_run:
  - M12.4 单测通过，覆盖 scope、M10-PA-005 指标完整性、M10-PA-004/007 未复测、source lineage、只读边界。
  - M12 相关专项单测通过。
  - 全量 unit 与 reliability 套件通过。
assumptions:
  - M12.4 允许复用 M10.9、M10.10、M12.3 的 clean-room artifacts。
  - M10-PA-004/007 在缺少可执行字段前不得输出 before/after 交易指标。
risks:
  - M10-PA-005 仍缺 range geometry 持久化字段，因此不能解除 needs_definition_fix。
  - M10-PA-004/007 仍需后续 detector/spec 层补字段后才能复测。
qa_focus:
  - M12.4 输出仅覆盖 M10-PA-005/004/007。
  - M10-PA-005 的 before/after 指标均回指 M10.9 artifact。
  - M10-PA-004/007 只有字段缺口，不得被解释为已完成复测。
  - paper_trading_approval=false, broker_connection=false, real_orders=false, live_execution=false。
rollback_notes:
  - 回退本阶段可 revert M12.4 commit；未触碰 src/broker、src/execution、src/risk 或 raw 资料。
next_recommended_action: 从 main 切 M12.5 Liquid Universe Scanner 分支，第一版只接 Tier A 的 M10-PA-001/002/012。
needs_user_decision: false
user_decision_needed:
```
