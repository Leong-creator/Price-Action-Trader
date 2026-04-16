# 分支与回退规范

## 1. 基本规则

- 禁止直接在 main/master 上开发。
- 每个 milestone、功能、修复、重构必须新建分支。
- 分支必须小而可回退。
- 未通过测试、文档同步、reviewer、qa 的改动不得合入主线。

## 2. 分支命名

- `feature/m<编号>-<slug>`
- `fix/<module>-<slug>`
- `refactor/<module>-<slug>`
- `test/<module>-<slug>`
- `docs/<module>-<slug>`
- `integration/m<编号>-<slug>`

## 3. subagent 并行规则

- read-only subagent 可以直接探索，不需要分支。
- 会写文件的 subagent 必须在指定 branch 或 worktree 内工作。
- 多个 subagent 同时写代码时，必须隔离到不同 branch/worktree。
- 主 agent 负责集成与冲突处理。

## 4. 高风险模块

涉及 `src/execution/`、`src/risk/`、`src/broker/`、凭证、实盘开关的变更必须单独分支、单独测试、单独复核。

## 5. 回退

每个任务交付时必须说明：

- 改了哪些文件。
- 如何回退。
- 是否影响数据结构。
- 是否需要迁移或清理生成文件。
