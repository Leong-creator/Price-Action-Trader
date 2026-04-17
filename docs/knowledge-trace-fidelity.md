# Knowledge Trace Fidelity

## 阶段 A 解决的问题

阶段 A 只修以下三类问题：

- user-facing 引用把 actual evidence hit 与 bundle / registry support 混在一起
- visible `knowledge_trace` 把 broad support rule 当成实际命中证据展示
- signal-level `applicability_state` 被治理性 `not_applicable` / maturity warning 污染

## 新语义

### Actual hit refs

- 来源：visible `knowledge_trace`
- 用途：`report.md`、`summary.json`、`knowledge_trace_coverage.json` 的默认用户语义
- 表示：本次 signal / blocked / no-trade 场景里真正命中的 evidence refs

### Bundle support refs

- 来源：reference pack、source registry、debug/support trace
- 用途：machine-readable provenance、bundle 追溯、调试
- 表示：为当前知识包提供支撑性来源，但不等于本次 signal 的实际命中证据

### Debug / support trace

- 保留 broad support refs、governance notes 与 support provenance
- 默认不直接进入 Markdown 报告

## 为什么 transcript / Brooks 之前“看起来被引用但实际 trace 没命中”

- 它们此前已经进入 source registry、rule pack 与 legacy `source_refs`
- 但这些引用大多属于 bundle/support 层，而不是具体 signal 的 actual evidence hit
- 因此用户会看到“source_refs 里有 transcript / Brooks”，却在 visible trace / coverage 里看不到真实命中

## 阶段 A 之后的可见变化

- `report.md` 默认只展示 actual hit refs
- bundle support refs 单独落盘，不再与 actual refs 混淆
- `m3-research-reference-pack` 这类 broad support rule 不再以 giant `chunk_set[...]` 进入 visible trace
- `knowledge_trace_coverage.json` 现在显式区分：
  - `actual_hit_*`
  - `bundle_support_*`

## 当前仍未做的事

- 未做 curated promotion
- transcript / Brooks 仍未因为阶段 A 自动变成新的 curated actual trace claim
- 未改 trigger
- 未让 `statement` / `source_note` / `contradiction` / `open_question` 进入 trigger
- 项目边界仍保持 `paper / simulated`
