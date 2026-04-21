# M9 Strategy Extraction Log

## Batch 1：Transcript 优先提炼

| 日期 | Batch | 来源 | 动作 | 产出 |
|---|---|---|---|---|
| 2026-04-20 | 1 | `fangfangtu-price-action-transcript` | 提炼市场周期、背景环境、突破 / 失败突破、开盘缺口、tight channel、2nd leg trap | `PA-SC-001` ~ `PA-SC-010` 的第一版骨架 |

已使用的 transcript 主题：

- 市场周期四阶段
- 背景环境大于信号 K
- 强趋势首次反转容易失败，需等 second entry
- 突破缺口、测量缺口、衰竭缺口
- 宽通道 / 交易区间中的失败突破与 trap
- 开盘缺口与微型双顶 / 头肩顶等开盘场景

## Batch 2：Brooks PPT 补证

| 日期 | Batch | 来源 | 动作 | 产出 |
|---|---|---|---|---|
| 2026-04-20 | 2 | `al-brooks-price-action-ppt-1-36-units` | 补 H2/L2、Always In、failed breakout、tight trading range、trend day、trend from the open | 为 `PA-SC-002`、`PA-SC-003`、`PA-SC-005`、`PA-SC-006`、`PA-SC-008`、`PA-SC-009` 提供可量化补证 |

已使用的 Brooks 主题页：

- `13/14`：H2/L2
- `29/30`：Always In
- `34/411-417/473`：failed breakout / signal bar 背景
- `464/471`：small TTR / trend resumption
- `918-957`：trend day / trend from the open

## Batch 3：Notes 补中文表述与缺口

| 日期 | Batch | 来源 | 动作 | 产出 |
|---|---|---|---|---|
| 2026-04-20 | 3 | `fangfangtu_notes` | 补充中文术语、例子、风险提醒与 open questions | 为各卡增加中文命名锚点与图表缺口说明 |

## 当前缺口

| 策略 ID | 缺口 | 当前处理 |
|---|---|---|
| `PA-SC-007` | 楔形判读高度依赖图表与重叠程度 | 保留 `draft` + `needs_visual_review: true` |
| `PA-SC-008` | 开盘区间突破 / 失败突破缺少标准化 regular-session 例图 | 保留 `draft` + `needs_visual_review: true` |
| `PA-SC-010` | 高波动个股过滤主要来自 Brooks 风险页，transcript 支撑偏弱 | 保留 `draft`，仅形成研究假设 |

## 当前结论

- 首批 10 张卡已全部落盘到 `knowledge/wiki/strategy_cards/`。
- `PA-SC-002`、`PA-SC-003`、`PA-SC-005` 已补成详细测试计划，是第一优先回测候选。
- `PA-SC-007`、`PA-SC-008`、`PA-SC-010` 保持 `draft`，原因分别是楔形图表依赖高、开盘例图不足、高波动过滤仍缺统一字段与事件标签。
- 本轮不生成“已跑回测”结论；若后续数据或事件标签不足，保持 `candidate` / `draft` 即可。
