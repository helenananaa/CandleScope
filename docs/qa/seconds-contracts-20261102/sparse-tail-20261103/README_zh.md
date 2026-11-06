# 真实Upbit首次加载失败、稀疏尾部区间修复与再次418

实际CI原包150bb85c于2026-11-03 00:08 UTC启动，四来源catalog可用。Binance1s/7s和Gate1s就绪，Upbit已有超过500根真实bar仍停留initialHistoryPending；六分钟等待后失败，未进入MA/保存/重启。只读repair=none API在同一区间返回100根，真实SQLite有268根（独立SQL与API响应原文在upbit-range-underread-before.json.gz）。

原因是_cap_range_request要求存在包含区间end的预期bucket；end位于已确认无成交秒时返回None，于是把整个区间的预期数误判为0、读取上限退回100。交易日历的休市末尾有同样问题。新增两个回归在旧代码上失败，既有月历/会话边界/47m任意边界三项通过。64f525ca改用calendar.last_expected_open(start,end,interval)，保留原始包含式边界、分页上限和无成交证据，不补造bar或放宽最终性。

修复后初组113通过、2项需要NATIVE_CALENDAR_TEST显式资格的既有测试跳过；合入最新main226后，262项API/秒线/历史边界/调度/指标owner与历史研究组合全通过。TypeScript、桌面构建和8项Pyne退役检查通过。当前来源38d8ee33，尚需新head云端CI。

原始失败包正常完整自有进程退出3835ms，0renderererrors，无新增418，原始1045源码/SDK文件；161前端资产、212个SDK文件前后匹配且原始签名有效。原失败包/profile完整保留，未清空缓存重签。首次工具尝试仅因/tmp Playwright不存在在Electron前失败，独立日志保留；固定1.56.1已恢复到持久隔离工具目录。

随后新候选38d8ee33使用已验证CI150bb的CPython3.12.15运行时克隆，替换当前backend/SDK、重建最新main226前端和当前插件桥接，更新ASAR和本地深度签名。1048源码/SDK、164前端资产、9插件资产/76Pine/SDK源码匹配，完整独立profile；它是本地组合候选，未进行全新独立运行时构建。

新候选在00:22 UTC真实启动后，Upbit185根实际bar时已marketReady=true/loading=false/initialHistoryPending=false；但初次四图就绪阶段遇到新的Binance418/-1003（retry-after2003秒）。脚本停止，全部自有进程正常退出15196ms，0renderererrors，退出后源码/资产仍匹配，SDK pyc为0，严格签名有效。已查看前后两张失败截图。

本轮没有完成四图MA数学、自然收线、保存/完整退出/重启，不能记为整体原生通过或认定旧共享指标恢复阻塞已解决。新的全局公共行情期限2026-11-03T00:55:56.876Z，未提前重试、不切入口/代理/机器绕过，保留原候选profile及限流状态。after-main226-native保存新418及严格后验回执。#200仍保持Draft，原#131全部功能也不据此关闭。
