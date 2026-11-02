# #152 当前桥接核对与前缀比较优化

基线 main a12432252f42c380245a90ec2fcfc48210f4e1f4。只优化已经由 SDK 不可变 Bar 身份证明的已保留前缀；没有修改 Pine 数学、IPC schema、引擎版本或绘图结果。

## 实际能力和范围修正

当前 SDK/sidecar 已协商 inputBarsPatch 与 outputPatch。历史 issue 使用的 b84b5e3d/发布锁并非当前桌面组装配方，不能据其推断现在每次全量传输。实际配方是 frontend/scripts/desktop-plugin-sources.json：SDK 0.2.1，bridge 0.4.0，engine 0.3.3+cs.1（c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc，加 host-contracts-v2 补丁 SHA256 53cc3758f4fb575d02e00094b5b8a29ff35e2992eddd57273ff72b1af6485ec3）。历史 release/release-lock.json 保持原样。

在保留的合格 H127 插件环境中只读加载实际 native engine；上游源码归档 SHA256 d7da1e620453bd978ea7afd76642717462d0bacf1000bc248f1acaa238a8b695 验证后用于 API 检查，未重编译或改动该环境。RealtimeSession 提供 changes，RuntimeReplica 可在 native 内 apply；但公开 result() 仍返回完整 Python 结果，没有已核实的局部读取接口。不能把 apply 后再次全量 result() 描述为消除全量物化。

## 改动

_normalize_bars 原有检查通过 SDK frozen Bar 的同一对象身份复用已验证行。新增私有 RetainedInputPrefix，把该证明绑定到同一 Pine session 的上一规范化窗口和位置。只有证明完整覆盖 retained overlap 时，才省略第二次字典前缀比较及对应切片；新的 Bar 对象、历史修正、窗口缩短、执行时钟、请求数据、源码/参数变化继续走原验证/reseed。证明不从请求 options 反序列化，不进入持久化 journal，恢复后需要重新证明。confirmed 行仍按原逻辑复制保存。

## 验证和测量

完整 bridge 包：228 passed, 1 skipped（核心未声明 compact external appends 的策略能力测试），使用实际 pinned native engine；跳过项见原始日志，未计入通过数。新增实际 SDK dispatcher 测试：稳定 tick 不再比较 confirmed 字典；旧历史修正触发 reseed，结果与独立 full-wire host 相同。既有完整包覆盖绘图对象、窗口、时钟、requested contexts 和恢复。

measure_bridge.py 使用实际 engine + 当前 source SDK/bridge，同输入 EMA20 与 close*2，100 tick，三个交替顺序的 paired trials。baseline 在同代码中仅关闭 validated_prefix；没有网络、IPC 或 UI。paired.json 的旧 scope 文案误写 tracemalloc enabled，原始显式 tracemalloc=false/cprofile=false 字段才是本组事实；原始记录保留，驱动文案已更正。

| 历史根数 | 旧比较路径 tick P50（3次，ms） | 复用证明后（3次，ms） |
| --- | --- | --- |
| 1k | 0.328 / 0.326 / 0.324 | 0.270 / 0.272 / 0.268 |
| 10k | 1.764 / 1.737 / 1.736 | 1.073 / 1.073 / 1.067 |
| 50k | 9.398 / 9.403 / 9.582 | 6.197 / 5.942 / 5.915 |

每组100 tick仍调用100次完整 native.result()，输出补丁100次。最初10k/20tick cProfile 显示全量 native conversion 约占总耗时9%，重复 confirmed 比较/切片是更大的 Python 成本。此优化没有消除所有 O(N) 输入准备、规范化、输出扫描/物化，也不是宿主全链路性能结论。

## 未完成资格

后端 host 集成21项通过。真实 sidecar/native 包默认路径、保存/完全退出/重启及 CI 尚需独立回执。更完整的 #152 原生输出变化消费与稳定 tick 无 result() 路径仍未实现；本 PR 不关闭整个 issue，不在 bridge 复制另一份 Pine 引擎或通过截短历史获得收益。Windows 单独资格。

## 当前源码 wheel 与真实隔离进程补充

本地重建 SDK/bridge wheel，SDK canonical SHA256 与已合格配方相同；桥接 wheel 为7fb01a231083f06ba34ef2475679b1006e2630ec4364707e1a8e108eb6ba5403。重用未改 engine wheel 的06c009...摘要经原锁核对，使用正式 build_locked_bundle 与 PluginInstaller 创建全新安装，不改保留环境。bundle SHA256 f9a075b9f5c2153ba3577f60d9cc5cd68469a030b06bb6b049f8481252d51912。此为本地受控包，非重新编译engine或正式发布。

qualify_bundle.py 仅把现有宿主测试的进程入口替换为该全新安装的 Python -I + wheel imports，保留原16步输出与44步输入断言，包括tick/收盘/滚窗/旧历史修正/多个订阅/会话淘汰/进程重启/journal恢复。60步比较通过，4个自有隔离进程正常停止。比较完整输入/输出与协商补丁结果一致。没有网络、HTTP/UI、真实市场或原生保存重启性能结论。

先前直接从通用开发venv运行源码sidecar测试时，父进程PYTHONPATH并不会传入安全子进程，故2项在handshake报缺少pine_compat；并非产品补丁失败。原始失败保留；改用正式安装wheel解决，未放宽安全环境隔离。
