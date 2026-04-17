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
