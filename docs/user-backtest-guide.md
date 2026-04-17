# 用户历史回测演示指南

## 1. 这是什么

这条链路的目标是让你直接看到：

- 公共真实历史数据下载到了哪里
- 当前策略在一段历史里大致赚还是亏
- 哪些交易赚钱，哪些交易亏钱
- 报告里能看到哪些解释

它仍然只处于 `paper / simulated` 边界。

它**不是**：

- 真实 broker 接入
- 真实账户联通
- live execution
- real-money 回测或实盘证明

## 2. 默认演示范围

默认配置文件：

- `/home/hgl/projects/Price-Action-Trader/config/examples/public_history_backtest_demo.json`

默认会跑：

- `NVDA`
- `TSLA`
- `SPY`

时间范围默认是：

- `2024-01-01` 到 `2024-06-30`

## 3. 一键命令

如果本地已经有 `.venv`，直接执行：

```bash
bash /home/hgl/projects/Price-Action-Trader/scripts/run_public_backtest_demo.sh \
  --config /home/hgl/projects/Price-Action-Trader/config/examples/public_history_backtest_demo.json
```

该命令会：

1. 优先尝试 `Alpha Vantage`（仅当环境里已有可用 key）
2. 否则自动回退到 `yfinance`
3. 把历史数据缓存到本地 CSV
4. 基于当前策略/回测/风控能力生成用户可读报告

## 4. 只下载不回测

```bash
/home/hgl/projects/Price-Action-Trader/.venv/bin/python \
  /home/hgl/projects/Price-Action-Trader/scripts/download_public_history.py \
  --config /home/hgl/projects/Price-Action-Trader/config/examples/public_history_backtest_demo.json
```

## 5. 数据与报告位置

本地缓存目录：

- `/home/hgl/projects/Price-Action-Trader/local_data/public_history/`

报告输出目录：

- `/home/hgl/projects/Price-Action-Trader/reports/backtests/<run_id>/`

每次回测至少会生成：

- `report.md`
- `trades.csv`
- `summary.json`
- `equity_curve.png`

## 6. 你可以改什么

最简单的改法是直接改配置文件里的：

- 标的列表
- 开始/结束日期
- 风控 demo 参数

## 7. 如果下载失败

请先检查：

- 当前环境是否能联网
- 是否需要提供 `ALPHAVANTAGE_API_KEY`
- 如果没有 key，`yfinance` 是否还能在当前环境里访问 Yahoo 数据

如果公共源都不可用，不要伪造 CSV。最小人工补充方式是：

1. 把你自己的历史 CSV 按 `src/data` 的 schema 放到本地目录
2. 把配置里的 cache 目录改到该 CSV 所在位置
3. 再执行一键回测
