# 阶段验收

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
  - M8C 已在 `integration/m8c-offline-reliability` 完成实现与验证，且仍保持 `paper / simulated` 与 `no-go` 边界。

### M8B.2a：Knowledge Atomization 基础层

完成条件：

- `M8B.2` 已在 `plans/active-plan.md`、`docs/status.md`、`docs/acceptance.md`、`docs/decisions.md` 与 `docs/knowledge-atomization.md` 中拆成 `2a / 2b`。
- 当前轮次明确只执行 `2a`，不得提前进入 `2b`。
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
- 10 个 in-scope source 都必须存在 machine-readable source record。
- `:Zone.Identifier` 必须被过滤并进入 `coverage_summary.filtered_files`，不得被误判为 source。
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
  - `source_manifest.json` 当前结果为 `parsed=9 / partial=1 / blocked=0`
  - 当前 partial source 为 `方方土视频笔记 - 楔形.pdf`
  - 当前未触发熔断
  - 关键 curated atoms 已形成 evidence-backed atom
  - `statement` 已落盘并满足 evidence-backed / non-executable / non-trigger 约束
  - M8B.2a.1 已完成 statement 质量审计，结论为 `pass_with_small_fixes`
  - 审计后的最小修复只限于：收紧 statement 提取条件、去除明显页眉页脚 / 时间轴 / 起始标点 / 未完成碎片、修正同一 source 内的明显重复
  - 审计后 statement 分布为：`al_brooks_ppt=11048`、`fangfangtu_transcript=81`、`fangfangtu_notes=42`
  - 审计后噪音门槛结果为：`exact_dup_extra=13`、`normalized_dup_extra=16`、`trailing_open=0`、`datey=0`、`start_punct=0`
  - 已于 2026-04-17 通过 merge commit `23755c0` 从 `feature/m8b2-knowledge-atomization-callable-access` 合并进稳定基线 `feature/m7-broker-api-assessment`
  - `M8B.2b` 仍未开始，必须从最新稳定基线重新开分支

### M8B.2b：Callable 接入 Strategy / Explanation / Review / Report

启动前提：

- `M8B.2a` 全部测试通过
- 未触发熔断
- reviewer 通过
- qa 通过

在满足以上条件前，不得启动 `2b`。

### M8C：离线端到端可靠性测试

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

### M8D：真实历史数据稳健性 + 实时 shadow / paper 验证框架

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
- `scripts/download_public_history.py` 必须支持：优先使用 Alpha Vantage（仅当环境已提供 key），否则回退到 `yfinance`，并将结果缓存为本地 CSV，而不是每次回测都临时联网抓取。
- 公共历史数据缓存目录必须落在本地不跟踪目录，并且缓存文件能继续通过 `src/data/` 的 schema 校验与重复加载。
- `scripts/run_public_backtest_demo.py` 或等价一键入口必须能基于缓存数据生成：
  - `report.md`
  - `trades.csv`
  - `summary.json`
  - `equity_curve.png`
- 用户可读报告必须明确：测试标的、时间范围、数据来源、总收益/总盈亏、最大回撤、交易笔数、胜率、盈亏比、代表性交易解释与局限。
- 该 public-history demo 仍只属于研究/演示能力，不得被写成真实 broker、真实账户、live execution 或实盘能力证明。
