# 用户导入 BAR 接入正式离线回放

关联 #166 / #169，main 基线 395007ac。当前首批范围为 LOCAL_OFFLINE：复用 LocalDatasetService 的固定版本规范行、既有 BAR 回放引擎、前后两个 Manager 和现有训练入口。数据集 ID 占用独立 venue 命名空间，market_type 为 local_bar，同名商品的不同导入互不替代。

- 固定源版本沿用资料库 data_epoch，不创建第三份行情文件；旧版本读取不随当前资料库指针切换。读取保留 Decimal 字符串和原始 open/close 时间，完整文件预加载不改变引擎的收盘揭示边界。
- 不提供在线来源或补齐、市场成交伪造、资产身份猜测。未知数据集、缺失版本、预算超限、无 volume 或含非最终 BAR 明确不可用。第一批只采用既有连续 UTC 固定周期 BAR 契约；日历和其他语义暂不宣称支持。
- 离线应用启动/退出回放 runtime，并绑定 DataManagerCore.replay；只开放既有 replay HTTP 和同一组 replay WS handlers。在线行情/采集接口继续由本地模式中间件阻止，外网守卫持续安装。
- 资料库原导入流程不变；离线导航经 Manager capability 开放回放入口，自动在线 preparation 仍不可用。

源码验证：52 项后端（导入适配、离线 app、API、揭示历史、服务和 DataManager）通过，4 条既有 FastAPI on_event 提示；去掉多余 preparation capability 开放后，当前离线 app 2 项再次通过。14 项前端入口/导航检查、类型、修改的前端 ESLint、生产构建和前端架构通过。后端架构保持 10 条 main 既有问题，未宣称全绿。

原生候选及 UI/保存/完整退出/新进程恢复正在准备，尚未验收通过。`native-replay.mjs` 使用真实 CSV 导入界面和已公开前端应用控制命令，推进训练/模拟订单，无服务响应替换。`assemble.py` 为本地 macOS arm64 runtime 复制候选，复制当前 backend/SDK、构建当前 frontend/desktop并更新ASAR/signature；不是完整独立runtime重编译。设置 CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1 时只允许复用逐源文件和固定引擎验证通过的包内插件，否则执行原有插件构建。不会覆盖旧候选/profile。

剩余：LIVE 模式导入入口、同运行多数据集/多商品资产契约及金融参考、市场成交导入、日历/无 volume 输入的明确后续语义、完整原生与 Windows 验收。第一批不解除已有跨市场账户身份限制，不关闭 #166。
