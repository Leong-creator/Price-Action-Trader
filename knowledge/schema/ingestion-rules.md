# Ingestion Rules

## 1. raw 层

- 原始资料只放在 `knowledge/raw/`。
- raw 层不可改写、覆盖或二次整理。

## 2. wiki 层

- 整理结果写入 `knowledge/wiki/`。
- 每页必须带 YAML frontmatter。
- 每页必须保留 `source_refs`。
- 缺图不阻塞入库，但必须记录 `missing_visuals`。

## 3. 来源与可追溯

- 来源文件、转录文档、补充资料都要能回溯到 raw 层。
- 不得把推断写成事实。
- 发现冲突时，记录在 `contradictions`。
