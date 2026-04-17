# 项目状态

## 当前阶段

- 阶段 7：正式券商 API 接入评估（已完成）

## 当前 milestone

- M7：正式券商 API 接入评估（已完成）

## 当前分支

- `feature/m7-broker-api-assessment`

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
- M5 已新增 `src/risk/` 最小 contracts / engine 与 `src/execution/` 最小 paper adapter / state / logging
- M5 已覆盖 allow、risk_block、market_closed、duplicate_signal、loss-streak halt、manual recovery、config_error、invalid_request、mismatched / stale / direction-mismatch risk decision
- M5 已通过 reviewer / qa 正式复审，确认风控先于执行、paper-only 边界清晰、close-path 审计日志可复盘，未越界到真实 broker / live execution
- M6 已新增 `src/news/` 最小 contracts / filtering 与 `src/review/` 最小 contracts / reporting
- M6 已补 `knowledge/wiki/rules/m6-news-review-evidence-pack.md`，并同步 `knowledge/wiki/index.md` 与 `knowledge/wiki/log.md`
- M6 已覆盖无新闻、caution、block、future-event leakage、防止缺失 reference timestamp、review 中 filter / explanation / risk_hint 角色透传、以及新闻不改写 signal 主字段
- M6 已通过 reviewer / qa 正式复审，确认新闻仍只作 filter / explanation / risk_hint，未越界到 signal / order / execution，且复盘输出保留结构化 `news_review_notes`
- M7 已新增 `src/broker/` assessment-only contract draft 与 `tests/unit/test_broker_contract_assessment.py`
- M7 已新增 `docs/broker-readiness-assessment.md` 与 `docs/broker-approval-checklist.md`，明确 readiness 边界、approval gates、rollback boundary 与当前 `no-go` 结论
- M7 已通过 reviewer / qa 正式复审，确认 broker 层仍停留在 contract draft / readiness artifact，未越界到真实 broker SDK、真实账户联通或 live execution

## 当前阻塞

- 若要进入 M7 之后的任何真实 broker 联通、真实账户、外部权限或付费服务阶段，需要用户明确批准

## 下一步

- 保持当前结论为 `no-go`，继续停留在 paper / simulated
- 除非用户明确批准外部权限、真实账户、付费服务或下一阶段评估，否则不进入任何真实 broker 接入实现
- 若未来获批，必须从当前 `feature/m7-broker-api-assessment` 检查点重新评估后续阶段，而不是直接启用 live execution
