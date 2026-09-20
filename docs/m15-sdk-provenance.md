# M15 官方 SDK 环境来源核验

正式解释器固定为项目根目录 `.venv-m15/bin/python`。旧 `.venv`、同版本本地
wheel、`PYTHON_BIN` 环境覆盖均不再具有正式入口资格。

`config/m15_official_sdk_artifact.json` 是需要独立核对和提交的信任记录。
其中 wheel 文件名、SHA256 与下载地址必须从官方 PyPI 对应版本发布元数据
取得并核对，不能根据当前已安装二进制计算后反填。版本号不足以证明来源。
本记录属于部署源码指纹的一部分；修改它必须重新审查、提交并签发部署清单。

在已安装纯净官方 wheel 的正式解释器下执行（将路径替换为实际保留的 wheel）：

```bash
.venv-m15/bin/python scripts/run_m15_sdk_provenance.py --wheel /absolute/path/longbridge-5.0.0-cp312-cp312-manylinux_2_39_x86_64.whl
.venv-m15/bin/python scripts/run_m15_sdk_provenance.py --verify
```

签发结果固定保存在 `reports/runtime/m15_sdk_environment.json`。核验完全离线，
不会导入 SDK、创建 OAuth、行情或账户连接。原始 wheel 必须保留在稳定位置，
不能仅存 `/tmp`。校验会重新核对官方预期 SHA256、安装包文件、原生模块、
解释器二进制和环境路径；本地补丁标记、额外包文件、导入路径遮蔽、旧 DNS
注入环境均拒绝。receipt 不是信任锚，修改其摘要不能绕过官方 wheel 对比。

5.0.0 的真实原生模块是 `longbridge.longbridge`，`longbridge.openapi` 是它导出的
Python 别名，没有独立 `__file__`；核验原生 `.so` 的路径/摘要，并在 SDK 已导入时
检查包导出、原生导出和 `sys.modules` 三处别名对象一致，不把 `openapi.py` 占位文件
误当原生模块。导入前后核验结果必须一致。

部署清单升级到 `m15.deployment-manifest.v2`，包含环境完整记录。旧清单拒绝；
切换解释器、wheel、模块或信任记录后需要重新核验并重新签发清单。运行层及
诊断入口在任何券商访问前调用 `verify_environment()`；返回 `verified=false`
时保留 `issues` 并终止启动。核验不负责中止已有进程或删除凭证。

Windows 安装器只注册一个任务，登录和工作日20:45两个触发器均通过同一个隐藏
VBS进入启动脚本；注册成功后清理同名旧 Startup 目录入口，注册失败直接报告。
脚本用 `flock` 排除同时触发，锁不传给后台子进程。默认只读，绝不自动附带
`--dispatch`，不进行自动重试；运行层原有故障锁仍须通过。

隔离离线测试不依赖真实券商环境：

```bash
python3 -m unittest tests.unit.test_m15_sdk_provenance tests.unit.test_m15_deployment_governance tests.unit.test_m15_canonical_startup -v
bash -n scripts/start_m15_trading_stack_after_boot.sh
```

真实官方 wheel 兼容测试可显式提供 `M15_OFFICIAL_TEST_ROOT`（含 `.venv-m15` 的项目）
和 `M15_OFFICIAL_TEST_WHEEL`（持久 wheel 路径）后运行同一测试。它只离线导入SDK，
不创建上下文；原生篡改验证在另建的临时环境完成，不修改正式安装或receipt。

风险边界：这是本地环境一致性与官方制品来源检查，不是抵御拥有本机写权限
攻击者的远程证明；运行中的同进程恶意内存修改不在本检查范围。正式启动器、
环境和信任记录的任何高风险改动仍需人工复核，不能由单测取代。
