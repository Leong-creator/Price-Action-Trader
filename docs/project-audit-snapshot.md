# Project Audit Snapshot

本页用于说明分析专用分支的用途，不定义新需求，不改变当前主线执行状态。

## 当前主线状态

- 稳定基线：`main`
- 基线提交：`14d43aa`
- 当前阶段：M8 可靠性验证
- 当前边界：继续保持 `paper / simulated`，不进入 broker / live / real-money

## 当前关键知识页

- `knowledge/wiki/concepts/market-cycle-overview.md`
- `knowledge/wiki/setups/signal-bar-entry-placeholder.md`
- `knowledge/wiki/rules/m3-research-reference-pack.md`
- `knowledge/wiki/sources/` 下 FangFangTu transcript、FangFangTu notes、Al Brooks PPT 相关 source 页

## 当前关键 run 目录

- `reports/backtests/m8c1_long_horizon_daily_validation/`
- `reports/backtests/m8c2_intraday_pilot_spy_15m/`
- `reports/backtests/m8c2_intraday_pilot_nvda_15m/`
- `reports/backtests/m8c2_intraday_pilot_spy_15m_regression/`
- `reports/backtests/smoke_public_demo_regression/`

## 分支用途

- 固定一个可公开访问的项目分析快照
- 让外部审计可直接基于 GitHub branch + commit 访问代码、文档、知识索引与关键运行产物
- 不作为新功能开发或缺陷修复分支

## 未新增公开内容的边界

- 不修改 `knowledge/raw/` 原始资料
- 不新增本地私密配置、凭证、缓存、虚拟环境或 `local_data/`
- 不为了快照重新运行新的 backtest / intraday session
