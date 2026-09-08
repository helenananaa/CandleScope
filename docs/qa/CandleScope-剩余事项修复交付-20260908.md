# CandleScope 剩余事项修复交付

日期：2026-09-08。承接上一轮 51 个修复提交，本轮新增 14 个独立修复提交，业务代码截至 `88e2c230`。每个问题都有分项记录和针对性验证；本文件是交付索引，不将原审计回写成“全部无问题”。

## 本轮修复

| 问题 | 修复结果 | 提交与记录 |
|---|---|---|
| 后端已退出，桌面进程仍等 15 秒 | 清除退出竞争中的残留定时器 | `2a42e95e` [F24](fixes/F24-sidecar-shutdown-timer.md) |
| 原生启动失败没有可见原因 | 原生错误对话框显示原因和日志位置 | `d55e0059` [F25](fixes/F25-native-startup-error-dialog.md) |
| 原生数据写进安装目录 | 改到 userData/data，保留显式覆盖 | `894d86e8` [F26](fixes/F26-native-writable-data-directory.md) |
| 退出时窗口流连接阻止后端停止 | 先关窗口，再停止后端与资源服务 | `5d48078d` [F27](fixes/F27-native-quit-stream-order.md) |
| RSI 第一根满足预热的实时值为空 | 补齐初始均值的只读预览 | `297fe54a` [F28](fixes/F28-rsi-first-valid-preview.md) |
| MACD 快慢线／信号线首个有效值为空 | 补齐三个 EMA 边界预览 | `38967281` [F29](fixes/F29-macd-first-valid-preview.md) |
| EMA 首个有效实时值为空 | 用含形成 K 线的初始平均预览 | `581c4c69` [F30](fixes/F30-ema-first-valid-preview.md) |
| ATR 首个有效实时值为空 | 补齐初始真实波幅平均预览 | `4d26e85a` [F31](fixes/F31-atr-first-valid-preview.md) |
| MA 首个完整窗口实时值为空 | 初始窗口计入形成 K 线，不误减旧值 | `e6b74b07` [F32](fixes/F32-ma-first-valid-preview.md) |
| 布林带首个完整窗口实时值为空 | 补齐初始均值和总体标准差预览 | `73f52e6d` [F33](fixes/F33-boll-first-valid-preview.md) |
| 历史补载后点数图日期轴保留旧日期 | 刷新 ordinal 日期缓存和共享时间点，保留视野 | `226d5679` [F13d](fixes/F13d-ordinal-source-date-refresh.md) |
| 自选无法按表头排序 | 四列表头支持快照升降序，持久化结果 | `263af574` [F34](fixes/F34-watchlist-column-sorting.md) |
| 原生包必须依赖项目 Python 环境 | 打包独立 Python、依赖及 SDK，默认从包内启动 | `77e164c5` [F35](fixes/F35-bundled-python-runtime.md) |
| 发行包启动重复解析 Python 源码 | 构建时生成可迁移的哈希字节码 | `88e2c230` [F36](fixes/F36-precompile-packaged-python.md) |

## 实际发行环境与验证

Mac arm64，Electron 43.3.0，Vite production 构建，无 HMR；最终包包含 Python 3.12.14。成品路径：`frontend/desktop-dist/mac-arm64/CandleScope.app`。标准复建命令为 `cd frontend && npm run desktop:package:dir`，构建机需具备 uv、Node、依赖下载条件；成品运行不需要项目虚拟环境。

最终启动使用全新 QA 用户目录、PATH=/usr/bin:/bin，移除 Python／sidecar 命令覆盖。进程路径确认运行包内解释器，原生窗口加载 1501 根历史及实时盘口。正常 Cmd+Q 后后端完成 application shutdown；没有再等待 15 秒强杀。所有此次用户数据和证据保留在 `output/user-audit-20260908/`，没有提交行情数据库。

验证结果按范围列出，不相加为“独立用例总数”：

- 最终包内 Python：指标、指标 API、DataManager bridge、批量计算、序列修订共 **116 passed**，1 条依赖弃用警告。日志 `final-bundled-backend-tests.log`。
- 桌面相关 **43 passed**；自选相关 **31 passed**。日志 `native-runtime-tests.log`、`watchlist-sort-tests.log`。
- 图表日期轴修复：适配器／图表表示 **426 passed**，相关组件生命周期 **45 passed**；点数图固定格值 500、历史 1501→2001、往返普通 K 线后日期与图形位置一致。范围见 F13d。
- 绘图和自选既有测试 **754 passed**。GUI 创建线段、矩形、文字、斐波那契、画笔，刷新、切换 SOL 返回 BTC、完整原生重启后恢复。截图 `drawing-btc-after-native-restart.png`。
- 自选 BTC／ETH／SOL：价格与涨跌幅升降序符合点击时数值；刷新和重启保留 ETH／SOL／BTC 顺序。见 F34。原生 HTML5 手工拖动未取得可靠成功证据，不把表头排序验证替代全部拖动路径验收。
- 七个内置指标、11 条输出、16265 个真实历史非空值独立核对全部匹配；最大误差约 2.87e-7。[方法与边界](指标真实数据独立核对-20260908.md)。
- 最终发行版 EMA20／RSI14：BTC 1h→15m→1h、BTC→ETH→BTC，指标随品种与周期更新。截图／AX 为 `final-indicators-*`。原先 O02 的短暂中间态不能仅凭这些离散采样宣布永不发生。
- 修改范围 TypeScript、ESLint、生产构建和原生打包通过。全局 i18n 检查仍报告未修改 WorkspacePanel.tsx 的 `+ Z`、`+ Shift + Z` 快捷键后缀，不能计为通过；本轮新增排序提示已补齐九种语言。

## 性能实测

### Python 启动

同一成品串行交替对照，每组 3 次，禁止写新缓存。`import uvicorn; import app.main` 的中位数由 **5.509 秒降至 1.682 秒，减少约 69.5%**。这是导入阶段结果，不是图表端到端速度提升比例。完整方法见 F36。

最终独立包另做 40 秒串行采样：健康检查约 **4.18 秒**就绪；整棵应用进程树 1 秒采样的 CPU 峰值约 **111%（一个核心为 100%）**，末 20 秒均值约 **19.7%**。末段平均分布：主进程 0.72%、GPU helper 4.56%、网络 helper 0.16%、Python 6.28%、renderer 7.94%。聚合 RSS 峰值 **1547 MiB**，包含重复计算的共享页，不等于真实物理内存，也不是内存泄漏证明。

这次测量解决了此前“只知道峰值、不知道谁在用”的一部分证据空缺；不能据此承诺 16／64 图、长时间运行或全部自定义脚本都没有峰值。原空闲扫描修复的 92→0 调用证据仍按原范围保留。

### 前端加载

通过电脑操控打开原生 DevTools Performance，保存普通重新加载与勾选 Disable cache 后重新加载两份轨迹。二者都没有命中 HTTP 缓存；操作系统文件缓存和全部 V8 内部状态未强制清空，后端历史为热缓存，不能称作全链路绝对冷启动。

| 页面导航后的标记 | 普通重新加载 | 禁用 HTTP 缓存 |
|---|---:|---:|
| app.boot.start | 106 ms | 98 ms |
| 首批 500 根 / chart.ready | 376 ms | 355 ms |
| 完整历史补齐 | 504 ms | 471 ms |
| 实时 WS 就绪 | 333 ms | 330 ms |
| HTTP 响应数 / 缓存命中 | 46 / 0 | 46 / 0 |

禁用缓存轨迹最大的 90 ms 主线程任务中，约 89 ms 是 DevTools `CpuProfiler::StartProfiling`。另有约 65 ms 的应用初始化任务，不能算作“零长任务”，但本次未观察到持续冻结。主线程 `v8.compile/compileModule` 记录合计约 3.4 ms；后台流式编译不在这个数字内，不能据此宣称全部脚本解析只有 3.4 ms。

大 chunk 警告仍存在。现有实测不支持把文件体积直接认定为当前持续卡顿根因，因此没有为消除警告而强行拆块。图表 firstBars 标记比 LCP 更接近本应用的可用性；不以普通网页 LCP 代替画布完成判断。

原始轨迹：`Trace-20260908T101014.json.gz`、`Trace-20260908T101216.json.gz`；离线分析：`frontend-trace-analysis.json`、`analyze_frontend_trace.py`；资源样本：`native-standalone-compiled-serial-profile.json`。

## 仍须明确的边界

- **Windows 原生构建、Windows 专属插件未测**；本机 Mac 不能替代 Windows 实机。打包检查会拒绝平台／架构不匹配的 Python。
- **Mac 成品未签名、公证，使用默认应用图标**。这是本地发行测试成品，不宣称已完成面向公众分发的认证。
- 未穷尽所有绘图类型、HTML5 拖放、所有指标参数和高速切换瞬态。已确认的问题已逐项修复，未确认现象保留证据边界。
- 本报告不是全项目全量测试，也不保证任意负载都无卡顿。上述具体场景、数值、命令和证据可用于后续复核。
