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
