# P-H01d：无下载任务时持续扫描 SQLite 页归属

## 定位

原报告 P-H01 只提供资源峰值关联，不能据此修改指标算法。后续 P-H01b 原生采样未定位业务函数，本轮继续使用临时 cProfile 启动器、电脑操控 production 页面，在 20 秒静置和 20 秒周期切换窗口内采集函数调用。

发现 `ManualHistoryService._run_loop` 即使 recoverable jobs 为空，每 0.2 秒也会调用 `_storage_block_reason`，进而执行 `storage_file_snapshot`。后者打开只读 SQLite、读取页计数，并通过 dbstat 扫描页归属。实际接口确认只有上一轮已 SUCCEEDED 的下载，没有等待或受存储阻塞的任务。

标准计时记录：静置窗口扫描 92 次，周期切换窗口扫描 89 次。调用路径主要为 `_run_loop → _storage_block_reason → runtime._storage_pressure → storage_file_snapshot`。这是一项明确且不随有没有待恢复任务而变化的多余扫描，不将它等同于原报告全部交互峰值的唯一原因。

## 修复

先筛选 BLOCKED_STORAGE 任务，仅有这类待恢复任务时才进行恢复所需的压力检查。任务取消优先级不变；run_job 执行前和下载过程中原有检查保留，不缓存压力结果或放宽空间门槛。

## 验证

- 新增单调度迭代测试：无任务不调用压力探测；BLOCKED_STORAGE 且压力恢复时仍探测、重置目标并排队。修改前无任务断言失败，恢复路径通过。
- 手动历史服务、runtime、GC protection 共 29 项测试通过，包含实际下载空间阻塞及恢复测试。
- 同样 20 秒窗口复测：静置扫描 **92→0**；周期切换 **89→1**。后者剩余调用来自执行器而非手动下载 `_storage_pressure`；修复后两个窗口都没有该下载压力闭包调用，不删除其他用途的存储探测。
- production build 成功。电脑操控相同 1m→3m→5m→15m 路径，恢复原周期；结束诊断后用普通 `uvicorn app.main:app` 无 reload 启动，页面刷新并恢复行情。
- `git diff --check` 通过。

## 测量可信度与边界

第一版诊断使用 thread_time，出现负累计耗时和超出窗口的单项时间，已明确判为无效，不采信其耗时排序。改用标准 cProfile timer 后没有负耗时，但并发调用树仍存在不直观的归并；因此本结论以调用次数、源码条件和确定性回归测试相互佐证，不宣称 CPU 百分比、端到端延迟或峰值内存改善。

cProfile 本身有额外开销，记录只用于定位；任务最终运行在无 profiler 的生产后端。数据仍是实时源，前后不是冻结市场的严格性能基准。Chrome 节能模式保留，Windows 原生包未测。P-H01 的其他计算/序列化热点仍待验证。

证据位于 `output/user-audit-20260907/`：`P-H01c-wall-{1,2}.pstats`、`P-H01d-after-{1,2}.pstats`、`P-H01d-comparison.json`、`P-H01d-before.log`、`P-H01d-tests.log`、`P-H01d-build.log`、相应后端日志与 `evidence/P-H01d-*.{png,txt}`。临时 `profile_backend.py` 留在输出目录供追溯，未提交至产品代码。
