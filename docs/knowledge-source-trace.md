# Knowledge Source Trace

## 当前接入链路

当前 public history demo 的代表性交易解释链路是：

`knowledge/raw/* -> knowledge/wiki/sources/* -> knowledge/wiki/concepts|setups|rules/* -> src/strategy/knowledge.py -> src/strategy/signals.py -> scripts/public_backtest_demo_lib.py`

其中真正进入 `signal.source_refs` / `signal.explanation` 的来源，取决于：

1. raw 文件是否真实存在。
2. 是否有对应的 `knowledge/wiki/sources/*.md` 登记页。
3. active rule pack 是否把这些 source page 接入 `source_refs`。
4. 默认 strategy knowledge bundle 是否真的加载 active rule pack。

## M8B.1 诊断结论

- `knowledge/raw/` 中已经存在：
  - `knowledge/raw/youtube/fangfangtu/transcripts/Price_Action方方土.pdf`
  - `knowledge/raw/brooks/ppt/AIbrooks价格行为通用版1-36单元.pdf`
  - `knowledge/raw/brooks/ppt/AIbrooks价格行为通用版37-52单元.pdf`
- 但在本次修复前，这些材料没有对应的 `knowledge/wiki/sources/*.md` 登记页。
- `knowledge/wiki_index.json` 与 `knowledge/wiki/rules/m3-research-reference-pack.md` 也没有收录它们。
- `src/strategy/knowledge.py` 的 `load_default_knowledge()` 默认只加载 concept/setup 页，不真正加载 active rule pack，因此即使 rule pack 增加了新来源，默认 signal 链也不会带出这些 supporting source refs。

## 本次最小修复

- 新增：
  - `knowledge/wiki/sources/fangfangtu-price-action-transcript.md`
  - `knowledge/wiki/sources/al-brooks-price-action-ppt.md`
- 把上述两页接入：
  - `knowledge/wiki/rules/m3-research-reference-pack.md`
  - `knowledge/wiki/rules/m3_signal_reference_index.json`
- 将 `src/strategy/knowledge.py` 的默认 bundle 改为实际加载 active rule pack。

## 仍然保留的边界

- 这次修复只补 traceability 接线，不补写 raw 内容，不发明 transcript/PPT 细节。
- transcript 与 Brooks PPT 当前仍然只是 `source` 级登记页，尚未完成页码/段落到 `concept/setup/rule` 字段的结构化映射。
- 因此它们现在可以作为“已接入的来源节点”进入 `source_refs`，但仍不能被包装成“已完成抽取的正式规则”。
