# M8B Golden Cases

本目录存放 M8B 的最小 knowledge-alignment case metadata。

约束：

- 这里只存 case metadata，不存真实收益结论。
- 如需 synthetic fixtures，只能用于 knowledge boundary / explanation / guardrail 测试。
- 不得把 synthetic fixture 包装成真实历史样本、真实回测或 live-ready 依据。

每个 case 至少包含：

- `case_id`
- `market`
- `timeframe`
- `expected_context`
- `allowed_setups`
- `forbidden_setups`
- `required_source_refs`
- `allowed_actions`
- `must_explain`
- `must_not_claim`
