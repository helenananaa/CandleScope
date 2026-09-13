# 通用 Python BAR 执行路径：原生构造与原格式回执

本轮在独立 worktree `CandleScope-strategy-replay-performance` 实现，接续此前未提交工作。未提交、未合并、未推送、未部署。

## 覆盖范围

不再按策略源码或官方模板筛选。符合现有 SDK 的普通 Python 脚本，包括状态机、依赖成交反馈的策略和直接下单策略，都继续使用原来的 prepare/warmup/step/on_execution_report/snapshot/restore 接口。无需换模板、声明纯行情或选择新协议。

目前优化接入 TRUSTED_LOCAL 的整个 BAR 回测工作进程。脚本仍逐根执行；宿主不把未来行传给脚本。SANDBOXED_LOCAL、交易带和双时钟执行未声明获得同等加速。输入数据或 SDK 布局不满足原生构造条件时走已有路径，保持原来的处理能力。

## 同机完整运行对照

2026-09-13，Windows x64 / Anaconda CPython 3.12.7。每个样本 100,000 根合成 K 线，EXECUTION_REALISM_V2，新工作进程，不复用策略结果缓存。包括工作进程启动、策略、撮合、成本敏感性、检查点和完整报告保存；不包括导入/冻结、先行 smoke、数据生成、排队和浏览器渲染。

| 普通 V1 脚本 | 关闭通用原生路径 | 开启 | 成交数 |
|---|---:|---:|---:|
| 空脚本（计数但不发单） | 7.285 s | 2.924 s | 0 |
| 官方 SMA 3/5 | 10.250 s | 5.758 s | 797 |
| 状态机 | 8.066 s | 3.978 s | 796 |
| 成交反馈驱动 | 9.255 s | 5.204 s | 1563 |
| 定期直接发出 MARKET 订单 | 8.658 s | 5.100 s | 2000 |

表格对应 `output/generic-python-20260912/final-<CASE>-<0|1>.json`，不是先前 SMA 专用 MARKET_BATCH_V1 通道。环境开关为 `BACKTEST_GENERIC_BAR_ENABLED`。

随后相邻复测（`repeat-*.json`）：空脚本 6.367 → 2.641 s，SMA 9.252 → 4.942 s。结合表中样本，空脚本开启后为 2.64–2.92 s，SMA 为 4.94–5.76 s；保留全部结果，不以最快单次值代替范围。

所有完成样本报告哈希校验通过，开关两侧的成交数、权益点数和报告字节数一致。各脚本完整 result/report 及两种 V1 transcript 的逐项相等，由复制同一个初始数据库的测试验证，避免把不同 runId 的报告哈希直接比较。

**覆盖面已扩展，整体 2–3 秒目标仍未达到。** 空脚本进入约 3 秒，包含信号、成交和报告的样本仍约 4–6 秒。这里是小样本本机对照，不能宣称生产 P95，也不能保证任意用户算法本体都很快。中间实现的较慢样本和 profiler 输出也保留在证据目录，不与最终表格混算。

### 内存

最终对照同时读取进程生命周期 PeakWorkingSetSize。空脚本的子进程约 105 MiB，SMA/状态机约 118–120 MiB，成交反馈约 133 MiB，直接下单约 141 MiB。开关两侧接近，没有观察到明显额外内存增长。父进程另约 144 MiB；两个峰值不代表同一时刻，不能相加冒充进程树同时峰值。

## 实现

1. `backend/native/rows.c` 是可选 CPython 扩展。一次构造脚本实际收到的 SDK Observation/Bar，省去宿主 Frame、SDK 输入字典及重复归一化。规范的十进制字符串保持原拼写；科学计数法等特殊输入回退到原有转换。
2. 保留 SDK 类型、独立可变字典和每根新的对象；不复用可被脚本修改的观察对象。检查 SDK 类、构造器身份和成员布局，避免对不同布局直接写入。
3. 原生构造输入 JSON、输出 JSON、V1 请求/响应记录及事件字节预算。对照涵盖控制字符、DEL、整数和 Unicode 回退；没有放宽消息、时钟或状态预算。
4. V1 的无绑定流式 SHA256 和有绑定链式 SHA256 均保持原字节内容。没有修改 transcript 协议、config hash 或报告身份来容纳新结果。
5. 任意用户方法仍动态逐根调用，成交反馈沿原路径执行。时间水位、序号、调用超时、取消和恢复继续由现有宿主与监督进程处理。
6. 空决策哈希直接使用标准 JSON 的字符串编码函数，避免额外创建 JSON encoder；其原始编码规则不变。

原生代码只接纳已证明等价的数据形状。复杂映射、非规范数字、超界整数或不匹配 SDK 会回退，不会因为策略没有认证而拒绝运行。此前的专用批量协议仍是独立可选路径，本轮不依赖它。

## 验证

- 后端回归 **266 项通过、4 条警告**：`output/generic-python-20260912/regression.xml`。
- 将实际通过安装验证的二进制放入活动 backend 包后，原生专项 **28 项通过、4 条警告**：`final-native-tests.xml`。两组有重叠，不相加。
- 测试覆盖每根 SDK 值及回执字节相等、ASCII 全字符范围、数值拼写、特殊值回退、对象别名隔离、引用计数/GC、SDK 构造器与成员变化、缺少/不兼容扩展、用户异常位置、状态和成交反馈。
- 空脚本、状态机、反馈、直接下单四类脚本，分别在绑定/未绑定 V1 transcript 模式下进行实际 spawn 的完整 result/report 对照。
- 原有真实超时、取消、恢复、stdout 限额、账户、撮合、双时钟和协议回归继续通过。
- 原生扩展使用本机 MSVC 14.44 编译，未借用另一个操作系统的测试结果。

### 已安装工件验证

原生和 SDK wheel 均已构建，安装到独立 target 目录。通过 `python -I scripts/verify_native_installation.py <site>` 检查模块实际来自该安装目录，验证输入、输出和 V1 记录哈希。

记录：`output/generic-python-20260912/installed-verification.json`，状态 PASS，`ROW_PROTOCOL_ABI=1`。

验证后用于最终运行的 `_native_rows.cp312-win_amd64.pyd` SHA256：

`3d88235c24aa38abaaa6e3e8eaf82a8e55dd89aa65851c1c11dc7104fd7e8872`

wheel 在 `output/generic-python-20260912/wheels/`。安装过程不访问索引；构建阶段使用了隔离构建依赖。尚未发布这些工件。

## 构建与复现

原生工件与 CPython ABI/架构匹配，不是 abi3。缺失或不匹配时自动退回原路径，因此普通源码 checkout 要重新构建才能获得此加速。详见 `backend/native/README.md`。

在 backend 目录：

```powershell
python native/setup_native.py build_ext --inplace --build-temp ../output/native-build
python -c "from app.backtest.strategy import _native_rows; print(_native_rows.__file__, _native_rows.ROW_PROTOCOL_ABI)"
$env:BACKTEST_GENERIC_BAR_ENABLED='1'
python -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --python-case FEEDBACK --v2 --output ../output/generic-feedback.json
```

`--python-case` 支持 EMPTY、SMA、STATE、FEEDBACK、ORDERS；将开关改为 `0` 获取原路径对照。不要添加 `--python-batch`，那是此前另一套显式协议的实验。
