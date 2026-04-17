# 项目状态

## 当前阶段

- 阶段 8：可靠性验证（进行中）

## 当前 milestone

- M8：可靠性验证（进行中）
- 当前子阶段：M8B.2b：Callable 接入 Strategy / Explanation / Review / Report（已完成并整合进稳定基线）

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
- M8A 已完成主线与门禁文档切换：`plans/active-plan.md`、`docs/acceptance.md`、`docs/status.md`、`docs/roadmap.md`、`docs/decisions.md`
- M8A 已新增 `docs/testing-reliability.md` 与 `docs/eval-rubric.md`，冻结 M8 的测试目标、输入边界、评分维度与硬门禁
- M8A 已新增 `docs/test-dataset-curation.md`，冻结 M8 可接受数据层级、样本元数据、脱敏与离线边界
- M8A 已落盘 `tests/golden_cases/`、`tests/integration/`、`tests/reliability/`、`reports/reliability/` 的 discoverable 骨架目录
- M8A 已新增 `scripts/run_reliability_suite.py`，默认运行当前 baseline unit suites，并对空目录或缺真实历史样本显式 skipped / deferred
- M8B 已新增 `src/strategy/alignment.py`，提供最小 knowledge alignment 评估入口
- M8B 已收紧 `src/strategy/knowledge.py` 的 `source_refs` 校验：缺失或不存在的 wiki/raw refs 现在会硬失败
- M8B 已在 `tests/golden_cases/cases/` 落盘 5 个 golden cases，覆盖 placeholder setup、news role conflict、insufficient evidence、not_applicable hard gate、missing/fake refs hard fail
- M8B 已新增 `tests/reliability/test_kb_alignment.py`、`tests/reliability/test_no_hallucinated_kb_refs.py`、`tests/reliability/test_no_trade_when_insufficient_evidence.py`
- M8B 已验证 reliability suite 7 项通过，且原有 `tests/unit/` 57 项无回归
- M8B 已于 2026-04-17 通过 merge commit `0047100` 从 `integration/m8-reliability-validation` 整合进稳定基线 `feature/m7-broker-api-assessment`
- M8C 已新增 `tests/integration/test_offline_e2e_pipeline.py`，覆盖 `src/data -> src/strategy -> src/backtest -> src/risk -> src/execution -> src/news -> src/review` 的离线端到端集成链路
- M8C 已新增 `tests/reliability/test_replay_determinism.py`、`tests/reliability/test_no_future_leakage.py`、`tests/reliability/test_audit_traceability.py`、`tests/reliability/test_forbidden_paths.py`
- M8C 已覆盖 deterministic replay 一致性、bars / news future leakage fail-fast、forbidden paths、audit/review traceability、`end_of_data`、缺 bar gap 与重复 bar 稳健性
- M8C 已验证 `tests/reliability` 18 项、`tests/integration` 4 项、`tests/unit` 57 项通过；`python scripts/run_reliability_suite.py` 当前合计执行 79 项本地离线测试
- M8C 保持 `paper / simulated` 与 `no-go` 边界，未新增真实 broker、真实账户或 live execution 路径
- M8D 已新增 `docs/shadow-mode-runbook.md` 与 `scripts/run_shadow_session.py`，固定 manifest 驱动的只读 shadow/paper 验证路径
- M8D 已新增 repo-safe 小样本 manifest：`tests/test_data/real_history_small/sample_us_5m_recorded_session/dataset.manifest.json`
- M8D 已新增 `tests/reliability/test_regime_robustness.py`、`tests/reliability/test_shadow_paper_consistency.py`、`tests/reliability/test_dataset_manifest_contract.py`
- M8D 已补齐 `docs/test-dataset-curation.md` 的 small/large dataset、realtime recording 与受控标签规范，并更新 `reports/reliability/README.md` 的报告最小字段
- M8D 当前已具备：manifest 校验、shadow/paper dry-run、报告 traceability、无样本 deferred 语义；尚未实际运行用户真实历史样本或录制型实时样本
- 已新增 `scripts/download_public_history.py`，支持优先使用 Alpha Vantage（若环境已有 key）、否则回退到 `yfinance` 下载公共历史数据并缓存为本地 CSV
- 已新增 `scripts/run_public_backtest_demo.py` 与 `scripts/run_public_backtest_demo.sh`，可在本地缓存基础上直接生成用户可读的历史回测演示报告
- 已新增 `config/examples/public_history_backtest_demo.json` 与 `docs/user-backtest-guide.md`，固定第一轮演示范围为 `NVDA / TSLA / SPY`、`2024-01-01 ~ 2024-06-30`、`1d`
- 已完成一轮公共历史数据演示回测：`yfinance` 下载的本地缓存已落在 `local_data/public_history/`，示例 run `demo_public_2024h1` 生成于 `reports/backtests/demo_public_2024h1/`
- 该示例 run 在当前 demo 风控参数下输出：总收益率 `1.9923%`、最大回撤 `1.5157%`、交易 `16` 笔、胜率 `43.75%`；仍明确保持 `paper / simulated`
- M8B.1 已完成知识源接入诊断与最小补齐：确认 transcript / Brooks PPT 先前缺席的根因是 raw-only、无 `source` 页、未入 active rule pack，且默认 strategy bundle 未读取 rule pack；现已新增真实存在文件的 `source` 页、补齐 rule-pack/index 接线，并让默认 signal 链能带出这些 `source` 页引用
- M8B.1 已新增 `docs/knowledge-source-trace.md` 与 `tests/reliability/test_knowledge_source_trace.py`，验证“已接线的 transcript/PPT 来源能进入 `source_refs`，未接线时不会被编造”
- M8B.2 已拆成两个子阶段：
  - `M8B.2a`：Source Registry + Chunk Registry + Knowledge Atom Schema + Builders/Validators + Callable Index
  - `M8B.2b`：仅在 `2a` 全部测试通过、未触发熔断且 reviewer / qa 通过后，才允许接 strategy / explanation / review / report
- M8B.2 的长期边界保持不变：`statement` 是中间层 callable atom，不是 executable rule，不得参与 trigger 判定
- M8B.2a 已完成：
  - 已新增 `knowledge/schema/source-registry-schema.md`、`chunk-registry-schema.md`、`knowledge-atom-schema.md`、`callable-access-contract.md`
  - 已新增 `knowledge/indices/source_manifest.json`、`chunk_manifest.jsonl`、`knowledge_atoms.jsonl`、`knowledge_callable_index.json`
  - 已新增 `scripts/build_source_manifest.py`、`build_chunk_registry.py`、`build_knowledge_atoms.py`、`build_callable_index.py`、`validate_kb_coverage.py`、`validate_knowledge_atoms.py`
  - 已补齐 5 份方方土笔记 source page 与 2 份 Brooks PPT per-file source page
  - 当前 source coverage 结果为 `parsed=9 / partial=1 / blocked=0`，未触发 `blocked >= 4` 熔断
  - 当前 partial source 为 `方方土视频笔记 - 楔形.pdf`，原因为 `1 page(s) produced no stable text`
  - 已落盘 `statement` atom，当前原子统计为：`statement=11171`、`source_note=5492`、`open_question=24`、`concept=1`、`setup=1`、`rule=1`
  - 关键 curated atoms 已形成 evidence-backed atom：`market-cycle-overview`、`signal-bar-entry-placeholder`、`m3-research-reference-pack`
  - 已新增 `tests/reliability/test_kb_coverage.py`、`test_knowledge_atoms.py`、`test_callable_access.py`
  - 已通过 `tests/reliability` 39 项与 `tests/unit` 60 项回归
  - M8B.2a.1 已完成 statement 质量审计与 merge gate，审计结论为 `pass_with_small_fixes`
  - 已完成最小修复：收紧 statement 提取条件，去除明显页眉页脚 / 时间轴 / 起始标点 / 未完成碎片，并对同一 source 内的 statement 做保守去重
  - 当前 statement 分布为：`al_brooks_ppt=11042`、`fangfangtu_transcript=88`、`fangfangtu_notes=41`
  - 当前重复/噪音摘要为：`exact_dup_extra=13`、`normalized_dup_extra=16`、`trailing_open=0`、`datey=0`、`start_punct=0`
  - 已于 2026-04-17 通过 merge commit `23755c0` 从 `feature/m8b2-knowledge-atomization-callable-access` 整合进稳定基线 `feature/m7-broker-api-assessment`
- M8B.2b 已完成：
  - 已新增 `src/strategy/knowledge_access.py`，提供 callable atom query、curated-first trace resolver、transitional view 与 legacy `source_refs` 聚合 helper。
  - `Signal` 已新增 `knowledge_trace`，`ReviewItem` 已新增 `kb_trace`，并保持 legacy `source_refs` / `kb_source_refs` 兼容。
  - `knowledge_trace` 当前只接入 trace / explanation / review / report；`statement`、`source_note`、`contradiction`、`open_question` 仍不得进入 trigger。
  - 已新增 source family 失衡保护：curated atom 优先、statement/source-note trace 去重、限量、按 source family 做多样性控制，不允许用 atom 数量当作 confidence 或 trigger 权重。
  - public demo 已新增 machine-readable `knowledge_trace.json`，Markdown `report.md` 只展示精简 trace 摘要，每笔代表性交易最多 3 条。
  - 已通过 `tests/reliability/test_strategy_atom_trace.py`、`tests/unit/test_strategy_signal_pipeline.py`、`tests/unit/test_news_review_pipeline.py`、`tests/unit/test_public_backtest_demo.py`、`python -m unittest discover -s tests/reliability -v`、`python -m unittest discover -s tests/unit -v`。
  - M8B.2b 已从 `feature/m8b2b-knowledge-trace-integration` 整合回稳定基线 `feature/m7-broker-api-assessment`。

## 当前阻塞

- 当前无阻塞
- 真实 broker / live 重新评估仍冻结，直到 M8 完成且用户另行批准；这不阻塞当前 M8 主线

## 下一步

- 当前下一步不是扩 broker/live，而是基于最新稳定基线继续做更长周期或更细粒度的 `paper / simulated` 验证。
- `M8B.2b` 已整合进稳定基线；trigger 逻辑未改变，`statement` 仍未进入 trigger。
- 当前稳定基线继续保持 `paper / simulated` 与 `no-go` 边界。
- 完成 M8 前，不重新评估真实 broker、真实账户、live execution 或付费 API。
