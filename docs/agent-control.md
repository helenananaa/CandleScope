# CandleScope agent control

当前实现提供运行中桌面应用的命令发现、状态查询、领域操作、文件传输和原生截图。MCP 与 CLI 共用控制服务，入口覆盖工作区、图表、绘图、提醒、设置维护、自选、数据/项目、策略、高级研究、回放和插件。所有业务操作保留已有领域校验与功能开关；覆盖范围和运行验收边界见 [能力清单](agent-control-coverage.md)。

## 启动与连接

本次整合保留主分支的四个 HTTP 图表工具和临时授权规则。每次启动均关闭，切换模式时撤销旧凭据；`--control`、`--control-edit` 和对应环境变量不再自动开启服务。

在桌面“设置 → AI 连接”中可以继续只开启图表 HTTP 工具。需要本页列出的更广工作流时，另外勾选“为本次授权启用可选的桌面工作流工具”，再选择只读或控制。控制模式需要界面确认。只读工作流可以读取脚本草稿、报告、截图和已有导出文件；控制模式额外允许领域编辑、模拟运行及受限文件上传。所有领域检查、归属校验和功能开关继续生效。

工作流使用独立 stdio 连接，可在同一设置页复制 JSON/TOML 配置。发布包使用自带 Electron 运行适配器，无需另装 Node；源码开发需先安装 frontend 和 `packages/candlescope-control` 依赖。`frontend/scripts/prepare-control-adapter.mjs` 使用锁定依赖构建完整适配器和第三方许可清单，打包前检查摘要。

插件安装信任、权限授予和 Python TRUSTED_LOCAL 确认额外需要 `--control-trust`；实盘控制额外需要 `--control-live`。它们只设置本次进程可授予的上限，仍必须在设置中显式开启工作流控制；普通控制不包含这些权限。启动参数不能代替插件声明、后端授权、确认哈希/令牌、订单预览、有效期和风险检查。

启用后，连接文件位于 Electron userData 的 `control/connection.json`。Windows 目录 ACL 限制到当前用户，Unix 目录 0700、文件 0600。撤销、切换模式及退出会关闭两类连接，并移除本实例的工作流凭据；重启不恢复授权。适配器配置不含 token，不会静默跨授权会话重连。

已提交的命令可能在撤销前已开始执行；断连不代表它已回滚。遇到不确定结果，应在新授权后重新查询领域状态，不能盲目重放。渲染回执绑定授权实例，旧会话的迟到回执不能完成新会话的同名请求。

```powershell
cd packages/candlescope-control
npm ci --ignore-scripts
node cli.mjs inspect --window main-window --connection "实际连接文件路径"
```

后文的 2026-10-08 验收记录和 `docs/evidence/agent-control-*20261008.json` 是历史证据，不代表本次整合已重新完成同等生产包验收。新的验证范围记录在本 PR 中。

## 工具与闭环

| MCP 工具 | 控制方法 | 用途 |
| --- | --- | --- |
| `app_capabilities` | `app.capabilities` | 实例、窗口、授权与固定能力上限 |
| `workspace_inspect` | `workspace.inspect` | 当前工作区 ID、revision、保存状态、各图配置和运行状态 |
| `workspace_configure` | `workspace.configure` | 原子更新布局、交易标的、周期、内置指标；仅编辑授权下注册 |
| `request_get` | `request.get` | 查询请求进度和终态，不重新执行 |
| `chart_capture` | `chart.capture` | 指定窗口可见内容 PNG；MCP 直接返回图片 |
| `app_commands` | `app.commands` | 已挂载命令组、参数 JSON Schema、available、contextToken |
| `app_query` | `app.query` | 只读命令；每组自带 inspect 查询状态 |
| `app_execute` | `app.execute` | 执行发现的领域操作，校验 expectedContext；编辑授权下注册 |
| `app_open` | `app.open` | 打开/聚焦行情、策略、回测、回放、本地数据页面；编辑授权下注册 |
| `file_read` | `file.read` | 读取已提交、当前窗口所有的文件块与身份信息 |
| `file_begin` | `file.begin` | 声明文件名、类型、长度和 SHA256；仅编辑授权下注册 |
| `file_write` | `file.write` | 顺序写入 base64 块；相同块重试安全，冲突拒绝 |
| `file_commit` | `file.commit` | 验证完整长度与 SHA256，生成可供领域操作读取的 fileRef |
| `file_remove` | `file.remove` | 释放文件引用；仅编辑授权下注册 |

通用操作先调用 app_commands(windowId)，选择真实 groupId、命令及 contextToken；app_query 检查状态后再提交。例如：

```json
{
  "windowId": "main-window",
  "groupId": "settings",
  "command": "appearance",
  "args": { "theme": "light" },
  "requestId": "theme-change-001",
  "expectedContext": "替换为刚刚发现的 contextToken"
}
```

CLI 对应 `commands --window ID`、`query/execute/open --params-file FILE`。查询参数只包含 windowId/groupId/command/args。写操作登记后查询 request_get，再 app_query(command="inspect") 验证实际领域状态。已有用户操作、session、文档或草稿等变化会更新 contextToken；冲突需重新发现并判断，不能套用旧 token。

命令随页面、功能开关、后台能力和挂载状态变化。用 `panels:<cellId>.show` 打开延迟加载的策略面板后重新发现；app_open 回执的 output.windowId 指向新页面，等 capabilities 标记窗口 ready 后再发现其命令。没有数据源或后端能力时，相应命令会缺席或 available=false。

绘图先 inspect 检查 pane 的 ready/readiness、scopeKey 和 revision；必要时调用 drawings:<cell>.prepare 请求既有 UI 的 scope 恢复，再重新发现并等待 ready。prepare 不修改绘图文档；apply 仍经过原 scope/series/revision、发布和保存屏障。准备操作后不得沿用旧 contextToken。

training-hub.createRun 返回 submitted，自动导航后重新发现 replay-initial-market 或 replay。前者需要先查询目录，再按 exchange:market_type:symbol 选择可用商品，必要时检查领域生成的降级提示。创建失败则查询 hub.error。回放 control 的 payload 遵循回放领域契约，例如 acquire_controller 用 {takeover:false}，step_base 用 {count:1}，advance 用 {basis:"VIRTUAL_TIME",duration_ms:600000}；旧 advance_by 别名使用 {ms:600000}。结束用 {open_order_disposition:"cancel",position_disposition:"mark_close"}。模拟 place_order 的 payload 是订单字段本身，数额使用规范 Decimal 字符串。

## 文件输入与输出

领域操作只接受窗口绑定的 `fileRef`，不接受主机路径。适配器 CLI 可从用户指定的本地文件上传，或将返回文件保存到显式目标路径：

```powershell
node cli.mjs upload --window main-window --file "C:/data/candles.csv"
node cli.mjs download --window main-window --id "导出回执的 fileRef" --out "C:/data/report.json"
```

上传完成后，把 fileRef 传给发现的 `data-library.importCsv`、项目导入、Python Studio ZIP、外部执行数据或插件安装准备命令。导出图表、项目、报告、自选和审计返回文件身份，使用 file_read 或 CLI 下载。完整项目设置/绘图/分析状态的捕获与恢复使用 `dataset-management:<id>`；data-library.exportProject 的 clientState 可由调用者显式提供。

每块最多 32 KiB，单文件最多 32 MiB，进程内总额 128 MiB、最多 64 个引用，闲置 30 分钟过期。文件驻留内存，窗口重载/关闭及进程退出清除；不能跨窗口使用。下载校验长度和 SHA256，默认拒绝覆盖已有目标文件。大于此限制的文件仍可通过原 UI 导入，不能声称文件协议与 UI 的任意文件大小完全等价。

插件信任流程先 prepare/review，再用领域返回的 candidate/hash/token confirm。实盘流程先 livePreview，再以该服务器预览的 previewRef 获取确认，最后 liveExecute；不能自行构造 receipt 绕过预览。后端继续验证行动类型、意图哈希、授权代次、有效期和风险。超时后 inspect/reconcile，禁止盲目重复提交。

先 inspect 获取真实 `workspaceId`、`windowId`、`revision`，将 revision 放入 `expectedRevision`。例如四图配置：

```json
{
  "requestId": "btc-four-chart-001",
  "workspaceId": "workspace-default",
  "windowId": "main-window",
  "expectedRevision": 2,
  "layout": "quad",
  "charts": [
    { "session": { "exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "5m" }, "indicators": [{ "name": "EMA", "period": 20 }, { "name": "EMA", "period": 60 }] },
    { "session": { "exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "15m" }, "indicators": [{ "name": "EMA", "period": 20 }, { "name": "EMA", "period": 60 }] },
    { "session": { "exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "1h" }, "indicators": [{ "name": "EMA", "period": 20 }, { "name": "EMA", "period": 60 }] },
    { "session": { "exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "4h" }, "indicators": [{ "name": "EMA", "period": 20 }, { "name": "EMA", "period": 60 }] }
  ]
}
```

把 JSON 存成参数文件后，CLI `configure --params-file FILE`；随后 `request --id btc-four-chart-001`，直到 `final=true`。截图用 `capture --window main-window --out FILE.png`。

有 layout 时按布局顺序配置全部格子，不传 cellId；无 layout 时必须逐图指定 inspect 返回的 cellId。支持 single、split-vertical、split-horizontal、quad，尊重布局锁和现有功能开关/容量上限。首版 exchange 为 binance/okx，marketType 为 spot/futures，周期必须使用规范形式（如 1h，不能 60m）。有效标的与实际数据能力仍由现有数据链路判断。

每张图的 indicators **替换整个列表**，最多八个，支持 MA/EMA/RSI，period 为 1..5000。配置后的图解除链接组，避免配置联动到其他图。指标使用现有 local 执行目标与后端指标计算接口。现有布局撤销只覆盖布局；不能依赖它撤销 session 或指标替换。

## 回执和并发

通用 `app_execute` 的 applied/command-acknowledged 只表示处理函数完成调用，不保证异步任务、保存或后台请求成功；需查询 busy/error/operationError/run.state/preparation/绘图 surfaceSynchronized 等具体后置状态。`app_query` 的 ready/observed 仅表示读到状态。进入动作后抛错返回 OUTCOME_UNKNOWN；结果不可序列化或目标卸载时保留 applied/unverified，不能自动重试。

以下为专用 `workspace_configure` 的更强回执语义：`accepted` 仅表示请求已登记；`applied` 表示领域动作已提交；`ready` 还要求目标 session/指标一致、非加载状态、有历史数据、指标输出完成且工作区保存成功。inspect 的 persistence.mode 表明保存方式，memory 回退模式不保证退出后的持久化。ready 不代表行情实时性、订单簿、策略或交易能力健康。receipt.revision 是本次配置提交的版本；后续窗口位置等更新可能增加 snapshot.revision，不会单独否定该配置。

同一实例内使用相同 requestId、方法和完全相同 JSON 参数重试会返回原回执。更换参数必须换 requestId。回执最多 1024 个且不淘汰；达到上限拒绝新编辑。在途原子配置/开页操作与其他编辑互斥；通用领域动作由各 renderer 串行执行，显式标注的取消动作允许中断在途操作。独立窗口可分别执行通用命令。领域修改校验 expectedRevision 或 contextToken；更改目标 session/指标、布局或切换工作区会使等待结果 superseded。IPC 结果还绑定接收请求的窗口。

初始化等待上限 25 秒，桌面派发上限 30 秒。超时、保存失败、窗口关闭和 reload 不等于回滚：检查 state/code/readiness。`applied` + `unverified` 保留已修改事实；`OUTCOME_UNKNOWN` 要先 inspect，不能盲目再执行。回执仅在当前进程有效，重启后不能凭旧 requestId 推断已完成。

## 服务边界和验证

控制 HTTP 只监听 127.0.0.1 随机端口，每次调用需要本实例 Bearer token、精确 Host；拒绝带 Origin 的浏览器请求，固定方法与领域命令目录，不接受任意 JavaScript 求值、文件路径、系统设置或原始扩展执行。策略源代码只能走已挂载的领域引擎与既有权限检查。请求 64 KiB、响应 2 MiB；截图输出边长最多 1600，并限制捕获尺寸、等待与 PNG 字节数。持有当前用户凭证的本地客户端获得启动时授权；截图含用户可见数据。

验证命令：frontend `npm run typecheck`、`npm run check:architecture`、`npm run test:desktop`，以及工作区/控制器的定向测试；适配器目录 `npm test` 和 `node desktop-smoke.mjs`。原生 smoke 使用独立 profile、生产构建、真实 Electron IPC、真实 SDK stdio MCP 和样本后端，保留 report、配置回执和图片到 `output/control-desktop/`，退出核验凭证删除。

2026-10-08 原生样本闭环还验证了全部主窗口命令组 JSON 状态、权限默认关闭、延迟加载的设置/提醒/指标/数据工作台、图表预览与绘图导出租约、文件完整哈希、跨窗口隔离、CSV 上传到原有库流程、项目文件返回和重载失效。

真实业务验收：先构建 frontend/dist，再在适配器目录运行 node real-backend-smoke.mjs。它启动隔离的实际后端，以确定性数据和离线网络 guard 验证 800 根 CSV 的逐行导入/质量、EMA 输出、完整项目恢复、已安装 Pyne 引擎的运行/取消/报告，以及 BAR/ONE_WAY 训练的创建、选市场、模拟买卖、结束、账户审计和报告。产物在 output/control-real-backend/；Python/引擎前置条件见适配器 README。此轮真实业务已通过，报告与精确边界见 [能力清单](agent-control-coverage.md) 和 [验收摘要](evidence/agent-control-real-backend-20261008.json)。真实交易所、实盘订单、历史精确账户/双向持仓训练、安装包发布与全部 UI 等价性仍需独立验收。
