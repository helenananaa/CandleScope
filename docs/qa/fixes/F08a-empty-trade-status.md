# F08a 空成交快照误报实时

原因：store 发布近期成交时不检查记录数，空列表也无条件进入 live，界面据此显示“实时连续”。

修复：空近期列表进入独立 waiting 状态，显示“等待成交”；空增量不会升级状态，第一笔有效成交到达后进入 live。新增状态标签覆盖现有九种语言。

验证：

- 成交 store 与流控制器测试 12 项通过，新增覆盖空快照、空批次及第一笔成交恢复。
- 相关 ESLint、TypeScript、Production build、git diff --check 通过。
- 电脑操控发行版确认当前有数据的 OKX 成交列表正常加载；本轮未现场获得空近期列表，等待分支由确定性回归测试验证。截图 output/user-audit-20260907/evidence/fix-F08a-live.png/.txt。
- 日志 output/user-audit-20260907/fix-F08a-tests.log、fix-F08a-typecheck.log、fix-F08a-build.log。

本次不将“没有新成交”等同断流。非空旧数据的新鲜度、观测模式的连续性措辞及全局连接标签仍属于 F08 后续事项。
