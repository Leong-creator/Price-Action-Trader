# 分支与回退规范

## 1. 基本规则

- 禁止直接在 main/master 上开发。
- `main` 是唯一长期稳定基线。
- 所有新的 `feature/*`、`fix/*`、`docs/*`、`test/*`、`integration/*` 分支都从 `main` 切出。
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

## 6. 验收后整合规则

- 对于低/中风险阶段，若某个 milestone 或子 milestone 已满足：验收通过、相关测试全绿、文档同步完成、无未解决 blocker，则“合并到 `main`”是该阶段最后一个必做动作。
- 不允许把已完成阶段长期停留在 `feature/`、`fix/`、`integration/` 等开发分支，拖到整个项目结束后再统一合并。
- 新阶段必须从最新稳定基线 `main` 重新开分支，不得从过期开发分支继续串行累积。
- `feature/m7-broker-api-assessment` 只保留为历史阶段基线/里程碑分支，不再作为未来默认合并目标。

## 7. 高风险模块例外

- `src/execution/`、`src/risk/`、`src/broker/`、以及任何 `live / real-money / real-account` 路径都视为高风险模块。
- 高风险模块可以自动准备合并所需的状态、测试、变更说明与回退说明。
- 高风险模块不得自动最终合并入 `main`，必须等待用户明确批准。
