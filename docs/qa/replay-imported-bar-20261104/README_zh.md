# 用户导入 BAR 接入正式离线回放

关联 #166 / #169 / #181。应用源码 a7455dbb（含 main84feb73f）。本批是固定版本用户 BAR 的 LOCAL_OFFLINE 正式回放及周期控制修复，issue 保持开放。

## 实现

复用 LocalDatasetService 的规范固定版本、现有 BAR 引擎和前后两个 Manager；数据集 ID 占用独立 venue 命名空间，market_type 为 local_bar，同名商品互不替代。保留 Decimal 字符串及原 open/close 时间，不新增行情文件或联网补齐；资料库切换当前版本后，已绑定回放仍读取原 epoch。无成交量、非最终 BAR、缺失版本及容量超限明确不可用；第一批只按既有连续 UTC 固定周期 BAR 契约工作。

离线应用启动/关闭 ReplayRuntime 并绑定 DataManagerCore.replay，只开放已有 replay HTTP 与同一组 replay WS handlers；在线行情/采集接口仍被拦截，loopback-only 外网守卫持续安装。资料库原导入流程沿用；离线导航通过 Manager capability 开放回放。

原生验证揭示两处缺口并已修复：发布的 replay period 控制现在由活动图表工作区拥有，避免共享 viewer 被旧 cell 周期改回；导入适配器接入已有 source_bucket_projection 揭示范围聚合器，并按真实固定基础周期计算行数、连续性与关闭边界。共用 reducer 的既有1m、月桶、缓存、官方与渐进历史回归保留，未复制聚合实现。

## 当前证据

- 当前 main234 整合源码：97 项后端通过，4 条既有 FastAPI on_event 提示；涵盖导入版本/同名隔离、原时间和精度、缺口/预算、历史与当前高周期揭示边界、预先计算未来后回退、离线 HTTP/WS、replay服务与Manager、渐进/官方历史和共享 bucket 缓存。
- 同一前端源码的完整 npm run check exit0：4863 functional、1 独立性能、130 desktop，显式 TypeScript、lint（0errors/1条既有SingleChartPanes warning）、架构、插件架构、i18n和生产build通过。后端架构仍为与main逐字相同的10条问题，新增0。
- macOS arm64 原生：真实资料库界面导入6000根，在正式训练产生1笔模拟成交；控制命令切5m、界面切15m再5m后周期保持，源游标不变。实际5m投影只使用已揭示完整基础BAR，未来极端价格未进入结果；图表实际加载20根历史K线。完整退出后新进程恢复config、账户/成交component、源游标和5m工作区，图表仍20根。
- 两次应用PID及完整退出耗时见 evidence/qualification.json。renderer异常、外网尝试均0。运行前后1041个源码/SDK、164个前端文件、9项插件资产与76个插件源匹配，严格签名通过。

最新证据在 evidence/main234-current-native；机器资格为 evidence/qualification.json。候选仅复用已验证runtime与逐源一致插件，构建当前frontend/desktop、更新ASAR并adhoc签名，不是独立runtime全量重编译。候选应用保留，后续私有profile可通过symlink共用相同app，未复制第二份应用。

## 失败记录与口径修正

早期fa0导入/成交/账户恢复有效，但周期请求被改回1m，不能作为周期通过；fccc周期保持但缺少投影，不能作为图表通过。两者原始输出均保留，旧结论已撤回。d5ed图表投影与恢复通过，但截图早于历史分页完成，最新main234在截图前确认20根可见历史。测试驱动曾缺Practice白名单、导航注册等待、使用旧URL/v1大小写及缺少control payload；这些失败及正常退出记录保留，未放宽产品校验。

## 复现与剩余

源码入口 backend/tests/test_replay_imported_bar.py。原生入口 native-replay.mjs，使用真实CSV导入UI、已公开应用控制与UI周期选择，无响应替换；独立profile且拒绝覆盖。assemble.py/verify.mjs校验来源、源码与插件字节和完整签名。设置 CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1 只复用逐源一致并验证固定engine的插件；否则走已有builder。

尚未完成：LIVE模式导入、同运行多数据集/商品账户身份契约和财务参考、市场成交导入、日历/无volume输入的后续语义、更多多图/指标/回退原生场景与Windows。这里的单数据集原生证据不关闭#166，也不替代完整157项验收。新head远程CI仍须独立核对后才可合并。
