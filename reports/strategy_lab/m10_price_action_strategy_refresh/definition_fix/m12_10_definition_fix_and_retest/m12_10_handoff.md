task_id: M12.10 Definition Fix and Retest
role: main_agent
branch_or_worktree: feature/m12-10-definition-fix-and-retest
objective: Persist M10-PA-005 range geometry fields, reuse traceable retest metrics, and formally downgrade M10-PA-004/007 when executable labels are absent.
status: success
files_changed:
  - README.md
  - docs/acceptance.md
  - docs/status.md
  - plans/active-plan.md
  - reports/strategy_lab/README.md
  - config/examples/m12_10_definition_fix_and_retest.json
  - scripts/m12_10_definition_fix_retest_lib.py
  - scripts/run_m12_10_definition_fix_retest.py
  - tests/unit/test_m12_10_definition_fix_retest.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest/
interfaces_changed:
  - Added M12.10 definition fix artifacts and runner.
commands_run:
  - python scripts/run_m12_10_definition_fix_retest.py
tests_run:
  - python scripts/validate_kb.py
  - python scripts/validate_kb_coverage.py
  - python scripts/validate_knowledge_atoms.py
  - python -m unittest tests/unit/test_m12_10_definition_fix_retest.py -v
  - python -m unittest tests/unit/test_m12_definition_fix_and_retest.py -v
  - python -m unittest discover -s tests/unit -v
  - python -m unittest discover -s tests/reliability -v
  - git diff --check
assumptions:
  - M10-PA-005 retest metrics remain sourced from M10.9; M12.10 adds geometry field persistence and decision clarity.
  - M10-PA-005 event_id is row-level for each distinct failed-breakout geometry candidate, not signal-level.
  - M10-PA-004/007 cannot be honestly retested without manual labels or a new detector.
risks:
  - M10-PA-005 remains reject_for_now after geometry review; do not route it into automatic observation.
qa_focus:
  - Confirm M10-PA-005 geometry fields are present.
  - Confirm M10-PA-004/007 have no fake trade metrics.
  - Confirm M10-PA-008/009 remain excluded from paper gate evidence.
rollback_notes:
  - Revert M12.10 commit or remove reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest artifacts.
next_recommended_action: Continue M12.11 read-only trading dashboard and keep M12.8 cache fetch plan as a separate controlled data task.
needs_user_decision: false
user_decision_needed:
summary:
  pa005_geometry_event_count: 34651
  pa005_decision: reject_for_now_after_geometry_review
  visual_definition_decisions: {'M10-PA-004': 'visual_only_not_backtestable_without_manual_labels', 'M10-PA-007': 'visual_only_not_backtestable_without_manual_labels'}
