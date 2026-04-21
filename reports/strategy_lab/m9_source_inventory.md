# M9 Source Inventory

## 来源优先级

1. `fangfangtu_transcript`
2. `al_brooks_ppt`
3. `fangfangtu_notes`

## 第一优先：FangFangTu Transcript

| Source Family | Source Page | Raw Source | Parse Status | Pages | 角色 |
|---|---|---|---|---:|---|
| `fangfangtu_transcript` | `knowledge/wiki/sources/fangfangtu-price-action-transcript.md` | `knowledge/raw/youtube/fangfangtu/transcripts/Price_Action方方土.pdf` | `parsed` | 15 | 首批策略卡的主证据来源 |

重点主题：

- 市场周期四阶段
- 背景环境大于信号 K
- 限价单 / 突破单 / 市价单的场景差异
- 突破与 follow-through
- 失败突破、2nd leg trap、tick trap
- gap / measured move / exhaustion
- 开盘相关反转与缺口场景

## 第二优先：Brooks PPT

| Source Family | Source Page | Raw Source | Parse Status | Pages | 角色 |
|---|---|---|---|---:|---|
| `al_brooks_ppt` | `knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md` | `knowledge/raw/brooks/ppt/AIbrooks价格行为通用版1-36单元.pdf` | `parsed` | 2819 | 首批规则补证主来源 |
| `al_brooks_ppt` | `knowledge/wiki/sources/al-brooks-price-action-ppt-37-52-units.md` | `knowledge/raw/brooks/ppt/AIbrooks价格行为通用版37-52单元.pdf` | `parsed` | 1397 | 第二补证来源 |

重点补证页：

- `1-36`：`13/14`（H2 / L2）、`29/30`（Always In）、`34`（failed breakout）、`411-417`（failed breakout / signal bar）、`464/471/473`（TTR / trend resumption / failed breakout）、`918-957`（trend day / trend from the open）
- `37-52`：作为 H2/H3、wedge、gap/measured move 的延伸补证，不作为首批 actual trace 主来源

## 第三优先：FangFangTu Notes

| Source Page | Raw Source | Parse Status | Pages | 本轮作用 |
|---|---|---|---:|---|
| `fangfangtu-market-cycle-note.md` | `knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf` | `parsed` | 3 | 术语澄清、市场周期中文摘要 |
| `fangfangtu-signal-bar-entry-note.md` | `knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf` | `parsed` | 3 | signal bar / entry 中文表述补充 |
| `fangfangtu-pullback-counting-bars-note.md` | `knowledge/raw/notes/方方土视频笔记 - 回调&数K线.pdf` | `parsed` | 3 | H1/H2/H3、L1/L2/L3 规则命名补充 |
| `fangfangtu-breakout-note.md` | `knowledge/raw/notes/方方土视频笔记-突破.pdf` | `parsed` | 4 | breakout / 2nd leg trap 补充 |
| `fangfangtu-gap-note.md` | `knowledge/raw/notes/方方土视频笔记 - 缺口.pdf` | `parsed` | 3 | gap 类型中文分类补充 |
| `fangfangtu-wedge-note.md` | `knowledge/raw/notes/方方土视频笔记 - 楔形.pdf` | `partial` | 6 | wedge 术语、变体和风险提示补充 |

说明：

- notes 只作第三优先补充来源，不单独把策略从 `draft` 推到 `promoted`。
- `fangfangtu-wedge-note` 为 `partial`，第 6 页不能作为关键证据。

## 首批 10 张卡的来源映射

| 策略 ID | 第一来源 | 第二来源 | 第三来源 | 图表依赖 |
|---|---|---|---|---|
| `PA-SC-001` | transcript | Brooks PPT | pullback & counting-bars notes | `medium` |
| `PA-SC-002` | transcript | Brooks PPT | breakout notes | `medium` |
| `PA-SC-003` | transcript | Brooks PPT | breakout notes | `medium` |
| `PA-SC-004` | transcript | Brooks PPT | breakout notes | `medium` |
| `PA-SC-005` | transcript | Brooks PPT | pullback & counting-bars notes | `medium` |
| `PA-SC-006` | transcript | Brooks PPT | market-cycle notes | `medium` |
| `PA-SC-007` | transcript | Brooks PPT | wedge notes | `high` |
| `PA-SC-008` | transcript | Brooks PPT | wedge notes | `high` |
| `PA-SC-009` | transcript | Brooks PPT | market-cycle notes | `medium` |
| `PA-SC-010` | transcript | Brooks PPT | wedge notes | `high` |
