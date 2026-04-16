# AGENTS.md

本目录负责数据接入、清洗、schema、回放和测试样本。

## 数据源优先级
静态 CSV/JSON > 用户导出文件 > 免费公共数据源 > 浏览器临时验证 > 正式券商 API。

## 数据规则
- 禁止编造行情数据。
- 测试样本必须放在 `tests/test_data/`。
- 所有数据 adapter 必须与策略核心解耦。
- 时间字段必须明确 timezone。
- OHLCV 必须校验 high/low/open/close 的基本关系。
