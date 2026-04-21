# M9 Initial Project Snapshot

## 1. Git 快照

| 项目 | 值 |
|---|---|
| 初始稳定分支 | `main` |
| 初始 commit | `d9ef8a73ff8bdb4e08605b13cd64233d95ade6dc` |
| 当前策略支线 | `feature/m9-price-action-strategy-lab` |
| 初始 `git status` | `?? knowledge/raw/brooks/ppt/`, `?? knowledge/raw/notes/`, `?? knowledge/raw/youtube/fangfangtu/transcripts/` |

## 2. 当前 M8 进度摘要

- `M8E.2 Longer-Window Daily Validation` 已完成并整合进 `main`。
- 当前 daily 更长窗口验证范围：`NVDA / TSLA / SPY`、`1d`、`2018-01-01 ~ 2026-04-17`。
- `validation / out_of_sample` 仍为 `insufficient_sample`，不能包装成“已充分验证”。
- 当前长期稳定基线仍是 `main`，M8 继续保持 `paper / simulated` 和 `no-go` 边界。

## 3. 目录概览

### 3.1 知识来源

- `knowledge/raw/brooks/ppt/`
- `knowledge/raw/brooks/extracted_text/`
- `knowledge/raw/youtube/fangfangtu/transcripts/`
- `knowledge/raw/youtube/fangfangtu/metadata/`
- `knowledge/raw/youtube/fangfangtu/supplements/`
- `knowledge/raw/notes/`

### 3.2 当前 wiki

- `knowledge/wiki/concepts/`
- `knowledge/wiki/setups/`
- `knowledge/wiki/rules/`
- `knowledge/wiki/sources/`
- 其余目录仍以占位或空目录为主

### 3.3 当前回测 / 验证报告

- `reports/backtests/demo_public_2024h1/`
- `reports/backtests/m8c1_long_horizon_daily_validation/`
- `reports/backtests/m8c2_intraday_pilot_spy_15m/`
- `reports/backtests/m8c2_intraday_pilot_nvda_15m/`
- `reports/backtests/m8e2_longer_window_daily_validation/`
- `reports/backtests/smoke_public_demo/`

## 4. 当前已知安全边界

- 默认运行边界：`paper / simulated`
- 当前正式 broker 结论：`no-go`
- 不得接真实账户
- 不得启用自动实盘下单
- 不得改写 `knowledge/raw/`
- 不得把 `statement` / `source_note` / `bundle support` 升格为 trigger

## 5. M9 起始目标

- 以 `fangfangtu_transcript > al_brooks_ppt > fangfangtu_notes` 的固定优先级盘点来源。
- 建立 `knowledge/wiki/strategy_cards/` 与 `reports/strategy_lab/`。
- 先产出首批 10 张 strategy cards 和 3 份详细测试计划，不把“已跑回测”作为本轮完成前提。
