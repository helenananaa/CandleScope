# 代码审查修复复核（Fix Audit）

本文件对代码审查修复批次逐条复核，核对这些改动是否正确、合理地落实了
以下三份文档所记录的问题与修复方案。2026-06-02 收口复查已重新对照当前
`main` 代码与未提交文档改动，修正了此前过期的宿主校验结论。

- [CODE_REVIEW_EXECUTION_PLAN.md](CODE_REVIEW_EXECUTION_PLAN.md)（63 条滚动记录）
- [CODE_REVIEW_ISSUE_VERIFICATION.md](CODE_REVIEW_ISSUE_VERIFICATION.md)（CR-001..CR-063 核实）
- [CODE_REVIEW_FIX_RESULTS.md](CODE_REVIEW_FIX_RESULTS.md)（修复执行记录）

**本次仅审查，不改动任何代码。**

## 复核方法

- 以工作区实际 diff 为准，逐条对照 `FIX_RESULTS.md` 声称的「Action / Result」。
- 判定每条修复是否：(a) 确实存在于 diff；(b) 正确对症；(c) 未引入回归或新风险。
- 基线验证：`cargo test --workspace` 全绿——**866 个用例通过，0 失败套件**
  （`pine-python` 经 pyo3，不在 cargo 测试范围内，单独的 `tests.rs` 仅做逻辑单测）。

## 总体结论

- 共 **63** 条记录，其中约 **35** 条产生了实际代码/测试/文档改动，其余为
  Deferred / Superseded / 纯设计说明，已核对无「偷偷改代码」。
- 已落地的修复**整体合理、对症、风险低**，且均配有回归测试与（必要时）
  fixture / conformance / 文档同步更新。
- 当前仍有 **2 处轻微后续项**（均非阻断），另有 1 条首轮遗留结论已被后续
  代码收口覆盖，见文末「遗留与建议」。

## 逐条复核结果

图例：✅ 合理且对症 ｜ 🟡 合理但有小瑕疵/可改进 ｜ ⬜ 文档声明无代码改动（已核对属实）

### A. 构建 / 工程基线

| CR | 改动文件 | 判定 | 说明 |
| --- | --- | --- | --- |
| CR-001 | README.md | ✅ | 包布局指向 `tests/fixtures/` 与 `conformance.tsv`，与实际目录一致，纯文档。 |
| CR-002 | Cargo.toml | ✅ | `repository` 填为 HTTPS 形式，与 `git remote` 一致。 |
| CR-003 | scripts/check_structure.py | ✅ | 新增 `is_test_support_file`，排除 `tests.rs`/`*_tests.rs`，不再把 `strategy/broker/tests.rs` 计入生产文件，避免广义 "test" 子串误伤。 |
| CR-004 | — | ⬜ | 明确 Deferred，未引入 `[workspace.dependencies]`，符合声明。 |
| CR-062 | Cargo.toml | ✅ | 补 `description`（clean-room 声明），与 CR-002 同处落地。 |

### B. 词法 / 语法（pine-syntax）

| CR | 改动 | 判定 | 说明 |
| --- | --- | --- | --- |
| CR-005 | parser.rs | ✅ | `parse_expr` 加 `MAX_EXPR_DEPTH=256` 包装，递归深度溢出报 `E_PARSE_EXPR_DEPTH`；增/减计数无被 `?` 绕过的早退，配回归测试。 |
| CR-006 | source.rs | ✅ | 列号由字节偏移改为字符计数（`chars().count()`），非字符边界回退到字节差；新增 UTF-8 用例。 |
| CR-007 | parser_phase_j.rs | ✅ | `export` 仅在后跟标识符时才当软关键字，`export = 5` 可作普通声明；针对已确认子集修复。 |
| CR-008 | lexer.rs | ✅ | `starts_valid_exponent` 正确识别 `e/E[+/-]digit` 科学计数法；下划线分隔符按计划 Deferred。 |
| CR-056 | tests/fixtures/syntax/* | ✅ | 新增 deep_expression_limit / malformed_number_recovery / parse_error_recovery / soft_keyword_export_identifier / utf8_diagnostic_column 五个 fixture，测试已绿。 |

### C. 语义分析与降级（pine-sema）

| CR | 改动 | 判定 | 说明 |
| --- | --- | --- | --- |
| CR-012 | expressions.rs/context.rs | ✅ | `analyze_expr` 加 `MAX_SEMA_EXPR_DEPTH=128` 包装，溢出报 `E_SEMA_EXPR_DEPTH`；`exit` 用 `saturating_sub`。 |
| CR-013 | statements.rs | ✅ | 重新赋值仅在 `can_assign` 时更新符号类型，且用 `reassigned_symbol_type`（`strongest_qualifier` + `common_kind`）合并，修复直接以 RHS 覆盖导致的类型收窄。 |
| CR-018 | functions.rs/methods.rs | ✅ | UDF/方法调用栈深 `MAX_FUNCTION_CALL_DEPTH=64`，报 `E_FUNCTION_CALL_DEPTH`；性能子项（符号扫描/实时克隆）按声明 Deferred。 |
| CR-025 | strategy.rs, pine-ir/lib.rs | ✅ | `StrategySettings::default` 默认 `Fixed(1.0)`，与 TradingView 一致；移除「缺 qty 即报错」的 sema arity 检查；仍保留 `default_qty_type` 非 fixed、`default_qty_value` 非正数的校验（见 strategy.rs:132-160）。配套 fixture/conformance/snapshot/文档同步。 |
| CR-036 | unsupported.rs/requests.rs/expressions.rs/user_types.rs | ✅ | 移除面向用户文案中的内部阶段标签（Phase J Slice / Phase L / Phase 1），改为能力子集描述。 |
| CR-037 | lowering/mod.rs/context.rs | ✅ | 引入 `LoweringLimits`：内联深度 64、HIR 节点 65536、临时符号 4096，超限报 `E_LOWERING_BUDGET`（一次性）；`lower_udf_call` 增加 `span` 用于定位。 |
| CR-038 | analysis.rs/modules.rs | ✅ | 消除根源被 `parse_source` 解析两次：改用 `module_validation.root_program`，根诊断由 `validate_modules` 统一收集，版本号取自该 program。 |
| CR-039 | modules_rewrite.rs | ✅ | 名称改写改为作用域感知：局部声明、函数/方法参数、for 计数器、元组声明都会 shadow 模块常量/函数目标（含 `prefix.field` 形式），修复「纯名称、易受作用域影响」缺陷。 |
| CR-041 | tests/builtin_registry.rs | 🟡 | 新增双向对账测试（注册签名 ↔ 运行时派发名），形成守卫。但 `RUNTIME_DISPATCHED_CALLS` 仍是手维护清单，并非由派发逻辑自动派生，未来仍需人工同步（见「遗留与建议」）。 |
| CR-011/CR-009 | — | ⬜ | 均 Deferred，未改代码，符合声明。 |
| CR-010/CR-016 | builtins history metadata / sema history / runtime registry / SAR+DMI+Supertrend+KC/KCW+MFI/TSI+Cross numeric baselines / fixed-offset runtime assertion helper | ✅ | 已引入 `BUILTIN_HISTORY_METADATA`、由 sema 消费，补 reviewed runtime/metadata 对账；fixed-offset runtime 隐式读取经 `read_declared_series_history` 做 debug/test 声明深度断言，并把 `ta.sar`/`ta.dmi`/`ta.supertrend`/`ta.kc`/`ta.kcw`/`ta.mfi`/`ta.tsi`/`ta.cross*` 数值基准绑定到各自 HIR retention。 |

### D. 运行时内核 / 数值（pine-runtime）

| CR | 改动 | 判定 | 说明 |
| --- | --- | --- | --- |
| CR-015 | runtime/expressions.rs | ✅ | 按运算符拆分：`Int±/*Int` 用 `checked_*` 保持 `Int`，溢出回退 `finite_float_or_na`；`%` 整数保 Int、除零返 `na`；**`/` 始终返回 float**——已核实与 Pine v5 语义一致（`5/2 == 2.5`）。根因修复，连带解决 CR-019/CR-024。 |
| CR-018/CR-061 | expressions.rs/historical.rs/lib.rs | ✅ | `eval_expr` 加 `MAX_RUNTIME_EVAL_DEPTH=512` 包装，溢出返 `RuntimeError`；series 缓存写入移至外层包装，语义等价。 |
| CR-019 | conformance/tests | ✅ | 计算长度（computed_lengths.pine）回归 + conformance 更新，根因即 CR-015。 |
| CR-024 | conformance/tests | ✅ | 计算数组下标/大小（computed_array_operands.pine）回归 + conformance 更新。 |
| CR-023 | arrays.rs / arrays.rs tests / runtime-error fixtures / docs | ✅ | 数组现有数组正向/负向越界从 `na`/no-op 改为 `RuntimeError`；合法负下标继续支持，并同步 conformance 与执行语义。 |
| CR-030 | request/provider.rs, builtins/requests.rs | ✅ | 缓存键去掉 `format!("{:?}", expr.kind)` 的 Debug 字符串身份，改用 `CallSiteId + symbol + timeframe`；不同 call site 仍由 id 区分，动态 symbol/timeframe 仍在键内，正确。 |
| CR-047/CR-061 | 跨 crate 预算 | ✅ | 由 sema/lowering/runtime 三层深度与资源预算共同约束跨宿主深递归崩溃面。 |

### E. 输出归一化 / 非有限值 / 宿主边界

| CR | 改动 | 判定 | 说明 |
| --- | --- | --- | --- |
| CR-031/CR-032 | output/json.rs | ✅ | 新增 `f64_json`：非有限 float 序列化为 `null`，覆盖 plots、strategy orders/trades/position/equity 及 `value_json`；顶层 `diagnostics` 不再硬编码 `[]`，改为真实序列化。配三个单测。 |
| CR-033 | cli/commands/analyze.rs | ✅ | 存在 Error 级诊断时返回 `Err("analysis failed")`（非零退出），仍打印全部诊断；含单测。 |
| CR-034 | cli/bars_csv.rs | ✅ | OHLCV 拒绝非有限值（NaN/inf）；`time` 单独按 `i64` 解析。 |
| CR-035 | cli/bars_csv.rs; wasm/lib.rs | ✅ | CLI 与 WASM `parse_bars_csv` 都调用 `validate_bar_times`，重复/未排序时间校验已对齐；size 上限与 JSON 转义去重按声明 Deferred。 |
| CR-043/CR-045/CR-047 | python/lib.rs, diagnostics.rs, tests.rs | ✅ | 非有限 float→`None`（含 `append_value`、各 strategy setter）；编译/运行改用 `diagnostics_have_errors`，放行 warning/info；诊断辅助抽到 `diagnostics` 模块并加单测。 |
| CR-048/CR-049 | wasm/lib.rs（+共享 json） | ✅ | WASM JSON 经 CR-031 共享写入器修复非有限值；CSV 拒绝非有限 OHLCV，含回归。 |
| CR-050/CR-051/CR-052 | — | ⬜ | 明确无代码改动，记为宿主契约/结构性后续项，符合声明。 |

### F. 测试 / 一致性 / 文档

| CR | 改动 | 判定 | 说明 |
| --- | --- | --- | --- |
| CR-055 | runtime tests/fixtures | ✅ | 计算整型操作数回归（arrays/builtins_math/ta_averages/control_flow/runtime_core 等）+ 新 fixture。 |
| CR-056 | syntax fixtures | ✅ | 见 B 区。 |
| CR-057 | 删除 8 个 strategy-exit fixture | 🟡 | 已删且代码/`.tsv`/`.rs` 无引用，测试全绿；但历史阶段文档（PHASE_N/P/Q/R 等）仍引用这些已删文件，造成轻微文档漂移。 |
| CR-058 | 非有限值测试 | ✅ | 非有限测试已补；f64 跨平台 CI 矩阵按声明 Deferred。 |
| CR-059 | docs/DIAGNOSTIC_CODES.md + cli 测试 | ✅ | 新增 `diagnostic_reference_documents_emitted_codes` 守卫，扫描全部 `E_*` 并要求文档覆盖（已绿，证明文档已补齐新代码）。 |
| CR-014/CR-017/CR-042/CR-063 | — | ⬜ | Superseded/无独立改动，符合声明。 |
| CR-020/021/022/026/027/028/029/040/044/046/053/054/060 | — | ⬜ | 均 Deferred / 设计说明，已核对未改代码。 |

## 遗留与建议（轻微，非阻断）

1. **CR-035 — 首轮遗留结论已过期**：当前
   `crates/pine-cli/src/bars_csv.rs` 与 `crates/pine-wasm/src/lib.rs` 的
   `parse_bars_csv` 都调用 `validate_bar_times`，并且 WASM 测试已覆盖重复与
   未排序 bar time。宿主输入契约在该点已对齐，不再作为后续 blocker。仍然
   Deferred 的是 size 上限和 CSV/JSON 解析去重，这不改变本次修复判定。

2. **CR-041 — 对账清单仍为手维护**：`RUNTIME_DISPATCHED_CALLS` 是硬编码列表，
   不是从运行时 dispatch 自动派生。它能检测「注册表 vs 该清单」漂移，但新增运行时
   分发仍需人工同步该清单，否则守卫可能与真实分发脱节。属可接受的轻量守卫，建议
   注释说明其维护约定。

3. **CR-057 — 历史文档悬挂引用**：删除的 8 个 exit fixture 仍被 `docs/PHASE_N/P/Q/R`
   等历史阶段文档引用。对当前测试无影响（无 `.rs/.tsv` 引用），且这些文件是
   历史阶段记录，不应反向扩大当前支持面；如后续整理历史文档，应标注这些 fixture
   名称是阶段历史而非当前文件清单。

## 验证证据

- `cargo test --workspace` → 866 passed，0 失败套件。
- `git --no-pager diff` 全量核对：改动文件均映射到对应 CR，未见无关改动。
- 关键语义核实：Pine v5 `/` 对整数仍返回 float，CR-015 选择 `/` 恒为 float 正确。
- 删除 fixture 的引用排查：代码/`.tsv` 中 0 引用，仅历史 `.md` 文档残留。
- 2026-06-02 收口复查：`rg` 确认 CLI/WASM 均调用 `validate_bar_times`；WASM
  测试包含重复与未排序 bar time 覆盖。

## 二次补读（覆盖首轮抽查项）

为完整性，对首轮仅抽查/经测试间接验证的部分做了逐行补读，结论均确认无误：

- **各 crate `Cargo.toml`**：统一新增 `description.workspace = true` 与
  `repository.workspace = true`，让 8 个子 crate 继承工作区元数据——这是
  CR-002/CR-062 的正确收尾（元数据真正传播到每个可发布 crate）。
- **docs/DIAGNOSTIC_CODES.md（CR-059）**：补齐新增码（`E_PARSE_EXPR_DEPTH`、
  `E_SEMA_EXPR_DEPTH`、`E_FUNCTION_CALL_DEPTH`、`E_LOWERING_BUDGET`，及新增
  `## Runtime` 段的 `E_RUNTIME`/`E_STRATEGY_*`）以及此前未记录的解析/语义码，
  与 `diagnostic_reference_documents_emitted_codes` 守卫一致。
- **新增 fixture 内容**：computed_array_operands→CR-024、computed_lengths→CR-019、
  strategy_builtin_default_quantity / supported_strategy_entry_default_quantity→CR-025、
  deep_expression_limit→CR-005、malformed_number_recovery→CR-008 边界、
  parse_error_recovery→CR-056、soft_keyword_export_identifier→CR-007、
  utf8_diagnostic_column→CR-006，均精准对症。
- **crates/pine-syntax/tests/fixtures.rs**：harness 对错误类 fixture 断言了**具体
  诊断码 + 恢复后语句数**，而非「能解析即可」。其中 `utf8_diagnostic_column`
  断言 `@` 位于 `line 3, column 9`（字符列；若按字节为第 11 列），**端到端坐实
  了 CR-006 列号修复**。

补读未改变任何判定，反而强化了「修复合理、测试到位」的结论。
