# Chunk Registry Schema

`chunk_manifest.jsonl` 是 `M8B.2a` 的切片层。

## Chunk Record

每行一条 JSON 对象，字段至少包括：

- `chunk_id`
- `source_id`
- `source_family`
- `locator_kind`
- `raw_locator`
- `chunk_text`
- `chunk_status`
- `parser_name`
- `parser_version`
- `derived_from`

## 字段约束

- `locator_kind`：首轮固定为 `page_block`
- `raw_locator`：对象，首轮至少包含
  - `locator_kind`
  - `page_no`
  - `block_index`
- `chunk_status`：首轮固定支持
  - `parsed`
  - `blocked`
- `chunk_text`：
  - `parsed` 时必须非空
  - `blocked` 时允许为空字符串

## 首轮切片规则

- 解析器固定为 `pypdf`
- transcript / PPT / note PDF 首轮统一按 `page_block` 路径切片
- 先按页抽文本，再按空行切 paragraph
- paragraph 为空则丢弃
- paragraph 过长时允许切成固定窗口块
- 不做 OCR
- 不猜时间戳
- 不做视觉结构推断

## 约束

- 每个 `chunk_id` 必须可稳定重建
- 每个 chunk 必须能回溯到 `source_id + raw_locator`
- 无法稳定提取的页面允许生成 `blocked` chunk，但不得编造文本
