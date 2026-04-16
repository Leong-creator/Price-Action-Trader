# Subagent Handoff Protocol

所有 subagent 完成任务后，必须用下面格式交接。主 agent、reviewer、qa 必须读取该交接信息。

## 1. 标准交接格式

```yaml
task_id:
role:
branch_or_worktree:
objective:
status: success | partial | failed | blocked
files_changed: []
interfaces_changed: []
commands_run: []
tests_run: []
assumptions: []
risks: []
qa_focus: []
rollback_notes: []
next_recommended_action:
needs_user_decision: false
user_decision_needed:
```

## 2. Failure Dossier

同一任务连续失败 3 次或 reviewer 连续打回 3 次时，必须输出：

```yaml
failure_dossier:
  task_id:
  branch_or_worktree:
  attempt_count:
  failed_commands: []
  failed_tests: []
  changed_files: []
  attempted_fixes: []
  suspected_causes: []
  rollback_plan:
  safest_degraded_option:
  decision_needed:
```

## 3. reviewer 使用规则

reviewer 必须检查 handoff 是否完整。handoff 缺失时，不得建议合并。

## 4. qa 使用规则

qa 必须根据 handoff 中的 `tests_run`、`qa_focus` 和当前 milestone 验收条件补充验证。
