# Backtest Reports

`reports/backtests/` 用于存放用户可读的历史回测演示输出。

约束：

- 这里只放本地生成的研究报告，不代表实盘能力。
- 仍处于 `paper / simulated` 边界。
- 不接真实 broker、真实账户或 live execution。
- 结果仅对本次选定时间窗口和公共历史数据成立，不得夸大为未来收益证明。

每个 run 目录至少包含：

- `report.md`
- `trades.csv`
- `summary.json`
- `equity_curve.png`
