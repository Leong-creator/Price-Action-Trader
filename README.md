# Price Action Trader

Price Action Trader 是一个以 Price Action 知识库为核心的交易研究与自动化辅助项目，当前优先服务美股和港股。

本仓库当前已经按 V2 active plan 完成 `M0` 到 `M7` 的既定范围，但项目结论仍停留在 `paper / simulated`，没有进入真实 broker 接入、真实账户联通或 live execution。

## 当前状态

- 当前分支：`feature/m7-broker-api-assessment`
- 当前阶段：`M7 正式券商 API 接入评估（已完成）`
- 当前结论：`no-go`
- 默认运行边界：`paper / simulated`

详细状态见：

- `plans/active-plan.md`
- `docs/status.md`
- `docs/acceptance.md`
- `docs/decisions.md`

## 已完成里程碑

- `M0`：基础设施初始化、仓库结构、Codex agents、测试样本、KB 脚本
- `M1`：知识库 schema、KB 校验、wiki index、资料投放流程
- `M2`：数据 schema、本地 CSV/JSON loader、deterministic replay
- `M3`：research-only 的 PA context / setup / signal 原型
- `M4`：最小回测引擎与报告
- `M5`：paper-only 的模拟执行与风控闭环
- `M6`：新闻过滤与复盘整合
- `M7`：FormalBrokerAdapter assessment-only contract draft、readiness dossier、approval checklist

## 关键模块

- `knowledge/`：raw 资料、wiki 知识页、schema
- `src/data/`：数据 schema、清洗、导入、回放
- `src/strategy/`：PA context、setup、signal 原型
- `src/backtest/`：最小回测引擎与报告
- `src/risk/`：paper-only 风控与熔断
- `src/execution/`：paper-only 执行、状态与审计日志
- `src/news/`：新闻过滤、解释与风险提示
- `src/review/`：复盘与报告聚合
- `src/broker/`：assessment-only broker contract draft

## 验证基线

常用验证命令：

```bash
python scripts/validate_kb.py
python -m unittest discover -s tests/unit -v
```

M7 assessment-only 验证：

```bash
python -m py_compile src/broker/__init__.py src/broker/contracts.py tests/unit/test_broker_contract_assessment.py
python -m unittest tests/unit/test_broker_contract_assessment.py -v
```

## 风险边界

- 不接真实资金
- 不启用实盘自动下单
- 不把付费券商 API 前置化
- 不把浏览器自动化写成生产执行链路
- 未获明确批准前，不进入真实 broker SDK、真实账户联通或 live execution

## 下一步

当前默认下一步不是继续编码，而是保持 `no-go` 结论并停留在 `paper / simulated`。

只有在用户明确批准以下任一事项后，才允许重新评估后续阶段：

- 外部权限
- 真实账户
- 付费服务
- 真实 broker 接入评估或联通

## 说明

- `knowledge/raw/` 用于用户投放原始资料，raw 层不可随意改写。
- 当前未跟踪的 `knowledge/raw/...` 目录属于本地资料输入，不属于已完成里程碑代码产物。
