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

- `/home/hgl/projects/Price-Action-Trader/config/examples/public_history_backtest_long_horizon_longbridge.json`

默认会跑：

- `NVDA`
- `TSLA`
- `SPY`

时间范围默认是：

- `2010-06-29` 到 `2026-04-21`

## 3. 一键命令

如果本地已经有 `.venv`，直接执行：

```bash
bash /home/hgl/projects/Price-Action-Trader/scripts/run_public_backtest_demo.sh
```

该命令会：

1. 使用 `Longbridge` 只读历史行情接口下载数据
2. 把历史数据缓存到本地 CSV
3. 基于当前策略/回测/风控能力生成用户可读报告

## 4. 只下载不回测

```bash
/home/hgl/projects/Price-Action-Trader/.venv/bin/python \
  /home/hgl/projects/Price-Action-Trader/scripts/download_public_history.py \
  --config /home/hgl/projects/Price-Action-Trader/config/examples/public_history_backtest_long_horizon_longbridge.json
```

## 5. 默认 Longbridge 模拟账户路径

当前项目默认历史回测入口已经切到这条路径，并且只要求模拟账户只读行情权限。

它仍然只允许：

- `longbridge kline history`
- 本地 CSV/JSON 缓存
- Codex 内 `paper / simulated` 回测

它不允许：

- 下单
- 资产查询
- 持仓管理
- live / real-money

安装 CLI：

```bash
mkdir -p ~/.local/bin
curl -L https://github.com/longbridge/longbridge-terminal/releases/latest/download/longbridge-terminal-linux-musl-amd64.tar.gz \
  -o /tmp/longbridge-terminal.tar.gz
tar -xzf /tmp/longbridge-terminal.tar.gz -C /tmp
install /tmp/longbridge ~/.local/bin/longbridge
```

登录模拟账户：

```bash
longbridge auth login
```

下载长周期日线缓存：

```bash
/home/hgl/projects/Price-Action-Trader/.venv/bin/python \
  /home/hgl/projects/Price-Action-Trader/scripts/download_public_history.py \
  --config /home/hgl/projects/Price-Action-Trader/config/examples/public_history_backtest_long_horizon_longbridge.json
```

运行 `SPY 5m` intraday pilot：

```bash
/home/hgl/projects/Price-Action-Trader/.venv/bin/python \
  /home/hgl/projects/Price-Action-Trader/scripts/run_intraday_pilot.py \
  --config /home/hgl/projects/Price-Action-Trader/config/examples/intraday_pilot_spy_5m_longbridge.json
```

当前 Longbridge 适配默认支持：

- daily: `1d`
- intraday: `1m`、`5m`、`15m`、`30m`、`1h`

如果授权完成但仍提示权限不足，请回到 Longbridge OpenAPI 授权页确认已勾选行情权限。

## 6. 数据与报告位置

本地缓存目录：

- `/home/hgl/projects/Price-Action-Trader/local_data/public_history/`
- `/home/hgl/projects/Price-Action-Trader/local_data/longbridge_history/`
- `/home/hgl/projects/Price-Action-Trader/local_data/longbridge_intraday/`

报告输出目录：

- `/home/hgl/projects/Price-Action-Trader/reports/backtests/<run_id>/`

每次回测至少会生成：

- `report.md`
- `trades.csv`
- `summary.json`
- `equity_curve.png`

## 7. 你可以改什么

最简单的改法是直接改配置文件里的：

- 标的列表
- 开始/结束日期
- 风控 demo 参数

如果是 intraday 配置，还需要同步改：

- `interval`
- `session.expected_bars_per_session`

## 8. 如果下载失败

请先检查：

- 当前环境是否能联网
- `longbridge` 是否已经安装到当前 shell 的 `PATH`
- 是否已经完成 `longbridge auth login`
- Longbridge OpenAPI 是否已经启用行情权限

如果你仍想手动测试旧公共源，请显式在配置里把 `source_order` 改成 `alpha_vantage` 或 `yfinance`。这两条路径不再是项目默认值。

如果公共源都不可用，不要伪造 CSV。最小人工补充方式是：

1. 把你自己的历史 CSV 按 `src/data` 的 schema 放到本地目录
2. 把配置里的 cache 目录改到该 CSV 所在位置
3. 再执行一键回测
