# D126 缓存元数据预算补缺（2026-11-12）

基线：`b589ede2dc28d4782b28fc3370dc091d113cb8fd`；接线提交 `3440459c0dd56c36f52f60e4ec3a660e4060508c`；最终诊断根补全 `79c81f399f88197cd98af02aeb1d685a368aa44a`。关联 #126。本批补齐 126-C 的一个实际漏计，父 issue 保持开放。

## 问题与修正

真实临时 SQLite 的规范写入可在没有任何 BarCache 行时留下修订冲突索引、待回读记录。原 `memory_usage()` 只统计 bar，`_memory_roots()` 只列 resident series，遗漏这些 D126 对象；历史容量预留身份和正在执行的冷读 token 也未列入。

相同 64 个系列写入，经默认 DataManager 的 revision consumer 采用后，缓存均为 0 行 / 0 series，索引和回读各 64 条：

| 量 | 基线 | 修正后 |
| --- | ---: | ---: |
| 共同预算 bar-cache estimated_bytes | 0 | 147948 |
| bar-cache unique_retained_bytes | 0 | 54077 |
| 独立遍历索引/回读值 | 53901 | 53901 |

没有删除数据或改变修订接纳结果。保守估算可重复计算共享的 key/string；opt-in 诊断按对象身份去重，复制容器形成安全诊断视图。两者都不是 RSS/allocator 的精确计量。

修正包含：

- 修订 recent/readback 的字节估算按入队、覆盖、淘汰、reset、确认维护，热路径不遍历整条 4096 队列。长度可变的完整语义身份纳入估算。
- BarCache 统计 series 元数据、预留容量身份、活动 read token 与修订 owner。每个 resident series 的 key 大小只在创建时计算。诊断根包含 series 壳、token、容量和 revision/readback 容器及值。
- 先读取 revision owner，再获取 cache 锁，避免与现有 `consumer -> cache` 同步顺序形成锁反转。
- 一致性索引和在途 token 不成为普通 GC 删除对象。受保护元数据导致超预算时，既有预算接纳返回显式 deferred；不为容纳新任务丢失删除/冲突证据。

## 验证

接线产品完整相关回归 **1215 passed / 2 existing deprecation warnings / 178.49s**，覆盖真实 repo/默认查询、快照/修订/删除/回补、归档、物化、共享块、GC/retention、Pyne 拒绝与分层。最终诊断容器补全后 7 项新增用例再次通过；此前 176 项 cache/revision/GC 定向回归也通过。架构检查及 whitespace 检查通过。云端最终 head CI 单独记录。

7 项新增用例检查：零 resident bar 的真实数据库修订统计、预算拒绝后证据保留；冷读 token 生命周期；bounded recent 淘汰/readback overflow/reset；两种诊断入口的锁顺序；旧 acknowledgement 不释放新回读；空历史容量预留身份及 clear 回收。既有队列上限未调整。

## 成本回执

`measure.py` 使用相同脚本/解释器分别导入完整基线 backend 和产品，输入 hash 一致：200 个 resident series 各 1 行，4096 个历史修订与4096 个待回读。没有网络或数据库写入。每场景 1000 样本。最终一组原始 P50/P95/P99 如下，单位 µs：

| 场景 | 基线 | 产品 |
| --- | --- | --- |
| cache memory_usage | 185.834 / 260.291 / 392.792 | 268.667 / 275.542 / 301.167 |
| 共同预算 snapshot | 157.458 / 188.792 / 200.750 | 272.125 / 279.708 / 318.667 |
| 一次 reserve/release | 142.584 / 144.875 / 147.584 | 281.500 / 287.334 / 300.667 |

同样对象的预算估算 115800 → 9847396 字节，诊断可见 heap 193932 → 3447317 字节；主要是补计既有 D126 元数据，不是声称新增了相同量的物理内存。保留较早产品运行结果（诊断容器随后补全）；其耗时也有波动。主机未冻结到空闲，样本不是端到端性能验收，没有宣称总 RSS 下降或稳定延迟通过。新增统计有成本，如实保留；原生、多图/持续实时性能仍属 #126 剩余条件。

## 复现及边界

从项目根运行，使用项目 pinned Python 环境：

```sh
PYTHONPATH=backend python docs/qa/cache-metadata-126-20261112/probe.py
PYTHONPATH=backend python docs/qa/cache-metadata-126-20261112/measure.py candidate
mkdir -p output/cache-owner-audit-126-20261112
PYTHONPATH=backend python docs/qa/cache-metadata-126-20261112/run-regression.py
```

`probe.py` 在 backend 导入前隔离所有配置路径，规范数据库位于全新 TemporaryDirectory。基线对照用 `git archive b589ede2dc28d4782b28fc3370dc091d113cb8fd backend` 解出完整 backend，并将 PYTHONPATH 指向该 backend；不混装旧 cache.py 与新模型。

原始 writer/read 契约见 [D126 contract](../../architecture/KLINE_REVISION_CONTRACT.md)。本轮追踪仍落在既有规范 upsert/replace、归档导入、DurableBarDelivery、manual_history_derived、显式删除/retention/离线 repair 的提交链；未新增 SQL writer、日志或 owner。只读出口、生产入口全清单、共同资源联合矩阵和原生实时/深历史/修正/关闭重开仍按 #126 原始条件验收，本小批不把它们一并认定完成。

`evidence/index.json` 固定产品来源 hash 与压缩回执；微基准和受控结果不代替公网、原生包或整体 RSS 资格。原有历史 QA 与删除水位全部保留。
