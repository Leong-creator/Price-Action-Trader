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
- replay snapshot、signal 序列或 backtest 汇总在相同输入下不稳定，直接判 fail
- bars / news 出现 future leakage，直接判 fail
- 被 `risk_block` 或 request-binding 阻断的请求若仍进入 simulated fill，直接判 fail
- close-path 审计字段缺失，直接判 fail
- review 缺少 KB `source_refs`、PA explanation、risk notes 或 news traceability，直接判 fail

### M8 Shadow/Paper Baseline

- 真实历史数据输入下的稳健性
- 实时只读输入下仍保持 shadow / paper
- 不进入真实 broker / live
- 保守性与可解释性保持稳定
- 缺失 manifest、manifest 指向缺失文件、或 `approved_for` 不允许 `m8d_shadow_paper` 用途时，必须 deferred 或 fail-fast
- `run_shadow_session.py` 若输出任何 broker-connected / live 字样，直接判 fail
- shadow / paper 输出若丢失 dataset metadata、session metadata、KB refs、PA explanation、risk/news traceability，直接判 fail
- 在没有真实历史样本时若声称“真实行情验证已完成”，直接判 fail

### M8D

- `M8D.1` 必须确保 artifact 中 `actual hit / actual evidence / bundle support` 分层清晰，broad support 不得伪装成 actual hit
- `M8D.2` 必须确保新增 promoted theme evidence 完整，且 transcript / Brooks 只通过 curated evidence chain 进入 actual trace，不进入 trigger
- `M8D.3` 必须确保 README / status / plan / acceptance / decisions / roadmap 与 reliability 辅助 README 口径一致，不再把 `feature/m7-broker-api-assessment` 表述为当前稳定基线
- 任一阶段若把 `statement` / `source_note` / `contradiction` / `open_question` 升格进 trigger，直接判 fail

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
