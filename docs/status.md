# 项目状态

## 当前阶段

- 阶段 2：测试数据、OHLCV schema、CSV/JSON 回放

## 当前 milestone

- M2：测试数据、OHLCV schema、CSV/JSON 回放 adapter

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

## 当前阻塞

- 无

## 下一步

- 从 `feature/m2-data-schema-replay` 启动 M2
- 优先统一 OHLCV / 新闻 schema、读取接口与 deterministic replay 契约
- 完成测试样本、异常路径与回放验证后，再进入 M3
