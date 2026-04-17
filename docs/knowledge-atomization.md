# Knowledge Atomization

## 目标

本轮 `M8B.2` 的目标不是新增交易规则，而是把已存在且可解析的 raw/source/wiki 材料升级成可登记、可切片、可原子化、可过滤、可审计的知识系统。

当前边界固定为：

- 仍处于 `paper / simulated`
- 不进入 broker / live / real-money / real-account
- 不修改 `knowledge/raw/`
- 不把 source-level 或 statement-level callable 包装成 executable strategy rule

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

本轮 `M8B.2a` 明确不执行这些内容。

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
