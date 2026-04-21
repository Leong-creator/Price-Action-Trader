# Knowledge Atomization

## 目标

本轮 `M8B.2` 的目标不是新增交易规则，而是把已存在且可解析的 raw/source/wiki 材料升级成可登记、可切片、可原子化、可过滤、可审计的知识系统。

当前边界固定为：

- 仍处于 `paper / simulated`
- 不进入 broker / live / real-money / real-account
- 不修改 `knowledge/raw/`
- 不把 source-level 或 statement-level callable 包装成 executable strategy rule
- `M9 strategy cards` 只允许消费上述层的 evidence / traceability，不得把 statement、source_note 或 bundle support 直接升格为 trigger

## 四层结构

### 1. Source-level callable

- 载体：`source_manifest.json`、`knowledge/wiki/sources/*.md`
- 表达：来源登记、来源类型、原始路径、解析状态、来源页引用
- 用途：让系统知道 raw 中有哪些资料、哪些可解析、哪些 blocked / partial
- 当前可调用方式：可按 `source_id`、`source_family`、`source_type` 查询
- 当前不能做的事：不能直接当作可执行规则进入交易决策

### 2. Statement-level callable

- 载体：`knowledge_atoms.jsonl` 中的 `statement`
- 表达：基于单个 evidence chunk 的最小可调用知识点
- 最小必备字段：
  - `atom_id`
  - `source_ref`
  - `raw_locator`
  - `evidence_chunk_ids`
  - `status`，默认 `draft`
  - `confidence`
  - `callable_tags`
- 当前可调用方式：可按 type / source / market / timeframe / pa_context / status / confidence / callable_tags 过滤
- 当前不能做的事：不能自动进入 trigger；不能被标记成 executable rule

### 3. Curated concept/setup/rule callable

- 载体：现有 curated wiki 页生成的 evidence-backed atom
- 当前范围仅限：
  - `knowledge/wiki/concepts/market-cycle-overview.md`
  - `knowledge/wiki/setups/signal-bar-entry-placeholder.md`
  - `knowledge/wiki/rules/m3-research-reference-pack.md`
  - `knowledge/wiki/rules/trend-vs-range-filter-minimal.md`
- 这些 atom 必须绑定真实 `evidence_chunk_ids` 和 `raw_locator`
- 当前可调用方式：可作为结构化 knowledge layer 的 curated callable 被查询和审计
- 当前不能做的事：本轮不新增 strategy 接线，不改变 trigger 逻辑

### 4. Executable strategy rule

- 载体：当前 strategy 已允许消费的 research-only curated executable path
- 当前仍维持既有边界，不在本轮扩写
- 本轮完成后，executable strategy rule 层不会自动吸收新的 source-level 或 statement-level atom

## M8B.2 两阶段

### M8B.2a

只做：

- Source Registry
- Chunk Registry
- Knowledge Atom Schema
- Builders / Validators
- Callable Index

本轮允许完成后可调用的层：

- source-level callable
- statement-level callable
- curated concept/setup/rule callable

本轮仍不进入交易决策的层：

- source-level callable
- statement-level callable
- contradiction / open_question

### M8B.2b

只有在以下条件全部满足时才允许启动：

- `M8B.2a` 全部测试通过
- 未触发熔断
- reviewer 通过
- qa 通过

`M8B.2b` 才允许讨论：

- `knowledge_trace`
- explanation / review / report 的 atom trace 接线
- legacy `source_refs` 的兼容映射

当前已完成的 `M8B.2b` 事实：

- `knowledge_trace` 已接入 `Signal`
- `kb_trace` 已接入 `ReviewItem`
- public demo 已新增 machine-readable `knowledge_trace.json`
- Markdown `report.md` 只展示精简 trace 摘要，不展开完整 atom trace
- 已实现 source family 失衡保护：curated atoms 优先，statement/source-note trace 去重、限量、按 source family 做多样性控制

本轮完成后，已进入 trace 但仍未进入 trigger 的层：

- source-level callable
- statement-level callable
- contradiction / open_question

本轮完成后，仍可能进入更深决策的只有：

- 当前既有的 curated executable path

并且即使如此，本项目仍保持 `paper / simulated`，未扩写 broker/live。

## Knowledge Reference Repair / 阶段 A

阶段 A 只修三类问题：

- actual hit refs 与 bundle support refs 被混在同一默认展示语义里
- visible trace 把 broad support / registry refs 误当成实际命中证据
- signal-level `applicability_state` 被治理性 `not_applicable` / maturity warning 污染

阶段 A 之后，trace 相关层次固定为：

### 1. Actual hit refs

- 来源：visible `knowledge_trace`
- 用途：用户报告、`summary.json`、coverage 主指标、`no_trade_wait` 默认展示
- 约束：只允许展示实际命中的 concept / setup / statement 等 evidence hit；不得把 broad support ref 冒充成 actual hit

### 2. Bundle support refs

- 来源：reference pack、source registry、debug/support trace
- 用途：machine-readable 支撑性来源、调试、bundle provenance
- 约束：可以落盘，但默认不应在 user-facing 报告中被当成实际命中证据

### 3. Visible trace

- 只展示 actual evidence hit
- 保持 curated-first、statement 仅作补充证据、source family 限量与多样性控制
- `m3-research-reference-pack` 这类 broad support rule 在无窄化 evidence 前不得默认进入 visible trace

### 4. Debug / support trace

- 用于保留 bundle support provenance、governance notes 与 machine-readable 调试信息
- 可以保留广义 support 信息，但不等于 signal 级实际命中

### 5. Governance notes

- 用于承载“未完成抽取前不作为可执行规则”“当前仍为 research-only”等治理/成熟度语义
- 不得继续直接映射成 signal-level `applicability_state=not_applicable`

阶段 A 完成后：

- transcript / Brooks 已明确作为 bundle support 可见
- 但它们尚未因为阶段 A 自动变成新的 curated actual trace claim
- 若要让 transcript / Brooks 在 actual trace 中真实出现，必须进入后续的最小 curated promotion（阶段 B）

## Knowledge Reference Repair / 阶段 B

阶段 B 只做最小 curated promotion，不做全量升级，不改 trigger。

当前已完成的 promotion 主题：

- `market cycle / context`
- `signal bar / entry`
- `trend vs range filter`
- `breakout follow-through / failed breakout`
- `tight channel / trend resumption`

阶段 B 之后，引用与证据的层次固定为：

### 1. Source-level callable

- 仍只代表来源登记与可追溯性
- 不因为阶段 B 自动变成 trigger 输入

### 2. Statement-level callable

- 仍是 evidence-backed 的最小知识点
- 当前可进入 query / filter / actual trace 的补充证据层
- 仍不得进入 trigger

### 3. Curated promoted callable

- 载体：evidence-backed 的 curated concept/setup/rule 页与 `knowledge/indices/curated_promotion_map.json`
- 当前已进入 actual visible trace
- 每条 promoted curated claim 都必须保留：
  - `claim_id`
  - `field_mappings`
  - `evidence_refs`
  - `evidence_locator_summary`
  - `evidence_chunk_ids`

### 4. Executable strategy rule

- 仍只限当前既有 trigger 路径
- 阶段 B 不把 promoted curated claim、statement、source_note、contradiction、open_question 升格为 trigger

阶段 B 完成后，用户在报告与 JSON 中应看到的变化：

- visible actual trace 不再只是 `placeholder concept/setup + generic support`
- transcript / Brooks 现在会通过 promoted curated claim 的 `evidence_refs` 与 `evidence_locator_summary` 真实出现
- report.md 只显示精简 evidence 摘要
- `knowledge_trace.json` 保留 machine-readable 全量 evidence chain
- 第二轮最小集只新增上述两个 promoted curated `rule` theme；它们通过 `evidence_refs / evidence_locator_summary / evidence_chunk_ids` 进入 actual trace，但仍保持 `draft / low confidence / research-only`

当前仍停留在 source / statement 层、尚未进入 trigger 的内容：

- transcript / Brooks 的绝大多数 statement
- source registry / bundle support refs
- `contradiction` / `open_question`
- 所有仍为 `draft / low confidence / research-only` 的 promoted curated claim

## 熔断条件

命中任一条件即停在 `M8B.2a`：

- 10 个 in-scope source 中 `blocked >= 4`
- 关键 curated atoms 无法形成稳定 evidence-backed atom
- `statement` 抽取无法稳定回溯证据

若熔断：

- 只完成 `2a`
- 更新 `docs/status.md` 与 `plans/active-plan.md`
- 输出 Failure Dossier
- 不得进入 `2b`
