# Price Action Trader Active Plan（V2 可执行版）

## 1. 当前状态

- 本计划用于替换初始化模板，并驱动后续全部实施。
- 当前已接受基线为 M0 基础设施初始化，基线提交为 `96259ad`。
- 当前只完成计划定稿与状态同步，不开始正式编码。
- 当前活动分支为 `feature/m1-kb-ingestion-index`，用于启动 M1。

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

- M0 已完成 → M1 知识库 schema / KB 校验 / wiki index / 资料投放流程 → M2 测试数据 / 数据 schema / CSV-JSON 回放 → M3 PA context / setup / signal 原型 → M4 最小回测与报告 → M5 纸面交易 / 模拟执行 / 风控闭环 → M6 新闻过滤与复盘整合 → M7 正式券商 API 接入评估。
- 第一实施波次固定为：M1 完成后进入 M2。
- 不得把浏览器自动化、正式券商 API、真实账户、实盘自动下单前置到 M1 或 M2。

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

## 9. M2 测试数据、OHLCV schema、CSV/JSON 回放 adapter

- 分支：`feature/m2-data-schema-replay`
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

## 10. M3 PA context、setup、signal 输出原型

- 分支：`feature/m3-pa-signal-prototype`
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

## 11. M4 最小回测引擎与报告

- 分支：`feature/m4-backtest-report`
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

## 12. M5 纸面交易、模拟执行与风控闭环

- 分支：`feature/m5-papertrading-risk`
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

## 13. M6 新闻事件过滤与复盘整合

- 分支：`feature/m6-news-review-integration`
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

## 14. M7 正式券商 API 接入评估

- 分支：`feature/m7-broker-api-assessment`
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

## 15. 公共接口冻结点

- KB 层在 M1 后冻结 frontmatter 主字段与 setup 专属字段，`source_refs`、`missing_visuals`、`open_questions`、`pa_context` 等字段视为稳定约束。
- 数据层在 M2 后冻结 OHLCV 输入字段、新闻 JSON 最小字段、回放输出的 deterministic bar 序列结构。
- 策略层在 M3 后冻结结构化 signal 输出字段，下游模块不得依赖自由文本。
- 回测层在 M4 后冻结交易记录和核心统计字段，供复盘与模拟统一消费。
- 执行与风控层在 M5 仅允许 paper/simulated contract，真实 broker contract 只能在 M7 评估中定义，不落真实实现。

## 16. 总体验证策略

- 所有 milestone 都必须包含最小可重复验证命令、代表性样本、失败路径和空输入路径。
- M1 重点测 frontmatter 缺失、setup 特殊字段、空 wiki、索引字段一致性。
- M2 重点测 timestamp/timezone 解析、重复记录、非法价格、高低价关系、排序与 replay 稳定性。
- M3 重点测无信号、单信号、多信号、`source_refs` 缺失、失效条件与解释字段完整性。
- M4 重点测零交易、单交易、多交易、止损/目标命中、数据不足和统计可重复性。
- M5 重点测允许交易、风险拦截、模拟成交、重复信号、市场关闭、连续亏损熔断和恢复条件。
- M6 重点测新闻仅作过滤/解释、不直接下单、复盘字段完整和 KB 引用可追溯。
- M7 重点测门禁清单完整性、审批前置条件和“无真实接入”边界。

## 17. 当前阶段与下一步

- 当前阶段：阶段 1：知识库 ingestion、schema、wiki index、KB 校验。
- 当前 milestone：M1：知识库 schema、KB 校验、wiki index、资料投放流程。
- 当前下一步：
  - 从 `feature/m1-kb-ingestion-index` 启动 M1
  - 优先校准 KB schema、frontmatter、validate/index 脚本与资料投放流程
  - M1 通过后进入 M2 的测试数据与数据 schema / CSV-JSON 回放

## 18. 假设

- 当前仓库基础设施已满足 M0 验收，且 GitHub push 工作流已打通。
- `python` 命令已可用，因此验证命令统一写为 `python ...`。
- 第一实施波次固定为 M1 后接 M2；浏览器验证与正式券商 API 评估都排在后续，不得前置。
- 若任一 milestone 在执行中触发熔断，则冻结该里程碑分支，更新 `docs/status.md`，输出 Failure Dossier，并等待用户决策。
