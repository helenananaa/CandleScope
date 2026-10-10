# CandleScope 用户审计修复总表

日期：2026-09-08。代码核对基线：`9a6bd111`，分支 `codex/fix-user-audit-20260907`。

## 交付结论

依据[原始用户视角审计](CandleScope-用户视角发行版测试-20260907.md)，已完成本轮明确问题的逐项修复、验证和独立提交，共 51 个修复提交。每项具体修改及测试边界见下表。此结论指原审计的已确认问题，不等于软件没有其他 bug 或所有功能、设备、网络组合均已通过。

所有 51 份修复记录已提交，且对应提交是当前 HEAD 的祖先。核查映射在 `output/user-audit-20260907/final-record-index.json`。文件存在与测试通过分别核验，证据数量不作为功能完成依据。

## 问题与提交

| 原项 | 当前结论 | 修复记录与提交 |
|---|---|---|
| F01 | 已确认问题已修复，验证范围见分项 | [F01-page-export](fixes/F01-page-export.md) `36cbf456` |
| F02 | 已确认问题已修复，验证范围见分项 | [F02-strategy-light-theme](fixes/F02-strategy-light-theme.md) `060fe9bf` |
| F03 | 已确认问题已修复，验证范围见分项 | [F03-workspace-undo-scope](fixes/F03-workspace-undo-scope.md) `880c7b0b` |
| F04 | 已确认问题已修复，验证范围见分项 | [F04-search-escape](fixes/F04-search-escape.md) `dbadf4b4` |
| F05 | 已确认问题已修复，验证范围见分项 | [F05-indicator-numeric-validation](fixes/F05-indicator-numeric-validation.md) `db43c269` |
| F06 | 已确认问题已修复，验证范围见分项 | [F06-symbol-search-separators](fixes/F06-symbol-search-separators.md) `47b41deb` |
| F07 | 已确认问题已修复，验证范围见分项 | [F07a-order-book-first-snapshot](fixes/F07a-order-book-first-snapshot.md) `539128d4`；[F07b-order-book-status-detail](fixes/F07b-order-book-status-detail.md) `a08351de`；[F07c-order-book-last-received](fixes/F07c-order-book-last-received.md) `ca1417e9`；[F07d-order-book-delivery-source](fixes/F07d-order-book-delivery-source.md) `78a7a669` |
| F08 | 已确认问题已修复，验证范围见分项 | [F08a-empty-trade-status](fixes/F08a-empty-trade-status.md) `ed41bd64`；[F08b-trade-freshness](fixes/F08b-trade-freshness.md) `a14a5525`；[F08c-trade-continuity-copy](fixes/F08c-trade-continuity-copy.md) `4cebcf45`；[F08d-kline-status-scope](fixes/F08d-kline-status-scope.md) `e1c5d7d3` |
| F09 | 已确认问题已修复，验证范围见分项 | [F09-runtime-unavailable](fixes/F09-runtime-unavailable.md) `a22d82ae`；[F09b-editor-toolbar-wrap](fixes/F09b-editor-toolbar-wrap.md) `91bde174` |
| F10 | 已确认问题已修复，验证范围见分项 | [F10-plugin-available-count](fixes/F10-plugin-available-count.md) `84cc7732` |
| F11 | 已确认问题已修复，验证范围见分项 | [F11a-backtest-number-format](fixes/F11a-backtest-number-format.md) `28d37649`；[F11b-drawdown-availability](fixes/F11b-drawdown-availability.md) `f5770be9` |
| F12 | 已确认问题已修复，验证范围见分项 | [F12a-subpane-label-overlap](fixes/F12a-subpane-label-overlap.md) `27ff55bf`；[F12b-compact-main-legend](fixes/F12b-compact-main-legend.md) `b9ce2594`；[F12c-readable-pane-heights](fixes/F12c-readable-pane-heights.md) `14e2357f` |
| F13 | 已确认问题已修复，验证范围见分项 | [F13a-synthetic-notice-layout](fixes/F13a-synthetic-notice-layout.md) `3b4659fa`；[F13b-sparse-synthetic-viewport](fixes/F13b-sparse-synthetic-viewport.md) `6216d603` |
| F14 | 已确认问题已修复，验证范围见分项 | [F14a-symbol-single-line](fixes/F14a-symbol-single-line.md) `7b042965`；[F14b-responsive-market-summary](fixes/F14b-responsive-market-summary.md) `b3db6322` |
| F15 | 已确认问题已修复，验证范围见分项 | [F15-export-dialog-viewport](fixes/F15-export-dialog-viewport.md) `3723de71` |
| F16 | 已确认问题已修复，验证范围见分项 | [F16-export-chart-context](fixes/F16-export-chart-context.md) `305abacf` |
| F17 | 已确认问题已修复，验证范围见分项 | [F17a-about-shortcut-keys](fixes/F17a-about-shortcut-keys.md) `61dcde48`；[F17b-indicator-parameter-labels](fixes/F17b-indicator-parameter-labels.md) `68921726`；[F17c-market-data-badge](fixes/F17c-market-data-badge.md) `9a0db600`；[F17d-drawing-tool-labels](fixes/F17d-drawing-tool-labels.md) `1ff7beb1`；[F17e-builtin-indicator-names](fixes/F17e-builtin-indicator-names.md) `4b019506`；[F17f-topbar-icons](fixes/F17f-topbar-icons.md) `81d41d66`；[F17g-replay-topbar-icons](fixes/F17g-replay-topbar-icons.md) `31c5142d`；[F17h-indicator-panel-icons](fixes/F17h-indicator-panel-icons.md) `9a6bd111` |
| F18 | 已确认问题已修复，验证范围见分项 | [F18a-chart-load-diagnostic](fixes/F18a-chart-load-diagnostic.md) `03880217`；[F18b-preserve-initial-history-error](fixes/F18b-preserve-initial-history-error.md) `2c91e871`；[F18c-network-engine-separation](fixes/F18c-network-engine-separation.md) `ea4901ae`；[F18d-copy-load-diagnostic](fixes/F18d-copy-load-diagnostic.md) `5152ba89` |
| F19 | 已确认问题已修复，验证范围见分项 | [F19-workbench-read-write-scope](fixes/F19-workbench-read-write-scope.md) `79af480a` |
| F20 | 已确认问题已修复，验证范围见分项 | [F20a-replay-data-preparation](fixes/F20a-replay-data-preparation.md) `355512f3`；[F20b-training-creation-language](fixes/F20b-training-creation-language.md) `d05dc6d7`；[F20c-manual-history-replay-archive](fixes/F20c-manual-history-replay-archive.md) `3fd5b03c`；[F20d-replay-watchlist-language](fixes/F20d-replay-watchlist-language.md) `84ea6c32` |
| F21 | 已确认问题已修复，验证范围见分项 | [F21-strategy-entry-context](fixes/F21-strategy-entry-context.md) `470d8de5` |
| F22 | 已确认问题已修复，验证范围见分项 | [F22a-signed-accessible-price-change](fixes/F22a-signed-accessible-price-change.md) `2bcb50ea`；[F22b-platform-shortcut-hints](fixes/F22b-platform-shortcut-hints.md) `d62eb38d` |
| F23 | 已确认问题已修复，验证范围见分项 | [F23-websocket-close-send-race](fixes/F23-websocket-close-send-race.md) `8d697866` |
| O01 | 添加失败未复现；默认列表名称不一致已修复 | [O01a-watchlist-display-name](fixes/O01a-watchlist-display-name.md) `ad93cc1d` |
| O02 | 未复现，不修改公式 | [双图复核](O02b-双图指标市场切换复核-20260908.md) |
| P-H01 | 已修复空闲存储扫描；原交互峰值非完整定位 | [P-H01d-idle-download-storage-probe](fixes/P-H01d-idle-download-storage-probe.md) `3cfd1a46` |
| P-H02 | 构建体积事实；尚未证明运行缺陷 | 保留原报告 P-H02，未据大 chunk 警告盲目拆包 |

## 汇总验证

- 最终代码上重新运行本轮新增/修改的 24 个前端测试文件，共 **108 项通过**；4 个后端测试文件，共 **35 项通过**。范围逐文件列于 `final-regression-scope.json`，结果为 `final-frontend-tests.log` 与 `final-backend-tests.log`。这些不是项目全量测试。
- 各提交分别有针对性检查；最后生产构建及类型检查为 F17h 日志，均成功，之后未再修改业务代码。此前视觉、故障注入、下载与回放等 GUI 验证详见分项。
- 实际测试使用 Vite production dist/preview，不是开发热更新；后端普通 uvicorn，无 reload。临时故障代理和 Python profiler 已停止，最终后端恢复普通模式。
- 功能闭环例：页面 PNG/WebP 实物导出；浅色策略回测与数值展示；回放 3345 根真实历史归档后识别 1706 个窗口，创建存档、选品、单步推进成功；断连和存储扫描问题有确定性失败→通过回归。
- 各分项测试数字有重叠，不能累加成独立用例总数。生产构建仍有大 chunk 提示，未将其隐藏或误称为已优化。

## 保留观察与环境限制

| 项目 | 已取得证据 | 边界与处置 |
|---|---|---|
| F13c 历史补载后合成图往返 | [15m/45m 复核](F13c-往返视野复核-20260908.md)普通往返未见明显偏移 | 未复刻原 viewport 补载同条件；不修改未证实的映射算法，也不宣称所有历史缓存场景通过 |
| O02 指标中间态 | [六个双图采样](O02b-双图指标市场切换复核-20260908.md)成对一致；预热不足时均显示“—” | 未证明原短暂现象消失，未做独立数学对拍；不改公式 |
| P-H01 资源峰值 | 原生采样及 Python 剖析定位出空闲扫描；修复后 20 秒扫描 92→0 | 不能把调用次数减少换算为 CPU/FPS 改善；其余峰值仍是排查线索 |
| P-H02 大块资源 | production 构建确认体积较大 | 未完成冷缓存加载/解析时序测量，未据文件名或警告推断热点 |
| 服务退出等待 | 部分停止需要第二次 SIGINT，另有正常退出记录 | 未把所有等待认定为同一故障；F23 只修复已复现的关闭后发送异常 |
| 原生发行环境 | 本机 Mac，浏览器 production 构建 | Windows 原生壳及平台专属插件未测；不可用插件明确提示，不强行启用 |
| 性能环境 | 后期 Chrome 显示节能模式开启 | 未改系统设置；工具等待时间不作为操作延迟，cProfile 有诊断开销 |

原审计覆盖表中原本“未测/部分”的动作（例如全部绘图持久化、全指标公式、所有自选排序路径）仍不是本轮局部修复可以证明的全产品验收结果。保留这些边界属于证据分类，不将其伪装为修复完成。

## 文件与本地数据

本总表、原始审计及复核文档保留在 `docs/qa/`；逐问题修复记录在 `docs/qa/fixes/`，图片、AX、测试/构建日志在 `output/user-audit-20260907/`。原始审计没有回写成无问题版本。测试加入的自选、历史下载和 QA 回放存档保留本地，未提交行情数据库或用户数据。
