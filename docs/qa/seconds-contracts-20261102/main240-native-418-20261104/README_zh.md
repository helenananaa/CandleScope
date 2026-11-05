# main240实际公网418：停止并完整退出

在2026-11-04T08:58:00.900Z旧共享冷却结束后启动原生候选127ba4f4，当前driver/QA head5797ca1b。真实记录显示Spot exchangeInfo/time/klines/WS当时200，后台/fapi/v1/exchangeInfo返回418、body -1003、used-weight-1m=0、retry-after=24179。随后共享IP circuit停止本轮。没有到达四来源设置、MA、保存重启资格，不能算这部分通过；也没有证据证明本客户端导致远端已有封禁。

新共享冷却2026-11-04T15:42:40.340Z（上海23:42:40），已同步主工作区backend-goal-20261102/STATE.json和development-goal状态。#223/#218/#227/#204均不能提前启动LIVE。完全拥有的10个进程15242ms退出，另行ps确认全部消失；renderer errors0，退出后源码/SDK1054、前端164、插件9/76及严格签名仍匹配。原profile、应用、原始诊断保留。

#234新增归因字段在本次实际响应生效：记录出触发418的Futures目录端点；同时/api/v3/depth仍匹配binance_spot_legacy、预算cost1，进入另一个本地审查/修复范围，不把它说成此次Futures封禁原因。此目录保留原始证据及小型归因汇总，未修改响应或绕过冷却。后续先继续不依赖公网的开发。
