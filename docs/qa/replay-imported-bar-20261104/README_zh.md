# 用户导入 BAR 接入正式离线回放

关联 #166 / #169，main 基线 395007ac。当前首批范围为 LOCAL_OFFLINE：复用 LocalDatasetService 的固定版本规范行、既有 BAR 回放引擎、前后两个 Manager 和现有训练入口。数据集 ID 占用独立 venue 命名空间，market_type 为 local_bar，同名商品的不同导入互不替代。

- 固定源版本沿用资料库 data_epoch，不创建第三份行情文件；旧版本读取不随当前资料库指针切换。读取保留 Decimal 字符串和原始 open/close 时间，完整文件预加载不改变引擎的收盘揭示边界。
- 不提供在线来源或补齐、市场成交伪造、资产身份猜测。未知数据集、缺失版本、预算超限、无 volume 或含非最终 BAR 明确不可用。第一批只采用既有连续 UTC 固定周期 BAR 契约；日历和其他语义暂不宣称支持。
- 离线应用启动/退出回放 runtime，并绑定 DataManagerCore.replay；只开放既有 replay HTTP 和同一组 replay WS handlers。在线行情/采集接口继续由本地模式中间件阻止，外网守卫持续安装。
- 资料库原导入流程不变；离线导航经 Manager capability 开放回放入口，自动在线 preparation 仍不可用。

源码验证：52 项后端（导入适配、离线 app、API、揭示历史、服务和 DataManager）通过，4 条既有 FastAPI on_event 提示；去掉多余 preparation capability 开放后，当前源码完整 52 项已再次通过。14 项前端入口/导航检查、修改的前端 ESLint、生产构建和前端架构通过。后端架构保持 10 条 main 既有问题，未宣称全绿。

原生范围修正：fa0d4d16 的导入/模拟成交/账户恢复证据有效，但画面复核发现展示周期在请求 5m 后被工作区恢复 1m；原驱动遗漏周期保持断言，故整项原生资格撤回，修复与重跑中。原记录：PID 19902 → 19937，真实资料库界面导入 6000 根，正式训练以固定来源运行并产生 1 笔模拟成交，周期请求不推进游标（5m 未保持，不能作为该项通过）；完整退出后恢复源游标、config 和全部 component（包括账户/成交），两次正常退出 536ms / 449ms，renderer 异常与外网尝试均 0。1041 个源码/SDK、164 个前端构建文件、9 项插件资产及 76 个插件源文件匹配，运行前后严格签名通过。应用源码 fa0d4d16；证据在 evidence。候选 app 复用一份已验证应用，后续各次独立 profile 通过 symlink 指向它，未复制第二份 app。先前 5 次原生驱动失败分别来自缺少 Practice 白名单、页面导航注册等待、旧 adapter URL、v1 source_kind 大小写及控制 payload；原始失败和完整退出记录保留，产品断言没有放宽。`native-replay.mjs` 使用真实 CSV 导入界面和已公开前端应用控制命令，推进训练/模拟订单，无服务响应替换。`assemble.py` 为本地 macOS arm64 runtime 复制候选，复制当前 backend/SDK、构建当前 frontend/desktop并更新ASAR/signature；不是完整独立runtime重编译。设置 CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1 时只允许复用逐源文件和固定引擎验证通过的包内插件，否则执行原有插件构建。不会覆盖旧候选/profile。

剩余：LIVE 模式导入入口、同运行多数据集/多商品资产契约及金融参考、市场成交导入、日历/无 volume 输入的明确后续语义、完整原生与 Windows 验收。第一批不解除已有跨市场账户身份限制，不关闭 #166。

类型验证说明：此前使用的增量 tsc -b 不代替 CI 的显式 typecheck；正式 npm run typecheck / 完整前端 check 与 CI 结果待补充。
