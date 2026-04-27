# Source Registry Schema

`source_manifest.json` 是 `M8B.2a` 的 machine-readable 来源登记层。

## 顶层结构

```json
{
  "schema_version": "m8b2.source-registry.v1",
  "generated_at": "2026-04-17T00:00:00Z",
  "sources": [],
  "coverage_summary": {}
}
```

## Source Record

每条 `sources[]` 记录至少包含：

- `source_id`
- `source_family`
- `source_type`
- `raw_path`
- `file_name`
- `parse_status`
- `machine_readable`
- `source_page_ref`
- `parse_notes`
- `reviewed_at`

可选但推荐字段：

- `page_count`
- `non_empty_pages`
- `empty_pages`
- `unit_count`（markdown-tree source）
- `evidence_file_count`（markdown-tree source）
- `asset_directory_present`（markdown-tree source）

## 字段约束

- `source_id`：稳定唯一 ID，格式为 `<source_family>--<slug>--<short_sha1>`
- `source_family`：首轮固定支持
  - `fangfangtu_notes`
  - `fangfangtu_transcript`
  - `al_brooks_ppt`
  - `brooks_v2_manual_transcript`
- `source_type`：首轮固定支持
  - `note_pdf`
  - `transcript_pdf`
  - `ppt_pdf`
  - `manual_transcript_md_tree`
- `parse_status`：首轮固定支持
  - `parsed`
  - `partial`
  - `blocked`
- `machine_readable`：
  - `true` 表示至少能提取部分稳定文本
  - `false` 表示当前只能 blocked
- `source_page_ref`：必须回指到真实存在的 `knowledge/wiki/sources/*.md`

## Coverage Summary

`coverage_summary` 至少包含：

- `total_expected`
- `total_registered`
- `parse_status_counts`
- `filtered_files`

## 约束

- `*:Zone.Identifier` 不得出现在 `sources[]` 中，只能进入 `filtered_files`。
- raw 中的 in-scope 文件不得处于“系统完全未知”状态。
- source registry 只登记来源，不把来源直接包装成可执行规则。
