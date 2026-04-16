# 项目状态

## 当前阶段

- 阶段 2：测试数据、OHLCV schema、CSV/JSON 回放（已完成）

## 当前 milestone

- M2：测试数据、OHLCV schema、CSV/JSON 回放 adapter（已完成）

## 当前分支

- `feature/m2-data-schema-replay`

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

## 当前阻塞

- 无

## 下一步

- 从 `feature/m3-pa-signal-prototype` 启动 M3
- 优先定义可解释 signal 对象、PA context / setup 表达与知识库引用边界
- 基于 M1 wiki 页面和 M2 replay 数据建立最小 signal 原型与验证样本
