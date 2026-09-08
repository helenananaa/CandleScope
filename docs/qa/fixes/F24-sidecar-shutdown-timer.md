# F24：后端退出后清理桌面监督器的超时定时器

日期：2026-09-08。来源：上一轮“服务退出等待”的补查。

## 确认的问题

SidecarSupervisor.stop 使用 Promise.race 等待子进程退出或超时。子进程先退出时，超时分支的定时器依然活跃；桌面配置为 15 秒。独立 Node 宿主已经输出 stopped、子进程也已经退出，但宿主在 2.5 秒测试期限内不能自然退出。此证据证明遗留定时器，不证明先前 Python 服务需要第二次 SIGINT 的所有情况均由此造成。

## 修复

在等待结束的 finally 中清理超时定时器与 exit 监听器。保留现有优雅退出、超时后强制结束策略。

## 验证

- 新增真实父子进程回归：子进程发出 ready 后由监督器停止；要求宿主自然结束且子进程已经退出。
- 修复前：输出 stopped 后仍超时失败，见 output/user-audit-20260908/exit-timer-before.log。
- 修复后：39 项桌面测试通过，见 exit-timer-desktop-tests.log。
- production 构建通过，见 exit-timer-build.log；仍有既有 chunk 体积提示。
- 本项没有界面变更。原生打包、Python 退出等待的进一步复核单独进行。
