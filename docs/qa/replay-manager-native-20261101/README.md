# 回放 Manager 原生验收

本记录验证应用源码 `09e5259f35bfd44b8eef1f330a52473666d13b3a`。随后提交只增加本目录证据。平台为本机 macOS arm64，使用从 ZIP 解压并移到带空格目录的签名应用、内置 Python 后端和隔离配置。

ZIP SHA-256：`dfa023703e512bb117660065285bd9dac609fcc781bbf7f514b83732ab1fbc0b`。包内 backend/desktop 文件及 162 个 dist 文件逐字节核对，源码清单共 3,096 项；运行前后严格签名检查通过。完整本地检查通过 4,699 项前端测试、1 项独立性能检查、127 项桌面测试，以及架构、插件、30 语言、类型、lint、生产构建。见 [检查记录](checks.json) 和 [包清单](source-package-manifest.json)。最终提交的云端 CI 仍是合并条件。

## 已验证范围

| 场景 | 结果与证据 |
| --- | --- |
| 创建、下单、推进、平仓 | 两笔近似模型市价成交与独立 Decimal 公式一致：费用 0.30060500，已实现盈亏 0.0598790，现金 9999.75927400，账本对账差为 0。[财务核算](financial-oracle.json) |
| 存档、完整退出、重启 | 账户、运行 ID、虚拟时钟恢复一致，重启后可继续推进；正常退出，逐个确认所属进程树消失。[基础回执](acceptance-basic.json) |
| 多图及连接 | 1m/5m 独立序列；已关闭 1m OHLCV 与输入公式逐项一致，无越过揭示时间的行情。实际断网及关闭 WebSocket 5 秒后重连，约 3,758 ms 可继续推进。关闭一图只释放其序列，回大厅后序列、连接、请求均为零。[生命周期回执](acceptance-lifecycle.json) |
| 指标与显示 | 已关闭 K 线对应的 MA20 实际输出逐点比较；1m 使用独立输入公式，5m 使用显示的 20 根已知收盘价计算，并对回放起点之后至少两根完整 5m K 线核对五根基础 K 线聚合。每图至少 30 个实际可见且已关闭的点必须有正确输出。正式控制接口将视图定位到已揭示历史，推进、保存、完整退出重启后，游标和输出点集一致。[指标回执](acceptance-indicator.json) · [双图截图](ma20.png) |
| 桌面导出 | 真实 renderer → 受信 IPC → 主进程固定回环地址 → Electron DownloadItem → 磁盘完成，509 字节、终止记录数量及 SHA-256 一致。下载目的地由验收脚本通过 DownloadItem 选择，没有替换响应或缓存整个 renderer Blob。[下载回执](acceptance-download.json) · [文件](native-export-probe.ndjson) |

所有上述成功回执均无 renderer 异常。输入是有限的合成 1m OHLCV 和配套合成商品元数据；窗口显式设置为 `DURATION=21600000`（6 小时），不是线上历史完整性或历史精确账户模型的证明。5m 起点之前的行情只作为实际显示输入计算 MA 参考，不宣称整段提供商历史等于合成 1m 数据。

## 修复与未通过边界

- 旧集成包在暂停重连时拒绝服务端重发的未变化原子快照。修复仅允许 reconnect/resync 下 sequence、revision、虚拟时间、源游标、state hash 完全一致的交接；已建立连接和其他因果校验未放宽。最终生命周期回执证明该路径可继续推进。较长断网若控制权过期仍需要重新获取；旧尝试观察到该行为，本次 5 秒尝试未触发。
- 旧普通导出链接被桌面跨端口导航限制拦截，见 [原生失败证据](export-blocked-native.json)。新增入口只接受 run ID，由主进程构造地址，不放开任意导航或下载。单市场夹具没有组合区间，因此 UI 正确隐藏曲线导出链接；本次直接调用真实 bridge 验证空导出。**非空多市场曲线的完整 UI 导出及系统保存对话框未验收。**
- `ALL_AVAILABLE` 的旧候选包曾出现冷 5m 历史等待超过 25 秒，以及 MA 报 `Could not read the provider history boundary`（HTTP 503），见 [失败回执](acceptance-indicator-all-available-failed.json)。最终 6 小时窗口通过不等于这些默认全部历史问题已解决。
- 验收脚本曾错误等待 renderer 的 `download` 事件，而实际主进程已触发 `will-download`；最终改为观察原生 DownloadItem 的完成事件并核对真实文件。另一次指标断言把全部缓存行情当成已请求的指标输出范围；更正后比较已关闭 K 线对应的实际输出，并要求实际可见区非空且覆盖完整。早期数值检查时视图曾停在未来空白区，不能当作可见渲染通过；最终显式定位到历史并保留双图截图。

原始尝试、日志、流量、隔离数据库、安装包保存在工作区 `output/pr180-native-20261101`、`output/pr180-native-final-20261101`、`output/pr180-native-host-final-20261101`，没有将失败记录改写为成功。

## 复现

脚本按基础、生命周期、指标、下载的顺序使用同一隔离运行；每个阶段结束后先存档其 `acceptance.json` 和 `traffic.json`。运行 `verify-package.mjs` 的工作目录须为仓库根目录，测试脚本的根路径和 ControlClient 路径应指向对应候选工作区。`setup-native.mjs` 拒绝覆盖已有而未记录夹具的数据库。完整退出通过 Playwright 的正常 Electron close 路径发起并核实子进程，不强杀进程制造通过。

本目录不代表 Windows/x64 安装验收、公证发布资格、#166 全部要求或完整 157 项验收通过。
