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
