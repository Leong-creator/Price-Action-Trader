# 项目状态

## 当前阶段

- 阶段 4：纸面交易 / 模拟执行与风控闭环（进行中）

## 当前 milestone

- M5：纸面交易 / 模拟执行与风控闭环（进行中）

## 当前分支

- `feature/m5-papertrading-risk`

## 已完成

- Git 仓库初始化
- V2 目录结构落盘
- Codex agents 配置写入
- 核心规则文档写入
- 测试数据样本写入
- KB 校验与索引脚本写入
- GitHub 登录与推送链路打通
- 正式 `plans/active-plan.md` 已写入
- M1 代表性 wiki 页面已补齐（concept / setup / source）
- M1 schema、frontmatter、KB validate、wiki index 契约已对齐
- M1 验收条目已补齐并通过 reviewer / qa
- M2 数据契约已统一到 `src/data/schema.py`
- M2 本地 CSV/JSON loader 与 deterministic replay 已完成
- M2 单测已覆盖正向样本、重复键、非法 market、非法 severity、非法 timezone 与时间归一化
- M2 已通过 reviewer / qa 技术验收
- M3 已新增 research-only 的知识引用包与最小结构化索引
- M3 已新增 `src/strategy/` 最小 contracts / knowledge / context / signal 原型
- M3 单测已覆盖无信号、单信号、traceability、placeholder 低置信度、news 风险附着、缺失 source_refs 早失败、invalidation、双信号稳定性
- M3 已通过 reviewer / qa 正式复审，确认 strategy 仅消费 M2 数据契约，未越界到 execution / risk / broker / 外部 API
- M4 已新增 `src/backtest/` 最小 contracts / engine / reporting 基线
- M4 已覆盖零交易、单交易、多交易、same-bar stop/target、end_of_data、news 不改收益、profit_factor 空值路径
- M4 已通过 reviewer / qa 正式复审，确认回测层只消费本地 replay / bars 与结构化 signal，未越界到 execution / risk / broker / 外部 API

## 当前阻塞

- 无

## 下一步

- 从 `feature/m5-papertrading-risk` 启动 M5
- 先读取 `src/execution/AGENTS.override.md` 与 `src/risk/AGENTS.override.md`，锁定 paper-only 边界
- 优先实现信号 -> 风控 -> 建议订单 -> 模拟成交 -> 持仓状态 的最小闭环，并保持默认模式为 paper/simulated
