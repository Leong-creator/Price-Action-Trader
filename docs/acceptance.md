# 阶段验收

## 分支治理补充

- `main` 是唯一长期稳定基线。
- 所有新的 `feature/*`、`fix/*`、`docs/*`、`test/*` 分支都从 `main` 切出。
- 低/中风险阶段验收通过后，默认合并目标是 `main`。
- `src/execution/`、`src/risk/`、`src/broker/` 及任何 `live / real-money / real-account` 路径仍属于高风险模块，只能自动准备合并，不得自动最终合并到 `main`，必须等待用户明确批准。
- `feature/m7-broker-api-assessment` 只保留为历史阶段/里程碑分支，不再作为未来默认合并目标。

## 阶段 0：基础设施初始化

完成条件：

- 目录树与基础文件按 V2 方案创建。
- `.codex/config.toml` 存在。
- `.codex/agents/*.toml` 存在。
- 根目录 `AGENTS.md` 为精简版规则文件。
- `tests/test_data/` 存在并包含样本。
- `scripts/validate_kb.py` 与 `scripts/build_kb_index.py` 可通过 `python -m py_compile`。
- `validate_kb.py` 能正常处理空 wiki 目录。
- 当前轮次不启动策略、回测、浏览器自动化、券商 API、实盘或自动下单开发。

## 阶段 1：知识库 schema、KB 校验、wiki index、资料投放流程

完成条件：

- `knowledge/schema/knowledge-schema.md`、`knowledge/schema/ingestion-rules.md`、
  `knowledge/schema/page-frontmatter-template.md` 三者字段契约一致。
- `scripts/validate_kb.py` 与上述 schema 契约一致，并覆盖：
  - 缺失 frontmatter。
  - 非法 `type` / `status` / `confidence` / `direction`。
  - 通用必填字段缺失。
  - `setup` 页面额外必填字段缺失。
  - 列表字段类型错误。
- `scripts/build_kb_index.py` 输出字段至少包含：
  `path`、`title`、`type`、`status`、`confidence`、`market`、`timeframes`、
  `direction`、`source_refs`、`pa_context`、`tags`、`open_questions`。
- 两个脚本都必须支持：
  - 空 wiki 目录路径。
  - 至少包含 `concept`、`setup`、`source` 三类代表性页面的临时样本路径。
- `knowledge/wiki/index.md` 满足当前 frontmatter 契约，且可被校验脚本和索引脚本处理。
- M1 不修改 raw 层资料，不接入外部 API，不进入策略、回测、模拟盘或实盘开发。

## 阶段 2：测试数据、OHLCV schema、CSV/JSON 回放

完成条件：

- `src/data/schema.py` 固定 OHLCV、新闻事件、ValidationError、CleanedRecord 的最小稳定契约。
- 本地 CSV/JSON loader 与 replay 必须直接消费 schema 契约，而不是维护并行私有类型。
- OHLCV 至少校验：
  - timestamp 可解析。
  - timezone 有效。
  - high/low/open/close 基本关系。
  - 非法价格与非法 volume。
  - 同一 symbol/timeframe/timestamp 重复。
  - 非法 market。
- 新闻样本至少校验：
  - 最小字段齐全。
  - timestamp 与 timezone 上下文有效。
  - 非法 market。
  - 非法 severity。
- `python -m unittest discover -s tests/unit -p 'test_data_pipeline.py' -v` 通过。
- replay 输出必须能暴露稳定的 bar identity_key，并与 schema 契约保持一致。
- M2 不接入外部行情 API，不引入浏览器自动化，不进入策略、回测统计、模拟盘或实盘开发。

## 阶段 3：PA context、setup、signal 输出原型

完成条件：

- `src/strategy/` 已冻结最小 `PAContextSnapshot`、`SetupCandidate`、`Signal` 结构化对象。
- strategy 层只消费 M2 的 `OhlcvRow`、`NewsEvent`、`DeterministicReplay` 契约，不直接读取 CSV/JSON。
- 已建立 research-only 的最小知识引用层，并保留直接回链到 wiki concept/setup/rule 页面与 source/raw 的 `source_refs`。
- 信号输出至少包含：
  - `signal_id`
  - `symbol`
  - `market`
  - `timeframe`
  - `direction`
  - `setup_type`
  - `pa_context`
  - `entry_trigger`
  - `stop_rule`
  - `target_rule`
  - `invalidation`
  - `confidence`
  - `source_refs`
  - `explanation`
  - `risk_notes`
- `python -m unittest tests/unit/test_strategy_signal_pipeline.py -v` 通过，并至少覆盖：
  - 无信号路径。
  - 单信号路径。
  - `signal_id` 与 `source_refs` 稳定性。
  - placeholder knowledge 导致的低置信度与风险提示。
  - news 只进入 `risk_notes`，不污染主信号字段。
  - 缺失 `source_refs` 的早失败路径。
  - invalidation 的最小阻断行为。
  - 多信号顺序稳定性与 `signal_id` 唯一性。
- `python scripts/validate_kb.py` 与 `python scripts/build_kb_index.py` 继续通过。
- M3 不接入外部行情 API，不进入回测成交撮合、模拟执行、正式券商 API、实盘或自动下单开发。

## 阶段 4：最小回测引擎与报告

完成条件：

- `src/backtest/` 已冻结最小 `TradeRecord`、`BacktestStats`、`BacktestReport` 结构化输出。
- 回测层只消费本地 `OhlcvRow` / `DeterministicReplay` 与 M3 的结构化 `Signal`，不直接读取 CSV/JSON。
- 已固定 deterministic baseline 假设，并在报告中显式注明：
  - next-bar-open entry
  - signal-bar extremum stop
  - fixed 2R target
  - same-bar stop-first
  - no slippage / fees / leverage / position sizing
- `python -m unittest tests/unit/test_backtest_pipeline.py -v` 通过，并至少覆盖：
  - 零交易路径。
  - 单交易目标命中。
  - 单交易止损命中。
  - 多交易 deterministic 行为。
  - same-bar stop/target 优先级。
  - end_of_data / 数据不足路径。
  - news 不改收益统计。
  - gross_loss == 0 时 `profit_factor` 不给出伪确定性哨兵值。
- 收益类统计只基于 closed trades；`end_of_data` / unfinished trade 不得混入 closed-trade 收益统计。
- `python -m unittest tests/unit/test_strategy_signal_pipeline.py -v` 与 `python -m unittest discover -s tests/unit -p 'test_data_pipeline.py' -v` 继续通过。
- M4 不接入外部行情 API，不进入模拟执行、正式券商 API、实盘或自动下单开发。

## 阶段 5：纸面交易、模拟执行与风控闭环

完成条件：

- `src/risk/` 已冻结最小 `RiskConfig`、`PositionSnapshot`、`TradingPauseState`、`SessionRiskState`、`RiskEvent`、`RiskDecision` 契约。
- `src/execution/` 已冻结最小 `ExecutionRequest`、`SuggestedOrder`、`FillEvent`、`PaperPosition`、`ExecutionLogEntry`、`ExecutionResult`、`PositionCloseResult` 契约。
- 执行层默认只支持 `paper/simulated`，不得出现真实 broker 凭证、真实账户连接、真实下单路径或 live 默认语义。
- 风控层至少覆盖：
  - 单笔最大风险
  - 总仓位限制
  - 标的集中度限制
  - 日内最大亏损
  - 连续亏损暂停
  - 熔断/暂停状态
  - 恢复交易条件
- `PaperBrokerAdapter.submit(...)` 必须在 simulated fill 之前阻断以下路径：
  - risk_block
  - config_error
  - invalid_request
  - market_closed
  - duplicate_signal
  - stale / mismatched risk decision
- close-path 审计日志至少保留：
  - `signal_id`
  - `symbol`
  - `source_refs`
  - `quantity`
  - `entry_price`
  - `exit_price`
  - `realized_pnl`
- `python -m unittest tests/unit/test_paper_execution_pipeline.py -v` 通过，并至少覆盖：
  - allow 路径
  - 风控拦截路径
  - 模拟成交路径
  - 市场关闭路径
  - 重复信号路径
  - 连续亏损熔断路径
  - 恢复交易条件路径
  - config_error / invalid_request 路径
  - mismatched / stale risk decision 路径
- `python -m unittest discover -s tests/unit -v` 继续通过。
- M5 不接入外部行情 API，不进入正式券商 API、实盘或自动下单开发。

## 阶段 6：新闻事件过滤与复盘整合

完成条件：

- `src/news/` 已冻结最小 `NewsMatch`、`NewsReviewNote`、`NewsFilterDecision` 与 `evaluate_news_context(...)` 契约。
- `src/review/` 已冻结最小 `ReviewTradeOutcome`、`ReviewItem`、`ReviewReport` 与 `build_review_report(...)` 契约。
- 新闻只能作为 filter / explanation / risk_hint 辅助因子，不得直接改写 `Signal` 主字段，不得直接转成 order / execution 语义。
- news filtering 必须显式要求 `reference_timestamp` 或等价的可验证参考时点；未来事件不得穿透到当前 signal 的过滤结果。
- review 输出至少保留：
  - KB `source_refs`
  - PA explanation
  - `news_outcome`
  - `news_review_notes`
  - `news_source_refs`
  - trade / execution evidence refs
  - improvement notes
- `python -m unittest tests/unit/test_news_review_pipeline.py -v` 通过，并至少覆盖：
  - 无新闻路径
  - caution 路径
  - block 路径
  - future-event leakage 防回归
  - 缺失 `reference_timestamp` 的明确失败路径
  - filter / explanation / risk_hint 三类角色在 review 中的结构化透传
  - 新闻不改写 signal 主字段
- `python scripts/validate_kb.py`、`python scripts/build_kb_index.py --output /tmp/price-action-trader-m6-kb-index.json` 与 `python -m unittest discover -s tests/unit -v` 继续通过。
- M6 不接入真实 broker、真实账户、正式券商 API 或 live execution，不把新闻模块升级成主信号源。

## 阶段 7：正式券商 API 接入评估

完成条件：

- `src/broker/` 若存在，只允许包含 `FormalBrokerAdapter` 的 interface-only contract draft，不得包含真实 broker SDK、HTTP client、WebSocket client、登录、下单、改单、撤单、账户同步或外部网络依赖实现。
- `FormalBrokerAdapter` contract draft 必须显式保留以下 assessment 边界：
  - live execution 默认禁用
  - 只能在既有 risk / execution gate 之后讨论未来接入
  - 不得包含默认凭证值
  - 不得授权真实账户联通
- `docs/broker-readiness-assessment.md` 必须覆盖：
  - capability matrix
  - credential isolation
  - simulated validation prerequisites
  - approval gates
  - go/no-go 模板
  - rollback boundary
- `docs/broker-approval-checklist.md` 必须覆盖：
  - 人工审批清单
  - reviewer / qa 依赖
  - no-go 时继续停留在 paper / simulated 的默认策略
- `python -m py_compile src/broker/__init__.py src/broker/contracts.py tests/unit/test_broker_contract_assessment.py` 通过。
- `python -m unittest tests/unit/test_broker_contract_assessment.py -v` 通过，并至少覆盖：
  - contract shape
  - no-live invariant
  - risk / execution gate dependency
  - 无默认凭证字段
- reviewer 必须确认 M7 产物仍是 assessment-only，不含真实接入实现。
- qa 必须确认 readiness dossier、approval checklist、go/no-go 条件与 rollback boundary 完整。
- M7 不接入真实 broker、不接入真实账户、不启用 live execution、不引入付费服务前置条件。

## 阶段 8：可靠性验证

### M8A：测试骨架与验收门禁落盘

完成条件：

- `plans/active-plan.md` 已新增 `M8` 与 `M8A / M8B / M8C / M8D`。
- `docs/status.md` 已把当前下一步切换为进入 `M8`，而不是继续 broker。
- `docs/roadmap.md` 已同步 `M8` 在 `M7` 之后、任何 broker / live 重新评估之前的位置。
- `docs/decisions.md` 已新增 “完成 M8 前，不重新评估 broker / live” 的冻结决策。
- 若新增 `docs/testing-reliability.md` 与 `docs/eval-rubric.md`，内容只能是计划、门禁、评分与人工抽检准则，不得包含测试实现细节。
- `docs/test-dataset-curation.md` 已说明允许的数据层级、最小元数据、脱敏与离线边界。
- `tests/golden_cases/`、`tests/integration/`、`tests/reliability/`、`reports/reliability/` 均存在且带 discoverable README/占位说明。
- `scripts/run_reliability_suite.py` 可通过 `python -m py_compile`。
- `python scripts/run_reliability_suite.py --list` 能列出当前 suite 入口。
- `python scripts/run_reliability_suite.py` 在没有真实历史样本、且 M8B/M8C/M8D 目录还没有测试文件时也能安全运行，并显式输出 skipped / deferred，而不是伪造通过。
- reviewer 必须确认 `M8` 被定义为可靠性验证阶段，而不是功能扩展或 broker 延续阶段。
- qa 必须确认所有门禁文档都继续保留 `paper / simulated` 与 `no-go` 边界。

### M8B：知识库对齐测试

完成条件：

- `M8B` 明确把知识库一致性定义为硬门禁，而不是质量建议项。
- 明确要求 `source_refs` 必须真实存在，不得 hallucinated refs。
- 明确要求 raw 中的 transcript / PPT 只有在对应 `source` 页、wiki index、active rule pack 与默认 strategy knowledge bundle 都已接线后，才允许进入 `signal.source_refs` / `explanation`；只有 raw 文件而无结构化接线时必须保持缺席。
- 明确要求不得越过 `not_applicable` 或等价的禁用条件。
- 明确要求知识冲突场景必须显式输出冲突，而不是伪装成单一路径。
- 明确要求资料不足时允许且鼓励 `no-trade / wait`。
- reviewer 与 qa 都必须把 “无伪造知识引用、无忽略不适用条件、无强行给方向” 作为强制审查项。
- M8B 不得通过新增规则或放宽适用边界来“修复”测试结果。
- 当前整合状态：
  - 已于 2026-04-17 通过 `tests/reliability` 7 项与 `tests/unit` 57 项验证。
  - 已通过 merge commit `0047100` 从 `integration/m8-reliability-validation` 合并到 `feature/m7-broker-api-assessment`。
  - M8B.1 已定位 transcript / Brooks PPT 缺席根因：此前只有 raw 文件，没有对应 `source` 页和 rule-pack 接线，且默认 strategy bundle 未加载 active rule pack；现已补齐最小 traceability 接线，但仍不把这些来源包装成已抽取完成的正式规则。
  - M8 的基础离线可靠性门禁已完成实现与验证，且仍保持 `paper / simulated` 与 `no-go` 边界。

### M8B.2a：Knowledge Atomization 基础层

完成条件：

- `M8B.2` 已在 `plans/active-plan.md`、`docs/status.md`、`docs/acceptance.md`、`docs/decisions.md` 与 `docs/knowledge-atomization.md` 中拆成 `2a / 2b`。
- `2a` 实施期间只允许建设 source/chunk/atom/index 基础层，不得提前进入 `2b`。
- 已新增：
  - `knowledge/schema/source-registry-schema.md`
  - `knowledge/schema/chunk-registry-schema.md`
  - `knowledge/schema/knowledge-atom-schema.md`
  - `knowledge/schema/callable-access-contract.md`
  - `knowledge/indices/source_manifest.json`
  - `knowledge/indices/chunk_manifest.jsonl`
  - `knowledge/indices/knowledge_atoms.jsonl`
  - `knowledge/indices/knowledge_callable_index.json`
  - `scripts/build_source_manifest.py`
  - `scripts/build_chunk_registry.py`
  - `scripts/build_knowledge_atoms.py`
  - `scripts/build_callable_index.py`
  - `scripts/validate_kb_coverage.py`
  - `scripts/validate_knowledge_atoms.py`
- M8B.2a 初始 10 个 in-scope source 都必须存在 machine-readable source record；后续 milestone 可追加新 source，但不得破坏原 source 可解析性。
- 若存在 `:Zone.Identifier` sidecar，必须被过滤并进入 `coverage_summary.filtered_files`，不得被误判为 source。
- 每个 source 都要么可解析进 chunk/atom，要么明确进入 `blocked / partial` 并写明原因。
- `statement` atom 必须存在，并且每条都具备：
  - `atom_id`
  - `atom_type=statement`
  - `source_ref`
  - `raw_locator`
  - `evidence_chunk_ids`
  - `status`
  - `confidence`
  - `callable_tags`
- `statement` 默认是 callable 中间层，不得被标记成 executable strategy rule，不得默认带 `strategy_candidate`。
- 无证据时不得产出 `statement`。
- transcript / Brooks / 全部方方土笔记都必须在 callable index 层可检索。
- 关键 curated atoms 必须形成 evidence-backed atom：
  - `market-cycle-overview`
  - `signal-bar-entry-placeholder`
  - `m3-research-reference-pack`
- 若满足以下任一条件，必须熔断并停在 `2a`：
  - `blocked >= 4`
  - 关键 curated atoms 无法 evidence-backed
  - `statement` 抽取无法稳定回溯证据
- `python -m unittest discover -s tests/reliability -v` 必须通过。
- 必须至少包含并通过：
  - `tests/reliability/test_kb_coverage.py`
  - `tests/reliability/test_knowledge_atoms.py`
  - `tests/reliability/test_callable_access.py`
- 本轮不得修改 strategy / explanation / review / report 接线，不得修改 trigger 逻辑，不得触碰 broker/live/real-money/real-account。
- 当前完成事实：
  - `source_manifest.json` 初始 M8B.2a 结果为 `parsed=9 / partial=1 / blocked=0`
  - 当前 partial source 为 `方方土视频笔记 - 楔形.pdf`
  - 当前未触发熔断
  - 关键 curated atoms 已形成 evidence-backed atom
  - `statement` 已落盘并满足 evidence-backed / non-executable / non-trigger 约束
  - M8B.2a.1 已完成 statement 质量审计，结论为 `pass_with_small_fixes`
  - 审计后的最小修复只限于：收紧 statement 提取条件、去除明显页眉页脚 / 时间轴 / 起始标点 / 未完成碎片、修正同一 source 内的明显重复
  - 审计后 statement 分布为：`al_brooks_ppt=11042`、`fangfangtu_transcript=88`、`fangfangtu_notes=41`
  - 审计后噪音门槛结果为：`exact_dup_extra=13`、`normalized_dup_extra=16`、`trailing_open=0`、`datey=0`、`start_punct=0`
  - 已于 2026-04-17 通过 merge commit `23755c0` 从 `feature/m8b2-knowledge-atomization-callable-access` 合并进稳定基线 `feature/m7-broker-api-assessment`
  - `M8B.2a` 已先整合进稳定基线，随后 `M8B.2b` 才从最新稳定基线独立分支启动

### M8B.2b：Callable 接入 Strategy / Explanation / Review / Report

启动前提：

- `M8B.2a` 全部测试通过
- 未触发熔断
- reviewer 通过
- qa 通过

完成条件：

- 已新增 `src/strategy/knowledge_access.py`，并能读取 `knowledge_atoms.jsonl` 与 `knowledge_callable_index.json`。
- `Signal` 必须新增 `knowledge_trace`，且每个 `KnowledgeAtomHit` 至少包含：
  - `atom_id`
  - `atom_type`
  - `source_ref`
  - `raw_locator`
  - `match_reason`
  - `applicability_state`
  - `conflict_refs`
- `ReviewItem` 必须新增 `kb_trace` 或等价结构化字段。
- legacy `source_refs` 必须保留；可新增 helper 从 `knowledge_trace` 聚合兼容 source refs，但不得移除旧字段。
- 现有 trigger 仍只能由当前允许的 curated `concept / setup / rule` 路径驱动。
- `statement` / `source_note` / `contradiction` / `open_question` 只能进入 trace / explanation / review / report，不得参与 trigger。
- trace resolver 必须有 source family 失衡保护：
  - curated atoms 优先
  - statement 去重与限量
  - source family 多样性控制
  - 不得使用 statement 数量作为 confidence 或 trigger proxy
- `reports/backtests/<run_id>/knowledge_trace.json` 必须存在，并保留 machine-readable 全量 trace。
- Markdown `report.md` 只允许展示精简 trace 摘要；每笔代表性交易最多 3 条，不得展开完整 atom trace。
- 必须至少通过：
  - `tests/reliability/test_strategy_atom_trace.py`
  - `tests/unit/test_strategy_signal_pipeline.py`
  - `tests/unit/test_news_review_pipeline.py`
  - `tests/unit/test_public_backtest_demo.py`
  - `python -m unittest discover -s tests/reliability -v`
  - `python -m unittest discover -s tests/unit -v`
- 当前完成事实：
  - `knowledge_trace` 已接入 `Signal` / `ReviewItem` / public demo machine-readable report
  - legacy `source_refs` 与 `kb_source_refs` 仍保留
  - 已实现 source family 失衡保护
  - trigger 逻辑未改变
  - `statement` 仍未进入 trigger
  - 项目边界仍保持 `paper / simulated`

### M8 基础离线可靠性门禁

完成条件：

- 明确要求无 future leakage。
- 明确要求同一输入必须 deterministic。
- 明确要求 `risk_block` 永远先于 simulated fill。
- 明确要求 audit / review 字段完整且可追溯。
- 明确要求 forbidden paths 被列为硬门禁。
- `tests/integration/test_offline_e2e_pipeline.py` 必须覆盖 `src/data -> src/strategy -> src/backtest -> src/risk -> src/execution -> src/news -> src/review` 的离线端到端链路。
- `tests/reliability/test_replay_determinism.py` 必须覆盖 deterministic replay、相同输入下 signal / backtest 稳定性、重复 bar fail-fast 与 gap bar 不伪造缺失 slot。
- `tests/reliability/test_no_future_leakage.py` 必须覆盖 bars / news 的 future leakage fail-fast，且缺失 `reference_timestamp` 时显式失败。
- `tests/reliability/test_audit_traceability.py` 必须覆盖 close-path 审计字段完整性，以及 review 中 KB / explanation / risk / news traceability 完整性。
- `tests/reliability/test_forbidden_paths.py` 必须覆盖被风控阻断或 request-binding 失配的请求不得进入 simulated fill。
- `python -m unittest discover -s tests/reliability -v`、`python -m unittest discover -s tests/integration -v`、`python -m unittest discover -s tests/unit -v` 必须全部通过。
- `python scripts/run_reliability_suite.py` 必须在无真实历史样本时仍可运行，并显式保持 `real_historical_data=deferred`。
- reviewer 必须确认离线可靠性定义没有越权到 broker / live。
- qa 必须确认 determinism、future leakage、risk-before-fill 与 traceability 都是硬门禁而非可选质量项。

### M8C：Long-Horizon & Intraday Paper Validation

#### M8C.1：长周期日线验证

完成条件：

- 保持 daily、equity/ETF、公有历史数据缓存驱动的验证边界；不得进入 intraday、期权、broker/live/real-money。
- 时间范围必须扩展到多个市场状态，不得只停留在 `2024H1` 单窗口。
- 必须至少覆盖 `NVDA / TSLA / SPY` 三个 equity/ETF 标的，并提供 per-symbol breakdown。
- 必须输出 walk-forward 风格 split 产物，至少包括：
  - `in_sample`
  - `validation`
  - `out_of_sample`
- 必须输出 regime 分层摘要，且 regime 仅用于验证分层，不得反向输入 trigger。
- 必须新增并落盘：
  - `summary.json`
  - `split_summary.json`
  - `regime_breakdown.json`
  - `knowledge_trace_coverage.json`
  - `no_trade_wait.jsonl`
  - `trades.csv`
  - `knowledge_trace.json`
  - `report.md`
  - `equity_curve.png`
- 必须新增结构化 `no-trade / wait` 持久化，且最小 reason class 至少覆盖：
  - `context_not_trend`
  - `duplicate_direction_suppressed`
  - `insufficient_evidence`
  - `risk_blocked_before_fill`
- 必须输出：
  - total return
  - drawdown
  - trade count
  - blocked signals
  - knowledge trace 覆盖率摘要
  - curated vs statement trace 占比摘要
- `knowledge_trace` 与 legacy `source_refs` 必须继续兼容。
- `statement` / `source_note` 只允许进入 trace / 报告，不得参与 trigger，不得影响 score / confidence。
- 必须明确体现 curated atom 优先，statement 只作补充证据；不得因 Brooks statement 数量偏大而污染验证结论。
- 必须至少通过：
  - `tests/reliability/test_long_horizon_daily_validation.py`
  - `tests/unit/test_public_backtest_demo.py`
  - `python -m unittest discover -s tests/reliability -v`
  - `python -m unittest discover -s tests/unit -v`
- 当前完成事实：
  - 已新增 `config/examples/public_history_backtest_long_horizon.json`
  - 已把 daily public history demo 扩展到 `2020-01-01 ~ 2025-12-31`
  - 已覆盖 `NVDA / TSLA / SPY`
  - 已完成 walk-forward split 与 regime 摘要
  - 已落盘 `no_trade_wait.jsonl`
  - 已保持 `paper / simulated`，未进入期权或 intraday

#### M8C.2：单标的日内试点

启动前提：

- `M8C.1` 已通过验收并整合进稳定基线。
- `M8C.2` 已在 feature 分支通过 reviewer / qa，并通过 merge commit 合入 `main`；当前已计入稳定基线事实。

完成条件：

- 只允许选择一个标的，优先 `SPY 15m`。
- 必须补齐 session open/close、market hours / timezone、日内风险重置、slippage / fee 最小模型、duplicate signal protection、`no-trade / wait` 结构化输出。
- 仍保持 `paper / simulated`，不得进入期权、broker/live/real-money。
- `statement` / `source_note` 继续只作 trace 证据，不得进入 trigger。
- 如实现被迫修改 `src/risk/` 或 `src/execution/` 核心语义，则停止自动合并并转高风险审批。
- 必须落盘：
  - `summary.json`
  - `session_summary.json`
  - `session_quality.json`
  - `knowledge_trace.json`
  - `knowledge_trace_coverage.json`
  - `no_trade_wait.jsonl`
  - `trades.csv`
  - `report.md`
- Markdown 报告必须明确：
  - 标的、周期、时间范围
  - `paper / simulated` 边界
  - 仍未进入期权
  - 仍未进入 broker/live
  - 只展示精简 trace 摘要，不展开全量 atom trace
- 必须至少通过：
  - `tests/unit/test_intraday_pilot.py`
  - `tests/reliability/test_intraday_pilot_validation.py`
  - `python -m unittest discover -s tests/reliability -v`
  - `python -m unittest discover -s tests/unit -v`
  - public demo 必要 smoke/regression
- 当前完成事实：
  - 已固定首轮 intraday pilot 为 `SPY / 15m / America/New_York / 2026-03-30 ~ 2026-04-16`
  - 已验证 session open/close、market hours / timezone、日内风险重置、duplicate signal protection、slippage / fee 最小模型、`no-trade / wait` 结构化输出
  - 已保持 `knowledge_trace` 与 legacy `source_refs` 兼容
  - 已保持 curated atom 优先、statement 仅作补充证据，且未让 Brooks statement 数量放大 trigger 或排序
  - 已保持 `paper / simulated`
  - 已保持 trigger 逻辑不变
  - 已保持未进入期权、broker、live、real-money
  - 已完成第二标的扩展验证：`NVDA / 15m / America/New_York / 2026-03-30 ~ 2026-04-16`
  - 第二标的扩展继续使用相同的 session / risk reset / duplicate protection / slippage / fee / `knowledge_trace` 契约，且 trigger 语义不变

### M8D.1：Artifact & Trace Unification

完成条件：

- 只允许统一旧 daily run 与当前 intraday run 的 trace 语义，不得进入 `M8D.2` 的 curated promotion，不得进入 `M8D.3` 的仓库状态整理。
- `reports/backtests/m8c1_long_horizon_daily_validation/` 必须重算并落盘，至少包含：
  - `summary.json`
  - `report.md`
  - `knowledge_trace.json`
  - `knowledge_trace_coverage.json`
  - `no_trade_wait.jsonl`
  - `trades.csv`
  - `split_summary.json`
  - `regime_breakdown.json`
  - `equity_curve.png`
- `actual hit`、`actual evidence`、`bundle support` 必须在 `summary.json`、`report.md`、`knowledge_trace.json`、`knowledge_trace_coverage.json` 中显式分层。
- user-facing `source_refs` 只允许表示 actual refs；`bundle_support_refs` 必须单独存在；若需要兼容旧语义，只能通过 `legacy_source_refs` 单独保留。
- broad support refs 不得继续以 actual evidence 身份进入 visible `knowledge_trace` 或 `report.md` 的主展示语义。
- `m3-research-reference-pack` 不得继续在 visible actual refs 中主导 long-horizon daily run 的展示；若仍需保留，只能进入 bundle support 或 legacy 兼容层。
- `knowledge_trace_coverage.json` 必须至少区分：
  - `actual_hit_source_family_presence`
  - `actual_evidence_source_family_presence`
  - `bundle_support_family_presence`
- transcript / Brooks 若只是 bundle support，不得在 actual hit coverage 中伪装成真实命中。
- 必须至少通过：
  - `tests/reliability/test_long_horizon_daily_validation.py`
  - `tests/reliability/test_intraday_pilot_validation.py`
  - `tests/reliability/test_knowledge_trace_fidelity.py`
  - `tests/unit/test_public_backtest_demo.py`
  - `python -m unittest discover -s tests/reliability`
  - `python -m unittest discover -s tests/unit`
  - `python scripts/run_reliability_suite.py`
- 必须保持：
  - trigger 逻辑不变
  - `statement` / `source_note` / `contradiction` / `open_question` 不进入 trigger
  - `knowledge/raw` 不变
  - 继续保持 `paper / simulated`
- 当前完成事实：
  - 已重算 `reports/backtests/m8c1_long_horizon_daily_validation/` 并把 long-horizon daily run 对齐到当前 intraday trace contract。
  - `summary.json`、`report.md`、`knowledge_trace.json`、`knowledge_trace_coverage.json`、`no_trade_wait.jsonl` 现在都能明确区分 actual refs 与 bundle support。
  - `source_refs` 在 user-facing artifact 中只代表 actual refs；兼容层只通过 `legacy_source_refs` 保留。
  - 本轮未做 curated promotion，未改 trigger，未改 `knowledge/raw`。

### M8D.2：Curated Promotion Minimal Expansion

- 当前状态：已完成。
- 本阶段只允许做第二轮最小 curated promotion，不做 full promotion，不改 trigger，不改 `knowledge/raw`，不进入 broker/live/real-money。
- 第二轮最小集只允许新增少量 evidence-backed promoted theme；当前已新增：
  - `breakout_follow_through_failed_breakout`
  - `tight_channel_trend_resumption`
- 每条 promoted curated claim 必须保留：
  - `claim_id`
  - `field_mappings`
  - `evidence_refs`
  - `evidence_locator_summary`
  - `evidence_chunk_ids`
- transcript / Brooks 必须通过 promoted curated claim 的 evidence chain 进入 actual trace；但 promoted curated claim、`statement`、`source_note`、`contradiction`、`open_question` 仍不得进入 trigger。
- `reports/backtests/m8c1_long_horizon_daily_validation/` 必须重算并落盘，使 checked-in daily artifact 能展示第二轮最小 promoted theme 的 actual trace。
- 必须至少通过：
  - `tests/reliability/test_curated_promotion_minimal_set.py`
  - `tests/reliability/test_strategy_atom_trace.py`
  - `tests/reliability/test_long_horizon_daily_validation.py`
  - `tests/unit/test_strategy_signal_pipeline.py`
  - `python -m unittest discover -s tests/reliability -v`
  - `python -m unittest discover -s tests/unit -v`
- 当前完成事实：
  - 已新增 `knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md`
  - 已新增 `knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md`
  - 已更新 `knowledge/indices/curated_promotion_map.json`、`knowledge_atoms.jsonl` 与 `knowledge_callable_index.json`
  - 已重算 `reports/backtests/m8c1_long_horizon_daily_validation/`
  - 已保持 trigger 不变、`knowledge/raw` 不变、阶段 C 未开始

### M8D.3：Repository State Consistency

- 当前状态：已完成。
- 本阶段只允许做仓库口径对齐，不得借机修改 trigger、knowledge promotion、`knowledge/raw`、broker/live/real-money 或新增验证窗口。
- 必须至少同步并对齐：
  - `README.md`
  - `docs/status.md`
  - `plans/active-plan.md`
  - `docs/acceptance.md`
  - `docs/decisions.md`
  - `docs/roadmap.md`
- 若存在与当前主线状态直接相关的辅助说明漂移，也必须最小同步：
  - `docs/testing-reliability.md`
  - `docs/eval-rubric.md`
  - `docs/shadow-mode-runbook.md`
  - `tests/reliability/README.md`
  - `tests/golden_cases/README.md`
  - `tests/integration/README.md`
  - `tests/test_data/real_history_small/README.md`
  - `tests/test_data/real_history_small/sample_us_5m_recorded_session/README.md`
  - `reports/reliability/README.md`
- 必须明确：
  - `main` 是唯一长期稳定基线
  - 当前主线已进入 `M8：可靠性验证`
  - `M8 shadow/paper baseline` 是已完成前置基线
  - `M8D.1`、`M8D.2`、`M8D.3` 的状态已完成
  - `feature/m7-broker-api-assessment` 只保留为历史阶段/里程碑分支
- 若修改 `scripts/run_shadow_session.py` 的 help / 文案，必须通过 `python -m py_compile scripts/run_shadow_session.py`。
- 必须至少完成 repo-wide drift audit，确认不再保留以下主显示口径：
  - “当前分支：feature/m7-broker-api-assessment”
  - “当前阶段：M7 正式券商 API 接入评估（已完成）”
  - “当前阶段仅完成 M8A 测试骨架”
- 必须保持：
  - trigger 逻辑不变
  - `knowledge/raw` 不变
  - 不进入 broker/live/real-money
  - 继续保持 `paper / simulated`
- 当前完成事实：
  - 仓库主线文档与辅助 README 已统一到 `main + M8 + M8 shadow/paper baseline + M8D.1/.2/.3`。
  - 旧的“`feature/m7-broker-api-assessment` 是当前分支/稳定基线”表述已从主显示口径中移除。
  - 旧的 “M8A skeleton only” README 口径已替换为当前实际存在的测试与报告说明。
  - 本阶段未改 trigger，未改 `knowledge/raw`，未新增新的验证扩展。

### M8E.1：Validation Gap Closure

完成条件：

- 只允许收口“更长窗口 daily validation 之前必须修”的验证缺口，不得进入 `M8E.2` 的更长窗口 daily run，不得进入 intraday 更长窗口。
- checked-in artifact 的路径元数据必须统一为 repo-relative logical path；至少覆盖：
  - `reports/backtests/m8c1_long_horizon_daily_validation/summary.json`
  - `reports/backtests/m8c1_long_horizon_daily_validation/report.md`
  - checked-in intraday pilot `summary.json` 中的 `cache_csv` / `cache_metadata` / `report_dir`
- `m8c1_long_horizon_daily_validation/summary.json` 必须新增 `sample_adequacy`，至少包含：
  - `overall_verdict`
  - `by_split[]`
  - `split_name`
  - `split_label`
  - `executed_trade_count`
  - `minimum_required_executed_trades`
  - `verdict`
- `sample_adequacy` 的最小规则固定为：
  - 每个 split 独立评估
  - `executed_trade_count >= 5` 记为 `adequate`
  - `< 5` 记为 `insufficient_sample`
- `report.md` 必须新增“样本充分性”小节，并明确 `insufficient_sample` 代表“验证诚实但样本不足”，不是伪造通过。
- 必须至少通过：
  - `tests/golden_cases/test_catalog_smoke.py`
  - `tests/unit/test_public_backtest_demo.py`
  - `tests/reliability/test_long_horizon_daily_validation.py`
  - `tests/reliability/test_intraday_pilot_validation.py`
  - `python scripts/run_reliability_suite.py`
  - `python -m unittest discover -s tests/reliability -v`
  - `python -m unittest discover -s tests/unit -v`
- `scripts/run_reliability_suite.py` 的 `golden` suite 不得再长期因为“无测试文件”而只剩 safe skip；至少要有 catalog smoke test 可执行。
- artifact `trades.csv` 必须保持稳定 LF 写出，不因本地解释器差异引入无意义 CRLF 漂移。
- 必须保持：
  - trigger 逻辑不变
  - `knowledge_trace` contract 不变
  - `knowledge/raw` 不变
  - 继续保持 `paper / simulated`
  - 不进入 broker/live/real-money
- 当前完成事实：
  - 已把 checked-in daily / intraday summary path 元数据统一为 repo-relative logical path。
  - 已为 `m8c1_long_horizon_daily_validation` 增加 `sample_adequacy`，并把 `validation` / `out_of_sample` 明确标为 `insufficient_sample`。
  - 已新增 golden catalog smoke test，并补强 artifact portability / sample adequacy 一致性回归。
  - 本阶段未改 trigger，未改 `knowledge_trace` contract，未改 `knowledge/raw`。

### M8E.2：Longer-Window Daily Validation

完成条件：

- 只允许在 `paper / simulated` 边界内，把 daily public history validation 扩展到更长窗口；不得进入 intraday 更长窗口、broker/live/real-money，也不得改 trigger。
- 验证范围固定为：
  - 标的：`NVDA / TSLA / SPY`
  - 周期：`1d`
  - 时间范围：`2018-01-01 ~ 2026-04-17`
- 必须新增：
  - `config/examples/public_history_backtest_longer_window.json`
  - checked-in run `reports/backtests/m8e2_longer_window_daily_validation/`
- 新 run 必须至少落盘：
  - `summary.json`
  - `report.md`
  - `knowledge_trace.json`
  - `knowledge_trace_coverage.json`
  - `no_trade_wait.jsonl`
  - `trades.csv`
  - `split_summary.json`
  - `regime_breakdown.json`
  - `equity_curve.png`
- 新 run 必须继续保持：
  - repo-relative artifact path
  - `sample_adequacy`
  - actual refs / bundle support 分层
  - `paper / simulated`
- 若某个 split 仍然 `insufficient_sample`，报告与 summary 必须明确写为“验证诚实但样本不足”，不得包装成通过。
- 必须至少通过：
  - `tests/reliability/test_longer_window_daily_validation.py`
  - `tests/reliability/test_long_horizon_daily_validation.py`
  - `tests/reliability/test_intraday_pilot_validation.py`
  - `tests/golden_cases/test_catalog_smoke.py`
  - `python scripts/run_reliability_suite.py`
  - `python -m unittest discover -s tests/reliability -v`
  - `python -m unittest discover -s tests/unit -v`
- 必须保持：
  - trigger 逻辑不变
  - `statement` / `source_note` / `contradiction` / `open_question` 不进入 trigger
  - `knowledge/raw` 不变
  - 不进入 intraday 更长窗口
  - 不进入 broker/live/real-money
- 当前完成事实：
  - 已新增 `config/examples/public_history_backtest_longer_window.json`。
  - 已新增 checked-in run `reports/backtests/m8e2_longer_window_daily_validation/`，并完整落盘 canonical artifact。
  - 当前 longer-window daily run 的 `in_sample` 为 `adequate`，`validation` / `out_of_sample` 仍为 `insufficient_sample`，并已在 `summary.json` / `report.md` 显式说明。
  - 已新增 `tests/reliability/test_longer_window_daily_validation.py`，并通过 reliability / unit / suite 全量回归。

### M8 Shadow/Paper Baseline：真实历史数据稳健性 + 实时 shadow / paper 验证框架

完成条件：

- 允许的真实输入只包括：用户导出的真实历史 CSV/JSON、免费公共数据源的本地快照、实时只读输入。
- 明确要求所有输出仍然停留在 `shadow / paper`，不得进入真实 broker、真实账户或 live execution。
- 明确要求真实输入下系统仍然保守、稳定、可解释，资料不足时仍允许 `wait / no-trade`。
- 明确要求任何 broker / live 的重新评估都排在 `M8` 完成之后。
- reviewer 与 qa 都必须把 “无越权到 broker/live” 作为强制审查项。
- M8D 不引入付费服务前置条件，不把浏览器自动化写成生产执行链路。
- `docs/shadow-mode-runbook.md` 必须存在，并明确 manifest、shadow/paper 命令、deferred 语义与 `paper / simulated` 边界。
- `scripts/run_shadow_session.py` 必须可通过 `python -m py_compile`，并默认保持只读输入、simulated 输出、无真实 broker 依赖。
- `scripts/run_shadow_session.py` 在未提供 manifest 时必须返回 deferred，而不是伪造真实历史验证已完成。
- repo-safe 小样本 manifest 必须存在，并能证明 M8D 框架可运行但不等于真实历史验证已完成。
- `tests/reliability/test_regime_robustness.py`、`tests/reliability/test_shadow_paper_consistency.py` 与 `tests/reliability/test_dataset_manifest_contract.py` 必须通过。
- `reports/reliability/README.md` 必须明确报告不是盈利证明，并保留 dataset/session/traceability 最小字段要求。
- public-history 入口的当前 `primary_provider` 必须由 repo config 中的 `source_order[0]` 解析，而不是在验收文档中写死某个 provider 名称。
- 公共历史数据缓存目录必须落在本地不跟踪目录，并且缓存文件能继续通过 `src/data/` 的 schema 校验与重复加载。
- `scripts/run_public_backtest_demo.py` 或等价一键入口必须能基于缓存数据生成：
  - `report.md`
  - `trades.csv`
  - `summary.json`
  - `equity_curve.png`
- 用户可读报告必须明确：测试标的、时间范围、数据来源、总收益/总盈亏、最大回撤、交易笔数、胜率、盈亏比、代表性交易解释与局限。
- 该 public-history demo 仍只属于研究/演示能力，不得被写成真实 broker、真实账户、live execution 或实盘能力证明。

## 阶段 9：Price Action Strategy Lab

<!-- strategy_factory_provider_contract={"active_provider_config_path":"config/strategy_factory/active_provider_config.json","primary_provider_runtime_source":"source_order[0]"} -->

完成条件：

- 已从 `main` 切出独立分支 `feature/m9-price-action-strategy-lab`，且 `main` 未被直接开发。
- 已生成 `reports/strategy_lab/m9_initial_project_snapshot.md`，至少记录：
  - 初始分支
  - 初始 commit
  - `git status`
  - 当前 M8 进度摘要
  - `knowledge/raw/`、`knowledge/wiki/`、`reports/backtests/` 目录概览
  - `paper / simulated`、`no-go`、不得接真实账户、不得自动实盘下单等边界
- 已把 M9 正式写入 `plans/active-plan.md`、`docs/status.md`、`docs/decisions.md`。
- 已保留 legacy `knowledge/wiki/strategy_cards/`，并包含：
  - `index.md`
  - `templates/strategy-card-template.md`
  - `templates/strategy-test-plan-template.md`
  - `brooks/`
  - `fangfangtu/`
  - `combined/`
- 已新增新的 Strategy Factory 根目录：
  - `knowledge/wiki/strategy_factory/index.md`
  - `knowledge/wiki/strategy_factory/strategies/`
  - `knowledge/wiki/strategy_factory/specs/`
  - `knowledge/wiki/strategy_factory/test_plans/`
- `scripts/validate_kb.py` 与 `scripts/build_kb_index.py` 已支持：
  - `candidate / tested / promoted / rejected` 状态枚举
  - strategy card 额外字段
  - strategy factory 额外字段
  - 跳过 `templates/` 目录
- 已新增或更新最小自动化验证，覆盖：
  - strategy card 正向校验
  - templates 跳过
  - strategy card 缺字段失败
  - strategy factory page 正向校验
  - build_kb_index 收录 strategy card 扩展字段
- 已保留 legacy M9 baseline 产物：
  - `m9_source_inventory.md`
  - `m9_strategy_extraction_log.md`
  - `m9_strategy_test_plan_index.md`
  - `m9_strategy_lab_summary.md`
  - `PA-SC-*` strategy cards 与 `PA-SC-002` 相关历史回测/诊断报告
- legacy `PA-SC-*` 目录与报告已明确标注为 `legacy / historical baseline`：
  - 不得作为新 catalog 的 seed、family prior、默认 merge target 或 triage baseline
  - `PA-SC-002` 只允许作为 historical benchmark / regression reference
- 已建立 Strategy Factory 运行台账：
  - `reports/strategy_lab/strategy_factory/coverage_ledger.json`
  - `reports/strategy_lab/strategy_factory/extraction_queue.json`
  - `reports/strategy_lab/strategy_factory/catalog_ledger.json`
  - `reports/strategy_lab/strategy_factory/backtest_queue.json`
  - `reports/strategy_lab/strategy_factory/triage_ledger.json`
  - `reports/strategy_lab/strategy_factory/run_state.json`
  - `reports/strategy_lab/strategy_factory/final_summary.md`
- 已建立 provider contract 配置：
  - `config/strategy_factory/active_provider_config.json`
- 已完成 `M9 Strategy Factory Full Extraction Completeness Audit v4`，并至少生成：
  - `reports/strategy_lab/strategy_catalog.json`
  - `reports/strategy_lab/strategy_dedup_map.json`
  - `reports/strategy_lab/chunk_adjudication.jsonl`
  - `reports/strategy_lab/source_family_completeness_report.json`
  - `reports/strategy_lab/source_theme_coverage.json`
  - `reports/strategy_lab/cross_chunk_synthesis.json`
  - `reports/strategy_lab/cross_source_corroboration.json`
  - `reports/strategy_lab/cross_source_corroboration_final.json`
  - `reports/strategy_lab/overmerge_review.json`
  - `reports/strategy_lab/saturation_report.json`
  - `reports/strategy_lab/unresolved_strategy_extraction_gaps.json`
  - `reports/strategy_lab/full_extraction_audit.json`
  - `reports/strategy_lab/factory_summary.md`
  - `reports/strategy_lab/cards/`
  - `reports/strategy_lab/specs/`
- `coverage_ledger.json` 已满足：
  - `knowledge/indices/source_manifest.json` 是唯一 coverage SoT
  - 全部 `10` 个 in-scope source 都已入账
  - 每个 source 只能处于 `pending / mapped / partial / blocked / parked` 之一
  - `fangfangtu-beginner-note` 已显式纳入
  - `fangfangtu-wedge-note` 已显式标为 `partial`
  - `al-brooks-price-action-ppt-37-52-units` 已显式保留为独立 source
- `run_state.json` 已至少包含：
  - `factory_run_id`
  - `current_phase`
  - `resume_cursor`
  - `active_batch_id`
  - `active_provider_config_path`
  - `primary_provider`
  - `heartbeat_status`
  - `last_summary_at`
- `python scripts/validate_strategy_factory_contract.py` 必须通过，并至少确认：
  - repo config、`plans/active-plan.md`、`docs/status.md`、`docs/acceptance.md` 的 provider contract marker 一致
  - `primary_provider` 只来自 `active_provider_config_path -> source_order[0]`
  - `run_state.json` 与 contract config 一致
- 若 repo config 与 `plans/active-plan.md`、`docs/status.md`、`docs/acceptance.md` 的 provider contract 不一致，`Contract Freeze` 必须失败，且不得进入提炼或回测。
- M9 必须继续保持：
  - `paper / simulated`
  - 不改 trigger
  - 不改 `knowledge/raw`
  - 不进入 broker/live/real-money
- 全部 parseable chunks 必须完成 full-pass 审计，且：
  - `unresolved = 0`
  - `unmapped = 0`
  - `transcript / PPT / notes` 三个 family 全量复审完成
- `Cross-Chunk Synthesis Pass`、`Overmerge Review`、`Notes Per-Source Findings`、`Source Section / Unit / Theme Coverage Matrix`、`Cross-Source Corroboration Report`、`Saturation / Convergence Pass` 必须全部落盘。
- `cross_source_corroboration_final.json` 必须在 catalog freeze 之后重算，文档与 summary 只能引用 final 版本。
- `saturation_report.json` 必须满足双轮连续零增量 closure 条件。
- `full_extraction_audit.json` 必须同时写出：
  - `text_extractable_closure = true`
  - `full_source_closure` 明确结论
  - `closure_scope_reason`
- 若 `full_source_closure = false`，则 `unresolved_strategy_extraction_gaps.json` 必须存在且完整。
- 本阶段仍不得启动任何 batch backtest；`ready_for_backtest` 只能作为结论字段存在，不得自动执行。
- 至少通过：
  - `python scripts/validate_kb.py`
  - `python scripts/build_kb_index.py`
  - `python scripts/validate_kb_coverage.py`
  - `python scripts/validate_knowledge_atoms.py`
  - `python scripts/validate_strategy_factory_contract.py`
  - `python -m unittest discover -s tests/unit -v`
  - `python -m unittest discover -s tests/reliability -v`
  - `python -m unittest discover -s tests/integration -v`
  - `python scripts/run_reliability_suite.py`

## 阶段 9H：Controlled Batch Backtest + Strategy Triage

完成条件：

- 只能基于已冻结的 `SF-*` catalog、`cross_source_corroboration_final.json` 与 provider contract 启动，且不得回退到 legacy `PA-SC-*` 作为 seed 或 triage baseline。
- 启动前必须通过 `python scripts/validate_strategy_factory_contract.py`。
- 当前 wave 只能让 `SF-001 ~ SF-004` 进入 batch backtest eligibility；`SF-005` 必须因 `single_source_risk` 保持 deferred。
- 必须落盘：
  - `reports/strategy_lab/backtest_eligibility_matrix.json`
  - `reports/strategy_lab/backtest_dataset_inventory.json`
  - `reports/strategy_lab/executable_spec_queue.json`
  - `reports/strategy_lab/backtest_queue.json`
  - `reports/strategy_lab/backtest_batch_summary.json`
  - `reports/strategy_lab/strategy_triage_matrix.json`
  - `reports/strategy_lab/final_strategy_factory_report.md`
  - `reports/strategy_lab/final_strategy_factory_trade_report.md`
  - `reports/strategy_lab/final_strategy_factory_cash_report.md`
- 若进入 wave2 或后续扩样本回测，必须把 `dataset_count`、`symbols`、`coverage_start`、`coverage_end` 写入 `backtest_batch_summary.json`、`automation_state.json` 与最终报告。
- 若某个 best variant 选中 `quality_filter`，必须明确标记为 `diagnostic_selected_variant`，不得写成正式冻结策略、validated rule 或默认生产版本。
- 若同一 strategy/variant 出现 `R` 口径与 cash 口径异号，必须在 merge gate 报告和现金报告中明确解释其为独立 sizing layer 的结果；未解释则不得通过合并门禁。
- 每个冻结策略必须生成 `reports/strategy_lab/<strategy_id>/` 目录；对已测试策略还必须生成 variant 级 artifact。
- 若 runner 改为多数据集聚合，则每个已测试 variant 还必须生成 `reports/strategy_lab/<strategy_id>/variants/<variant_id>/datasets/<symbol>/` 的数据集级 artifact。
- triage 结果必须清楚区分：
  - `modify_and_retest`
  - `insufficient_sample`
  - `retain_candidate`
  - `rejected_variant`
  - `deferred_single_source_risk`
  - 其他 parked/deferred 状态
- 本轮不得把任何结果写成实盘能力、稳定盈利或可自动交易。
- 本轮必须继续保持：
  - `paper / simulated`
  - 不改 trigger
  - 不改 `knowledge/raw`
  - 不进入 broker/live/real-money
- 若样本已扩展到多标的、多时间窗，`robust_candidate` 只表示样本覆盖达到更高门槛，不得被解释成稳定盈利、实盘 readiness 或自动交易能力。
- wave2 完成后不得自动继续下一波 batch backtest；merge gate 通过后的默认下一步是更窄范围的 `v0.2 spec freeze`。
- 至少通过：
  - `python scripts/validate_strategy_factory_contract.py`
  - `python scripts/validate_kb.py`
  - `python scripts/build_kb_index.py`
  - `python -m unittest tests/unit/test_strategy_factory_backtest_eligibility.py tests/unit/test_strategy_factory_queue.py tests/unit/test_strategy_triage.py -v`
  - `python -m unittest tests/reliability/test_strategy_factory_pipeline.py -v`
  - `python -m unittest discover -s tests/unit -v`

## 阶段 9I.1：Freeze v0.2 Candidate Specs

完成条件：

- 只允许基于 `Wave2` 已被选中的 `quality_filter` 观察结果生成 `v0.2-candidate`；不得新增未测试过的过滤器、阈值组合或策略 family。
- 只能生成：
  - `reports/strategy_lab/specs/SF-001-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-002-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-003-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-004-v0.2-candidate.yaml`
- 现有 `reports/strategy_lab/specs/SF-001.yaml ~ SF-004.yaml` 必须保留为 `v0.1` 基线；`strategy_catalog.json` 必须继续保持 `catalog_status = frozen`，且 `final_strategy_count = 5`。
- 每个 `v0.2-candidate` 文件必须是完整自包含 spec，并至少包含：
  - `spec_version = v0.2-candidate`
  - `candidate_status = frozen_candidate`
  - `base_spec_ref`
  - `selected_variant_id = quality_filter`
  - `selected_variant_role = diagnostic_selected_variant`
  - `wave2_run_id`
  - `wave2_artifacts`
  - `rule_overrides`
  - `change_log`
  - `expected_failure_mode_improvements`
  - `residual_risks`
  - `validation_scope = wave3_robustness_validation_candidate`
  - `validation_claims`
- 每个 `v0.2-candidate` 必须可追溯到：
  - `reports/strategy_lab/backtest_batch_summary.json`
  - `reports/strategy_lab/strategy_triage_matrix.json`
  - 对应 `reports/strategy_lab/SF-00x/summary.json`
  - 对应 `reports/strategy_lab/SF-00x/diagnostics.md`
  - 对应 `reports/strategy_lab/SF-00x/variants/quality_filter/summary.json`
  - `reports/strategy_lab/final_strategy_factory_trade_report.md`
  - `reports/strategy_lab/final_strategy_factory_cash_report.md`
- `rule_overrides` 必须与 `Wave2` 已测试实现完全一致：
  - `SF-001`: `signal_bar_body_ratio_min = 0.50`，`max_pullback_bars = 2`
  - `SF-002`: `breakout_bar_body_ratio_min = 0.60`，`follow_through_bar_body_ratio_min = 0.60`
  - `SF-003`: `range_height_to_avg_bar_range_max = 6.0`，`reversal_body_ratio_min = 0.55`
  - `SF-004`: `channel_overlap_ratio_max = 0.35`
- `SF-005` 必须继续保持 `deferred_single_source_risk`，不得生成 `SF-005-v0.2-candidate.yaml`。
- 必须新增 `reports/strategy_lab/v0_2_spec_freeze_summary.md`，明确：
  - 本轮只冻结 `v0.2-candidate`
  - `quality_filter` 是 `diagnostic_selected_variant`
  - 本轮未新增未测试过滤器
  - `SF-005` 继续 deferred
  - 本轮不自动进入 `Wave3`
- 本阶段不得：
  - 启动新的 batch backtest
  - 新增 strategy cards
  - 继续提炼知识来源
  - 处理 visual gaps
  - 改 trigger
  - 进入 broker/live/real-money
- 至少通过：
  - `python scripts/validate_strategy_factory_contract.py`
  - `python scripts/validate_kb.py`
  - `python -m unittest tests/unit/test_strategy_catalog.py tests/unit/test_strategy_triage.py tests/unit/test_v0_2_candidate_specs.py tests/unit/test_strategy_factory_docs_sync.py -v`
  - `git diff --check`

## 阶段 9I.2：Wave3 Holdout / Walk-forward Robustness Validation

完成条件：

- 只允许加载冻结后的：
  - `reports/strategy_lab/specs/SF-001-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-002-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-003-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-004-v0.2-candidate.yaml`
- 本阶段不得：
  - 修改上述 4 份 frozen spec
  - 新增 strategy cards
  - 继续提炼知识来源
  - 改 trigger 核心语义
  - 进入 broker/live/real-money
  - 把 `SF-005` 纳入本轮
- Wave3 必须至少落盘：
  - `reports/strategy_lab/wave3_robustness_summary.md`
  - `reports/strategy_lab/wave3_robustness_summary.json`
  - `reports/strategy_lab/SF-001/wave3/`
  - `reports/strategy_lab/SF-002/wave3/`
  - `reports/strategy_lab/SF-003/wave3/`
  - `reports/strategy_lab/SF-004/wave3/`
- 每个策略的 `wave3/` 子目录至少包含：
  - `summary.json`
  - `holdout_summary.json`
  - `walk_forward_windows.csv`
  - `symbol_breakdown.csv`
  - `regime_breakdown.csv`
  - `time_of_day_breakdown.csv`
  - `cost_stress.json`
  - `conversion_analysis.json`
- Wave3 必须显式覆盖：
  - holdout / out-of-sample validation
  - walk-forward / rolling-window validation
  - symbol-level breakdown
  - regime-level breakdown
  - time-of-day breakdown
  - cost / slippage stress
  - candidate event -> executed trade conversion analysis
  - robustness score
- 切分必须满足：
  - `core_history / proxy_holdout / strict_post_freeze_holdout` 彼此不重叠
  - walk-forward 的 `IS / OOS` 不重叠
  - walk-forward 的任何窗口都不能泄漏进 proxy / strict holdout
- triage 结果只能落入：
  - `retain_candidate`
  - `modify_and_retest`
  - `insufficient_sample`
  - `rejected_variant`
  - `parked`
- 若不存在 strict post-freeze holdout，则本轮不得输出 `retain_candidate`。
- `strategy_triage_matrix.json` 必须保留 Wave2 历史，并追加 Wave3 history，不得覆盖 `SF-005` 的 deferred 历史事实。
- `reports/strategy_lab/backtest_dataset_inventory.json` 必须更新为本轮实际使用的数据窗口与 provider 来源。
- 至少通过：
  - `python scripts/validate_strategy_factory_contract.py`
  - `python scripts/validate_kb.py`
  - `python -m unittest discover -s tests/unit -v`
  - `python -m unittest tests/reliability/test_strategy_factory_pipeline.py -v`
  - `git diff --check`

## 阶段 10：Price Action Strategy Refresh

完成条件：

- 必须从 `main` 创建独立分支 / worktree：`codex/m10-price-action-strategy-refresh`。
- 必须先完成 workspace / worktree / branch audit，并把旧 M8/M9、`PA-SC-*`、`SF-*`、旧 reports/specs/catalog/triage 登记为 legacy-only。
- Clean-room extraction 阶段不得读取或参考：
  - `knowledge/wiki/strategy_cards/`
  - `reports/strategy_lab/strategy_catalog.json`
  - `reports/strategy_lab/cards/`
  - `reports/strategy_lab/specs/`
  - `reports/strategy_lab/strategy_triage_matrix.json`
- 新策略 namespace 固定为 `M10-PA-*`。
- 来源优先级固定为：
  - `brooks_v2_manual_transcript`
  - `fangfangtu_youtube_transcript`
  - `fangfangtu_notes`
- Brooks v2 单源支撑不得仅因缺少 YouTube/notes 交叉验证而被拒绝。
- FangFangTu YouTube 单源支撑不得仅因缺少 Brooks/notes 交叉验证而被拒绝。
- Notes-only 条目必须降级为 `research_only` 或 `needs_corroboration`。
- 必须登记 ChatGPT share 与 Codex thread 为 reference-only，不得作为策略 source of truth。
- 必须导入 / 登记 Brooks v2 manual transcript：
  - `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/README.md`
  - `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/`
  - `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/evidence/`
  - `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/manifest.json`
  - `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/checksums.sha256`
  - `knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/assets_evidence_checksums.sha256`
- 图片资产 `assets/evidence/` 必须按 local-only + checksum 管理，不得默认纳入普通 Git 跟踪。
- 必须更新 source manifest / chunk / atom / callable builder，使 Brooks v2、YouTube transcript、notes 可独立检索。
- 必须生成：
  - `reports/strategy_lab/m10_price_action_strategy_refresh/strategy_catalog_m10.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/source_support_matrix_m10.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/chatgpt_bpa_comparison.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/legacy_comparison_m10.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_gap_ledger.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/backtest_eligibility_matrix.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_test_plan.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_catalog_review.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/strategy_catalog_m10_frozen.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_strategy_test_queue.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_golden_cases/`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_visual_golden_case_index.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_visual_case_selection_ledger.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_2_visual_review_summary.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_3_backtest_spec_handoff.md`
- M10.1 catalog freeze 必须满足：
  - 当前 frozen catalog 共 `16` 条 `M10-PA-*` 策略/规则条目。
  - `backtest_wave_a` 只能包含 `M10-PA-001`、`M10-PA-002`、`M10-PA-005`、`M10-PA-012`。
  - `backtest_wave_b_candidate` 当前只能包含 `M10-PA-013`；高视觉策略只有通过 M10.2 visual golden case 后才可进入 Wave B。
  - `visual_golden_case_first` 只能包含 `M10-PA-003`、`M10-PA-004`、`M10-PA-007`、`M10-PA-008`、`M10-PA-009`、`M10-PA-010`、`M10-PA-011`。
  - `supporting_rule` 只能包含 `M10-PA-014`、`M10-PA-015`，且不得生成独立 entry trigger。
  - `research_only` 只能包含 `M10-PA-006`、`M10-PA-016`。
  - Visual golden case 不是所有策略的统一前置门槛；只对 `visual_golden_case_first` 队列生效。
  - `strategy_catalog_m10_frozen.json` 不得出现旧 `PA-SC-*` 或 `SF-*` 策略 ID。
- M10.1 Wave A 测试队列必须满足：
  - `M10-PA-001`、`M10-PA-002`、`M10-PA-005` 测试线为 `1d / 1h / 15m / 5m`。
  - `M10-PA-012` 测试线为 `15m / 5m`。
  - 每条必须规划 candidate events、skip/no-trade ledger、source ledger、成本/滑点敏感性、per-symbol、per-regime、failure-mode notes。
  - M10.1 不允许输出 `retain/promote`；只允许 `needs_definition_fix`、`needs_visual_review`、`continue_testing`、`reject_for_now`。
- M10.2 Visual Golden Case Pack 必须满足：
  - visual pack 只覆盖 `M10-PA-003`、`M10-PA-004`、`M10-PA-007`、`M10-PA-008`、`M10-PA-009`、`M10-PA-010`、`M10-PA-011`。
  - 每个 `visual_pack_ready` 策略至少包含 `3` 个 Brooks v2 正例、`1` 个反例、`1` 个边界例。
  - 每个 case 必须包含 `strategy_id`、`case_type`、Brooks unit ref、evidence image logical path、checksum、pattern decision points、disqualifiers、OHLCV approximation risk、review status。
  - Brooks v2 图片资产必须继续按 local-only + checksum 管理；tracked artifact 只保存 logical path 和 checksum。
  - `M10-PA-001/002/005/012/013/014/015/006/016` 不得进入 visual golden case pack。
  - `m10_3_backtest_spec_handoff.md` 只能记录 Wave A spec freeze 承接，不得生成正式 backtest spec、回测结论或 `retain/promote`。
- M10.3 Backtest Spec Freeze 必须满足：
  - 只生成 `M10-PA-001`、`M10-PA-002`、`M10-PA-005`、`M10-PA-012` 四条 Wave A backtest specs。
  - `M10-PA-001/002/005` 的测试周期必须为 `1d / 1h / 15m / 5m`；`M10-PA-012` 必须只允许 `15m / 5m`。
  - 每份 spec 必须包含 `schema_version = m10.backtest-spec.v1`、`stage = M10.3.backtest_spec_freeze`、`strategy_id`、`title`、`timeframes`、`paper_simulated_only`、`source_refs`、`source_ledger_ref`、`event_definition`、`entry_rules`、`stop_rules`、`target_rules`、`skip_rules`、`cost_model_policy`、`sample_gate_policy`、`outputs_required`、`allowed_outcomes`、`not_allowed`。
  - `allowed_outcomes` 只能是 `needs_definition_fix`、`needs_visual_review`、`continue_testing`、`reject_for_now`。
  - spec、index、event ledger、skip ledger、policy artifact 中不得出现 legacy `PA-SC-*` 或 `SF-*`。
  - `M10-PA-014/015` 只能作为 supporting rules 被引用，不得生成独立 entry trigger。
  - `M10-PA-003/004/007/008/009/010/011`、`M10-PA-013`、`M10-PA-006/016` 不得进入 Wave A spec index。
  - 成本敏感性 policy 必须固定 baseline `1 bps`、stress low `2 bps`、stress high `5 bps`。
  - 样本门槛必须固定为每个 strategy/timeframe 至少 `30` 个 candidate events，且 skip 后至少 `10` 个 executed trades；低于门槛只能标记 `continue_testing` 或 `needs_definition_fix`。
  - M10.3 不得运行 historical backtest，不得输出收益结论、`retain/promote`、broker connection、live execution 或 real orders。
- M10.4 Historical Backtest Pilot 必须满足：
  - 只运行 Wave A：`M10-PA-001/002/005` 的 `1d / 1h / 15m / 5m`，以及 `M10-PA-012` 的 `15m / 5m`。
  - 不运行 visual-first、Wave B candidate、supporting-only 或 research-only 条目作为 entry trigger。
  - Daily 默认窗口必须为 `2010-06-29 ~ 2026-04-21`，不得回退到短窗口；若某标的实际数据起点更晚，必须写入 dataset inventory。
  - 数据解析顺序必须优先当前 worktree `local_data/`，其次 sibling main worktree `/home/hgl/projects/Price-Action-Trader/local_data/`；本地仍缺失时只能生成 `data_unavailable_deferred`，不得伪造事件或交易。
  - `15m / 1h` 若从 `5m` 聚合，必须在 dataset inventory 中记录 `derived_from_5m` lineage。
  - 必须输出 `m10_4_data_availability.json`、`m10_4_dataset_inventory.json`、`m10_4_wave_a_pilot_summary.json`、`m10_4_wave_a_pilot_report.md`，以及每个 strategy/timeframe 的 candidate events、skip/no-trade ledger、source ledger、成本敏感性、per-symbol、per-regime、failure-mode notes。
  - outcome 只能是 `needs_definition_fix`、`needs_visual_review`、`continue_testing`、`reject_for_now`。
  - 不得输出 `retain/promote`、收益证明、broker connection、live execution 或 real orders。
- M10.5 Read-only Observation Plan 必须满足：
  - 只制定只读观察方案，不启动实时观察 runner，不接 broker，不下单，不批准 paper trading。
  - observation queue 只能包含 `M10-PA-001`、`M10-PA-002`、`M10-PA-005`、`M10-PA-012`。
  - `M10-PA-001/002/005` 只能规划 `1d / 1h / 15m / 5m`；`M10-PA-012` 只能规划 `15m / 5m`。
  - visual-first、Wave B candidate、supporting-only、research-only 条目不得进入 read-only queue。
  - `1d` 必须规划为 regular session close 后观察；`1h / 15m / 5m` 必须规划为 regular-session bar close 后记录。
  - event schema 必须包含 strategy、symbol、timeframe、bar timestamp、event/skip、hypothetical entry/stop/target、source/spec refs、data source、review status，并强制 `paper_simulated_only=true`、`broker_connection=false`、`real_orders=false`、`live_execution=false`。
  - M10.4 daily 长窗口 `2010-06-29 ~ 2026-04-21` 与 `15m / 1h = derived_from_5m` lineage 必须在 M10.5 artifacts 中被引用。
  - candidate density 过高的 strategy/timeframe 必须标记 `definition_breadth_review`；该标记不得基于 PnL 自动拒绝策略。
  - 若没有实时只读输入方案，必须写入 `observation_input_deferred`，不得补假事件。
  - M10.5 artifacts 不得出现 legacy `PA-SC-*` 或 `SF-*` 策略 ID 污染。
- M10.6 Read-only Observation Input / Ledger Prototype 必须满足：
  - 只使用本地 cached OHLCV 做 recorded replay，不接 broker、不接真实账户、不订阅实时行情、不下单。
  - 必须只加载 M10.5 observation queue 中的 `M10-PA-001/002/005/012`；`M10-PA-012` 只能生成 `15m / 5m` ledger。
  - visual-first、Wave B candidate、supporting-only、research-only 条目不得进入 M10.6 ledger。
  - `1d` ledger 必须按收盘后观察语义生成；`1h / 15m / 5m` ledger 必须按 regular-session bar-close 语义生成。
  - ledger row 必须符合 `m10_5_observation_event_schema.json`，并强制 `paper_simulated_only=true`、`broker_connection=false`、`real_orders=false`、`live_execution=false`。
  - `15m / 1h` 从 `5m` 派生时，input manifest 与 summary 必须记录 `derived_from_5m` lineage。
  - 数据缺失时只能写入 `m10_6_deferred_inputs.json`，不得生成 synthetic observation event。
  - M10.6 summary / report 不得输出收益证明、paper gate approval、live-ready 或策略状态升级结论。
  - M10.6 不得修改 `src/risk/`、`src/execution/`、`src/broker/` 的 live 行为。
- M10.7 Business Metric Policy 必须满足：
  - 必须生成 `m10_7_business_metric_policy.md`、`m10_7_capital_model.json`、`m10_7_client_report_template.md`。
  - capital model 必须固定币种 `USD`、初始本金 `100000.00`、单笔风险当前权益 `0.50%`、不使用杠杆、允许 fractional shares 保持模拟确定性。
  - 成本压力必须固定为 baseline `1 bps`、stress low `2 bps`、stress high `5 bps`。
  - 后续甲方成绩单必备指标必须包括 initial capital、final equity、net profit、return percent、trade count、win rate、profit factor、max drawdown、max consecutive losses、average holding bars。
  - M10.7 只冻结后续资金曲线模拟口径，不运行新回测，不接 broker、不接真实账户、不下单、不批准 paper trading。
- M10.8 Wave A Capital Backtest 必须满足：
  - 只覆盖 `M10-PA-001`、`M10-PA-002`、`M10-PA-005`、`M10-PA-012`；`M10-PA-012` 只能覆盖 `15m / 5m`。
  - 必须使用 M10.4 candidate events 的 `entry/stop/exit` 字段按 M10.7 capital model 重新计算仓位、成本、权益、胜率和回撤，不得直接把 R 值当作资金曲线。
  - 必须输出 `m10_8_wave_a_metrics.csv`、`m10_8_wave_a_trade_ledger.csv`、`m10_8_wave_a_strategy_scorecard.md`、`m10_8_wave_a_client_report.md`、`m10_8_wave_a_capital_summary.json` 与 `m10_8_wave_a_equity_curves/`。
  - metrics 必须覆盖 strategy、strategy/timeframe、strategy/timeframe/symbol 与 cost tier 粒度，并包含 M10.7 必备甲方指标。
  - trade ledger 必须包含 `event_id`、`trade_id`、risk budget、risk-budget quantity、notional-cap quantity、gross/cost/net PnL、equity before/after 与 source/spec refs。
  - `M10-PA-005` 的 `1h / 15m / 5m` 必须保留 `definition_breadth_review` / `needs_definition_fix`，不得因资金结果自动升级。
  - M10.8 不得接 broker、不接真实账户、不下单、不批准 paper trading，也不得输出 real execution 能力结论。
- M10.9 Definition Tightening 必须满足：
  - 只覆盖 `M10-PA-005`，不得修改其他 Wave A 策略定义或资金口径。
  - 收紧依据只能是结构性清理：重复确认去重、同标的同方向日内 20-bar 冷却；不得使用 PnL、资金曲线、胜率或 profit factor 做调参依据。
  - 必须输出 `m10_9_definition_filter_ledger.json`、`m10_9_before_after_metrics.csv`、`m10_9_retest_summary.json`、`m10_9_definition_fix_report.md`、`m10_9_wave_a_retest_client_summary.md`。
  - 必须明确记录 M10.4 candidate events 缺少 `range_high/range_low/range_midpoint/breakout_extreme/reentry_confirmation_index`，因此 `M10-PA-005` 不能解除 `needs_definition_fix`。
  - M10.9 不得接 broker、不接真实账户、不下单、不批准 paper trading，也不得输出 real execution 能力结论。
- M10.10 Visual Wave B Gate 必须满足：
  - 只复核 `M10-PA-003/004/007/008/009/010/011` 的 visual golden case pack。
  - 必须输出 `m10_10_visual_strategy_review.md`、`m10_10_wave_b_entry_queue.json`、`m10_10_visual_client_summary.md` 与结构化 summary。
  - Wave B queue 只能包含 gate 通过的视觉策略与既有 `M10-PA-013` candidate；Wave A、supporting-only、research-only 策略不得进入 queue。
  - `M10-PA-011` 只能进入 `15m / 5m`，不得扩成 daily 或 `1h`。
  - M10.10 不得运行回测，不得接 broker、不接真实账户、不下单、不批准 paper trading，也不得输出 real execution 能力结论。
- M10.11 Wave B Capital Backtest 必须满足：
  - 只覆盖 M10.10 queue 中的 `M10-PA-013/003/008/009/011`，不得跑未通过 visual gate 的策略。
  - 必须输出 `m10_11_wave_b_metrics.csv`、`m10_11_wave_b_trade_ledger.csv`、`m10_11_wave_b_strategy_scorecard.md`、`m10_11_wave_b_client_report.md`、`m10_11_wave_b_capital_summary.json` 与 `m10_11_wave_b_equity_curves/`。
  - 必须沿用 M10.7 资本模型和三档成本压力，trade ledger 必须包含 entry/stop/target/exit、risk budget、gross/cost/net PnL、equity before/after 与 source/spec refs。
  - `M10-PA-011` 只能输出 `15m / 5m`，`15m / 1h` 数据 lineage 必须保留 `derived_from_5m`。
  - M10.11 不得接 broker、不接真实账户、不下单、不批准 paper trading，也不得输出 real execution 能力结论。
- 测试规划必须明确：
  - Daily、1h、15m、5m 是独立测试线；日线不是 5m 辅助过滤器。
  - OHLCV 可近似量化策略进入 historical backtest queue。
  - 高视觉依赖策略进入 visual review / golden-case queue。
  - 阶段顺序为 historical backtest -> realtime read-only observation -> paper trading -> live approval。
- 本阶段不得：
  - 接真实 broker
  - 接真实账户
  - 自动实盘下单
  - 修改 live execution / risk / broker 行为
  - 把 M9 legacy 结果作为 M10 入选先验
- 至少通过：
  - `python scripts/validate_kb.py`
  - `python scripts/validate_kb_coverage.py`
  - `python scripts/validate_knowledge_atoms.py`
  - `python -m unittest tests/unit/test_m10_strategy_refresh.py tests/unit/test_m10_backtest_spec_freeze.py tests/reliability/test_kb_coverage.py -v`
  - `python -m unittest tests/unit/test_m10_historical_pilot.py -v`
  - `python -m unittest tests/unit/test_m10_read_only_observation_plan.py -v`
  - `python -m unittest tests/unit/test_m10_read_only_observation_replay.py -v`
  - `git diff --check`
