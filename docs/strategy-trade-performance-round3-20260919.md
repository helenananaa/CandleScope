# 成交策略测试：第三轮性能优化

继续在 `CandleScope-strategy-replay-performance` 的前两轮未提交修改上工作，HEAD 仍为 `172ae4dd`。本轮未提交、合并或部署，也没有修改运行服务的数据库。

## 改动

**内置 SMA 的等价增量哈希。** 原来每次输出信号都会重新把全部历史 close 转成字符串并编码为 JSON 数组，再计算 SHA256。现在保存该数组尚未写入结尾 `]` 的 SHA256 状态，只追加新 close；输出时复制哈希状态并补上 `]`。结果与原 `canonical_hash([str(close), ...])` 逐字节对应，包含小数尾零和指数形式。prepare、restore、历史列表替换或 Decimal `capitals` 改变时重建；公开快照与 close 回执完全不变。仅精确类型的内置 SMA 使用此路径，子类保持原行为。不裁掉历史，也不修改 SMA 计算公式。

**扩展成交检查点的分块范围。** 新增 `TRADE_HISTORY_CHUNKS_V2`，除订单/成交外，封存追加后不再修改的决策、订单生命周期事件、成交来源事件和冻结意图。双时钟的外层决策与意图用独立流，避免与执行内核混淆。仍按 256 条一块，保存时只编码新块和尾部；公开 snapshot 返回完整原结构。账户流水、可变权益记录、provider 快照等本轮未分块。

展开后的完整 JSON 字节预算、事务和 generation/sequence 检查、每个分块的哈希校验保持不变。读取同时支持原完整检查点、成交分块 V1 和 V2；未增加数据库表或改变 schema 版本。

新增开关，默认 `1`：

| 环境变量 | 设为 0 |
|---|---|
| `BACKTEST_INCREMENTAL_SMA_HASH_ENABLED` | 内置 SMA 每个信号重新编码全部历史并计算哈希 |
| `BACKTEST_EXTENDED_TRADE_HISTORY_ENABLED` | 新成交检查点退回 V1，仅封存订单和成交 |

完全停止分块写入仍使用第一轮的 `BACKTEST_TRADE_INCREMENTAL_CHECKPOINT_ENABLED=0`。关闭开关不会自动改写已保存的 V2 检查点；旧二进制不识别 V2，不能直接替换运行。需要回滚时，在服务停止并备份后，用本轮代码的 `rollback_history(database)` 离线展开为完整格式并降至 schema 7，再由目标版本迁移。损坏分块会拒绝回滚，事务不会部分提交。

## 完整运行证据

本轮对照固定前两轮优化开启，只交替新增两个开关。每次 100,000 条合成聚合成交、10 条成交一根 1 分钟 K 线、SMA 3/5、V2 撮合，每 1,000 条行情保存检查点。计时含 worker 启动、策略、逐笔撮合、成本矩阵、检查点和报告持久化，不含数据构造/导入、HTTP 和浏览器。与构建、测试串行运行。

| 配对 | 上轮路径 | 本轮路径 | 耗时降幅 |
|---|---:|---:|---:|
| 1 | 16.054 s | 8.193 s | 48.97% |
| 2（先开启） | 11.323 s | 7.551 s | 33.31% |
| 3 | 14.275 s | 7.981 s | 44.09% |

耗时中位数 **14.275 → 7.981 秒**；三对降幅中位数 **44.09%**。均产生 2,219 笔策略成交，每对完整 result/report 完全相等。绝对耗时存在整机波动，只使用同轮配对结果，不拿上一轮记录的 10.6 秒和本轮最快值相除。

证据：`performance-evidence-20260919/round3-dual-100k.json`。SMA 的哈希收益不代表任意用户脚本都能获得相同比例；扩展检查点则适用于使用该内核和检查点路径的其他成交策略。

## 验证范围

补充低交易量负载：同样 100,000 条行情，改为每根 K 线 100 条成交，共 219 笔策略成交。三对耗时分别为 3.565 → 3.455、3.393 → 3.448、3.367 → 3.403 秒，中位数 3.393 → 3.448 秒。两对略慢，没有稳定提速；全部完整 result/report 一致。证据：`performance-evidence-20260919/round3-sparse-dual-100k.json`。这说明本轮收益主要出现在历史记录增长较快的负载。

最终回归 **268 passed**，无失败、错误或跳过，4 条已有 FastAPI 弃用警告；Ruff 和 `git diff --check` 通过。回归记录为 `performance-evidence-20260919/round3-regression.xml`，当前源码哈希收据为 `performance-evidence-20260919/round3-validation.json`。另外覆盖了不带 `extended` 属性的旧式快照编码回调兼容性。

- 比较 2,000 根输入的每个 SMA 输出，包括 state/output hash、prepare/reset、restore 和最终 close 回执；覆盖 Decimal 指数大小写变化、小数尾零与空历史，子类回退。
- 基础/V2 撮合、普通成交/双时钟四种组合验证扩展检查点的完整字节预算、展开后全快照一致、新尾部追加和恢复继续执行。
- 验证重复检查点不产生重复的新块；新增决策块损坏后拒绝恢复和离线回滚。
- 实际服务在 600 条行情持久化后中断，恢复时分别关闭全部分块或仅关闭扩展格式，继续产生订单并比较完整 result。

复现：设置 backend 和两个 SDK 的 `PYTHONPATH` 后，从工作树根运行：

```powershell
python -m scripts.benchmark_trade_strategy --round3 --events 100000 --pairs 3 --output output/trade-round3.json
```

这是 Windows 本地合成行情的服务端验证，不是生产部署、真实交易所全量数据或浏览器性能资格结论。
