# 路线图

## 已完成阶段

1. `M0`：基础设施初始化
2. `M1`：知识库 schema、KB 校验、wiki index、资料投放流程
3. `M2`：测试数据、OHLCV schema、CSV/JSON 回放
4. `M3`：PA context、setup、signal 输出原型
5. `M4`：最小回测引擎与报告
6. `M5`：纸面交易、模拟执行与风控闭环
7. `M6`：新闻事件过滤与复盘整合
8. `M7`：正式券商 API readiness assessment，当前冻结结论为 `no-go`

## 当前主线

9. `M8`：可靠性验证（Reliability Validation，已完成至当前检查点）
   - 已完成：`M8A` 测试基线、文档与门禁落盘
   - 已完成：`M8B` 知识库对齐测试与 callable/trace 接入
   - 已完成：`M8C.1` 长周期日线验证
   - 已完成：`M8C.2` 单标的与第二标的日内试点
   - 已完成：`M8 shadow/paper baseline` 真实历史数据与录制型实时输入的只读验证基线
   - 已完成：`M8D.1` Artifact & Trace Unification
   - 已完成：`M8D.2` Curated Promotion Minimal Expansion
   - 已完成：`M8D.3` Repository State Consistency
   - 已完成：`M8E.1` Validation Gap Closure
   - 已完成：`M8E.2` Longer-Window Daily Validation
   - 延后：`M8E.3` Intraday Window Expansion（待每标的至少 30 个完整 regular session）

10. `M9`：Price Action Strategy Lab（legacy / historical baseline）
   - 已完成：Strategy Lab、Strategy Factory、Wave2 / Wave3 历史验证产物。
   - 当前边界：`PA-SC-*` 与 `SF-*` 只作为 legacy comparison，不作为 M10 提炼先验。

11. `M10`：Price Action Strategy Refresh（进行中）
   - 目标：从 Brooks v2 manual transcript、方方土 YouTube transcript、方方土 notes 重新提炼 `M10-PA-*` catalog 与测试计划。
   - 来源优先级：`brooks_v2_manual_transcript > fangfangtu_youtube_transcript > fangfangtu_notes`
   - 已完成：`M10.1` catalog freeze / test queue 与 `M10.2` Visual Golden Case Pack。
   - 当前产物：`reports/strategy_lab/m10_price_action_strategy_refresh/`

## 当前边界

- 默认运行边界仍为 `paper / simulated`
- 当前 `no-go` 结论继续有效
- M10 不重新评估真实 broker、真实账户、live execution 或付费 API
- 浏览器方案继续只允许只读观察、截图辅助分析、导出文件与临时验证，不进入生产执行链路
