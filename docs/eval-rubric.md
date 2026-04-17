# 可靠性评分规则

## 1. 总原则

- 评分只作为辅助判断。
- 任何硬门禁失败，直接判定该阶段不通过。
- 评分结果不得被解释为实盘可用性或收益承诺。

## 2. 硬门禁

以下任一失败，直接判不通过：

- 出现 fake / hallucinated `source_refs`
- 出现 future leakage
- 被阻断路径仍进入 fill path
- 出现真实 broker / 真实账户 / live execution 路径
- 关键审计字段缺失
- 在资料不足或明确 `not_applicable` 的场景下仍强行给结论

## 3. 质量项

以下指标用于辅助判断质量，不替代硬门禁：

- explanation 完整率：目标 `>= 95%`
- KB 适用性合规率：目标 `>= 90%`
- 保守 `no-trade` 正确率：目标 `>= 85%`
- 审计日志完整率：目标 `= 100%`
- 报告生成成功率：目标 `= 100%`

## 4. 子阶段关注点

### M8A

- `plans/active-plan.md`、`docs/status.md` 与 `docs/acceptance.md` 的 M8A 状态同步
- `tests/golden_cases/`、`tests/integration/`、`tests/reliability/`、`reports/reliability/` 的目录 discoverability
- `scripts/run_reliability_suite.py` 的 skipped / deferred 语义清晰，不伪造真实历史结果
- 不引入外部网络、真实 broker、真实账户或 live execution 路径

### M8B

- `source_refs` 真实性
- `not_applicable` 场景拦截
- knowledge conflict 显式化
- insufficient evidence 时的保守 `no-trade / wait`
- explanation 必须带 setup / rule / source 回链
- 缺失 `source_refs`、fake wiki ref、忽略 `not_applicable`、把 conflict 伪装成 clean signal 都直接判 fail

### M8C

- determinism
- no future leakage
- risk-before-fill
- audit / review traceability
- forbidden paths

### M8D

- 真实历史数据输入下的稳健性
- 实时只读输入下仍保持 shadow / paper
- 不进入真实 broker / live
- 保守性与可解释性保持稳定

## 5. 人工抽检规则

人工抽检至少覆盖：

- knowledge conflict
- insufficient evidence
- news filtering
- risk block

人工抽检重点不是“是否多出信号”，而是：

- 是否违背知识库
- 是否越过边界
- 是否在不确定时保持保守
- 是否保留完整解释与审计链

## 6. 结论判定

- 全部硬门禁通过，且质量项达到目标线，可判定对应子阶段通过。
- 只要出现任一越权到 broker / live 的路径，直接判定该子阶段失败并停止继续推进。
