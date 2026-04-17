# Price Action Trader Active Plan（V2 可执行版）

## 1. 当前状态

- 本计划用于替换初始化模板，并驱动后续全部实施。
- 当前已接受基线为 M0 基础设施初始化，基线提交为 `96259ad`。
- M1 已完成知识库 schema、KB 校验、wiki index、资料投放流程的最小闭环。
- M2 已完成测试数据、OHLCV schema、CSV/JSON 回放的最小闭环。
- M3 已完成 PA context、setup、signal 输出的 research-only 最小闭环。
- M4 已完成最小回测引擎与报告的 deterministic baseline。
- M5 已完成 paper-only 的模拟执行与风控闭环。
- M6 已完成新闻过滤与复盘整合，且保持新闻只作辅助因子。
- M7 已完成正式券商 API readiness assessment，当前冻结结论为 `no-go`。
- 当前分析基线固定为 `main`。
- `feature/m7-broker-api-assessment` 保留为历史阶段/里程碑分支，不再作为未来默认合并目标。
- `M8B` 已于 merge commit `0047100` 从 `integration/m8-reliability-validation` 整合进稳定基线 `feature/m7-broker-api-assessment`。
- M8 的基础离线可靠性红线与 shadow/paper 框架已完成并冻结，作为后续验证主线的前置基线。
- `M8C` 当前已切换为 `Long-Horizon & Intraday Paper Validation`：
  - `M8C.1：长周期日线验证` 已完成并整合进稳定基线
  - `M8C.2：单标的日内试点` 已完成实现与验收，待整合进 `main`
- `M8B.1` 已完成知识源接入诊断与最小补齐：补齐 transcript / Brooks PPT 的 `source` 页、rule-pack / index 接线，并修复默认 strategy bundle 读取 active rule pack 的缺口。
- `M8B.2a：Knowledge Atomization 基础层` 已完成，`M8B.2b：Knowledge Trace 接入` 已完成并整合进稳定基线。

## 2. 执行总原则

- Source of Truth 固定为：`AGENTS.md`、`docs/requirements.md`、`docs/architecture.md`、`docs/data-sources.md`、`docs/pa-strategy-spec.md`、`docs/roadmap.md`、`docs/acceptance.md`、`docs/implement.md`、`docs/branching.md`、`docs/status.md`。
- 当前阶段必须从轻资产验证开始，不把正式券商 API、真实账户、实盘自动下单作为前置条件。
- 浏览器自动化只允许排在后续验证或只读观察路径，不得进入前置 milestone。
- 每个 milestone 完成条件固定为：范围符合 plan、验证已运行、reviewer 通过、qa 通过、`docs/status.md` 已同步、存在清晰回退点；高风险里程碑还必须标记人工复核。
- 回退边界固定为每个已验收 milestone 的分支终点；未合并分支直接废弃，已合并 milestone 通过 revert 该 milestone 合并提交回退。
- 当前初始回退点固定为 `96259ad`。

## 3. 分支策略

- 禁止直接在 `main`、`master` 或稳定主线上开发。
- 每个 milestone 开始前必须从最近一个已验收检查点创建新分支。
- milestone 分支命名固定为：
  - `feature/m1-kb-ingestion-index`
  - `feature/m2-data-schema-replay`
  - `feature/m3-pa-signal-prototype`
  - `feature/m4-backtest-report`
  - `feature/m5-papertrading-risk`
  - `feature/m6-news-review-integration`
  - `feature/m7-broker-api-assessment`
  - `integration/m8-reliability-validation`
- 当前与后续所有新的 `feature/*`、`fix/*`、`docs/*`、`test/*`、`integration/*` 分支都从 `main` 切出。
- 低/中风险阶段验收通过后的默认合并目标是 `main`。
- `feature/m7-broker-api-assessment` 仅保留为历史阶段基线/里程碑分支，不再作为未来默认长期合并目标。
- 并行写代码时优先使用独立 branch 或 worktree。
- 涉及 `src/execution/`、`src/risk/`、`src/broker/`、凭证、实盘开关的改动必须单独分支、单独测试、单独复核。

## 4. Subagent 策略

- 若 milestone 内存在 2 个以上独立子任务、同时涉及知识库与代码、同时涉及探索/实现/审查/测试、跨多个模块边界、或触及高风险目录，则必须显式创建 subagent。
- `planner`：用于 milestone 启动、依赖变化、阻塞后重排和阶段切换。
- `researcher`：用于只读摸底、现状差距定位、接口与风险点搜集。
- `data_engineer`：负责样本、schema、回放、时区与数据质量。
- `kb_curator`：负责 raw→wiki 整理、来源登记、source refs、`missing_visuals` 和样例页。
- `implementer`：负责有边界的实现与必要的最小文档改动。
- `reviewer`：负责合并前审查正确性、回归风险、分支规范和高风险边界。
- `qa`：负责里程碑验收、失败路径验证和验收清单核对。
- 所有 subagent 输出必须遵守 `docs/handoff-protocol.md`。

## 5. 防死循环与熔断

- 同一子任务连续失败 3 次，必须熔断。
- 同一 reviewer 连续打回 3 次，必须熔断。
- 熔断后必须输出 Failure Dossier。
- 熔断后暂停该任务，不得盲目重试。
- 只有在用户补充关键决策、权限、凭证或接受降级方案后，才能继续该任务。

## 6. Milestone 顺序

- M0 已完成 → M1 知识库 schema / KB 校验 / wiki index / 资料投放流程 → M2 测试数据 / 数据 schema / CSV-JSON 回放 → M3 PA context / setup / signal 原型 → M4 最小回测与报告 → M5 纸面交易 / 模拟执行 / 风控闭环 → M6 新闻过滤与复盘整合 → M7 正式券商 API 接入评估 → M8 可靠性验证。
- 第一实施波次固定为：M1 完成后进入 M2。
- 不得把浏览器自动化、正式券商 API、真实账户、实盘自动下单前置到 M1 或 M2。
- 在完成 M8 可靠性验证前，不重新评估真实 broker、真实账户、live execution 或付费 API。

## 7. M0 基础设施与规范基线

- 分支：已完成于 `feature/m0-infra-v2`
- 目标：完成仓库结构、Codex agent 配置、规则文档、知识库目录、测试样本、KB 脚本、GitHub 推送能力的初始化。
- 当前验收状态：视为已通过，可作为后续全部开发基线。
- 验证基线：
  - `python -m py_compile scripts/validate_kb.py scripts/build_kb_index.py`
  - `python scripts/validate_kb.py`
  - 空 wiki 校验
  - GitHub remote 与 push 已打通
- 回退点：`96259ad`

## 8. M1 知识库 schema、KB 校验、wiki index、资料投放流程

- 分支：`feature/m1-kb-ingestion-index`
- 当前状态：已完成
- 目标：把 `knowledge/raw/` → `knowledge/wiki/` → `knowledge/wiki_index.json` 的基础流转做成可重复执行、可校验、可回退的最小闭环。
- 交付内容：
  - 统一 `knowledge/schema/*` 与 KB 脚本的字段契约。
  - 补齐 wiki 页面类型与 frontmatter 约束。
  - 明确 raw 投放、source refs、`missing_visuals`、冲突记录与整理流程。
  - 让 `validate_kb.py` 与 `build_kb_index.py` 对空目录、代表性页面、字段缺失和 setup 页面必填项都能给出稳定结果。
- 关键接口：
  - wiki frontmatter 字段集以 `knowledge/schema/page-frontmatter-template.md` 为准。
  - 索引输出字段至少保持 `path`、`title`、`type`、`status`、`confidence`、`market`、`timeframes`、`direction`、`source_refs`、`pa_context`、`tags`、`open_questions`。
- 验证方式：
  - 空 wiki 与非空 wiki 两条路径都要跑通。
  - 至少覆盖 `concept`、`setup`、`source` 三类代表性页面。
  - `python scripts/validate_kb.py` 和 `python scripts/build_kb_index.py` 必须可重复执行。
  - 索引结果需与 frontmatter 一致。
- 验收条件：
  - raw 层不可变原则未被破坏。
  - wiki 页面可被校验与索引。
  - KB 入库流程文档清晰。
  - reviewer 确认 raw/wiki/schema 未混淆。
  - qa 确认脚本行为与 frontmatter 约束一致。
- 可并行子任务：
  - `kb_curator` 负责样例页面与来源规范。
  - `implementer` 负责脚本与模板对齐。
  - `researcher` 负责找出 schema 与脚本差距。
  - `qa` 负责空目录、缺字段、setup 特殊字段的验收。
- 依赖：只依赖 M0。
- 风险：
  - schema 与脚本再次漂移
  - 样例页字段不全
  - 将猜测写入 wiki
- 回退点：
  - 若 M1 未通过，直接废弃 `feature/m1-kb-ingestion-index`
  - 若已合并，回退到 M0 基线
- 实际完成摘要：
  - 已补齐 `concept`、`setup`、`source` 三类代表性 wiki 页面。
  - 已统一 `knowledge/schema/*`、frontmatter 模板、`validate_kb.py`、`build_kb_index.py` 的契约。
  - 已补充 M1 验收条目，并完成空目录、当前 wiki、代表性样本与负向校验。
  - reviewer 与 qa 已通过。

## 9. M2 测试数据、OHLCV schema、CSV/JSON 回放 adapter

- 分支：`feature/m2-data-schema-replay`
- 当前状态：已完成
- 目标：建立可供策略、回测和 QA 复用的本地数据最小闭环，优先围绕 `tests/test_data/` 和用户导出文件，不引入外部付费或浏览器依赖。
- 交付内容：
  - 明确 OHLCV 与新闻 JSON schema。
  - 实现本地 CSV/JSON 读取、字段归一化、timezone 解析、重复检查、价格关系校验、非法值处理和 deterministic bar replay。
  - 保留对后续 adapter 的抽象边界。
- 关键接口：
  - OHLCV 最小字段固定为 `symbol`、`market`、`timeframe`、`timestamp`、`timezone`、`open`、`high`、`low`、`close`、`volume`。
  - 新闻样本至少包含 `symbol`、`market`、`timestamp`、`source`、`event_type`、`headline`、`severity`、`notes`。
- 验证方式：
  - 以 `tests/test_data/ohlcv_sample_5m.csv` 与 `tests/test_data/news_sample.json` 为主样本。
  - 覆盖时间解析、排序、重复时间戳、高低价关系、空值或非法值。
  - 验证 replay 输出 bar 顺序稳定，不依赖外部网络。
- 验收条件：
  - 数据导入与 replay 可在本地独立运行。
  - 策略与回测可以消费统一结构。
  - reviewer 确认没有把浏览器或第三方 SDK 写入核心数据路径。
  - qa 确认异常样本能正确报错或拦截。
- 可并行子任务：
  - `data_engineer` 负责 schema、清洗规则和异常样本。
  - `implementer` 负责 replay adapter。
  - `researcher` 负责现有脚本与模块落点。
  - `qa` 负责样本矩阵。
- 依赖：
  - M1 的知识库字段约束应已稳定。
  - 代码层只依赖 M0。
- 风险：
  - 时间区与市场字段不一致
  - 样本过少导致回放接口设计偏差
- 回退点：
  - 若 M2 失败，保留 M1 产物不动，废弃 `feature/m2-data-schema-replay`
- 实际完成摘要：
  - 已新增 `src/data/schema.py`，固定 OHLCV、新闻事件、ValidationError、CleanedRecord 等最小稳定契约。
  - 已新增本地 CSV/JSON loader 与 deterministic replay，统一消费 schema 契约。
  - 已建立 `tests/unit/test_data_pipeline.py`，覆盖正向样本、重复键、非法 market、非法 severity、非法 timezone、aware timestamp 归一化和统一类型输出。
  - reviewer 与 qa 已通过，确认核心数据路径未引入浏览器或第三方 SDK。

## 10. M3 PA context、setup、signal 输出原型

- 分支：`feature/m3-pa-signal-prototype`
- 当前状态：已完成
- 目标：在不接入实盘的前提下，用规则化、可解释、可追溯的方式产出最小交易信号原型。
- 交付内容：
  - 建立 PA context、setup、signal 的内部表示。
  - 信号输出至少包含 `signal_id`、`symbol`、`market`、`timeframe`、`direction`、`setup_type`、`pa_context`、`entry_trigger`、`stop_rule`、`target_rule`、`invalidation`、`confidence`、`source_refs`、`explanation`、`risk_notes`。
  - 要求每个 setup 能回溯到知识库规则。
- 关键接口：
  - PA 字段以 `docs/pa-strategy-spec.md` 和 KB frontmatter 为准。
  - 信号只用于研究、回测和模拟，不得直连执行。
- 验证方式：
  - 使用 M1 的知识页与 M2 的 replay 数据。
  - 覆盖无信号、单信号、多信号、失效条件和缺 `source_refs` 的路径。
- 验收条件：
  - 信号对象结构稳定且可解释。
  - setup 与 `source_refs` 可追溯。
  - reviewer 确认没有把未经验证规则写成稳定盈利策略。
  - qa 确认输出字段完整。
- 可并行子任务：
  - `kb_curator` 负责把知识页整理成可引用规则。
  - `implementer` 负责信号原型。
  - `researcher` 负责策略输入输出界面梳理。
  - `qa` 负责解释性与字段完整性。
- 依赖：M1 和 M2。
- 风险：
  - 过早把知识库抽象成黑箱规则
  - 信号字段缺少解释性
- 回退点：回退到 M2 已验收检查点
- 实际完成摘要：
  - 已新增 `knowledge/wiki/rules/m3-research-reference-pack.md` 与 `knowledge/wiki/rules/m3_signal_reference_index.json`，形成 research-only 的最小知识引用层。
  - 已新增 `src/strategy/` 最小 contracts / knowledge / context / signal 原型，且 strategy 层只消费 M2 的 `OhlcvRow`、`NewsEvent` 与 `DeterministicReplay` 契约。
  - 已建立 `tests/unit/test_strategy_signal_pipeline.py`，覆盖无信号、单信号、traceability、placeholder 低置信度、news 只作风险说明、缺失 `source_refs` 早失败、invalidation、多信号稳定性。
  - reviewer 与 qa 已通过，确认信号字段完整、来源可追溯、research-only 边界清晰，且未越界到 execution / risk / broker / 外部 API。

## 11. M4 最小回测引擎与报告

- 分支：`feature/m4-backtest-report`
- 当前状态：已完成
- 目标：基于静态 OHLCV 与 M3 信号，生成可复现的最小回测结果与报告，不伪造收益结论。
- 交付内容：
  - 最小 trade lifecycle、交易记录、胜率、盈亏比、期望值、最大回撤、交易频率、滑点敏感性统计。
  - 输出复盘或回测摘要，明确数据不足和假设边界。
- 关键接口：
  - 回测输入固定为本地 replay 数据与结构化信号。
  - 输出需能被后续 review/simulation 消费。
- 验证方式：
  - 固定样本运行结果可重复。
  - 覆盖零交易、单交易、多交易、止损/目标命中、样本不足等路径。
  - 验证统计口径与报告字段一致。
- 验收条件：
  - 回测可重复运行，报告可解释。
  - 数据不足时不会给出伪确定性结论。
  - reviewer 确认没有暗含实盘假设。
  - qa 确认统计正确性与边界条件。
- 可并行子任务：
  - `data_engineer` 负责样本和统计口径。
  - `implementer` 负责引擎与报告。
  - `reviewer` 审查结果可信度。
  - `qa` 做回归样本验证。
- 依赖：M2、M3。
- 风险：
  - 信号与成交假设耦合过深
  - 回测统计口径不一致
- 回退点：回退到 M3 已验收检查点
- 实际完成摘要：
  - 已新增 `src/backtest/` 最小 contracts / engine / reporting，回测层只消费本地 bars / replay 与结构化 signal。
  - 已建立 `tests/unit/test_backtest_pipeline.py`，覆盖零交易、单交易、多交易、same-bar stop/target、end_of_data、news 不改收益、profit_factor 空值路径。
  - 已固定 deterministic baseline：next-bar-open entry、signal-bar extremum stop、固定 2R target、same-bar stop-first。
  - reviewer 与 qa 已通过，确认回测层未越界到 execution / risk / broker / 外部 API，且数据不足路径不会伪装成确定性收益统计。

## 12. M5 纸面交易、模拟执行与风控闭环

- 分支：`feature/m5-papertrading-risk`
- 当前状态：已完成
- 目标：在完全不触碰真实账户的前提下，完成信号 → 风控 → 建议订单 → 模拟成交 → 持仓状态 → 日志 的闭环。
- 交付内容：
  - `PaperBrokerAdapter` 最小实现。
  - 执行请求结构、风控校验链、连续亏损暂停、日内最大亏损、总仓位限制、集中度限制、止损规则、熔断与恢复条件。
  - 所有默认模式必须是 paper/simulated。
- 关键接口：
  - 执行层必须与 `src/execution/`、`src/risk/` 的高风险规则对齐。
  - 不得绕过风控直接下单。
  - 不得出现任何真实 broker 凭证路径。
- 验证方式：
  - 正常允许路径
  - 风控拦截路径
  - 模拟成交路径
  - 市场关闭路径
  - 重复信号路径
  - 连续亏损触发熔断路径
  - 恢复交易条件路径
- 验收条件：
  - 默认仍为模拟盘。
  - 风控失败会阻断执行。
  - 日志可用于复盘。
  - reviewer 确认未进入真实下单边界。
  - qa 覆盖高风险失败路径。
- 可并行子任务：
  - `implementer` 分离 paper execution 与 risk 模块。
  - `reviewer` 做高风险审查。
  - `qa` 执行阻断与异常路径。
  - `planner` 在高风险边界变更时重排。
- 依赖：M3、M4。
- 风险：
  - 执行层与风控接口耦合不清
  - 默认模式误入实盘语义
- 回退点：
  - M5 未通过不得合入
  - 若已合入，必须整体 revert M5 合并提交
- 实际完成摘要：
  - 已新增 `src/risk/` 最小 contracts / engine，固定 `RiskConfig`、`SessionRiskState`、`RiskDecision` 与 paper-only 风控状态流转。
  - 已新增 `src/execution/` 最小 contracts / paper adapter / state / logging，形成 signal -> risk decision -> suggested order -> simulated fill -> position state -> close-path audit log 的最小闭环。
  - 已补 request-binding 校验，显式阻断 stale / mismatched risk decision、duplicate signal、market closed、config_error、invalid_request 与风险超限路径。
  - 已建立 `tests/unit/test_paper_execution_pipeline.py`，覆盖 allow、risk_block、market_closed、duplicate_signal、loss-streak halt、manual recovery、config_error、invalid_request、mismatched / stale / direction-mismatch risk decision。
  - reviewer 与 qa 已通过，确认 paper-only 边界清晰、close-path 审计日志可复盘，且未越界到真实 broker / live execution。

## 13. M6 新闻事件过滤与复盘整合

- 分支：`feature/m6-news-review-integration`
- 当前状态：已完成
- 目标：把新闻/事件样本纳入解释和风险过滤链路，同时把 KB 规则引用、价格行为解释和结果统计纳入统一复盘输出。
- 交付内容：
  - 新闻只作为过滤、解释或风险提示因子。
  - 复盘结构中整合 signal 来源、KB 引用、PA 解释、新闻影响、入场/止损/目标、结果统计、错误原因和待改进项。
- 关键接口：
  - 新闻输入沿用 M2 JSON schema。
  - 输出不得把新闻情绪直接转成实盘订单。
- 验证方式：
  - 覆盖有新闻过滤、有新闻但不触发阻断、无新闻、高风险事件提示、复盘引用 KB `source_refs` 等场景。
- 验收条件：
  - 新闻不会直接触发下单。
  - 复盘可同时引用 KB、信号、结果和新闻。
  - reviewer 确认新闻仍处于辅助地位。
  - qa 确认复盘信息完整。
- 可并行子任务：
  - `kb_curator` 负责规则引用与复盘知识链接。
  - `implementer` 负责过滤和报告整合。
  - `qa` 负责新闻样本路径。
- 依赖：
  - M3、M4
  - 与 M5 只在输出接口稳定后可部分并行
- 风险：
  - 新闻模块越权成为主信号源
  - 复盘字段和回测字段分叉
- 回退点：回退到 M5 已验收检查点
- 实际完成摘要：
  - 已新增 `src/news/` 最小 `NewsMatch`、`NewsReviewNote`、`NewsFilterDecision` 与 `evaluate_news_context(...)`，固定新闻只作 filter / explanation / risk hint 的 research-only 辅助语义。
  - 已新增 `src/review/` 最小 `ReviewTradeOutcome`、`ReviewItem`、`ReviewReport` 与 `build_review_report(...)`，把 KB `source_refs`、PA explanation、news review notes、回测结果与执行阻断证据整合进统一复盘输出。
  - 已新增 `knowledge/wiki/rules/m6-news-review-evidence-pack.md`，并同步 `knowledge/wiki/index.md` 与 `knowledge/wiki/log.md`，登记 M6 的知识证据包与开放问题。
  - 已建立 `tests/unit/test_news_review_pipeline.py`，覆盖无新闻、caution、block、future-event leakage、防止缺失 `reference_timestamp`、review 中 filter / explanation / risk_hint 结构化透传、以及新闻不改写 signal 主字段。
  - reviewer 与 qa 已通过，确认新闻未越界到 signal / order / execution，future-event leakage 已关闭，且复盘输出保留结构化 `news_review_notes` 与可追溯的 `source_refs`。

## 14. M7 正式券商 API 接入评估

- 分支：`feature/m7-broker-api-assessment`
- 当前状态：已完成
- 目标：只做 readiness assessment，不做真实接入、不做真实下单、不做真实账户联通。
- 交付内容：
  - `FormalBrokerAdapter` 接口草案
  - 凭证隔离要求
  - 模拟验证前置条件
  - 测试策略
  - 人工审批清单
  - 是否进入下一阶段的 go/no-go 评估结论
- 关键接口：
  - 只允许定义 adapter contract、风险门禁与审批条件。
  - 不允许实现真实 broker 调用链。
- 验证方式：
  - reviewer 审查是否误入实盘边界。
  - qa 核对 go/no-go 清单是否覆盖凭证、模拟验证、人工批准、回退与审计要求。
- 验收条件：
  - 产出的是评估与门禁，而不是接入代码。
  - 正式 API 仍不是前置条件。
  - 若结论为 no-go，计划停留在模拟与研究阶段。
- 可并行子任务：
  - `planner` 负责阶段切换和决策门禁。
  - `researcher` 负责 API 能力调研。
  - `reviewer` 做高风险边界审查。
- 依赖：
  - M5 稳定闭环
  - M6 复盘整合完成
- 风险：
  - 评估阶段偷跑到接入实现
  - 凭证与审批门禁不足
- 回退点：
  - M7 仅产生评估文档与接口草案，若越界立即整体回退
- 实际完成摘要：
  - 已新增 `src/broker/` assessment-only contract draft，固定 `FormalBrokerAdapterDraft`、`BrokerCredentialPolicy`、`BrokerExecutionGateDependency`、`BrokerCapabilityRequirement` 与 `BrokerAssessmentEnvelope` 最小接口草案。
  - 已新增 `docs/broker-readiness-assessment.md` 与 `docs/broker-approval-checklist.md`，明确 capability matrix、credential isolation、approval gates、rollback boundary 与当前 `no-go` 结论。
  - 已新增 `tests/unit/test_broker_contract_assessment.py`，覆盖 contract shape、no-live invariant、risk / execution gate dependency 与无默认凭证字段。
  - reviewer 与 qa 已通过，确认 M7 仍停留在 readiness assessment，不含真实 broker SDK、外部网络调用、真实账户联通或 live execution 路径。
  - 当前阶段最终结论为 `no-go`；在用户明确批准外部权限、真实账户、付费服务或下一阶段评估前，系统继续停留在 paper / simulated。

## 15. M8 可靠性验证

- 分支：`integration/m8-reliability-validation`（M8A/M8B 已完成）；`M8B.2a` 已从 `feature/m8b2-knowledge-atomization-callable-access` 整合进稳定基线 `feature/m7-broker-api-assessment`
- 当前状态：进行中
- 当前子阶段：M8B.2a.1：Statement Quality Audit + Merge Gate（已完成）
- 目标：以行为可靠性而不是功能扩展为首目标，验证 M0-M7 既有交付物在知识约束、研究链可复现性、paper-only 安全性和真实输入下的保守稳定性。
- 总边界：
  - 默认运行边界仍为 `paper / simulated`
  - 不接真实资金
  - 不启用实盘自动下单
  - 不重开真实 broker、真实账户、live execution、付费 API 或浏览器生产化讨论
  - M8 完成前，不重新评估 broker / live
- 可接受输入边界：
  - P0：静态测试样本
  - P1：用户导出的真实历史 CSV/JSON
  - P2：免费公共数据源的本地快照
  - 实时只读输入：shadow / paper 观察路径
  - 明确不进入 P4 broker / live

### M8A：测试骨架与验收门禁落盘

- 当前状态：已完成
- 目标：
  - 将 M8 正式写入 `plans/active-plan.md`
  - 将 M8 验收条件写入 `docs/acceptance.md`
  - 将当前阶段切换写入 `docs/status.md`
  - 在 `docs/roadmap.md`、`docs/decisions.md` 中冻结 M8 位置与门禁
  - 新增 `docs/testing-reliability.md` 与 `docs/eval-rubric.md`
  - 落盘 `tests/golden_cases/`、`tests/integration/`、`tests/reliability/`、`reports/reliability/` 的 discoverable 骨架
  - 新增 `docs/test-dataset-curation.md`
  - 新增 `scripts/run_reliability_suite.py`，提供当前可靠性相关 suite 的本地统一入口
- 交付物类型：
  - 主线文档
  - 验收门禁
  - 评分规则
  - 阶段 runbook 总纲
  - 测试目录骨架
  - 数据集整理规范
  - 本地 suite 运行入口
- 验证方式：
  - reviewer 审查 M8 是否被定义为 M7 之后的当前下一阶段，而不是 broker 后续开发
  - qa 核对 `docs/status.md`、`docs/roadmap.md`、`docs/acceptance.md`、`docs/decisions.md` 是否同步
  - `python -m py_compile scripts/run_reliability_suite.py`
  - `python scripts/run_reliability_suite.py --list`
  - `python scripts/run_reliability_suite.py`
  - `python -m unittest discover -s tests/unit -v`
  - reviewer 与 qa 都把 “无越权到 broker/live” 作为硬门禁
- 验收条件：
  - `plans/active-plan.md` 已新增 M8 与 M8A/M8B/M8C/M8D
  - `docs/acceptance.md` 已新增阶段 8 验收
  - `docs/status.md` 已把下一步切到 M8，而不是继续 broker
  - `docs/roadmap.md` 已同步 M8 在 M7 之后的位置
  - `docs/decisions.md` 已新增 “先 M8、后 broker/live” 的冻结决策
  - `docs/testing-reliability.md` 与 `docs/eval-rubric.md` 只包含计划与门禁，不含实现细节
  - `docs/test-dataset-curation.md` 已说明可接受数据层级、样本元数据、脱敏与离线边界
  - `tests/golden_cases/`、`tests/integration/`、`tests/reliability/`、`reports/reliability/` 均已可发现且带 README/占位说明
  - `scripts/run_reliability_suite.py` 在无真实历史样本、无 M8B/M8C/M8D 测试文件时可安全运行，并显式输出 skipped / deferred 提示
- 可并行子任务：
  - `planner` 负责冻结主线与阶段切换
  - `researcher` 负责核对附件与现有 SoT 的一致性
  - `implementer` 负责骨架目录、README、数据集规范与 suite 入口落盘
  - `reviewer` 负责高风险边界审查
  - `qa` 负责门禁完整性复核
- 依赖：
  - M7 已完成且当前结论为 `no-go`
  - 当前分析基线固定为 `main`
- 风险：
  - 把 M8 写成收益优化或 broker 延续阶段
  - 在门禁文档或脚手架中混入 M8B/M8C/M8D 的具体实现细节
  - 未同步 `docs/roadmap.md` 导致 SoT 再次分叉
  - 在无真实历史样本时误报“真实稳健性已通过”
- 回退点：
  - 若 M8A 文档越界，整体回退 `integration/m8-reliability-validation` 上的文档改动，回到当时的稳定基线提交；该历史基线分支仍保留为 `feature/m7-broker-api-assessment`
- 实际完成摘要：
  - 已补齐 `tests/golden_cases/`、`tests/integration/`、`tests/reliability/`、`reports/reliability/` 的 README 骨架。
  - 已新增 `docs/test-dataset-curation.md`，冻结 M8 可接受数据层级、最小元数据、脱敏与离线边界。
  - 已新增 `scripts/run_reliability_suite.py`，默认运行当前稳定存在的 baseline unit suites，并对空目录或缺真实历史样本显式 skipped / deferred。
  - 已验证新增骨架不会破坏 `python -m unittest discover -s tests/unit -v`。

### M8B：知识库对齐测试

- 当前状态：已完成
- 目标：
  - 定义 golden-case 主线
  - 验证输出是否严格受知识库约束，而不是“看起来像遵守”
- 交付物类型：
  - KB alignment 测试计划
  - golden-case 输入约束
  - reviewer / qa 审查清单
- 验证方式：
  - 重点围绕 `source_refs` 真实性、适用性 / 不适用性、冲突显式化、资料不足时保守 `no-trade / wait`
  - reviewer 核对知识页引用边界
  - qa 核对保守输出与冲突场景要求
- 验收条件：
  - 明确要求 `source_refs` 必须真实存在
  - 明确禁止 hallucinated refs
  - 明确禁止越过 `not_applicable`
  - 冲突场景必须显式提示冲突
  - 资料不足时允许且鼓励 `no-trade / wait`
  - 整个子阶段不得引入新的策略规则扩展
- 可并行子任务：
  - `kb_curator` 负责 golden-case 引用边界
  - `researcher` 负责梳理知识冲突与资料不足场景
  - `qa` 负责 KB consistency 硬门禁清单
- 依赖：
  - M8A 已完成
  - M1/M3/M6 的知识与信号契约保持冻结
- 风险：
  - 将“知识不足”误写成必须给方向
  - 把冲突知识页简化成单一路径
  - 用实现细节代替门禁要求
- 回退点：
  - 如门禁定义越界或放宽边界，回退到 M8A 检查点
- 实际完成摘要：
  - 已新增 `src/strategy/alignment.py`，提供 M8B 的最小 knowledge alignment 评估入口。
  - 已把 `source_refs` 真值校验收紧到 knowledge load/validate 层，缺失或不存在的 wiki/raw refs 现在会硬失败。
  - 已在 `tests/golden_cases/cases/` 落盘 5 个最小 golden cases，覆盖 placeholder setup、news role conflict、insufficient evidence、not_applicable hard gate、missing/fake refs hard fail。
  - 已新增 `tests/reliability/test_kb_alignment.py`、`tests/reliability/test_no_hallucinated_kb_refs.py`、`tests/reliability/test_no_trade_when_insufficient_evidence.py`。
  - 已验证 explanation 必须存在且回链到 setup/rule/source，且 `wait / no-trade` 在证据不足场景下视为合格结果。
  - 已于 2026-04-17 通过 merge commit `0047100` 整合进稳定基线 `feature/m7-broker-api-assessment`。
  - 已完成 M8B.1：定位 transcript / Brooks PPT 先前缺席是因为 raw-only、无 `source` 页、未入 active rule pack，且默认 strategy bundle 未加载 rule pack；现已补齐最小 traceability 接线并验证“能接入时出现、未接入时不编造”。

### M8B.2a：Knowledge Atomization 基础层

- 当前状态：已完成
- 目标：
  - 为 in-scope source 建立 machine-readable source registry
  - 为可解析资料建立 chunk registry
  - 为 chunk 与 curated wiki 页面建立 evidence-backed knowledge atoms
  - 建立可按 source/type/context/status 查询的 callable index
- 交付物类型：
  - source / chunk / atom / callable schema
  - source / chunk / atom / callable indices
  - builders / validators
  - reliability tests
- 验证方式：
  - 运行 `test_kb_coverage.py`、`test_knowledge_atoms.py`、`test_callable_access.py`
  - 运行全量 `tests/reliability`
  - reviewer 核对 evidence-backed 原则与 callable 层边界
  - qa 核对熔断条件与“本轮不进入 2b”的边界
- 验收条件：
  - `M8B.2` 已在 SoT 中拆成 `2a / 2b`
  - 10 个 in-scope source 全部进入 source registry
  - `Zone.Identifier` 被过滤且显式记录
  - `statement` atom 已落盘，且具备 `atom_id / source_ref / raw_locator / evidence_chunk_ids / status / confidence / callable_tags`
  - 无证据不产出 `statement`
  - transcript / Brooks / 全部方方土笔记在 callable index 层可检索
  - 关键 curated atoms 已形成 evidence-backed atom
  - 本轮不修改 strategy / explanation / review / report 接线，不修改 trigger
- 熔断条件：
  - 10 个 in-scope source 中 `blocked >= 4`
  - 关键 curated atoms 无法形成稳定 evidence-backed atom
  - `statement` 抽取无法稳定回溯证据
- 可并行子任务：
  - `source_inventory / kb_auditor` 负责 coverage baseline 与 source-page 缺口
  - `kb_structurer` 负责 schema、builders、validators、indices
  - `reviewer / qa` 负责 contract、熔断判定与回归
- 依赖：
  - M8B.1 已完成 source traceability 最小接线
  - 当前仍保持 `paper / simulated`
- 风险：
  - 把 source-level 或 statement-level atom 误包装成 executable rule
  - PDF 解析失败导致 coverage 统计与 evidence atom 不稳定
  - 在 2a 中偷跑 strategy 接线
- 回退点：
  - 如命中熔断，停在 `M8B.2a`，更新状态并输出 Failure Dossier，不进入 `2b`
- 实际完成摘要：
  - 已补齐 10 个 in-scope source 的 source registry 覆盖，并把 `Price_Action方方土.pdf:Zone.Identifier` 显式过滤到 `coverage_summary.filtered_files`。
  - 已新增 5 份方方土笔记 source page 与 2 份 Brooks PPT per-file source page；现有 `al-brooks-price-action-ppt.md` 继续保留为 family overview。
  - 已用 `pypdf` 构建 `source_manifest.json`、`chunk_manifest.jsonl`、`knowledge_atoms.jsonl` 与 `knowledge_callable_index.json`。
  - 当前 source coverage 结果为 `parsed=9 / partial=1 / blocked=0`，partial 来源是 `方方土视频笔记 - 楔形.pdf`，原因为 `1 page(s) produced no stable text`。
  - 已落盘 `statement` callable atom，且保持 `draft`、evidence-backed、无 `strategy_candidate`；当前 atom 统计为 `statement=11171`、`source_note=5492`、`open_question=24`、`concept=1`、`setup=1`、`rule=1`。
  - 关键 curated atoms `market-cycle-overview`、`signal-bar-entry-placeholder` 与 `m3-research-reference-pack` 已形成 evidence-backed atom。
  - 已通过 `python scripts/validate_kb_coverage.py`、`python scripts/validate_knowledge_atoms.py`、`python -m unittest discover -s tests/reliability -v` 与 `python -m unittest discover -s tests/unit -v`。
  - M8B.2a.1 已完成 statement 质量审计，结论为 `pass_with_small_fixes`；最小修复仅限于收紧 statement 提取条件、去除明显页眉页脚 / 时间轴 / 起始标点 / 未完成碎片，并对同一 source 内的明显重复做保守去重。
  - 审计后 statement 分布为：`al_brooks_ppt=11042`、`fangfangtu_transcript=88`、`fangfangtu_notes=41`；重复/噪音摘要为：`exact_dup_extra=13`、`normalized_dup_extra=16`、`trailing_open=0`、`datey=0`、`start_punct=0`。
  - 已于 2026-04-17 通过 merge commit `23755c0` 从 `feature/m8b2-knowledge-atomization-callable-access` 整合进稳定基线 `feature/m7-broker-api-assessment`。
  - 当前未触发熔断；`M8B.2a` 已先整合进稳定基线，后续 `M8B.2b` 由最新稳定基线独立分支启动。

### M8B.2b：Callable 接入 Strategy / Explanation / Review / Report

- 当前状态：已完成并整合进稳定基线
- 启动前提：
  - `M8B.2a` 全部测试通过
  - 未触发熔断
  - reviewer 通过
  - qa 通过
- 当前约束：
  - trigger 逻辑保持不变
  - `statement` / `source_note` / `contradiction` / `open_question` 只进入 trace，不进入 trigger
  - 继续保持 `paper / simulated`
- 实际完成摘要：
  - 已新增 `src/strategy/knowledge_access.py`，为 callable atom 提供 query、trace resolve 与 legacy `source_refs` 兼容 helper。
  - `Signal` 已新增 `knowledge_trace`，`ReviewItem` 已新增 `kb_trace`。
  - public demo 已新增 `knowledge_trace.json`；Markdown `report.md` 仅展示每笔最多 3 条 trace 摘要。
  - 已实现 source family 失衡保护：curated atom 优先、statement/source-note 去重与限量、source family 多样性控制、禁止把 atom 数量当作 confidence/trigger proxy。
  - 已通过 `tests/reliability/test_strategy_atom_trace.py`、`tests/unit/test_strategy_signal_pipeline.py`、`tests/unit/test_news_review_pipeline.py`、`tests/unit/test_public_backtest_demo.py`、`python -m unittest discover -s tests/reliability -v` 与 `python -m unittest discover -s tests/unit -v`。
  - 已从 `feature/m8b2b-knowledge-trace-integration` 整合回稳定基线 `feature/m7-broker-api-assessment`；trigger 逻辑未改变，`statement` 仍未进入 trigger。

### M8 基础离线可靠性门禁

- 当前状态：已完成
- 目标：
  - 围绕当前最小闭环定义离线集成可靠性红线
  - 固化无 future leakage、可复现、风险先于成交、审计与复盘可追溯
- 交付物类型：
  - offline E2E 测试总纲
  - 红线清单
  - forbidden path 清单
- 验证方式：
  - 以现有 `data -> strategy -> backtest -> risk -> execution -> news -> review` 最小闭环为对象
  - reviewer 审查 forbidden path 与 leak path 定义
  - qa 核对 determinism、future leakage、audit traceability 门禁
- 验收条件：
  - 明确禁止 future leakage
  - 明确要求相同输入必须 deterministic
  - 明确要求 `risk_block` 永远早于 simulated fill
  - 明确要求 review / audit 字段可追溯
  - 明确 forbidden paths，不得越过到 broker/live
- 可并行子任务：
  - `researcher` 负责现有闭环输入输出依赖梳理
  - `planner` 负责红线优先级与阶段排序
  - `qa` 负责离线可靠性验收条目
- 依赖：
  - M8B 已冻结 KB alignment 门禁
  - M2/M4/M5/M6 的既有契约保持冻结
- 风险：
  - 只测收益，不测行为正确性
  - future leakage 定义模糊
  - 将 paper-only 执行红线降级为质量项
- 回退点：
  - 如离线可靠性门禁表述模糊，回退到 M8B 检查点
- 实际完成摘要：
  - 已新增 `tests/integration/test_offline_e2e_pipeline.py`，覆盖 `src/data -> src/strategy -> src/backtest -> src/risk -> src/execution -> src/news -> src/review` 的离线端到端链路。
  - 已新增 `tests/reliability/test_replay_determinism.py`、`tests/reliability/test_no_future_leakage.py`、`tests/reliability/test_audit_traceability.py`、`tests/reliability/test_forbidden_paths.py`。
  - 已覆盖 deterministic replay 一致性、bars / news future leakage fail-fast、forbidden paths、audit / review traceability、`end_of_data`、缺 bar gap 与重复 bar 的稳健性。
  - 已更新 `scripts/run_reliability_suite.py`，使 `integration` 与 `reliability` suites 可统一运行且继续保持 `real_historical_data=deferred`。
  - 已通过 `tests/reliability` 18 项、`tests/integration` 4 项、`tests/unit` 57 项与统一 reliability suite 验证。

### M8C：Long-Horizon & Intraday Paper Validation

- 当前状态：进行中
- 总目标：
  - 在不改 trigger 的前提下，把当前 short-window daily demo 扩展为更长周期、更分段、更可解释的 `paper / simulated` 验证套件。
  - 先完成长周期日线验证，再决定是否进入单标的日内试点。
  - `knowledge_trace` 与 legacy `source_refs` 继续兼容；`statement` / `source_note` 只作 trace 证据，不进入 trigger。

#### M8C.1：长周期日线验证

- 当前状态：已完成
- 范围与边界：
  - 只做 daily、equity/ETF、公有历史数据缓存驱动的长周期验证。
  - 不做期权、不做 intraday、不改 trigger、不改变 `knowledge_trace` 与 legacy `source_refs` 的兼容语义。
  - `knowledge_trace` 只用于解释、审计和覆盖率摘要，不得作为 trigger 或 score proxy。
- 实际完成摘要：
  - 已新增 `config/examples/public_history_backtest_long_horizon.json`，把 daily demo 扩展到 `2020-01-01 ~ 2025-12-31`，覆盖 `NVDA / TSLA / SPY` 三个 equity/ETF 标的。
  - 已新增 walk-forward 风格 split：`in_sample`、`validation`、`out_of_sample`。
  - 已新增 regime 分层窗口：`covid_crash_high_vol`、`liquidity_trend_up`、`macro_drawdown`、`recovery_rotation`、`ai_momentum_and_range`。
  - 已新增结构化产物：
    - `summary.json`
    - `split_summary.json`
    - `regime_breakdown.json`
    - `knowledge_trace_coverage.json`
    - `no_trade_wait.jsonl`
    - `trades.csv`
    - `knowledge_trace.json`
    - `report.md`
    - `equity_curve.png`
  - 已新增 `no-trade / wait` 结构化持久化，最小 reason class 包括：
    - `context_not_trend`
    - `duplicate_direction_suppressed`
    - `insufficient_evidence`
    - `risk_blocked_before_fill`
  - 已补齐 per-symbol breakdown、regime 摘要、blocked signals 汇总、knowledge trace 覆盖率摘要，以及 curated vs statement trace 占比摘要。
  - 已保持 curated atom 优先、statement 仅作补充证据；禁止使用 statement 数量作为 confidence 或 trigger proxy。
  - 已通过新增 `tests/reliability/test_long_horizon_daily_validation.py`、`tests/unit/test_public_backtest_demo.py` 回归，以及现有 `tests/reliability` / `tests/unit` 套件。
- 验收门槛：
  - 报告与 JSON 产物生成成功率为 `100%`。
  - 同一缓存输入重复运行结果保持 deterministic。
  - executed trades 的 `knowledge_trace` 覆盖率与 curated-first trace 约束稳定。
  - `no_trade / wait` 输出可重复生成，且保持 `paper / simulated`、不进入期权或 broker/live。
- 回退点：
  - 若长周期报告产物、trace 覆盖率摘要或 `no_trade / wait` 持久化不稳定，回退到 `M8B.2b` 检查点。

#### M8C.2：单标的日内试点

- 当前状态：已完成实现与验收，待整合进 `main`
- 启动前提：
  - `M8C.1` 验收通过并整合进稳定基线。
  - 继续保持 `paper / simulated`，不进入期权、broker/live/real-money。
- 计划边界：
  - 默认只选一个标的，优先 `SPY 15m`。
  - 必须补 session open/close、market hours / timezone、日内风险重置、slippage / fee 最小模型、duplicate signal protection、`no-trade / wait` 结构化输出。
  - 如实现被迫修改 `src/risk/` 或 `src/execution/` 核心语义，则停止自动合并并转高风险审批。
 - 实际完成摘要：
   - 已新增 `config/examples/intraday_pilot_spy_15m.json`、`scripts/intraday_pilot_lib.py`、`scripts/run_intraday_pilot.py`。
   - 已把首轮 intraday pilot 冻结为 `SPY / 15m / America/New_York / 2026-03-30 ~ 2026-04-16`，并把数据缓存到 `local_data/public_intraday/`。
   - 已新增结构化产物：
     - `summary.json`
     - `session_summary.json`
     - `session_quality.json`
     - `knowledge_trace.json`
     - `knowledge_trace_coverage.json`
     - `no_trade_wait.jsonl`
     - `trades.csv`
     - `report.md`
     - `equity_curve.png`
   - 已验证：
     - session open/close
     - market hours / timezone
     - 日内风险重置
     - duplicate signal protection
     - slippage / fee 最小可配置模型
     - `no-trade / wait` 结构化输出
     - intraday 下的 `knowledge_trace` 与 legacy `source_refs` 兼容
     - curated atom 优先、statement 仅作补充证据，且 source family 失衡保护继续生效
   - 已保持 trigger 逻辑不变；`statement` / `source_note` / `contradiction` / `open_question` 仍未进入 trigger。
   - 已通过新增 `tests/unit/test_intraday_pilot.py`、`tests/reliability/test_intraday_pilot_validation.py`，以及现有 `tests/reliability` / `tests/unit` / public demo smoke 回归。

### M8D：真实历史数据稳健性 + 实时 shadow / paper 验证框架

- 当前状态：进行中
- 目标：
  - 在真实输入条件下验证系统仍然保守、稳定、可解释
  - 只建立 shadow / paper 验证框架，不进入真实 broker
- 交付物类型：
  - 真实历史数据验证计划
  - shadow / paper 验证 runbook 需求
  - 报告与人工抽检门禁
- 验证方式：
  - 允许真实历史 CSV/JSON、本地快照、实时只读输入
  - 明确仍为 shadow / paper，不连接真实 broker、不启用 live
  - reviewer 审查真实输入边界是否干净
  - qa 核对 shadow / paper 与 no-go 结论是否一致
- 验收条件：
  - 明确真实历史数据与实时只读输入的范围
  - 明确禁止真实 broker、真实账户、live execution
  - 明确要求输出仍为 shadow / paper 结果
  - 明确要求真实输入下仍保守 `wait / no-trade`，而不是强行给结论
  - 明确任何 broker/live 重新评估都排在 M8 完成之后
- 可并行子任务：
  - `researcher` 负责输入源与 regime 范围定义
  - `planner` 负责 shadow / paper 阶段门禁
  - `qa` 负责真实输入下的保守性与报告门禁
- 依赖：
  - M8C 已完成离线可靠性门禁定义
  - 当前数据源优先级仍以 `docs/data-sources.md` 为准
- 风险：
  - 用“实时验证”模糊掉 shadow / paper 边界
  - 将真实输入测试误解成真实 broker 恢复
  - 在未完成 M8 前重开 live 讨论
- 回退点：
  - 如出现任何真实 broker / live 暗示，整体回退到 M8C 检查点
- 实际完成摘要：
  - 已新增 `docs/shadow-mode-runbook.md`，固定 manifest、shadow/paper 命令、deferred 语义与运行边界。
  - 已新增 `scripts/run_shadow_session.py`，提供本地 manifest 驱动的只读 shadow/paper runner，默认不连接真实 broker、不触发 live execution。
  - 已新增 repo-safe 小样本 manifest：`tests/test_data/real_history_small/sample_us_5m_recorded_session/dataset.manifest.json`。
  - 已新增 `tests/reliability/test_regime_robustness.py`、`tests/reliability/test_shadow_paper_consistency.py`、`tests/reliability/test_dataset_manifest_contract.py`。
  - 已补齐 `docs/test-dataset-curation.md` 与 `reports/reliability/README.md`，固定 small/large dataset 约定、受控标签与报告最小字段。
  - 已新增 `scripts/download_public_history.py`、`scripts/run_public_backtest_demo.py`、`scripts/run_public_backtest_demo.sh`，打通公共历史数据下载缓存、用户可直接执行的一键回测入口与用户可读报告链路。
  - 已新增 `config/examples/public_history_backtest_demo.json` 与 `docs/user-backtest-guide.md`，固定第一轮演示为 `NVDA / TSLA / SPY`、`2024-01-01 ~ 2024-06-30`、`1d`。
  - 已完成一轮公共历史数据演示回测：使用 `yfinance` 作为 research-only fallback，把数据缓存到 `local_data/public_history/`，并生成 `reports/backtests/demo_public_2024h1/`。
  - 该示例 run 在当前 demo 风控参数下录得 `1.9923%` 总收益率、`1.5157%` 最大回撤、`16` 笔交易、`43.75%` 胜率；仍明确保持 `paper / simulated`，不代表实盘能力。
  - 当前更完整的真实历史样本、用户自有 CSV、录制型实时样本与 shadow/paper 延展验证仍可继续扩展，但本轮没有引入真实 broker、真实账户或 live execution。

## 16. 公共接口冻结点

- KB 层在 M1 后冻结 frontmatter 主字段与 setup 专属字段，`source_refs`、`missing_visuals`、`open_questions`、`pa_context` 等字段视为稳定约束。
- 数据层在 M2 后冻结 OHLCV 输入字段、新闻 JSON 最小字段、回放输出的 deterministic bar 序列结构。
- 策略层在 M3 后冻结结构化 signal 输出字段，下游模块不得依赖自由文本。
- 回测层在 M4 后冻结交易记录和核心统计字段，供复盘与模拟统一消费。
- 执行与风控层在 M5 仅允许 paper/simulated contract，真实 broker contract 只能在 M7 评估中定义，不落真实实现。

## 17. 总体验证策略

- 所有 milestone 都必须包含最小可重复验证命令、代表性样本、失败路径和空输入路径。
- M1 重点测 frontmatter 缺失、setup 特殊字段、空 wiki、索引字段一致性。
- M2 重点测 timestamp/timezone 解析、重复记录、非法价格、高低价关系、排序与 replay 稳定性。
- M3 重点测无信号、单信号、多信号、`source_refs` 缺失、失效条件与解释字段完整性。
- M4 重点测零交易、单交易、多交易、止损/目标命中、数据不足和统计可重复性。
- M5 重点测允许交易、风险拦截、模拟成交、重复信号、市场关闭、连续亏损熔断和恢复条件。
- M6 重点测新闻仅作过滤/解释、不直接下单、复盘字段完整和 KB 引用可追溯。
- M7 重点测门禁清单完整性、审批前置条件和“无真实接入”边界。
- M8A 重点测主线文档、验收门禁、状态切换、测试骨架与 suite 入口是否同步，且无 broker/live 越界表述。
- M8B 重点测知识库对齐、`source_refs` 真实性、`not_applicable` 约束、冲突显式化、explanation 回链与资料不足时的保守 `no-trade`。
- M8C 重点测无 future leakage、同输入 deterministic、risk-before-fill、audit / review traceability 与 forbidden paths。
- M8D 重点测真实历史数据与实时只读输入下仍保持 shadow / paper、保守稳定、可解释，且不进入真实 broker / live execution。

## 18. 当前阶段与下一步

- 当前阶段：阶段 8：可靠性验证（进行中）。
- 当前 milestone：M8C.2：单标的日内试点（实现与验收完成，待整合进 `main`）。
- 当前下一步：
  - 本轮已完成 `SPY 15m` intraday pilot 的实现、测试与报告候选；下一步先通过 merge gate 合并进 `main`，期间仍保持 `paper / simulated`、不进入期权、broker/live。
  - 若本轮 merge gate 通过，后续继续扩大验证范围时，只允许从最新稳定基线 `main` 单独开分支进入新的 intraday/extended validation 任务；仍不进入期权、broker/live。
  - 保持当前 `no-go` 结论与 `paper / simulated` 边界，不继续 broker 开发。
  - 完成 M8 之前，不重新评估真实 broker、真实账户、live execution 或付费 API

## 19. 假设

- 当前仓库基础设施已满足 M0 验收，且 GitHub push 工作流已打通。
- `python` 命令已可用，因此验证命令统一写为 `python ...`。
- 第一实施波次固定为 M1 后接 M2；浏览器验证与正式券商 API 评估都排在后续，不得前置。
- 若任一 milestone 在执行中触发熔断，则冻结该里程碑分支，更新 `docs/status.md`，输出 Failure Dossier，并等待用户决策。
