# 分阶段代码审查执行文档（Code Review Execution Plan）

本文件用于对 `pine-compat-runtime` 进行一次系统性、逐阶段的代码审查。目标是
在不改变功能的前提下，逐步建立对整个代码库的深入理解，记录潜在问题、风险和
改进点，并为后续重构或扩展打下基础。

本审查计划面向「人 + AI 协作逐文件走读」的工作方式：每个阶段是一个可独立完成
的工作单元，规模适中（通常 1 次会话内可覆盖），并带有明确的审查清单与产出。

## 如何使用本文档

- 按阶段顺序推进（流水线上游 → 下游），因为下游依赖上游的契约。
- 每个阶段开始时，把状态标记为「进行中」；完成后标记为「已完成」，并在该阶段
  末尾的「发现记录」中填入结论。
- 审查中**不直接修改功能代码**；发现的问题先记录，统一在每个阶段末尾决定是否
  立即修复（小问题）或登记为后续任务（较大改动）。
- 每个阶段的「审查清单」是通用问题模板，可按文件实际情况增删。

## 审查通用关注点（每个文件都问一遍）

- **正确性**：边界条件、`na`/`nz` 处理、空集合、整数溢出、浮点比较与精度。
- **确定性**：相同程序 + 数据 + 输入是否产生完全一致的输出（无时钟、无随机、
  无文件/网络、无遍历顺序依赖）。
- **错误处理**：错误是否带 source span？上游错误是否被吞掉？panic / unwrap /
  expect 是否可被恶意或异常输入触发？
- **契约边界**：core crate 是否意外读取文件、网络、时钟（架构红线）。
- **可读性与一致性**：命名、模块边界、重复逻辑、`TODO`/`FIXME`、与文档声明是否
  一致。
- **安全性**：不可信输入路径（脚本源码、CSV、host JSON）是否会导致越界、无限
  循环、内存暴涨、资源耗尽。
- **测试覆盖**：是否有对应单测/快照/fixture；是否覆盖失败路径与边界。

## 阶段总览

| 阶段 | 范围 | 主要 crate / 目录 | 规模(行,约) | 状态 |
| --- | --- | --- | --- | --- |
| 0 | 仓库与构建基线 | 根 `Cargo.toml`、`scripts/`、docs 索引 | — | 已完成 |
| 1 | 词法与语法 | `pine-syntax` | 2.7k | 已完成 |
| 2 | 中间表示 | `pine-ir` | 0.3k | 已完成 |
| 3 | 语义分析（核心） | `pine-sema` analyzer/resolver/types | 7k | 已完成 |
| 4 | 语义降级与模块图 | `pine-sema` lowering/modules/source_graph | 2k | 已完成 |
| 5 | 内置签名注册表 | `pine-builtins` | 5.3k | 已完成 |
| 6 | 运行时内核 | `pine-runtime` runtime/ + bar/error/lib | 2.5k | 已完成 |
| 7 | 运行时内置：数值/字符串/时间 | `pine-runtime/builtins` (ta/math/strings/time) | 4k | 已完成 |
| 8 | 运行时内置：数组/绘图/输出/变量 | `pine-runtime/builtins` (arrays/drawings/outputs) | 3.5k | 已完成 |
| 9 | 策略与撮合 | `pine-runtime/strategy` | 1.5k | 已完成 |
| 10 | 请求数据边界 | `pine-runtime/request` + builtins/requests | 0.4k | 已完成 |
| 11 | 输出归一化与 JSON | `pine-runtime/output` | 1.5k | 已完成 |
| 12 | CLI | `pine-cli` | 1.8k | 已完成 |
| 13 | Python 绑定 | `pine-python` | 0.8k | 已完成 |
| 14 | WASM 绑定 | `pine-wasm` | 1.2k | 已完成 |
| 15 | 测试/快照/一致性 | `*/tests`、`tests/fixtures`、`conformance` | 8k+ | 已完成 |
| 16 | 横切：诊断/确定性/安全/合规 | 跨 crate | — | 已完成 |

---

## 阶段 0 — 仓库与构建基线

**目标**：建立对整体工程结构、构建与验证流程的认识，确认审查环境可用。

**涉及内容**
- 根 [Cargo.toml](Cargo.toml)、各 crate 的 `Cargo.toml`、`pyproject.toml`
- [scripts/check_structure.py](scripts/check_structure.py)、[scripts/verify.sh](scripts/verify.sh)
- 文档索引：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、
  [docs/LANGUAGE_SCOPE.md](docs/LANGUAGE_SCOPE.md)、
  [docs/EXECUTION_SEMANTICS.md](docs/EXECUTION_SEMANTICS.md)

**审查清单**
- 工作区成员、依赖版本、feature flag 是否一致；是否有重复/冲突依赖。
- `edition = 2024`、`rust-version` 与实际使用的语言特性是否匹配。
- 验证脚本能否一键跑通：`cargo check`、`cargo test`、结构检查、wasm target、pytest。
- 文档与代码现状的偏差（README「Current Baseline」声明 vs 实际能力）。

**产出**：一份「构建与验证操作手册」要点，确认基准命令；记录文档/实现偏差清单。

### 阶段 0 审查结论（2026-05-31）

**构建与验证基线 — 全部通过（绿）**

基准命令（来自 [scripts/verify.sh](scripts/verify.sh)，CI 经 [.github/workflows/ci.yml](.github/workflows/ci.yml) 调用同一脚本）：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 格式 | `cargo fmt --check` | 通过 |
| Lint | `cargo clippy --workspace --all-targets -- -D warnings` | 通过（零告警） |
| 测试 | `cargo test --workspace` | 全部通过（多套件，合计约 880+ 用例） |
| 结构守卫 | `python3 scripts/check_structure.py` | 通过（135 个生产源文件） |
| WASM | `cargo check -p pine-wasm --target wasm32-unknown-unknown` | 通过 |
| Python | `maturin build … && pip install … && pytest python/tests` | 38 passed |

- 工具链：`rustc 1.95.0`，与 workspace `rust-version = 1.95`、`edition = 2024` 一致。
- `git status`：干净（仅本审查文档未跟踪）。

**依赖图**：单向、无环、无版本冲突。
`pine-ir` 为无依赖叶子；`pine-builtins → pine-ir`；`pine-sema → {builtins, ir, syntax}`；
`pine-runtime → {builtins, ir}`（dev: sema, syntax）；CLI/Python/WASM 为顶层聚合。
外部依赖：`chrono 0.4`(default-features=false)、`regex 1`、`serde_json 1`、`pyo3 0.28.3`、`wasm-bindgen 0.2.121`。

**确定性红线（初查通过）**：core crate 全量 grep 未发现 `Utc::now / Local::now / SystemTime::now / Instant::now` 调用；
`chrono` 关闭默认特性（即关闭 `clock`），从依赖层面阻断了系统时钟访问。

**发现的问题/偏差**（仅记录，未修改）：

- [低] 文档漂移：[README.md](README.md#L81) 的「Current Package Layout」列出了 `tests/conformance/`
  目录，但实际不存在；一致性数据实际位于 [tests/fixtures/conformance.tsv](tests/fixtures/conformance.tsv)（354 行）。
- [低] 包元数据不完整：根 [Cargo.toml](Cargo.toml#L17) `repository = ""` 为空。对一个目标是发布
  稳定 Rust/Python/WASM 绑定的项目，建议补全（暂记，不在审查阶段修改）。
- [信息] 结构守卫分类缺口：[scripts/check_structure.py](scripts/check_structure.py) 仅排除 `/src/tests/`
  路径，因此 [crates/pine-runtime/src/strategy/broker/tests.rs](crates/pine-runtime/src/strategy/broker/tests.rs)
  （1245 行，实为测试文件）被当作「implementation」纳入 1500 行上限统计并逼近阈值。分类规则与实际语义不符。
- [信息] 无 `[workspace.dependencies]` 集中管理：外部依赖在各 crate 内分散声明。当前各外部依赖仅出现在
  单一 crate，无重复/冲突；但未来共享依赖存在版本漂移风险。
- [信息] CI 存在并直接运行 `scripts/verify.sh`（与本地验证同源），覆盖 fmt/clippy/test/结构/wasm/python 全链路。

**结论**：仓库基线健康、可审查，可进入阶段 1。上述偏差均为低风险，留待阶段 16（横切）统一处置或单独提任务。

---

## 阶段 1 — 词法与语法（`pine-syntax`）

**目标**：审查从源码到 AST 的全过程，确认 span 精确、诊断可恢复、无 host 依赖。

**涉及文件**
- [crates/pine-syntax/src/lexer.rs](crates/pine-syntax/src/lexer.rs)
- [crates/pine-syntax/src/parser.rs](crates/pine-syntax/src/parser.rs)
- [crates/pine-syntax/src/parser_phase_j.rs](crates/pine-syntax/src/parser_phase_j.rs)
- [crates/pine-syntax/src/ast.rs](crates/pine-syntax/src/ast.rs)
- [crates/pine-syntax/src/source.rs](crates/pine-syntax/src/source.rs)
- [crates/pine-syntax/src/diagnostic.rs](crates/pine-syntax/src/diagnostic.rs)

**审查清单**
- Token span 与字节/行列偏移是否精确、是否处理多字节字符。
- 表达式优先级（Pratt）、历史引用 `x[n]`、命名参数、缩进/换行块的解析正确性。
- 错误恢复策略：是否会无限循环、是否吞掉后续错误。
- Lexer 对非法字符、未闭合字符串/注释、超长输入的健壮性（安全性关注点）。
- AST 节点是否携带足够的 span 供下游诊断；是否存在重复/可合并的节点定义。

**产出**：语法层问题清单 + AST 结构图（节点种类与字段）。

### 阶段 1 审查结论（2026-05-31）

**总体**：手写 lexer + Pratt 表达式解析器，结构清晰，无 host 依赖（无文件/网络/时钟）。语法层质量良好；早期记录的表达式递归深度健壮性问题已关闭。

**良好实践（已验证）**
- 所有字面量解析错误（int/float/color/version）优雅降级为诊断 + 占位值，无 panic。
- 字符串与未知转义按完整 UTF-8 scalar 消费（多字节安全）。
- Span 为字节偏移（start/end）+ `merge`；`SourceFile` 预计算 `line_starts`，`line_col` 为 O(log n)。
- 错误恢复 `recover_stmt` 有界；块/恢复路径无死循环（`Dedent`/`Eof` 优先检查）。
- `current()` 安全：Eof 总被追加且 `bump()` 在末尾钉住。
- 缩进栈 + Indent/Dedent token + `E_LEX_INDENT` 不一致缩进诊断。

**发现的问题（仅记录，未修改）**
- [已关闭] 解析器递归无深度上限：当前 [parser.rs](crates/pine-syntax/src/parser.rs) 为 `parse_expr` 增加 `MAX_EXPR_DEPTH=256`，超限报 `E_PARSE_EXPR_DEPTH` 而非栈溢出，并由 `rejects_expression_nesting_past_depth_limit` 与 `deep_expression_limit.pine` fixture 覆盖。
- [低] `line_col` 列号按字节计算而非字符：含多字节 UTF-8 的行，诊断列号偏大（仅影响诊断显示）。— [source.rs](crates/pine-syntax/src/source.rs)
- [低] 软关键字碰撞：`library/export/type/method` 被词法当作普通 Identifier，`phase_j_statement` 用上下文判定。`export`/`library` 无 lookahead 守卫，`export = 5`、`type x = 5` 等会误解析。Pine 中这些为保留字，影响有限。— [parser_phase_j.rs](crates/pine-syntax/src/parser_phase_j.rs)
- [低] 数值字面量不支持科学计数法/下划线分隔：`number()` 仅识别十进制整数与 `d.d` 浮点；`1e6` 会被拆为 `1` + 标识符 `e6`。需与 LANGUAGE_SCOPE 核对是否为预期。— [lexer.rs](crates/pine-syntax/src/lexer.rs)
- [信息] 版本指令可出现在任意行：`comment_or_version` 在任何 `//@version=` 处发射 VersionDirective token，但 parser 仅在开头消费；文件中后续版本指令会成为游离 token 触发解析错误。
- [信息] 浮点上溢静默为 `inf`：`parse::<f64>` 对超大字面量返回 inf 不报错（与 int 溢出报 E_LEX_INT 不一致）。
- [信息] `Severity::Warning/Info` 在语法层未被使用（仅 `Diagnostic::error` 构造器）。
- [信息] 制表符固定按 4 空格计算缩进（tab=4 硬编码）；混合制表符/空格可能产生意外层级（有不一致缩进诊断兜底）。
- [信息] 诊断码盘点：语法层共 7 个 `E_LEX_*` + 14 个 `E_PARSE_*`（共21），留待阶段 16 与 DIAGNOSTIC_CODES.md 核对。

**结论**：语法层可靠、可进入阶段 2。历史递归深度上限问题已关闭并有 fixture/单测守护，其余为低/信息级，留待阶段 16 或单独提任务。

---

## 阶段 2 — 中间表示（`pine-ir`）

**目标**：理解 HIR/MIR/bytecode 的定义（当前仅 290 行，bytecode VM 已延后）。

**涉及文件**
- [crates/pine-ir/src/lib.rs](crates/pine-ir/src/lib.rs)
- 参考 [docs/BYTECODE_VM_EVALUATION.md](docs/BYTECODE_VM_EVALUATION.md)

**审查清单**
- IR 数据结构是否足以表达当前已支持子集；是否存在过早抽象。
- HIR 与 sema lowering、runtime 执行之间的字段契约是否清晰。
- 注释/文档与实际「直接执行 MIR」的现状是否一致。

**产出**：IR 契约说明（谁生产、谁消费、各字段语义）。

### 阶段 2 审查结论（2026-05-31）

**总体**：`pine-ir` 是纯数据定义 crate（290 行，仅 lib.rs），无逻辑、无 I/O、无依赖。仅含 `Default for StrategySettings`、`PineType::new`、`default_entry_qty` 三个纯函数。质量良好，符合架构红线。

**契约梳理**
- 生产者：`pine-sema` lowering（阶段 4）；消费者：`pine-runtime`。IR 仅表达 **HIR**（`HirProgram`→`HirStmt`→`HirExpr`）。
- `HirProgram` 携带脚本模式、策略设置、符号表、分配游标（next_*_id）与历史需求（程序级 + 每序列级 max_constant_offset / has_dynamic_offsets），为有界缓冲区提供依据。
- `Qualifier`（Const/Input/Simple/Series）+ `ValueKind`（含标量/数组/绘图/UserType/Na/Void）组成 `PineType`（Copy）。
- 含 f64 的类型正确地仅 derive `PartialEq` 而非 `Eq`。

**发现的问题（仅记录，未修改）**
- [低] HIR 不携带 `Span`：`HirStmt`/`HirExpr` 丢失源位置信息。架构文档声明「每阶段都应暴露带 span 的诊断」，但运行时错误（如除零/数组越界）无法回指源码位置。留待阶段 6/16 核实运行时诊断是否需要 span。— [lib.rs](crates/pine-ir/src/lib.rs)
- [信息] builtins/调用为字符串型：`HirExprKind::Builtin(String)` 与 `Call{callee: String}` 用名称标识，跨 IR→runtime 边界无编译期保证（拼写错误只能运行时发现）；存在 `SymbolId`/`CallSiteId` 但未用于 builtin 拘留。
- [信息] 文档术语漂移：ARCHITECTURE 称「首发版可直接执行 MIR」，但实际无 MIR/bytecode 类型，runtime 直接执行 HIR。与 BYTECODE_VM_EVALUATION 的延后决定一致，仅措辞需更新。
- [信息] 平行枚举重复：AST 的 `BinaryOp/UnaryOp/Literal` 与 IR 的 `HirBinaryOp/HirUnaryOp/HirLiteral` 变体完全一致。解耦意图合理，但 lowering 需 1:1 映射且两者必须同步维护。
- [信息] UserType 无类型身份：所有用户类型共用 `ValueKind::UserType`，字段按位置 `index: usize` 访问；与 Phase J「root-local、不跟踪导入 UDT 身份」的范围一致。

**结论**：IR 层干净、足以表达当前子集，无过早抽象。主要设计观察是 HIR 无 span（低）与字符串型 builtin（信息）。可进入阶段 3。

---

## 阶段 3 — 语义分析核心（`pine-sema` analyzer）

**目标**：审查名称解析、类型/限定符推断、声明与重赋值规则、不支持特性的显式诊断。

**涉及文件（建议拆 2 次会话）**
- 解析与符号：[resolver.rs](crates/pine-sema/src/resolver.rs)、
  [symbols.rs](crates/pine-sema/src/symbols.rs)、
  [types/mod.rs](crates/pine-sema/src/types/mod.rs)、
  [history.rs](crates/pine-sema/src/history.rs)
- analyzer 子模块：
  [context.rs](crates/pine-sema/src/analyzer/context.rs)、
  [statements.rs](crates/pine-sema/src/analyzer/statements.rs)、
  [expressions.rs](crates/pine-sema/src/analyzer/expressions.rs)、
  [calls.rs](crates/pine-sema/src/analyzer/calls.rs)、
  [functions.rs](crates/pine-sema/src/analyzer/functions.rs)、
  [methods.rs](crates/pine-sema/src/analyzer/methods.rs)、
  [user_types.rs](crates/pine-sema/src/analyzer/user_types.rs)、
  [strategy.rs](crates/pine-sema/src/analyzer/strategy.rs)、
  [requests.rs](crates/pine-sema/src/analyzer/requests.rs)、
  [alerts.rs](crates/pine-sema/src/analyzer/alerts.rs)、
  [unsupported.rs](crates/pine-sema/src/analyzer/unsupported.rs)

**审查清单**
- 限定符（const/input/series）推断与传播是否正确，尤其在分支/循环/重赋值中。
- 历史偏移 `x[n]`（常量 vs 受控动态）的合法性判定。
- 「不支持特性」是否在此层稳定地转为诊断，而非泄漏到 runtime。
- 用户自定义函数/类型/方法的作用域、receiver 传参、纯度判断。
- 诊断码与 [docs/DIAGNOSTIC_CODES.md](docs/DIAGNOSTIC_CODES.md) 是否一一对应。

**产出**：限定符/类型推断规则速查 + 诊断覆盖缺口清单。

### 阶段 3 审查结论（2026-05-31）

**总体**：语义层是迄今最复杂的部分（analyzer/resolver/types/history 约 7k 行）。整体设计扎实：限定符格点清晰、不支持特性稳定转诊断、UDF/方法均有递归守卫。本阶段未发现「高」级问题，主要为耦合风险（中）与文档/语义细节（低/信息）。

**限定符/类型推断规则速查（产出 1）**
- 限定符格点（`types/mod.rs::qualifier_rank`）：`Const(0) < Input(1) < Simple(2) < Series(3)`。`strongest_qualifier` 取秩较大者；二元/三元/switch 结果限定符 = 各子表达式限定符之并（取最强）。
- `can_assign(target,value)`：同 `kind` 时要求 `value.qualifier ≤ target.qualifier` **或** `target` 为 Series（Series 是最宽汇点，接受任意限定符）；额外允许 `Int → Float` 隐式拓宽。
- 数值二元（`+ - * / %`）：限定符取最强，`kind` 由 `numeric_result_kind` 定——`/` 恒为 `Float`，否则任一为 `Float` 则 `Float`，全 `Int` 则 `Int`。比较运算恒为 `Bool`，`and/or` 要求两侧 `Bool`。
- 内置返回类型由 `ReturnSpec`（`Fixed/SameAsArg/Promoted*/ArrayElement/…` 共 20+ 变体）驱动，`return_type()`/`type_of_expr_with_params` 两处各实现一遍（见下「平行推断路径」）。
- 持久性（`PersistenceKind`）与限定符正交：`var`→`Var`、`varip`→`Varip`（仅标量+标量数组，绘图 id/UDT/元组被拒），各自分配 `VarSlotId`。
- 历史需求（`history.rs`）：常量偏移累积 `max_constant_offset`（程序级 + 每 `SeriesId` 级），动态偏移置 `has_dynamic_offsets`；`ta.*` 隐式回看（如 `ta.tr→close[1]`、`ta.sar→high/low[2],close[1]`）硬编码于 `record_call_history`。

**诊断覆盖缺口清单（产出 2）**
- sema 共发射 ~50 个诊断码。其中 **11 个已实现但未登记于 DIAGNOSTIC_CODES.md**：`E_STRATEGY_MODE`、`E_SCRIPT_DECL_LOCATION`、`E_SCRIPT_DECL_DUPLICATE`、`E_LOOP_CONTROL`、`E_LOOP_RANGE_TYPE`、`E_LOOP_STEP`、`E_LOOP_RETURN`、`E_UNKNOWN_FUNCTION`、`E_UNKNOWN_METHOD`、`E_UNKNOWN_COLOR`、`E_METHOD_RECEIVER_TYPE`。

**良好实践（已验证）**
- UDF 与用户方法均有递归守卫：`function_stack` 命中即报 `E_RECURSIVE_FUNCTION` / `E_RECURSIVE_METHOD`，主分析路径不会无界递归。
- 不支持特性集中经 `unsupported()` 转为 `E_UNSUPPORTED_FEATURE` 诊断并登记 `compatibility.unsupported`，不泄漏到 runtime；命名空间级兜底（`strategy./request./array./drawing.`）覆盖未实现内置。
- `finish()` 仅在 `!has_errors()` 时才 lowering 生成 HIR——有错误时不产出可执行 IR，杜绝半成品下传。
- UDF 副作用约束完整：函数内禁止 output/声明类内置、数组变异、全局重赋值，且禁止把副作用调用作为实参传入。
- 常量求值 `const_int_value`/`constant_hir_int` 用 `checked_neg`，无溢出 panic。

**发现的问题（仅记录，未修改）**
- [已关闭][中] `ta.*` 隐式历史需求已从 `history.rs` 手写 callee 表迁到 [pine-builtins history metadata](crates/pine-builtins/src/history.rs)，`history.rs::record_call_history` 改为消费该共享声明，且 `infers_implicit_ta_history_requirements_by_series` 覆盖主要隐式 `ta.*` 表项。当前已补 `runtime_implicit_history_calls_match_shared_metadata`，用 reviewed runtime 隐式历史读取清单与共享 metadata 做完全对账；fixed-offset runtime 隐式读取经 `read_declared_series_history` 做 debug/test 声明深度断言；`runs_sar_over_historical_bars`、`runs_dmi_over_historical_bars`、`runs_supertrend_over_historical_bars`、`runs_keltner_channels_over_historical_bars`、`runs_keltner_channel_width_over_historical_bars`、`runs_mfi_over_historical_bars`、`runs_tsi_over_historical_bars` 与 `runs_cross_functions_over_historical_bars` 已把端到端数值序列绑定到对应 HIR retention 断言。显式历史和 length-derived 读取仍保留 Pine warmup/`Na` 语义。— [history.rs](crates/pine-sema/src/history.rs)
- [低] 平行类型推断路径需手工同步：`analyze_expr`（带诊断、有递归守卫）与 `type_of_expr_with_params`（纯推断、**无**独立递归守卫，靠「有错即跳过 lowering」间接兜底）各自实现一套 `ReturnSpec`/二元/三元/switch 推断。两者一旦漂移即产生「分析期类型」与「lowering 期类型」不一致。当前递归 UDF 总会先在 `analyze_udf_call` 报错从而不进入 lowering，故暂不可达；属潜在脆弱点。— [expressions.rs](crates/pine-sema/src/analyzer/expressions.rs)
- [已关闭] 语义层主分析递归无深度上限：当前 [expressions.rs](crates/pine-sema/src/analyzer/expressions.rs) 用 `MAX_SEMA_EXPR_DEPTH=128` 报 `E_SEMA_EXPR_DEPTH`，UDF/方法调用链用 `MAX_FUNCTION_CALL_DEPTH=64` 报 `E_FUNCTION_CALL_DEPTH`；`rejects_deep_semantic_expression_nesting`、`rejects_deep_acyclic_function_call_chain` 与 sema fixtures 覆盖该边界。纯推断路径的手工同步风险仍由上一条“平行类型推断路径”跟踪。
- [低] 重赋值会按 RHS 限定符覆盖符号类型：`Reassign` 末尾 `update_symbol_type(name, value_type)` 直接以右值类型替换符号类型，可能把一个 `var`/曾为 Series 的变量**收窄**为 Const/Simple；条件分支内的重赋值也不会强制提升为 Series。持久性虽由 `var_slot`/`PersistenceKind` 单独跟踪，但限定符不反映「逐 bar 可变=series」的 Pine 语义。需与 runtime 行为核对是否影响正确性。— [statements.rs](crates/pine-sema/src/analyzer/statements.rs)
- [信息] 不支持原因串混用内部阶段标签：`unsupported.rs` 的 reason 文案夹带 “Phase J Slice 0 / Phase 1 / Phase L” 等内部里程碑词汇，且粒度不一（有的写 “Phase 1”、有的写 “current subset”），面向最终用户时含义不清。建议统一为面向用户的措辞，留待阶段 16。— [unsupported.rs](crates/pine-sema/src/analyzer/unsupported.rs)
- [信息] `expr_types`/`expr_user_types`/`bindings` 以 `(span.start, span.end)` 或 `BindingKey{span,name}` 作记忆化键：依赖 span 唯一性。当前 AST 中各表达式 span 互异，无冲突；若未来出现合成/复用 span（如宏展开）需警惕键碰撞。— [context.rs](crates/pine-sema/src/analyzer/context.rs)

**结论**：语义核心质量良好、契约清晰，无「高」级问题。最值得跟进的是 `ta.*` 隐式历史表与 runtime 的同步（中），其余为低/信息级。可进入阶段 4（lowering/模块图）。

---

## 阶段 4 — 语义降级与模块图（`pine-sema` lowering）

**目标**：审查 AST→HIR 降级、import/source graph、模块内联与重写。

**涉及文件**
- [lowering/mod.rs](crates/pine-sema/src/lowering/mod.rs)
- [source_graph.rs](crates/pine-sema/src/source_graph.rs)
- [modules.rs](crates/pine-sema/src/modules.rs)、
  [modules_rewrite.rs](crates/pine-sema/src/modules_rewrite.rs)
- [analysis.rs](crates/pine-sema/src/analysis.rs)、
  [cache.rs](crates/pine-sema/src/cache.rs)、
  [compatibility.rs](crates/pine-sema/src/compatibility.rs)

**审查清单**
- `SourceId` 分配（root=0，库按 import key 排序）是否确定性；key 规范化与去重。
- 导出 const 内联、导出纯函数 lower 为 UDF 路径的正确性与隔离性。
- 缓存键是否覆盖所有影响结果的输入；缓存是否会引入跨脚本污染。
- core 不读文件/网络/时钟的红线是否守住（host 提供的 map 才是唯一来源）。

**产出**：lowering 数据流图 + 模块/缓存契约说明。

### 阶段 4 审查结论（2026-05-31）

**总体**：lowering 与模块图（~2k 行）质量良好。核心设计是**源级单态化/内联**：UDF、用户方法、导入函数都在 lowering 期按调用点展开为 HIR 块，常量导出被原地替换——runtime 不需函数/模块概念。本阶段未发现「高/中」级问题。

**lowering 数据流（产出 1）**
- `validate_modules(input)` → 解析各源、检查导入（缺库/别名/私有符号/重复导出/环）、构建 `ImportPlan`、用 `rewrite_program` 重写 root（常量内联 + 函数名重定向）→ 返回重写后 root + 导入函数表。
- `analyze_input` 以重写后 root + 导入函数表构 `Analyzer` → `analyze_program`（类型/诊断）→ `finish` 仅在无错时 `lower_program`。
- `lower_program`：跳过 Function/Import/Library/Export/UserType/Method/Unsupported 顶层声明，逐句 `lower_stmt` → `lower_symbols`（仅允许时） → `infer_history_requirements` + `infer_max_bars_back` → `HirProgram`。
- UDF 内联：`lower_udf_call` 为每个实参建 `Decl` 临时符号，用 `param_exprs`/`param_types` 替换形参，`lower_function_body` 在 `lower_symbol_overrides` 栈帧内 lower 体（嵌套内联时用 `fresh_lower_symbol` 避免槽位别名）。

**模块/缓存契约（产出 2）**
- `SourceId` 确定性：root=0，库按**规范化后 key 排序**依次 `library(0..)`；`normalize_library_key` 拒空/控制字符/内部空白，`with_library_sources` 去重（trim 后冲突报 `DuplicateLibraryKey`）。同一输入集总得相同 id。
- `CompileCache` 键 = root(name+text) + 各库(key+name+text) 全量，覆盖**所有**影响结果的输入；键含全文，不会跨脚本污染。
- core 红线守住：库源唯一来自 host 提供的 map，无文件/网络/时钟读取。
- 导入隔离：导出函数内联为 `alias.name` 键，私有被引用函数为 `__import_alias_name` 键；`E_IMPORT_PRIVATE_SYMBOL`/`E_IMPORT_UNKNOWN_EXPORT` 隔离未导出符号；导出函数副作用被 `E_IMPORT_FUNCTION_SIDE_EFFECT` 拦截。

**良好实践（已验证）**
- 导入环检测 `detect_import_cycles` 用 visiting/visited 双集 DFS，出环报 `E_IMPORT_CYCLE` 且不无限递归。
- 导出常量经 `is_const_import_expr` 验证仅允许字面量/常量限定符/纯运算，非常量报 `E_IMPORT_CONST_VALUE`。
- 模块层 10 个 `E_IMPORT_*` 诊断码**均已登记**于 DIAGNOSTIC_CODES.md（与阶段3 sema 核心的 11 个缺口形成对比）。
- `collect_library_declarations` 用 `mem::take` 避免克隆整个 AST 遍历（性能+借用友好）。

**发现的问题（仅记录，未修改）**
- [已关闭] 内联递归无深度/规模上限：当前 [lowering/mod.rs](crates/pine-sema/src/lowering/mod.rs) 通过 `LoweringLimits` 限制 inline 深度、HIR 节点数与临时符号数，超限报 `E_LOWERING_BUDGET`；`rejects_lowering_temp_symbol_budget_exhaustion` 覆盖预算失败路径。
- [信息] root 被解析两次：`validate_modules` 内 `parse_source(graph.root())` 一次，`analyze_input` 又 `parse_source(input.root())` 一次。正确性无损（诊断不重复），仅单次调用内重复解析开销；可复用一份 AST。— [analysis.rs](crates/pine-sema/src/analysis.rs)
- [信息] 常量按名替换的潜在遮蔽：`rewrite_expr` 对任意 `expr_name` 命中 `context.constants` 的表达式整体替换为常量值。若库体内局部符号与某导入常量同名，可能被意外替换（当前子集下概率低）。— [modules_rewrite.rs](crates/pine-sema/src/modules_rewrite.rs)
- [信息・已关闭] 模块/重写递归与阶段1 同类：`rewrite_expr`/`visit_expr`/`is_const_import_expr` 处理的是已通过 parser 的 AST，host 提供库表达式同受 `MAX_EXPR_DEPTH` 约束；深表达式主崩溃面已由阶段1解析深度上限间接关闭。— [modules_rewrite.rs](crates/pine-sema/src/modules_rewrite.rs)、[modules.rs](crates/pine-sema/src/modules.rs)

**结论**：lowering/模块层确定性、隔离性、诊断覆盖均良，无「高/中」级问题。历史内联无上限问题已由 `LoweringLimits` 关闭，剩余为重复解析、模块常量遮蔽等信息级工程观察。可进入阶段 5（内置签名注册表）。

---

## 阶段 5 — 内置签名注册表（`pine-builtins`）

**目标**：审查内置命名空间、函数签名、常量、返回类型契约（编译期元数据，不含执行）。

**涉及文件**
- [registry.rs](crates/pine-builtins/src/registry.rs)、
  [signature.rs](crates/pine-builtins/src/signature.rs)、
  [returns.rs](crates/pine-builtins/src/returns.rs)
- `namespaces/`：`ta.rs`、`math.rs`、`strings.rs`、`arrays.rs`、`drawings.rs`、
  `outputs.rs`、`strategy.rs`、`requests.rs`、`alerts.rs`、`time.rs`、`colors.rs`、
  `core.rs`、`types.rs`
- `constants/`：colors/floats/ints/series/strings

**审查清单**
- 签名（参数名、可选/必填、类型、返回）与 runtime 实际实现是否一致（关键对账）。
- 与 [docs/BUILTIN_SIGNATURES.md](docs/BUILTIN_SIGNATURES.md) 的同步性。
- 常量值（颜色、数学常量）正确性。
- 是否存在「签名声明了但 runtime 未实现」或反之的悬空项。

**产出**：签名 ↔ 实现对账表（标注一致 / 缺口 / 不一致）。

### 阶段 5 审查结论（2026-05-31）

**总体**：`pine-builtins`（~5.3k 行）是纯编译期元数据 crate：`BuiltinSignature` 静态表由 const fn 在编译期拼装，零运行期成本。质量良好，未发现「高/中」级问题。

**签名 ↔ 实现对账（产出，实测）**
- 共 **252** 个 `BuiltinSignature` vs runtime **250** 个 callee 分发臂，对账**干净**：
  - 13 个「仅签名、无 runtime 分发臂」全为声明/输入类：`indicator`、`input`、`input.*`。这些经专用路径处理（`input.*` 在 [variables.rs](crates/pine-runtime/src/builtins/variables.rs) 解析为输入值，声明类不走 callee 分发），**非真缺口**。
  - 11 个「仅 runtime 分发臂、无签名」全为**字符串常量值**（`format.price/percent/volume`、`order.ascending/descending`、pivot 类型串 `Camarilla/Classic/Fibonacci/Traditional/Woodie`、`DM`），均已在 [constants/strings.rs](crates/pine-builtins/src/constants/strings.rs) 登记为字符串常量，是参数**值**而非函数名。
  - 结论：**无悬空签名（声明了但 runtime 未实现），也无孤儿 runtime 实现（实现了但无签名）**。

**良好实践（已验证）**
- `BUILTIN_COUNT` 由各子表 `.len()` 编译期求和，`build_phase_1_builtins` 用 const fn 拼接：新增/遗漏签名会在编译期长度不匹配而暴露，不会静默漂移。
- 颜色调色板与 Pine 标准一致（`color.orange=0xFF9900`、`color.red=0xFF0000` 等 17 色）；`math.e/pi` 用 `std::f64::consts`，`math.phi/rphi` 数值正确。
- `Accepts`（30+ 变体）与 `ReturnSpec`（20+ 变体）类型丰富，能表达序列/简单/常量限定符及准确返回推导（SameAsArg/Promoted*/ArrayElement 等）。
- strategy 声明/entry/exit/close 签名有专门单测锁定参数名与 accepts。

**发现的问题（仅记录，未修改）**
- [信息] `syminfo.mintick=0.01` / `syminfo.pointvalue=1.0` 硬编码：真实 Pine 中随品种动态，此处固定常量，跨品种脚本数值会偏差（兼容性限制）。留待运行时阶段核实是否有被覆盖路径。— [constants/floats.rs](crates/pine-builtins/src/constants/floats.rs)
- [信息] 注册表/常量查找均为线性 O(n)：`get_phase_1_builtin`/`named_color`/`named_float_constant` 每次调用线性扫描全表。规模小（~252/~17）影响可忽，但热路径高频调用时可考虑排序二分/完美哈希。— [registry.rs](crates/pine-builtins/src/registry.rs)
- [信息] 签名 ↔ runtime 一致靠测试与人工维护，无编译期强约束（callee 为字符串，与阶段2 字符串型 builtin 观察一致）。建议加一个 reconciliation 单测遍历 `PHASE_1_BUILTINS`，校验每个非声明类 builtin 在 runtime 有分发臂，锁住本阶段手工对账结论。— [registry.rs](crates/pine-builtins/src/registry.rs)
- [信息] 签名与 [docs/BUILTIN_SIGNATURES.md](docs/BUILTIN_SIGNATURES.md) 的同步性未逐项核对，留待阶段 16 统一文档对账。

**结论**：内置签名表与 runtime 分发**完全对齐**（252⇔250 + 已解释的声明/常量差集），颜色/数学常量值正确，无「高/中」级问题。仅信息级观察（品种常量硬编码、线性查找、缺 reconciliation 单测）。可进入阶段 6（运行时内核）。

---

## 阶段 6 — 运行时内核（`pine-runtime` runtime/）

**目标**：审查 bar-by-bar VM 主循环、上下文、表达式求值、历史/实时模型。

**涉及文件**
- [runtime/historical.rs](crates/pine-runtime/src/runtime/historical.rs)
- [runtime/context.rs](crates/pine-runtime/src/runtime/context.rs)
- [runtime/expressions.rs](crates/pine-runtime/src/runtime/expressions.rs)
- [bar.rs](crates/pine-runtime/src/bar.rs)、[error.rs](crates/pine-runtime/src/error.rs)、
  [lib.rs](crates/pine-runtime/src/lib.rs)、[profile.rs](crates/pine-runtime/src/profile.rs)
- 参考 [docs/REALTIME_MODEL.md](docs/REALTIME_MODEL.md)、
  [docs/SERIES_MODEL.md](docs/SERIES_MODEL.md)

**审查清单**
- 序列存储 / state 存储 / `var` / `varip` 的提交时机与历史回看语义。
- 实时 forming-bar 回滚的正确性与状态隔离。
- 运行时限制（步数/内存/递归）是否存在，能否防 DoS（安全关注点）。
- 表达式求值的 `na` 传播、整数/浮点语义、错误冒泡是否带上下文。

**产出**：执行循环时序图 + 状态生命周期说明。

### 阶段 6 审查结论（2026-05-31）

**总体**：运行时是 bar-by-bar 解释执行的 HIR 树遍历器，主循环、序列保留、实时 forming 回滚、`var`/`varip` 持久化语义均结构清晰且具备多处防御。但本阶段实测发现一个**高危正确性缺陷**：整数算术在求值层统一坍缩为 `Float`，导致任何「以算术表达式计算的整数」（for 循环上下界、数组下标、数组尺寸等）在被 `as_i64()` 取整数时静默失败——这是迄今全程审查发现的最严重问题。

**执行循环时序图（`append_bar_with_context` 每根 bar）**

```
run_historical(program, bars)
  └─ SeriesRetention::from_program(program)   // 用 sema 计算的 series_history 定缓冲深度
  └─ for each bar:
       set_current_bar(idx)
       current_symbols.clear() / current_series.clear()   // 每 bar 重置临时态
       set_builtin_symbols(bar)         // 计算 ~22 个内置(open/high/.../bar_index)，线性扫描 symbols
       for stmt in program.statements:
           eval_stmt(stmt)              // 树遍历求值；Break/Continue 逃逸→RuntimeError(非 panic)
       strategy_broker.evaluate_pending_exits() + record_equity()
       finalize_series_outputs()
       commit_current_series()          // 把 current_series 写入 series_store，按 max_depth 裁剪
         └─ projected_series_values_after_commit() > MAX_SERIES_HISTORY_VALUES(1e6) → RuntimeError  // DoS 防护
       bars += 1
```

**状态生命周期说明**
- 每 bar 重置：`current_symbols`、`current_series`（仅本 bar 内有效，bar 末提交）。
- 跨 bar 持久：`series_store`（提交后按 `SeriesRetention::max_depth_for` 裁剪深度）、`var_store`（`var`/`varip` 槽位）、`array_store`、各指标滚动状态（rsi/macd/vwap/...）。
- 历史回看：`series_store.read(series_id, offset)` 读「当前 bar 之前」已提交值；`offset==0` 直读当前；`offset > buffer.len()` **静默返回 `Na`**（关键：与阶段 3 的历史深度耦合在此落地）。
- 实时模型（[realtime.rs](crates/pine-runtime/src/runtime/realtime.rs)）：`RealtimeRuntime{confirmed, forming}`。Forming/Confirmed 更新均**克隆 `confirmed`** 后重放，forming 永不写回 confirmed → 天然实现 forming-bar 回滚与状态隔离；`seed_intrabar_persistence_from` 仅把 `Varip` 槽位（及其数组）跨 forming→confirmed 续传，符合 `varip` 语义。

**良好实践（已验证）**
- DoS 防护齐全：`commit_current_series` 强制 `MAX_SERIES_HISTORY_VALUES=1_000_000`；`eval_while_loop` 受 `MAX_WHILE_ITERATIONS=100_000` 上限保护；`eval_for_loop` 用 `checked_add`/`checked_abs` 防溢出、`step==0` 报错；`set_builtin_symbols` 的时间换算用 `checked_add`/`checked_mul` → `RuntimeError` 而非 panic。
- `na` 传播完备：`eval_binary`/`eval_unary` 任一操作数为 `Na` 即返回 `Na`；除零/非有限 → `finite_float_or_na` → `Na`（不 panic）；成交量类指标（accdist/nvi/obv/pvi/pvt/vwap/wad/wvad）在除零/非有限时防御性返回 `Na`。
- 历史偏移校验稳健（[history.rs](crates/pine-runtime/src/runtime/history.rs)）：负偏移/超界/非整型分别报错或返回 `Na`，`usize::try_from` 防越界。
- 序列保留按 series 维度精确裁剪（[retention.rs](crates/pine-runtime/src/retention.rs)）：静态偏移用 `max_constant_offset`，动态偏移退化为 `max_bars_back` 或全量（受 1e6 全局上限兜底），内存有界。
- `var`/`varip` 持久化（[persistence.rs](crates/pine-runtime/src/runtime/persistence.rs)）：`eval_decl` 首次求值后缓存于 `var_store`，后续 bar 直接复用，符合一次初始化语义。

**发现的问题（仅记录，未修改）**
- [已关闭] [expressions.rs](crates/pine-runtime/src/runtime/expressions.rs) 早期审查记录的整数算术坍缩为 `Float` 问题在当前实现中已修复：`Int +/-/*/% Int` 通过 `numeric_add`/`numeric_sub`/`numeric_mul`/`numeric_mod` 保留 `PineValue::Int`（溢出时才回退到有限 float/`na`），`/` 仍按 Pine 数值除法走 float。回归证据包括 `runs_for_loop_with_computed_integer_bound`、`runs_array_get_with_computed_integer_index`、`runs_sma_with_computed_integer_length`、`runs_math_sum_with_computed_integer_length`，以及 conformance 中的 `computed_array_operands.pine`/`computed_lengths.pine`。
- [中] 运行时侧确认阶段 3 历史深度耦合：[context.rs](crates/pine-runtime/src/runtime/context.rs) `commit_current_series` 用 `series_retention.max_depth_for(series_id)`（源自 sema 的 `program.series_history`）裁剪缓冲；若 sema 的 `ta.*` 隐式回看表低估深度，缓冲被裁短，后续 `series_store.read(offset>len)` **静默返回 `Na`** 而非真实历史值——错误结果而非崩溃。与阶段 3 [中] 同根，建议统一为单一数据源并加端到端回归。
- [低] 运行时错误无源位置：[error.rs](crates/pine-runtime/src/error.rs) `RuntimeError` 仅含 `message: String`，无 span。除零/越界/「history offset must be an int」等错误无法回指源码，落实阶段 2 [低] 的 HIR-无-span 影响。
- [已关闭] 表达式求值递归无显式深度上限：当前 [expressions.rs](crates/pine-runtime/src/runtime/expressions.rs) 用 `MAX_RUNTIME_EVAL_DEPTH=512` 包裹 `eval_expr`，超限返回 `RuntimeError`，并由 `rejects_hir_expression_past_runtime_eval_depth` 覆盖。
- [信息] 普遍线性扫描 `program.symbols.iter().find()`：`set_builtin_symbols`（每 bar ~22 次）、`persistent_slot_for_symbol`、`current_builtin_f64`、`series_id_for_symbol` 等逐符号访问均 O(symbols)，可预构建索引映射。
- [信息] `HistoricalRuntime` 为巨型结构体，实时每次 Forming 更新整体 `clone()`（含全部 HashMap/Vec），高频 forming 更新下内存/性能开销显著；正确性无虞，仅性能观察。

**结论**：运行时主循环、保留、实时回滚、持久化语义结构正确且防御充分；早期记录的整数算术坍缩 P0 与 eval 深度无上限均已关闭并有回归覆盖。其余为阶段 3 历史耦合的运行时确认、无-span、线性扫描与 forming clone 等承接性观察。可进入阶段 7（数值/字符串/时间内置）。

---

## 阶段 7 — 运行时内置：数值/字符串/时间

**目标**：审查 `ta.*`、`math.*`、`str.*`、时间相关内置的数值正确性。

**涉及文件**
- ta：[builtins/ta.rs](crates/pine-runtime/src/builtins/ta.rs)、
  `ta/averages.rs`、`ta/statistics.rs`、`ta/flow.rs`、`ta/pivots.rs`
- [builtins/math.rs](crates/pine-runtime/src/builtins/math.rs)
- [builtins/strings.rs](crates/pine-runtime/src/builtins/strings.rs)
- [builtins/time.rs](crates/pine-runtime/src/builtins/time.rs)
- 算法库：[algorithms/](crates/pine-runtime/src/algorithms/mod.rs)（numeric/random/rolling_window）

**审查清单**
- 滚动窗口/累积算法在 `na`、窗口未满、长度为 0/1 时的行为。
- 与 Pine 语义的差异点（取整、种子、边界）——对照
  [docs/SEMANTIC_MODEL.md](docs/SEMANTIC_MODEL.md)。
- `random` 的确定性（种子来源）；时间解析是否依赖本地时区/系统时钟。
- 浮点累积误差、`ta` callsite state 的隔离与复位。

**产出**：数值内置语义差异清单 + 高风险算法标注。

### 阶段 7 审查结论（2026-05-31）

**总体**：`math.*`/`ta.*`/`str.*`/时间内置实现完整、`na`/空窗口/除零防御到位，且在确定性（随机种子不依赖系统时钟）、正则线性时间（无 ReDoS）等方面表现良好。阶段 6 早期记录的整数坍缩缺陷已关闭，`ta.*`/`math.*` 的计算长度路径由 `computed_lengths.pine` 与聚焦测试覆盖。

**数值内置语义差异清单**
- 整数保留（良好面）：`math.max/min/abs/floor/ceil/trunc/round(x)` 均保留 `Int`（`math.max/min` 用 `has_float` 跟踪）；二元 `Int +/-/*/% Int` 当前也保留 `Int`，与这些数学内置保持一致。
- 递归序列暖机种子：`ema_next`/`rma_next` 首值 `None => source`（以首个源值播种）；`ta.rsi` 首 bar 返 `Na` 后用 rma 种子。需对照 TradingView 暖机期（部分指标首个 RMA 用 SMA-of-length 播种）核实前 `length` 根是否有数值偏差。
- `ta.sma`/`math.sum` 等滑动窗口未满返 `Na`；`length<=0` 返 `Na`——边界处理正确。
- 时间：`year/month/.../timestamp/timeframe.*` 均基于 UTC、不读系统时钟；时间戳越界、`timestamp` 无效日期均报 `RuntimeError`；`timeframe_seconds` 各单位范围有界。

**高风险算法标注**
- 计算整数长度路径已由 `ta.sma(close, 1 + 1)`、`math.sum(close, 1 + 1)` 等回归覆盖；后续风险集中在递归指标暖机口径与状态隔离。
- 递归/反复指标（supertrend/sar/dmi/tsi/macd 等）依赖 `call_state` 按 `call_site_id` 隔离，状态随 `HistoricalRuntime` 克隆（实时 forming 每次 clone），逻辑正确但加重阶段 6 的 clone 开销观察。

**良好实践（已验证）**
- `math.random` 确定性：默认种子源自 `call_site_id`（`default_random_seed`）、显式 `seed` 走 `mix_random_seed`，**不读系统时钟**，可复现。
- `str.match`/`str.split` 用 Rust `regex` crate（线性时间、无回溯），即使正则来自脚本字符串也**无 ReDoS** 风险。
- `str.format`/`format_number` 健壮：不匹配 `{`/`}` 报错、分组/百分比/货币/精度格式化完备、非有限→`NaN`。
- `set_builtin_symbols`/时间换算用 `checked_*`、`u32::try_from`/`i32::try_from` 防越界→`RuntimeError` 而非 panic。

**发现的问题（仅记录，未修改）**
- [已关闭・承接阶段 6] 整数坍缩缺陷曾扩散至 `ta.*`/`math.*` 长度参数；当前 `numeric_add`/`numeric_sub`/`numeric_mul`/`numeric_mod` 保留 `Int` 后，`ta.sma(close, n * 1)`、`math.sum(close, 1 + 1)` 等计算长度路径已恢复，并由 `runs_sma_with_computed_integer_length`、`runs_math_sum_with_computed_integer_length` 与 `computed_lengths.pine` 覆盖。
- [中] 时区仅支持 UTC 等价物：[time.rs](crates/pine-runtime/src/builtins/time.rs) `is_supported_utc_timezone` 仅接受 `UTC/Etc\/UTC/GMT/Z/+0000/+00:00`，其余（如 `America\/New_York`、`Asia\/Shanghai`）使 `year/month/.../str.format_time` **报 `RuntimeError`** 而非按时区计算。与 Pine 支持 IANA/交易所时区不兼容；需对照 [LANGUAGE_SCOPE.md](docs/LANGUAGE_SCOPE.md) 确认是否为有意裁剪。
- [信息] 暖机期种子待对照：`ema_next`/`rma_next`/`ta.rsi` 以首个源值播种，可能与 TradingView 首 `length` 根（部分用 SMA 播种）有数值偏差 — 用 conformance fixtures 核实。
- [信息] `math.round_to_mintick` 用硬编码 `syminfo.mintick=0.01`（承接阶段 5）；`format_month`/`format.*` 常量格式与 Pine 需逐项对照（阶段 11/16）。

**结论**：数值/字符串/时间内置实现健壮、确定性与防御到位；整数坍缩在 `ta.*`/`math.*` 长度参数上的历史扩散已关闭并有回归覆盖。当前仍需处理 [中] 时区仅 UTC 的兼容缺口，并继续用 conformance 核实递归指标暖机口径。可进入阶段 8（数组/绘图/输出/变量）。

---

## 阶段 8 — 运行时内置：数组/绘图/输出/变量

**目标**：审查类型化数组、绘图对象、plot/hline/fill 等输出副作用、变量内置。

**涉及文件**
- [builtins/arrays.rs](crates/pine-runtime/src/builtins/arrays.rs)（1.4k，最大单文件）+ `arrays/calls.rs`
- `drawings/`：`labels.rs`、`lines.rs`、`boxes.rs`、`tables.rs`、
  [builtins/drawings.rs](crates/pine-runtime/src/builtins/drawings.rs)
- [builtins/outputs.rs](crates/pine-runtime/src/builtins/outputs.rs)
- [builtins/variables.rs](crates/pine-runtime/src/builtins/variables.rs)、
  [builtins/casts.rs](crates/pine-runtime/src/builtins/casts.rs)、
  [builtins/colors.rs](crates/pine-runtime/src/builtins/colors.rs)

**审查清单**
- 数组越界、负索引、容量增长、`na` 元素、跨 bar 持久化的正确性与内存上限。
- 绘图对象生命周期、ID 管理、上限裁剪（防内存暴涨）。
- 输出副作用收集顺序的确定性。
- 类型转换 `cast` 的丢失/溢出处理。

**产出**：集合/绘图边界条件清单 + 内存上限审查结论。

### 阶段 8 审查结论（2026-05-31）

**总体**：类型化数组、绘图对象、输出副作用、转换均具备完备的内存上限与确定性输出顺序。主要问题是几项**与 TradingView 的语义分歧**：绘图对象上限固定为 500 且溢出报错（而非淘汰最旧）、忽略脚本的 `max_*_count` 声明。数组越界语义已在后续 CR-023 slice 中对齐为运行时错误，合法负下标继续支持。

**集合/绘图边界条件清单**
- 数组下标：`normalize_array_index` 支持合法负下标（`len+index`）与越界检查；越界 `array.get`/`set`/`insert`/`remove` 已对齐为 `RuntimeError`。
- 内存上限：`MAX_ARRAY_ELEMENTS=100_000`（`new`/`from`/`push`/`insert`）、`MAX_LABELS/LINES/BOXES=500`、`MAX_TABLES`/`MAX_TABLE_CELLS`，超限均报 `RuntimeError`。
- ID 管理：`next_label_id`/`next_line_id`/`next_array_id` 等用 `checked_add` 防溢出。
- 转换：`int(x)` 截断 `Float→Int`（`value.trunc() as i64`）、`float`/`bool`/`string`/`color` 均防 `NaN`/非有限。
- 输出：`plot`/`plotshape`/... 按 `call_site_id` 键控、`self.bars` bar 对齐写入，顺序确定。

**内存上限审查结论**：数组与绘图均有硬上限防内存暴涨（DoS 防护到位）；但上限**固定且不按脚本声明可调**，且**溢出策略为报错而非淘汰**，与 Pine 不一致（见下）。

**良好实践（已验证）**
- 所有集合/绘图写入路径都有明确内存上限 + `checked_add` ID 防溢出，无静默无限增长。
- 合法负下标与越界由 `normalize_array_index` 统一处理，不 panic。
- 排序/二分查找对 `na`/非有限/空串作为“特殊值”统一排序，避免 `partial_cmp` panic。
- 输出按 `call_site_id` + bar 对齐，多次运行顺序确定（可复现）。

**发现的问题（仅记录，未修改）**
- [中] 绘图上限固定 + 溢出报错，且忽略 `max_*_count` 声明：[labels.rs](crates/pine-runtime/src/builtins/drawings/labels.rs)/[lines.rs](crates/pine-runtime/src/builtins/drawings/lines.rs)/[boxes.rs](crates/pine-runtime/src/builtins/drawings/boxes.rs) 在 `len() >= MAX_*` 时返 `RuntimeError`。全仓未引用 `max_labels_count`/`max_lines_count`/`max_boxes_count`（grep 无命中）。而 TradingView 默认保留最近 N（默认 50、可声明至 500）并**静默淘汰最旧**。后果：逐 bar 画图超 500 根的脚本在本引擎**报错中止**，而 TradingView 正常运行。建议：读取声明的 `max_*_count` 并改为环形淘汰最旧对象。
- [中][已关闭] 数组越界语义分歧：[arrays.rs](crates/pine-runtime/src/builtins/arrays.rs) 曾在 `array.get` 越界时返 `Na`，`array.set`/`insert`/`remove` 越界时静默 no-op 或返 `Na`。CR-023 已改为对现有数组的正向/负向越界下标抛 `RuntimeError`；合法负下标保留，因为官方 Pine 也支持。
- [信息·已关闭] 数组下标/`array.new_*` 尺寸参数的算术整数路径已由 `computed_array_operands.pine` 与 `runs_array_get_with_computed_integer_index` 覆盖，阶段 6/7 早期记录的 `array.get(a, k-1)→na` 不再复现。
- [信息] 绘图样式/位置默认值字符串硬编码（`label.style_label_down`/`yloc.price`/`shape.xcross` 等），与 Pine 常量需逐项对照（阶段 11/16）。

**结论**：数组/绘图/输出实现内存有界、顺序确定、边界不 panic；阶段 8 原记录的数组越界语义分歧已由 CR-023 关闭，仍存在 [中] 绘图上限固定/溢出报错/忽略声明。阶段 6/7 整数坍缩在数组下标的历史延伸已关闭并有回归覆盖。可进入阶段 9（策略与撮合）。

---

## 阶段 9 — 策略与撮合（`pine-runtime/strategy`）

**目标**：审查 broker 状态机、entry/close/exit、bracket/trailing 触发与成交。

**涉及文件**
- [strategy/broker/mod.rs](crates/pine-runtime/src/strategy/broker/mod.rs)
- [strategy/broker/exits.rs](crates/pine-runtime/src/strategy/broker/exits.rs)
- broker `fills`、`accounting`、`tests`
- [builtins/strategy.rs](crates/pine-runtime/src/builtins/strategy.rs)
- 参考 PHASE_L/M/R/S/U 各审计文档

**审查清单**
- pending-exit 身份、触发转换、both-hit（stop/loss 优先）选择逻辑。
- 权益/持仓/成交计数的会计一致性；浮点累计。
- 不支持组合（同侧 bracket、3+ 触发、做空、反手、金字塔）是否被稳定拒绝。
- 部分数量退出（Phase U）边界与 `schemaVersion: 3` 输出契约稳定性。

**产出**：broker 状态机图 + 触发优先级/拒绝矩阵核对。

### 阶段 9 审查结论（2026-05-31）

**总体**：broker 是一个**文档化的 long-only 简化撮合器**（PHASE_L/N_AUDIT、SEMANTIC_MODEL）。状态机干净、不 panic、会计一致、退出触发优先级清晰。主要问题是与 TradingView 的几项**撮合口径/缺省语义分歧**，以及“运行时静默无操作”需与 sema 拒绝边界对齐。

**broker 状态机图**

```
  flat ──strategy.entry(long, qty>0)──▶ long(position_size=qty, avg_price=close)
   ▲                                         │
   │                                         ├─ strategy.exit ⇒ 注册单一 pending_exit
   │                                         │     （stop/limit/bracket/trailing）
   │                                         │     下一根 bar 用 high/low 评估触发
   │                                         │
   └── strategy.close / pending_exit 成交 ◀──┘
        （全量或部分；部分退出后回到 long）
```

- 单一持仓、单一 `pending_exit`；`evaluate_pending_exits` 每根 bar 最多触发一次，`last_update_bar_index >= bar_index` 守卫保证入场当根不立即退出。
- both-hit 选择：Bracket 中 `downside`（stop/loss）优先于 `upside`（limit/profit），与 TradingView 保守口径一致。

**触发优先级 / 拒绝矩阵核对**
- entry：`qty` 非有限或 ≤0 → `E_STRATEGY_QTY` 诊断并拒单；`price` 非有限 → `E_STRATEGY_PRICE`；已有持仓（`position_size>0`）再入场静默忽略（无 pyramiding）。
- close：仅当 `entry_id` 匹配且有持仓时平仓；价格非有限 → 诊断。
- exit：仅接受“单一 trailing 激活 + offset”或固定 stop/limit/bracket 组合，其余组合在 [builtins/strategy.rs](crates/pine-runtime/src/builtins/strategy.rs) 静默返回 Void（依赖 sema 已拒绝不支持组合）。
- 方向：仅 `strategy.long`；非 long 在 `eval_strategy_entry` 静默返回 Void（sema 已拒绝 `strategy.short`，见 fixture `unsupported_strategy_entry_short.pine`）。

**良好实践（已验证）**
- 全部下单/成交路径有 finite/正数校验并产生结构化诊断码，绝不 panic。
- 会计清晰：`realized_profit + open_profit`、`normalize_zero` 防 `-0.0`、`closed/open_trade_count` 有界（`i64::try_from`）。
- 退出在**下一根 bar**用 high/low 评估，避免入场当根立即触发；trailing 激活/步进单调推进。
- 文档化范围限制（long-only/无做空/无金字塔/无手续费滑点）在 sema 层一致拒绝不支持形式，形成“sema 拒绝 + 运行时静默兜底”的双层防御。

**发现的问题（仅记录，未修改）**
- [中] 缺省下单量分歧：当 `strategy()` 未声明 `default_qty_value` 且 `strategy.entry` 未给 `qty` 时，[pine-ir lib.rs](crates/pine-ir/src/lib.rs) `default_entry_qty()` 返 `None` → [strategy.rs](crates/pine-runtime/src/builtins/strategy.rs) `unwrap_or(f64::NAN)` → `entry_long` 以 `E_STRATEGY_QTY` 拒单、不开仓。而 TradingView `default_qty_value` 缺省为 1（1 contract），裸 `strategy.entry("L", strategy.long)` 会正常开 1 手。建议：缺省回退为 1.0 对齐 TradingView。
- [中] 撮合时序简化：entry 以**当前 bar 收盘价** `bar.close` **立即成交**，exit 用**下一根** bar 的 high/low；TradingView 默认市价单在下一根 bar **开盘**成交（`process_orders_on_close=false`），且支持 intrabar tick 撮合。未建模 `process_orders_on_close`/`calc_on_order_fills`/`calc_on_every_tick`。属文档化简化，但回测口径与 TradingView 有系统性偏差，阶段 16 应在兼容性文档中显式声明。
- [信息·文档化范围] 无手续费/滑点：[accounting.rs](crates/pine-runtime/src/strategy/broker/accounting.rs) `profit = (exit - entry) * qty`、`cash ± qty*price`，未扣 commission/slippage；`strategy()` 签名（[core.rs](crates/pine-builtins/src/namespaces/core.rs)）仅识别 title/shorttitle/overlay/max_bars_back/initial_capital/default_qty_type/default_qty_value，`commission_*`/`slippage`/`pyramiding`/`margin_*` 由 sema 报未知参数（与 BUILTIN_SIGNATURES 对照，阶段 16）。
- [信息] “sema 拒绝 + 运行时静默 Void”双层防御：阶段 16 需逐项核对，确保不存在“通过 sema 但运行时静默吞掉”的方向/组合路径（当前看 short/非法组合均被 sema 拦截，运行时兜底冗余但安全）。
- [信息] 退出每根 bar 仅触发一次、基于 bar high/low（非 intrabar tick），trailing 步进按 bar 粒度；与 TradingView intrabar 撮合存在精度偏差（文档化简化）。

**结论**：long-only 简化 broker 在其声明范围内会计自洽、状态机健壮、触发优先级与拒绝矩阵一致，但存在 [中] 缺省下单量（缺省应为 1）与 [中] 撮合时序（当根收盘成交 vs 次根开盘）两项与 TradingView 的口径分歧，其余为文档化范围限制。可进入阶段 10（请求数据边界）。

---

## 阶段 10 — 请求数据边界（`pine-runtime/request`）

**目标**：审查 host-neutral 请求契约、`request.security` 对齐与缓存。

**涉及文件**
- [request/provider.rs](crates/pine-runtime/src/request/provider.rs)
- [builtins/requests.rs](crates/pine-runtime/src/builtins/requests.rs)
- 参考 [docs/PHASE_F_AUDIT.md](docs/PHASE_F_AUDIT.md)、ARCHITECTURE 请求章节

**审查清单**
- 高/同时间框对齐（`lookahead_off`/`gaps_off`）规则、forward-fill、首确认前 `na`。
- 缓存键（callsite/symbol/timeframe/HIR 表达式身份）是否充分且隔离。
- requested-context runtime 与 chart runtime 的状态隔离。
- core 不 fetch 网络/文件红线；provider 错误形态。

**产出**：请求对齐规则核对 + 缓存键充分性结论。

### 阶段 10 审查结论（2026-05-31）

**总体**：`request.security` 的 host-neutral 契约设计良好：**无前视对齐**、**请求上下文状态隔离**、provider 为 host 供给的可信边界（core 不拉网络/文件）。主要问题是时间框架限制过严与 scope 覆盖面较窄，以及缓存键用 Debug 字符串的脆弱点。

**请求对齐规则核对**
- 同上下文快路径：`symbol == chart_symbol && requested_tf == chart_tf` 时直接在当前上下文 `eval_expr(args[2])`，无需 provider。
- 同时间框外部 symbol（`requested.seconds == chart.seconds`）：按 `time == current_time` 精确匹配，缺失 → `Na`（不前填）。
- 高时间框（HTF）：`take_while(|(time,_)| time + requested_duration <= chart_close).last()` — 仅采“在当前 chart bar **收盘前已收盘**”的请求 bar，**杠绝未来泄露**，并 forward-fill 最后一个已确认值；首确认前为 `Na`。测试 `aligns_higher_timeframe_without_future_values` / `higher_timeframe_gap_fills_last_confirmed_value` 覆盖。
- 时间均为毫秒，`saturating_add/mul` 防溢出 panic。

**缓存键充分性结论**
- `RequestCacheKey = call_site_id + symbol + timeframe + format!("{:?}", expression.kind)`；call_site_id 已唯一区分调用点，同一调用点表达式固定，表达式判别量偏冗余；但 Debug 字符串作键有脆弱点（见下）。隔离性充分：不同调用点/symbol/tf 不会互相污染。

**良好实践（已验证）**
- **无前视对齐**：HTF 仅取已收盘请求 bar，从机制上避免 repaint/未来函数泄露。
- **请求上下文隔离**：`evaluate_requested_values` 以独立 `HistoricalRuntime::with_request_environment` 在请求上下文逐 bar 求值，ta.* 状态与图表状态隔离（测试 `isolates_provider_ta_state_from_chart_state` 覆盖）。
- **host-neutral provider 契约**：`RequestDataProvider` trait + `InMemory`/`No` 实现；core 不 fetch 网络/文件（`NoRequestDataProvider` 默认返 `MissingData`）；插入时 `validate_requested_bars` 校验已排序且无重复时间，`DuplicateKey` 防重复流。
- 确定性：缓存键含 call_site_id，输出按 provider 提供顺序求值；同上下文快路径避免不必要的 provider 依赖。

**发现的问题（仅记录，未修改）**
- [中] 时间框架限制过严：[requests.rs](crates/pine-runtime/src/builtins/requests.rs) `validate_provider_timeframe` 要求 requested 不低于 chart 且为 chart 的**整数倍**（`% != 0` 报错）。TradingView 支持任意 HTF 组合（如 3m chart 请求 5m，`300 % 180 != 0`）与 LTF 请求（repaint 语义）；此处均报 RuntimeError。属兼容缺口，阶段 16 需在兼容性文档明确。
- [中·scope] 仅支持 `request.security` 的 **3 参数形式**（`args.len() != 3` 直接报错）：`gaps`/`lookahead` 参数不支持（无法表达 `barmerge.lookahead_on`），且无 `request.security_lower_tf`/`request.financial`/`request.dividends`/`request.economic` 等。需与 BUILTIN_SIGNATURES 核对是否在 sema 层一致拒绝。
- [低] 缓存键用 `format!("{:?}", expression.kind)`（HirExpr 的 Debug 字符串）作判别量：每次未命中时分配字符串、依赖 Debug 表示稳定性、不同表达式 Debug 相同则碰撞。建议去掉表达式判别量（call_site_id 已足以区分调用点）或改用结构化身份。
- [低] 嵌套 `request.security` 无深度/环检测：requested 表达式内若含 `request.security`，会以相同 environment 递归 evaluate，无循环防护（依赖 sema 是否限制）。
- [信息] `requested_bars` 数量无运行时上限（provider 供给，受信边界）；首次访问即对整条流求值并缓存（O(N)），内存随流长增长。

**结论**：请求边界在无前视与状态隔离上实现正确、host-neutral 红线清晰、不 panic，但存在 [中] 时间框架整数倍限制过严、[中·scope] 覆盖面窄（仅 3 参 request.security），以及 [低] 缓存键 Debug 字符串脆弱。可进入阶段 11（输出归一化与 JSON）。

---

## 阶段 11 — 输出归一化与 JSON（`pine-runtime/output`）

**目标**：审查 host-neutral 输出模型、对齐、收集、JSON 序列化、schema 版本。

**涉及文件**
- [output/model.rs](crates/pine-runtime/src/output/model.rs)、
  [output/collect.rs](crates/pine-runtime/src/output/collect.rs)、
  [output/align.rs](crates/pine-runtime/src/output/align.rs)
- [output/json.rs](crates/pine-runtime/src/output/json.rs)、
  `output/drawings.rs`、`output/alerts.rs`、`output/strategy.rs`、`output/mod.rs`

**审查清单**
- `schemaVersion` 与各 host 绑定、快照的一致性。
- 序列对齐、`na` 表示、浮点格式化的确定性（跨平台稳定）。
- JSON 字段顺序/数值精度是否影响快照稳定性。

**产出**：输出 schema 字段清单 + 序列化确定性结论。

### 阶段 11 审查结论（2026-05-31）

**总体**：输出为**手写 JSON 拼接**（非 serde），但字符串转义 RFC 合规、字段顺序固定、序列化确定。早期记录的**非有限浮点未在序列化边界归一化**问题已关闭；当前主要剩余项是手写拼接的长期维护成本。

**输出 schema 字段清单**
- 顶层（[json.rs](crates/pine-runtime/src/output/json.rs) `public_runtime_result_json`）：`schemaVersion`(=3, [model.rs](crates/pine-runtime/src/output/model.rs))、`plots`/`plotChars`/`plotShapes`/`plotArrows`/`plotBars`/`plotCandles`、`bgColors`/`barColors`、`hlines`/`fills`、`labels`/`lines`/`boxes`/`tables`、`alerts`、可选 `strategy`、`diagnostics`。
- `profiled` 变体：复用基础 JSON，`pop('}')` 后追加 `profile`（几十个内存/容量计数字段，固定顺序）。
- 值编码（`value_json`）：Int/Float/Bool/Color → 数值；String → 转义字符串；Plot/HLine/Label/Line/Box/Table → id 数值；UserType/Tuple → 数组；Array/Na/Void → `null`。

**序列化确定性结论**
- 字段顺序全部硬编码；各序列按 Vec 顺序输出。
- plot/series 由 [collect.rs](crates/pine-runtime/src/output/collect.rs) `push_series_value` 按“**首次发射顺序**”（call_site_id）追加，bar 对齐（前缀 `Na` 填充 + `finalize_series_values` 尾部补 `Na`），同输入多次运行**字节级一致**。
- f64 经 `Display` 输出全十进制（无科学计数、本地无关、最短 round-trip），跨平台稳定。

**良好实践（已验证）**
- **字符串转义 RFC 合规**：`json_escape` 处理 `" \ \n \r \t \b \f` 及所有 `<0x20` 控制字符（`\u00xx`）；value_json 对 `String` 一律走 json_escape — label text/tooltip、plotchar/plotshape text、alert message、strategy id/direction 均安全转义，无 JSON 注入/截断风险。
- Na/Void/Array → `null`（合法 JSON）；`f64_json` 将非有限 float 统一写为 `null`，覆盖 plot 值、`value_json` 与 strategy 数值字段；color 为 u32 数值。
- profiled 变体结构稳定，schemaVersion 常量化。

**发现的问题（仅记录，未修改）**
- [已关闭] 非有限浮点未在序列化边界归一化：当前 [json.rs](crates/pine-runtime/src/output/json.rs) 通过 `f64_json` 将 `NaN`/`±Inf` 统一输出为 `null`，覆盖 `value_json`、plots、strategy orders/trades/position/equity/alerts，并由 `runtime_json_serializes_non_finite_plot_floats_as_null` 与 strategy 非有限序列化单测守护。
- [信息] 顶层 `"diagnostics"` 硬编码为 `[]`：当前运行时诊断仅来自 broker（经 `strategy.diagnostics` 输出），顶层恒空；若未来新增非策略运行时诊断会被静默丢弃。
- [信息] 手写 JSON 拼接（非 serde）：维护成本高、新增字符串字段需记得走 json_escape（现有已正确覆盖）；profiled 变体用 `output.pop()` 依赖末尾为 `'}'` 的隐式契约。建议长期考虑 serde_json 或集中式 writer。
- [信息] 整数值 Float（如 15.0）经 Display 输出为 `"15"`（承接阶段 6 整数坍缩，JSON 层无 `.0`）；极端值产生超长数字串但仍为合法 JSON。

**结论**：输出序列化在转义安全与确定性上表现良好、跨平台稳定；非有限浮点非法 JSON 的历史缺陷已关闭。当前剩余的是手写拼接的维护性信息项。可进入阶段 12（CLI）。

---

## 阶段 12 — CLI（`pine-cli`）

**目标**：审查命令行入口、参数解析、CSV 读取、analyze/run/matrix/conformance。

**涉及文件**
- [main.rs](crates/pine-cli/src/main.rs)、`commands/`（run/analyze/matrix/fmt_ast/mod）
- [bars_csv.rs](crates/pine-cli/src/bars_csv.rs)、[json.rs](crates/pine-cli/src/json.rs)、
  [library_sources.rs](crates/pine-cli/src/library_sources.rs)、
  [conformance.rs](crates/pine-cli/src/conformance.rs)

**审查清单**
- CSV 解析对畸形输入的健壮性（列缺失、非数值、超大文件）。
- `--request-bars`、库源参数的解析与错误信息。
- 退出码、stderr/stdout 分离、诊断输出格式。

**产出**：CLI 输入健壮性清单。

### 阶段 12 审查结论（2026-05-31）

**总体**：CLI 为手写位置/标志参数解析，错误信息清晰、`run` 的 stdout/stderr 分离得当、单测覆盖充分。早期记录的 **CSV 数值解析接受 `NaN`/`inf`** 问题已关闭；本阶段仍保留 `analyze` 退出码等 CLI 行为项供后续单独复核。

**CLI 输入健壮性清单**
- 子命令：`analyze` / `fmt-ast` / `run` / `matrix`（[main.rs](crates/pine-cli/src/main.rs)）；未知命令/标志→ `usage()` 作为 Err → 退出 1。
- CSV（[bars_csv.rs](crates/pine-cli/src/bars_csv.rs)）：逐行 split(',')，要求恰好 6 列（time,open,high,low,close,volume），列数不符/非数值均报错并附行号；首行含 "close" 视为表头跳过。
- `run` 参数：`--bars`（必填）、`--profile`、`--request-bars SYMBOL:TIMEFRAME=csv`（`rsplit_once(':')` 支持交所前缀符号）、`--library-source KEY=path`。
- 退出码：`main` 仅 SUCCESS/FAILURE；`run` 诊断走 stderr、结果 JSON 走 stdout。

**良好实践（已验证）**
- `run` 的 **stdout/stderr 分离**：JSON 结果→stdout，诊断（`code:severity:line:col: message`）→stderr；分析有错时返回 Err（退出 1）。
- CSV 错误信息带行号与列名；library-source/request-bars 重复键检测；schemaVersion 经 matrix 表面化。
- json_escape 与运行时一致（RFC 合规）；广泛单测覆盖解析/边界。

**发现的问题（仅记录，未修改）**
- [中] `analyze` 无条件返回 `Ok(())`（[analyze.rs](crates/pine-cli/src/commands/analyze.rs)）：即使诊断含 error 严重度也退出 0，且诊断走 **stdout**（`println!`）— 与 `run` 的 stderr+Err 不一致；CI/脚本无法通过退出码检测分析错误。建议：有 error 诊断时返回非零退出码并将诊断写 stderr。
- [已关闭] CSV 数值解析接受非有限值：当前 [bars_csv.rs](crates/pine-cli/src/bars_csv.rs) 的 `parse_f64_column` 要求 OHLCV `is_finite()`，`NaN`/`inf`/`infinity` 均报错，并由 `rejects_non_finite_ohlcv_values` 覆盖。
- [低] 主 `--bars` 未在 CLI 层校验时间单调递增/无重复（request-bars 经 provider 有 validate_requested_bars，但主 bars 直进 run_historical）；`fs::read_to_string` 一次性读入整个文件，无大小上限（超大 CSV 可 OOM）。
- [信息] json_escape 在 [pine-cli/json.rs](crates/pine-cli/src/json.rs) 与 pine-runtime output 中重复实现（逻辑一致）— 可考虑提取共享。

**结论**：CLI 边界处理总体稳健、错误信息友好；CSV 非有限 OHLCV 注入的历史问题已关闭。`analyze` 退出码等 CLI 行为项留待后续单独复核。可进入阶段 13（Python 绑定）。

---

## 阶段 13 — Python 绑定（`pine-python`）

**目标**：审查 PyO3 接口、参数转换、错误映射、与 runtime 结果的映射。

**涉及文件**
- [crates/pine-python/src/lib.rs](crates/pine-python/src/lib.rs)
- [python/tests/test_bindings.py](python/tests/test_bindings.py)

**审查清单**
- `request_bars` dict、库源的解析与校验；GIL/异常映射。
- 返回结构与 Rust 输出模型是否同构、是否丢字段。
- 重建 wheel 的流程（见用户记忆：maturin build + force-reinstall）。

**产出**：Python API 表面核对 + 错误映射清单。

### 阶段 13 审查结论（2026-06-01）

**总体**：`pine-python`（764 行，仅 lib.rs）是一层薄 PyO3 包装：`compile_script`/`analyze_script`/`run_script` + `Program.run`，把 Python dict/sequence 转为 `Bar`/`AnalysisInput`/`RequestEnvironment`，再把 `Analysis`/`RuntimeResult` 逐字段镜像为 Python dict/list。无业务逻辑、无 I/O，与 CLI/WASM 共享同一 sema/runtime 入口。结构清晰、错误统一映射为 `PyValueError`、输出字段与 JSON 模型同构。未发现「高」级问题；早期记录的非有限浮点跨 host 表示分歧已关闭，剩余为承接性/范围观察。

**Python API 表面核对（产出 1）**
- 顶层函数：`compile_script(source, library_sources=None) -> Program`、`analyze_script(source, library_sources=None) -> dict`、`run_script(source, bars, request_bars=None, library_sources=None) -> dict`；类 `Program.run(bars, request_bars=None) -> dict`。模块名 `pine_compat`。
- 输入转换：`parse_bar` 接受 **dict（按 time/open/high/low/close/volume 命名键）或 6 元 sequence**；`bars` 经 `try_iter` 逐项解析。`request_bars` 为 `{ "SYMBOL:TIMEFRAME": bars }` dict（`rsplit_once(':')` 拆分，支持交所前缀），`library_sources` 为 `{ key: text }` dict——与 CLI/WASM 键规则一致。
- 输出同构：`run` 结果字段与 [output/json.rs](crates/pine-runtime/src/output/json.rs) 的 `public_runtime_result_json` **完全对齐**（schemaVersion=3、plots/plotChars/plotShapes/plotArrows/plotBars/plotCandles、bgColors/barColors、hlines/fills、labels/lines/boxes/tables、alerts、可选 strategy、diagnostics）；strategy 子结构 orders/trades/position/equity/diagnostics 字段名与 JSON 一致（pytest 已逐字段锁定）。
- analysis 结果字段（schemaVersion=2、languageVersion、diagnostics、compatibility{supported/unsupported}、executable）与 WASM [analysis_json.rs](crates/pine-wasm/src/analysis_json.rs) 同集（返回 dict，键顺序与 WASM JSON 略有不同但对消费者无影响）。

**错误映射清单（产出 2）**
- 所有失败统一为 `PyValueError`：库源非 dict/值非字符串、request 键非 `SYMBOL:TIMEFRAME`/空 symbol、timeframe 解析失败、bar 缺字段/非 6 元 sequence、`with_library_sources`/`from_streams` 校验失败、runtime 错误（`err.message`）、「analysis did not produce executable HIR」。
- 分析诊断：`compile_script`/`run_script` 失败时把**全部诊断**经 `format_diagnostics` 拼成单一换行串作为异常 message（丢失结构化 code/severity/span）；`analyze_script` 则返回结构化 `diagnostics` 列表。
- 与 CLI/WASM 对账：错误形态（compile 失败即抛拼接串、run 失败抛 `runtime failed`/`err.message`）在三个 host 间一致。

**良好实践（已验证）**
- 输出字段与 JSON 模型严格同构，pytest（~60 用例）覆盖 indicator/strategy/exit/bracket/trailing/partial-qty/alert/request/绘图全部输出族，且断言精确字典值——回归保护充分。
- 字符串字段（label text/tooltip、alert message、strategy id/direction、plotchar/shape text）经 Python 原生对象承载，无需手写转义即天然安全。
- 库源/请求键的校验、`ChartContext::default()`（symbol=`NASDAQ:AAPL`）、`rsplit_once(':')` 交所前缀拆分与 CLI [run.rs](crates/pine-cli/src/commands/run.rs) **逐项一致**，跨 host 行为可预期。
- `request_bars` 缺失时回退 `RequestEnvironment::default()`（`NoRequestDataProvider`），与 CLI/WASM 一致；缺数据报 `missing request data ...`（测试覆盖）。

**发现的问题（仅记录，未修改）**
- [已关闭・跨 host 分歧] 非有限浮点表示在 Python 与 CLI/WASM 间不一致：当前 [outputs.rs](crates/pine-python/src/outputs.rs) 的 `append_value`、`set_finite_f64`、`set_option_finite_f64` 将非有限 float 统一转为 `None`，与 JSON 边界的 `null` 收敛；`test_run_script_converts_non_finite_plot_values_to_none` 覆盖 plot 输出。
- [低] compile/run 失败丢失结构化诊断：`compile_script`/`run_script` 把诊断拼成单一字符串抛出，调用方要拿到结构化 code/span 必须**另行调用 `analyze_script`（二次分析）**。与 WASM `compile*` 行为一致（非 Python 独有），但 Python 已有结构化 `analyze_script` 可绕过。建议评估让异常携带结构化诊断（如自定义异常类型）。— [lib.rs](crates/pine-python/src/lib.rs)
- [低] `compile_script`/`run_script` 对**任意严重度**诊断都拒绝（`if !analysis.diagnostics.is_empty()`），而 `analyze_script` 的 `executable` 取 `hir.is_some()`。若未来 sema 发射 warning/info 级诊断且仍产出 HIR，会出现 `analyze_script(executable=True)` 但 `compile_script` 抛错的自相矛盾。当前 sema 不发非 error 诊断（承接阶段 1）故不可达；三 host（CLI/WASM/Python）行为一致。建议改为按 `has_errors()` 门控以与 `executable` 对齐。— [lib.rs](crates/pine-python/src/lib.rs)
- [信息] Python 无 profile API：CLI 有 `--profile` → `public_runtime_profiled_result_json`，而 `Program.run`/`run_script` 无 profile 参数，Python host 无法获取 `RuntimeProfile`（WASM 亦无）。属能力范围差异，相对 CLI 的缺口。— [lib.rs](crates/pine-python/src/lib.rs)
- [信息] 运行期全程持有 GIL：`run` 未用 `Python::allow_threads` 包裹 `run_historical_with_request_environment`，长脚本/长 bar 流会阻塞其他 Python 线程；正确性无虞，仅并发性能观察。— [lib.rs](crates/pine-python/src/lib.rs)
- [信息] `value_to_py` 分配开销：每个标量值都先建一个单元素 `PyList`、append 后取 `get_item(0)` 再 unbind——是绕开「无独立 to-object」的实现技巧，但对长序列产生 O(n) 次额外 list 分配。建议改用直接构造 `PyObject` 的辅助。— [lib.rs](crates/pine-python/src/lib.rs)
- [信息・承接阶段 12] bar 输入有限性已补：Python `float('nan')`/`float('inf')` 会被拒绝（`test_run_script_rejects_non_finite_bar_values` 覆盖）。主 bars 时间单调/去重仍未在 Python host 层校验（request 流经 `from_streams` 有校验）；dict 路径静默忽略多余键、sequence 路径严格要求 6 元——两路径宽严不一。— [lib.rs](crates/pine-python/src/lib.rs)
- [信息・已关闭] 深递归崩溃面经 Python 暴露：解析/语义/内联/求值的主深度上限已补齐，深嵌套脚本应转为结构化诊断或 runtime error，而非 Python 进程级 SIGABRT。Python 仍可考虑更丰富的结构化异常，但该 DoS 主线已关闭。

**结论**：Python 绑定是忠实、字段同构、错误统一的薄封装，pytest 回归充分，与 CLI/WASM 行为基本一致，无「高/中(独有)」级缺陷。非有限浮点跨 host 表示、bar 非有限输入与深递归崩溃面的历史问题已关闭；其余为承接性观察（无 profile、GIL、value_to_py 分配、bar 时间校验）。可进入阶段 14（WASM 绑定）。

---

## 阶段 14 — WASM 绑定（`pine-wasm`）

**目标**：审查浏览器/host WASM 接口、JSON 请求桥、与核心结果一致性。

**涉及文件**
- [crates/pine-wasm/src/lib.rs](crates/pine-wasm/src/lib.rs)
- [analysis_json.rs](crates/pine-wasm/src/analysis_json.rs)、
  [request_bars.rs](crates/pine-wasm/src/request_bars.rs)、
  [library_sources.rs](crates/pine-wasm/src/library_sources.rs)
- [crates/pine-wasm/src/tests/mod.rs](crates/pine-wasm/src/tests/mod.rs)

**审查清单**
- `SYMBOL:TIMEFRAME`（最后一个冒号分割）键解析、交易所前缀符号。
- JS↔Rust JSON 边界的错误处理与确定性；`runCsvWithRequestBars` 等 API。
- 与 CLI/Python 输出的跨 host 一致性（Phase T 平价）。

**产出**：WASM API 表面核对 + 跨 host 一致性结论。

### 阶段 14 审查结论（2026-06-01）

**总体**：`pine-wasm`（lib.rs + analysis_json/request_bars/library_sources 共 ~1.2k 行含测试）是 `wasm-bindgen 0.2.121` 薄绑定：8 个顶层函数 + `Program.runCsv*`，输入/输出全部以**字符串**穿越 JS↔Rust 边界（源码、CSV、JSON 入参；结果为 JSON 字符串）。run 路径直接复用 runtime 的 `public_runtime_result_json`，与 CLI **字节一致**；确定性处理（库源/请求键用 `BTreeMap` 排序）比 Python 更显式。未发现「高」级问题。早期记录的非有限 JSON/CSV 边界问题已关闭，剩余主要是 duplicate 键静默坍缩与代码重复等。

**WASM API 表面核对（产出 1）**
- 编译/分析：`compileScript`/`compileScriptWithLibraries` → `Program`（失败抛 `JsValue` 字符串）；`analyzeScript`/`analyzeScriptWithLibraries` → JSON 字符串（**不抛**，错误经 `analysis_error_json` 内嵌 `E_HOST_INPUT` 诊断）。
- 运行：顶层 `runScriptCsv`/`...WithRequestBars`/`...WithLibraries`/`...WithLibrariesAndRequestBars`，类方法 `Program.runCsv`/`runCsvWithRequestBars`，均返回 JSON 字符串或抛 `JsValue`。
- 入参编码：bars 为 CSV 文本（[lib.rs](crates/pine-wasm/src/lib.rs) `parse_bars_csv`）；`library_sources` 与 `request_bars` 为 JSON 对象字符串。请求键 `rsplit_once(':')`（交所前缀），timeframe 经 `RequestTimeframe::parse`，与 CLI/Python 键规则一致。
- 输出：run 结果由 `public_runtime_result_json` 生成（schemaVersion=3，字段集与 CLI 完全相同）；analysis 由 [analysis_json.rs](crates/pine-wasm/src/analysis_json.rs) 手写拼接（schemaVersion=2、languageVersion、executable、diagnostics、compatibility）。

**跨 host 一致性结论（产出 2）**
- **run 输出与 CLI 字节一致**：二者都调 `public_runtime_result_json`，无独立序列化器，天然 parity（测试 `run_csv_with_request_bars_matches_direct_request_api` 还验证「直接 API == 编译后 API == 重复运行」三者全等，确定性达标）。
- CSV 解析：WASM [run.rs](crates/pine-wasm/src/run.rs) 的 `parse_bars_csv` 与 CLI [bars_csv.rs](crates/pine-cli/src/bars_csv.rs) 行为一致（跳空行、首行含 "close" 视表头、严格 6 列、拒绝非有限 OHLCV）——行为一致但仍有复制粘贴重复。
- `ChartContext::default()`（symbol=`NASDAQ:AAPL`）与 CLI/Python 一致；空 `request_bars` → `NoRequestDataProvider`，与 CLI 空 specs 一致。
- analysis JSON 与 Python 的 `analysis_to_py` 是**两套并行序列化器**（手写 JSON vs 构造 dict），字段集相同但需手工保持同步。

**良好实践（已验证）**
- 确定性显式化：`library_sources` 经 `BTreeMap<String,String>`、`request_bars` 经 `deterministic_entries`（`BTreeMap`）按键排序后再喂 provider，迭代序不依赖 host JSON 书写顺序。
- 字符串转义 RFC 合规：analysis 路径 `json_escape` 覆盖 `"`、`\`、控制字符（测试 `json_escape_escapes_control_characters` 锁定）。
- 输入校验完备：请求键缺 timeframe/空 symbol/非法 timeframe、bar 缺字段/非对象/非数值、库源/请求非 JSON 对象均有明确错误信息（大量单测覆盖）；run 输出有 golden snapshot（`analysis_outputs_match_golden_snapshots`）。
- 边界错误不 panic：所有 host 输入错误走 `Result<_, String>` → `JsValue`，分析错误内嵌 `E_HOST_INPUT`（已登记于 [DIAGNOSTIC_CODES.md](docs/DIAGNOSTIC_CODES.md)）。

**发现的问题（仅记录，未修改）**
- [已关闭・承接阶段 11，WASM 边界放大] 非有限浮点使整段结果在 JS 端不可解析：WASM run 输出共享 `public_runtime_result_json`，已随 `f64_json` 修复为非有限 float→`null`；测试覆盖输出中不含 `NaN`。
- [已关闭・承接阶段 12] CSV 数值解析接受非有限值：当前 [run.rs](crates/pine-wasm/src/run.rs) 的 `parse_f64_column` 拒绝 `NaN`/`inf`/`infinity`，并由 `run_script_csv_rejects_non_finite_ohlcv_values` 覆盖。
- [低] duplicate JSON 键静默坍缩，与 CLI 的去重语义分歧：`request_environment_from_json` 经 `serde_json` 解析对象时，重复的 `SYMBOL:TIMEFRAME` 键被 serde 静默坍缩为最后一个（测试 `request_bars_documents_duplicate_json_key_collapse` 文档化此行为），**不触发** provider 的 `DuplicateKey`；而 CLI 多个 `--request-bars` 同键会被 `from_streams` 报「duplicate request data ...」。`library_sources` 经 `BTreeMap` 同样坍缩重复键。跨 host 行为不一致（WASM 后者胜、CLI 报错）。建议统一为显式拒绝或文档明示。— [request_bars.rs](crates/pine-wasm/src/request_bars.rs)、[library_sources.rs](crates/pine-wasm/src/library_sources.rs)
- [信息] CSV 解析 + json_escape 代码三处重复：`parse_bars_csv` 在 [pine-wasm/lib.rs](crates/pine-wasm/src/lib.rs) 与 [pine-cli/bars_csv.rs](crates/pine-cli/src/bars_csv.rs) 完全复制；`json_escape` 在 runtime output、[pine-cli/json.rs](crates/pine-cli/src/json.rs)、[pine-wasm/analysis_json.rs](crates/pine-wasm/src/analysis_json.rs) 三处各一份（承接阶段 12[信息]）。漂移风险，建议提取共享 crate/模块。
- [信息] analysis 报告双序列化器：WASM 手写 `analysis_json` 与 Python `analysis_to_py` 各实现一遍，字段集需手工同步（与阶段 11 手写 JSON 维护性观察同类）；run 输出则因共用 `public_runtime_result_json` 无此问题。建议 analysis 也收敛到单一 writer。— [analysis_json.rs](crates/pine-wasm/src/analysis_json.rs)
- [信息] 无 profile API：WASM 未暴露 `public_runtime_profiled_result_json`（与 Python 同缺、CLI 有 `--profile`）。
- [信息] 无 panic hook：深递归栈溢出主线已由 parser/sema/lowering/runtime 深度预算关闭；但 WASM 仍未依赖 `console_error_panic_hook`，若未来出现意外 panic，host JS 仍只得较弱的 trap 信息。建议 release 仍考虑设置 panic hook 改善可观测性。— [Cargo.toml](crates/pine-wasm/Cargo.toml)
- [信息・共享范围限制] chart 上下文不可配置：WASM/Python/CLI 三 host 均硬编码 `ChartContext::default()`（`NASDAQ:AAPL` + 默认 tf），host 无法设置图表 symbol/timeframe；`request.security` 同 symbol 快路径恒以默认 symbol 匹配。属共享 scope 限制，留待阶段 16。— [chart.rs](crates/pine-runtime/src/request/chart.rs)

**结论**：WASM 绑定输入校验完备、确定性显式（BTreeMap 排序）、run 输出与 CLI 字节一致、转义合规，质量良好，无「高/中(独有)」级缺陷。非有限浮点在 WASM 字符串边界被放大的历史问题已随序列化/CSV 边界修复关闭；剩余为 duplicate 键坍缩分歧与代码重复/双序列化器等工程项。可进入阶段 15（测试/快照/一致性）。

---

## 阶段 15 — 测试 / 快照 / 一致性

**目标**：评估测试体系的覆盖与质量（单测、快照、fixture、conformance）。

**涉及内容**
- `crates/*/src/tests/`、`crates/*/tests/`
- [tests/fixtures/](tests/fixtures/)、[tests/snapshots/](tests/snapshots/)
- [tests/fixtures/conformance.tsv](tests/fixtures/conformance.tsv) 及 CONFORMANCE 文档

**审查清单**
- 失败路径/边界/不支持特性是否有显式测试。
- 快照是否对非确定性敏感（浮点格式、字段顺序）。
- conformance 标注（partial/unsupported）与实现现状是否一致。
- 是否存在仅测 happy-path 的内置；缺口登记。

**产出**：测试覆盖热力图（按内置/特性）+ 缺口清单。

### 阶段 15 审查结论（2026-06-01）

**总体**：测试体系规模可观（~831 个 Rust `#[test]` + 38 个 pytest；304 个 `.pine` fixture + CSV 共 317 文件；72 个 golden 快照；conformance.tsv 353 个特性=225 supported/115 partial/13 unsupported）。**最强项是确定性保证**（全部 runtime fixture 的「增量==全量」parity）与**密集的失败路径/不支持诊断覆盖**。主要缺口是**正确性维度**：大量数值指标 fixture 仅被 smoke+parity 执行而**无 golden 数值断言**，conformance 状态准确性**无机器校验**。阶段 6/7 的高危整数坍缩缺陷已补计算循环上界、数组下标/尺寸、`ta.*`/`math.*` 计算长度回归，不再是当前测试缺口。

**测试覆盖热力图（产出 1，按层/机制）**
- 单测分布：runtime 414、sema 306、wasm 39、syntax 34、cli 33、builtins 5、ir 0、python 0（pytest 38 独立）。数值正确性主要靠 `src/tests/builtins_*.rs` 等**内联小脚本 + 手算期望值**。
- fixture 驱动机制：
  1. [sema/tests/fixtures.rs](crates/pine-sema/tests/fixtures.rs)：显式路径，**海量 unsupported/supported 诊断断言**（exit 变体、varip、UDT、side-effect、import、递归等失败路径密集）。
  2. [runtime/tests/incremental.rs](crates/pine-runtime/tests/incremental.rs)：`read_dir` 遍历**全部** `tests/fixtures/runtime/*.pine` → 断言「无诊断 + 可 lower + **增量 append == 全量重算**」。覆盖广但**只验确定性/增量 parity，不验数值正确**（无期望值）。
  3. [runtime/tests/realtime.rs](crates/pine-runtime/tests/realtime.rs)：16 个 realtime fixture 逐个显式测试 forming/var/varip/alert/array/drawing **回滚语义并断言具体值**。
  4. [runtime/tests/profile_fixtures.rs](crates/pine-runtime/tests/profile_fixtures.rs)：内存/容量增长上限守护。
  5. golden 快照：[pine-cli/main.rs](crates/pine-cli/src/main.rs) 与 [pine-wasm](crates/pine-wasm/src/tests/mod.rs) 对策略/绘图/分析/matrix 输出做**字节级**比对（`UPDATE_SNAPSHOTS` 再生）。
  6. [conformance.rs](crates/pine-cli/src/conformance.rs)：严格 TSV 结构校验（4 列、特性唯一、status 合法、notes/fixtures 非空、status→fixture 目录规则、request 特性须引 request fixture）+ 存在性检查测试。

**缺口清单（产出 2）**
- [中] conformance 状态准确性无机器校验：[conformance.rs](crates/pine-cli/src/conformance.rs) 的 `validate_fixture_paths` 仅检查 fixture 文件**存在**，无任何测试验证 (a) fixture 真的使用了所声明的 feature，(b) status（supported/partial/unsupported）与实现现状一致。115 个 **partial** 项尤其没有「partial 边界」断言。实现回归后矩阵仍会声称 supported（只要文件在）。建议加 feature↔fixture 语义链接校验或 partial 边界回归。
- [中] runtime 指标 fixture 仅 smoke+parity、无数值 golden：incremental.rs 对所有 runtime fixture 断言「无诊断 + 增量==全量」，但**不校验输出数值**。而 golden 快照只覆盖策略/绘图等少数 fixture——大量 `ta.*`/`math.*` 指标 fixture（alma/ao/cci/cmo/dmi/sar/supertrend/tsi/vwap…）**无 golden 数值快照**，仅被 smoke+parity 执行。因此承接阶段 7「暖机种子可能偏离 TradingView」的数值偏差**无法被测试体系捕获**。建议为高风险递归指标补 golden 值快照 / conformance 数值基准。
- [低][已关闭] 整数坍缩高危缺陷已补回归守护：阶段 6/7 实测的 `for i = 0 to n-1`、`array.get(a, k-1)`、`ta.sma(close, n*1)` 静默失效路径，当前由 `runs_for_loop_with_computed_integer_bound`、`runs_array_get_with_computed_integer_index`、`runs_sma_with_computed_integer_length`、`runs_math_sum_with_computed_integer_length` 以及 `computed_array_operands.pine`/`computed_lengths.pine` 覆盖。后续要求是保留这些回归，不再把该项列为活跃缺口。
- [低][已关闭] 语法层 fixture 回归近空白：当前 [syntax/tests/fixtures.rs](crates/pine-syntax/tests/fixtures.rs) 已覆盖 `deep_expression_limit.pine`、`utf8_diagnostic_column.pine`、`parse_error_recovery.pine`、`malformed_number_recovery.pine`、`soft_keyword_export_identifier.pine` 等边界，不再只有 `phase1_basic`。
- [信息] 8 个死 fixture（引用于零处）：`tests/fixtures/sema/unsupported_strategy_exit_{stop,stop_limit,stop_profit,limit_loss,profit_loss,profit_qty,qty_stop,trailing_partial_quantity}.pine`——这些组合现多已 supported（存在对应 `supported_strategy_exit_*` 并被测），旧 unsupported 版残留为死文件。建议清理或纳入测试。
- [信息][已关闭] 非有限/不可解析输出无 fixture：阶段 11/12/14 的非有限 Float→非法 JSON / 不可 `JSON.parse` 历史缺口已补 runtime JSON、CLI CSV、WASM CSV、Python 输出/输入回归；后续要求是保留这些跨 host 守护。
- [信息] 跨平台浮点格式无显式快照矩阵：f64 `Display`（阶段11）的跨平台字节稳定性靠假设，无跨架构 CI 快照断言（属阶段16 确定性主线，可在此登记）。

**良好实践（已验证）**
- **增量==全量 parity** 覆盖全部 runtime fixture：是对阶段 6「实时 forming 回滚 / 增量 append」语义的强确定性保证，任何破坏增量一致性的改动都会被捕获。
- 失败路径覆盖密集：sema 对 unsupported 特性（strategy exit 全变体、varip、UDT、import、side-effect、递归、动态/负历史偏移）有大量精确诊断码/消息断言。
- realtime 回滚逐项值断言、profile 内存上限守护、字节级 golden 快照 + 再生纪律，**零孤儿快照**（72 个全部被引用）。
- conformance.tsv 有强结构校验 + 存在性检查；matrix 输出有 golden 快照锁定。
- fixture 引用完整性良好：conformance.tsv 引用的 287 个 fixture **全部存在**（实测无缺失）。

**结论**：测试体系在**确定性、失败路径、增量一致性、结构校验**维度扎实且自动化程度高，但**正确性维度**存在系统性缺口：数值指标 fixture 多为 smoke+parity 而无 golden 值、conformance 状态准确性靠人工维护无机器校验、阶段 6/7 高危整数坍缩缺陷无回归能捕获、语法层 fixture 近空白，另有 8 个死 fixture。建议优先（随阶段 16）补：算术长度/下标回归 fixture、高风险指标 golden 值、conformance 语义链接校验。可进入阶段 16（横切关注点）。

---

## 阶段 16 — 横切关注点

**目标**：跨 crate 复核诊断、确定性、安全、合规四条主线。

**审查清单**
- **诊断**：所有错误带 span；诊断码全集 vs [DIAGNOSTIC_CODES.md](docs/DIAGNOSTIC_CODES.md)。
- **确定性**：全链路无时钟/随机/文件/网络/HashMap 迭代序依赖。
- **安全**：不可信输入（源码/CSV/host JSON）的资源上限、panic 面、整数/内存边界；
  对照 OWASP 思路审计 DoS 与崩溃面。
- **合规**：clean-room 边界、命名与品牌（[COMPATIBILITY_AND_LEGAL.md](docs/COMPATIBILITY_AND_LEGAL.md)）。

**产出**：横切风险汇总 + 优先修复建议排序。

### 阶段 16 审查结论（2026-06-01）

**总体**：跨 crate 复核四条主线。**确定性与合规两条线健康**（实测红线守住、clean-room 政策完备且被遵守）；**安全线**中历史「无界递归栈溢出」主线已由 parser/sema/lowering/runtime 深度预算关闭，运行时执行路径基本无 panic 面、DoS 上限齐备；**诊断线**存在系统性文档缺口（22 个码未登记）与「错误无 span」承接问题。本阶段收口，给出全局风险汇总与优先修复排序。

**诊断主线（实测对账）**
- **22 个已发射诊断码未登记** [DIAGNOSTIC_CODES.md](docs/DIAGNOSTIC_CODES.md)（比阶段 3 记录的 11 个更全，含跨 crate 全量）：`E_LEX_INDENT`、`E_PARSE_BLOCK/FOR/FUNCTION`、`E_LOOP_CONTROL/RANGE_TYPE/RETURN/STEP`、`E_SCRIPT_DECL_DUPLICATE/LOCATION`、`E_STRATEGY_MODE/PRICE/QTY`、`E_STRATEGY_EXIT_ENTRY/MINTICK/PRICE/QTY/TICKS`（后 5 个为 broker **运行时**诊断）、`E_UNKNOWN_FUNCTION/METHOD/COLOR`、`E_METHOD_RECEIVER_TYPE`。诊断码是公开 DX 契约，建议全部补登。`E_HOST_INPUT` 已登记且确在 WASM 发射（手写 JSON 转义，非缺口）。
- 错误无 span（承接阶段 2/6）：HIR/`RuntimeError` 无源位置，除零/越界/历史偏移等运行时错误无法回指源码。
- 顶层 `diagnostics` 恒 `[]`（承接阶段 11）：非策略运行时诊断目前无出口。

**确定性主线（实测通过）**
- 红线守住：core 五 crate 全量 grep **无** `Utc::now/Local::now/SystemTime::now/Instant::now/thread_rng/rand::/std::fs/File::open/reqwest/TcpStream/env::var`；`chrono` 关 clock 特性（阶段 0）。随机种子源自 `call_site_id`（阶段 7）。
- HashMap 用于按 id 键控的存储（series/var/array/symbol/缓存），**读取按显式键**而非迭代入输出；输出顺序由 `call_site_id` + Vec 决定（阶段 11），确定。
- 增量==全量 parity 测试覆盖全部 runtime fixture（阶段 15），强保证。
- **残留风险**：f64 `Display` 跨平台字节稳定性靠假设，无跨架构 CI 快照矩阵（阶段 15[信息]）。

**安全主线（实测）**
- 运行时执行路径（处理不可信 bars/HIR）**几乎无 panic 面**：runtime+builtins 非测试代码仅 1 处 `unreachable!`（[arrays.rs](crates/pine-runtime/src/builtins/arrays.rs) min/max 内部枚举守卫，不可由输入触发），无可达 unwrap。143 个 `unwrap()`/26 个 `panic!` 集中在 sema/syntax 编译期，且字面量解析已优雅降级（阶段 1）。
- DoS 上限齐备：`MAX_WHILE_ITERATIONS`、`MAX_SERIES_HISTORY_VALUES=1e6`、`MAX_ARRAY_ELEMENTS=1e5`、绘图 `MAX_*=500`，溢出用 `checked_*`（阶段 6/8）。
- **已关闭：无界递归栈溢出主线**（阶段 1/3/4/6 一致）：解析、语义表达式、UDF/方法调用链、lowering inline/HIR 预算、runtime eval 均已有显式上限，深嵌套脚本应转为 `E_PARSE_EXPR_DEPTH`/`E_SEMA_EXPR_DEPTH`/`E_FUNCTION_CALL_DEPTH`/`E_LOWERING_BUDGET` 或 runtime error，而非跨 host 崩溃。
- 不可信输入注入面（承接）：CSV/bars 接受 `NaN`/`inf` 与非有限 Float 产出非法 JSON / WASM 整段不可 `JSON.parse` 的历史问题已关闭；剩余输入面主要是 CSV 无大小上限可 OOM（阶段 12）。

**合规主线（实测通过）**
- [COMPATIBILITY_AND_LEGAL.md](docs/COMPATIBILITY_AND_LEGAL.md) 定义了完整 clean-room 政策（首选/避免措辞、非关联声明、实现规则、fixture 政策），README 含非关联声明。
- 代码中唯一的 "Pine Script" 提及是 [expressions.rs](crates/pine-runtime/src/runtime/expressions.rs) 一处解释 `==` 语义的注释（陈述公开文档行为，符合 clean-room）；用户可见串无品牌/错误文案复制。
- 轻微：包元数据 `repository=""` 空且 crate 元数据未含非关联声明（承接阶段 0[低]）。

**横切风险汇总 + 优先修复排序（产出）**

| 优先级 | 问题 | 严重度 | 来源阶段 | 建议 |
| --- | --- | --- | --- | --- |
| **P0** | 整数算术坍缩为 Float，`for i=0 to n-1`/计算下标/`ta.*` 计算长度静默失效 | 高（已关闭） | 6/7 | 当前实现已通过 `numeric_add`/`numeric_sub`/`numeric_mul`/`numeric_mod` 保留 `Int`；继续保留计算上界/下标/长度回归 |
| **P1-a** | 无界递归 → 栈溢出，跨所有 host 崩溃 DoS | 中(安全，已关闭) | 1/3/4/6 | 当前 parser/sema/lowering/runtime 均有深度/预算上限；继续保留深嵌套回归 |
| **P1-b** | 非有限 Float 未在序列化/输入边界归一（非法 JSON、WASM 不可解析） | 中（已关闭） | 11/12/14 | 当前已通过 `f64_json` 非有限→`null`、CLI/WASM/Python bar 边界拒绝非有限 OHLCV，并保留跨 host 回归 |
| **P1-c** | `ta.*` 隐式历史回看表与 runtime 强耦合，漂移静默低估缓冲区 | 中（已关闭/guarded） | 3/6 | 已引入 `pine-builtins` 共享 history metadata、sema 消费、runtime reviewed-list 对账、fixed-offset runtime debug assertion helper 与 `ta.sar`/`ta.dmi`/`ta.supertrend`/`ta.kc`/`ta.kcw`/`ta.mfi`/`ta.tsi`/`ta.cross*` retention+数值基准 |
| **P2** | 与 TradingView 口径分歧：撮合时序、绘图上限/淘汰策略、时区仅 UTC、request 时间框整数倍+仅 3 参；缺省下单量与数组越界已关闭 | 中 | 7/8/9/10 | 对齐 TradingView 或在兼容性文档显式声明口径 |
| **P3** | 工程/文档：22 诊断码未登记、运行时错误无 span、`analyze` 退出码、conformance 无机器校验 + 数值 golden 缺口、parse_bars_csv/json_escape 重复、8 死 fixture、文档漂移、包元数据 | 低/信息 | 0/2/6/11/12/14/15/16 | 批量清理，多数可独立小改 |

**结论**：经 16 阶段系统走读，`pine-compat-runtime` 整体工程质量高——架构红线清晰、确定性与 clean-room 合规可靠、失败路径与增量一致性测试扎实、运行时执行路径防御充分。历史 P0 整数算术坍缩、P1-a 无界递归崩溃面与 P1-b 非有限边界均已关闭并有回归覆盖；当前优先级前列转为 `ta.*` 历史耦合（正确性）这一「中」级横切问题。其余为与 TradingView 的兼容口径分歧（多为文档化范围限制）与工程/文档清理项。建议按已关闭项回归守护、剩余 P1→P3 的顺序继续推进。**全部 16 阶段审查完成。**

---

## 发现记录（滚动追加）

> 每个阶段完成后，在此追加结论。建议格式：
> `[阶段N][严重度 高/中/低] 文件:行 — 问题描述 — 建议/后续动作`

- [阶段0][低] README.md:81 — 「Current Package Layout」列出不存在的 `tests/conformance/` 目录（实际为 tests/fixtures/conformance.tsv） — 修正文档布局描述。
- [阶段0][低] Cargo.toml:17 — `repository = ""` 包元数据为空 — 发布前补全仓库地址。
- [阶段0][信息] scripts/check_structure.py — 仅排除 `/src/tests/`，导致 strategy/broker/tests.rs(1245行) 被当作生产实现计入阈值 — 扩展测试文件排除规则。
- [阶段0][信息] Cargo.toml — 无 `[workspace.dependencies]` 集中管理外部依赖 — 未来共享依赖时引入以防版本漂移。
- [阶段1][中][已关闭] crates/pine-syntax/src/parser.rs — parse_expr/parse_prefix 递归无深度上限曾使深嵌套表达式栈溢出 SIGABRT — 当前 `MAX_EXPR_DEPTH=256` 超限报 `E_PARSE_EXPR_DEPTH`，并有单测/fixture 守护。
- [阶段1][低] crates/pine-syntax/src/source.rs — line_col 列号按字节而非字符计算，多字节行诊断列号偏大 — 按字符计算列号。
- [阶段1][低] crates/pine-syntax/src/parser_phase_j.rs — 软关键字 library/export/type/method 无 lookahead 守卫，同名标识符误解析 — 加上下文守卫。
- [阶段1][低] crates/pine-syntax/src/lexer.rs — 数值字面量不支持科学计数法(1e6)/下划线 — 按 LANGUAGE_SCOPE 确认是否需补齐。
- [阶段2][低] crates/pine-ir/src/lib.rs — HIR 不携带 Span，运行时错误无法回指源码位置 — 评估是否为 HirExpr 补充 span（阶段6/16）。
- [阶段3][中][已关闭] crates/pine-sema/src/history.rs / crates/pine-builtins/src/history.rs / crates/pine-runtime/src/{runtime/context.rs,tests/{builtin_registry,builtins_ta_flow,builtins_ta_averages}}.rs — ta.* 隐式历史需求已迁到共享 metadata、由 sema 消费，并与 reviewed runtime 隐式历史读取清单对账；fixed-offset runtime 隐式读取经 `read_declared_series_history` 做 debug/test 声明深度断言；`ta.sar`、`ta.dmi`、`ta.supertrend`、`ta.kc`、`ta.kcw`、`ta.mfi`、`ta.tsi` 与 `ta.cross*` 已有绑定 HIR retention 的端到端数值基准。
- [阶段3][低] crates/pine-sema/src/analyzer/expressions.rs — 平行类型推断路径（analyze_expr vs type_of_expr_with_params）需手工同步，后者无独立递归守卫，靠「有错跳过 lowering」间接兜底 — 合并或加显式守卫。
- [阶段3][低][已关闭] crates/pine-sema/src/analyzer/{expressions,functions,methods}.rs — 语义层表达式/UDF/方法调用链曾无深度上限 — 当前 `MAX_SEMA_EXPR_DEPTH`/`MAX_FUNCTION_CALL_DEPTH` 转为诊断并有回归守护。
- [阶段3][低] crates/pine-sema/src/analyzer/statements.rs — Reassign 以 RHS 限定符覆盖符号类型，可把 var/Series 变量收窄为 Const/Simple，条件重赋值不强制 Series — 与 runtime 行为核对限定符语义。
- [阶段3][低] docs/DIAGNOSTIC_CODES.md — 11 个 sema 诊断码未登记（E_STRATEGY_MODE / E_SCRIPT_DECL_LOCATION / E_SCRIPT_DECL_DUPLICATE / E_LOOP_CONTROL / E_LOOP_RANGE_TYPE / E_LOOP_STEP / E_LOOP_RETURN / E_UNKNOWN_FUNCTION / E_UNKNOWN_METHOD / E_UNKNOWN_COLOR / E_METHOD_RECEIVER_TYPE） — 补登文档（阶段16 统一核对）。
- [阶段6][高][已关闭] crates/pine-runtime/src/runtime/expressions.rs — 整数算术坍缩为 Float（旧 `numeric_binary→finite_float_or_na` 路径），曾致 `for i = 0 to n-1`、`array.get(a, k-1)` 等以算术计算的整数静默失效 — 当前 `Int +/-/*/% Int` 保留 Int，并由计算循环上界/数组下标/长度回归守护。
- [阶段6][中][已关闭] crates/pine-runtime/src/runtime/context.rs — 运行时侧确认阶段3历史深度耦合：series_retention.max_depth_for 源自 sema series_history，低估则 series_store.read(offset>len) 静默返回 Na（错误结果非崩溃） — 阶段3已把 sema 需求统一到 `pine-builtins` metadata，补 reviewed runtime/metadata 对账，为 fixed-offset runtime 隐式读取补 `read_declared_series_history` debug/test 断言，并把 `ta.sar`/`ta.dmi`/`ta.supertrend`/`ta.kc`/`ta.kcw`/`ta.mfi`/`ta.tsi`/`ta.cross*` 数值基准绑定到 HIR retention。
- [阶段6][低] crates/pine-runtime/src/error.rs — RuntimeError 仅含 message，无 span，运行时错误无法回指源码（承接阶段2[低]） — 评估为运行时错误补充 span（阶段16）。
- [阶段6][信息] crates/pine-runtime/src/runtime/expressions.rs — eval_expr 递归无深度上限已由 `MAX_RUNTIME_EVAL_DEPTH` 关闭；`program.symbols.iter().find()` 普遍线性扫描与 `HistoricalRuntime` 巨型结构体实时每 Forming 更新整体 clone 仍为性能观察 — 预构建符号索引 + 评估 forming 增量更新。
- [阶段7][高][已关闭] crates/pine-runtime/src/builtins/ta/averages.rs 等 — 整数坍缩缺陷曾扩散至 ta.*/math.* 长度参数（算术计算长度取 0 → 返回 Na） — 已随阶段6根因关闭，由 `computed_lengths.pine`、`runs_sma_with_computed_integer_length`、`runs_math_sum_with_computed_integer_length` 守护。
- [阶段7][中] crates/pine-runtime/src/builtins/time.rs — 时区仅支持 UTC 等价物（is_supported_utc_timezone），非 UTC 时区使 time 组件/str.format_time 报 RuntimeError，与 Pine IANA/交易所时区不兼容 — 对照 LANGUAGE_SCOPE 确认是否有意裁剪。
- [阶段7][信息] crates/pine-runtime/src/builtins/ta/averages.rs — ema/rma/rsi 暖机期以首个源值播种，可能与 TradingView 首 length 根有偏差；math.* 函数与二元 `Int +/-/*/% Int` 当前均保留 Int — 用 conformance fixtures 继续核实暖机口径。
- [阶段8][中] crates/pine-runtime/src/builtins/drawings/{labels,lines,boxes}.rs — 绘图上限固定 500 且溢出报 RuntimeError（非淘汰最旧），且全仓未引用 max_labels_count/max_lines_count/max_boxes_count 声明 — 读取声明上限并改为环形淘汰最旧，对齐 TradingView。
- [阶段8][中][已关闭] crates/pine-runtime/src/builtins/arrays.rs — array.get 曾越界返 Na，array.set/insert/remove 曾越界 no-op 或返 Na；CR-023 已改为现有数组正向/负向越界均抛 RuntimeError，合法负下标继续支持。
- [阶段8][信息][已关闭] crates/pine-runtime/src/builtins/arrays.rs — 数组下标/array.new_* 尺寸参数的算术整数路径已由 `computed_array_operands.pine` 覆盖；绘图样式默认值字符串硬编码待对照（阶段11/16）。
- [阶段9][中] crates/pine-ir/src/lib.rs + crates/pine-runtime/src/builtins/strategy.rs — 未声明 default_qty_value 且 entry 无 qty 时 default_entry_qty()=None→unwrap_or(NaN)→拒单不开仓，而 TradingView 缺省 default_qty_value=1 会开 1 手 — 缺省回退为 1.0 对齐 TradingView。
- [阶段9][中] crates/pine-runtime/src/builtins/strategy.rs + strategy/broker — 撮合时序简化：entry 当根收盘价立即成交、exit 次根 high/low，而 TradingView 默认次根开盘成交且支持 intrabar；未建模 process_orders_on_close/calc_on_order_fills — 阶段16 在兼容性文档显式声明口径差异。
- [阶段9][信息] crates/pine-runtime/src/strategy/broker/accounting.rs + crates/pine-builtins/src/namespaces/core.rs — long-only、无手续费/滑点/金字塔/做空均为文档化范围限制；strategy() 签名仅识别 7 个参数，commission_*/slippage/pyramiding/margin_* 由 sema 报未知参数 — 阶段16 与 BUILTIN_SIGNATURES 核对并确认无“sema 通过但运行时静默吞掉”的路径。
- [阶段10][中] crates/pine-runtime/src/builtins/requests.rs — validate_provider_timeframe 要求 requested 为 chart 的整数倍且不低于 chart，否则 RuntimeError；TradingView 支持任意 HTF（如 3m→05m）与 LTF 请求 — 兼容缺口，阶段16 在兼容性文档明确。
- [阶段10][中·scope] crates/pine-runtime/src/builtins/requests.rs — 仅支持 request.security 3 参形式，gaps/lookahead 不支持（无法表达 barmerge.lookahead_on），无 request.security_lower_tf/financial/dividends/economic — 与 BUILTIN_SIGNATURES 核对 sema 是否一致拒绝。
- [阶段10][低] crates/pine-runtime/src/request/provider.rs (RequestCacheKey) — 缓存键用 format!("{:?}", expression.kind) 作判别量：每次分配字符串、依赖 Debug 稳定性、可能碰撞 — 去掉表达式判别量（call_site_id 已足）或改用结构化身份；嵌套 request.security 无深度/环检测。
- [阶段11][中][已关闭] crates/pine-runtime/src/output/json.rs (value_json/f64_json) — 非有限浮点未在序列化边界归一化曾导致 NaN/inf 非法 JSON — 当前非有限 Float 统一输出 null，覆盖 value_json、plots 与 strategy 数值字段。
- [阶段11][信息] crates/pine-runtime/src/output/json.rs — 顶层 "diagnostics" 硬编码为 []（运行时诊断仅经 strategy.diagnostics 输出，未来非策略诊断会被丢弃）；手写 JSON 拼接非 serde，新增字符串字段需走 json_escape，profiled 变体依赖末尾 '}' 隐式契约 — 长期考虑 serde_json/集中 writer。
- [阶段12][中] crates/pine-cli/src/commands/analyze.rs — analyze 无条件 Ok(())：诊断含 error 也退出 0且诊断走 stdout（与 run 的 stderr+Err 不一致），CI 无法依退出码检错 — 有 error 诊断时返回非零退出码并写 stderr。
- [阶段12][中][已关闭] crates/pine-cli/src/bars_csv.rs (parse_f64_column) — f64::from_str 曾接受 "NaN"/"inf"/"infinity"，非有限 bar 数据可入运行时 — 当前 CSV 边界拒绝非有限 OHLCV。
- [阶段12][低/信息] crates/pine-cli/src/commands/run.rs + bars_csv.rs — 主 --bars 未在 CLI 层校验时间单调/去重（request-bars 有校验）；fs::read_to_string 一次性读入无大小上限（超大 CSV OOM）；json_escape 在 cli 与 runtime 重复实现。
- [阶段3][信息] crates/pine-sema/src/analyzer/unsupported.rs — 不支持原因串夹带内部阶段标签（Phase J/1/L）且粒度不一 — 统一面向用户措辞。
- [阶段4][低][已关闭] crates/pine-sema/src/lowering/mod.rs — UDF/方法/导入函数按调用点内联曾无深度/规模上限 — 当前 `LoweringLimits` 约束 inline 深度、HIR 节点数、临时符号数，超限报 `E_LOWERING_BUDGET`。
- [阶段4][信息] crates/pine-sema/src/analysis.rs — root 源被解析两次（validate_modules 与 analyze_input 各一次） — 复用一份 AST 以减开销。
- [阶段4][信息] crates/pine-sema/src/modules_rewrite.rs — 常量按名整体替换，库体内同名局部符号可被意外替换 — 按作用域限定替换范围（当前子集下概率低）。
- [阶段5][信息] crates/pine-builtins/src/constants/floats.rs — syminfo.mintick=0.01 / pointvalue=1.0 硬编码常量，跨品种数值偏差 — 运行时阶段核实是否有覆盖路径。
- [阶段5][信息] crates/pine-builtins/src/registry.rs — 签名↔runtime 一致靠人工维护，无编译期强约束 — 加 reconciliation 单测遍历 PHASE_1_BUILTINS 校验 runtime 分发。
- [阶段5][信息] 签名总数 252 与 runtime 250 callee 分发已实测对齐，差集均为声明/输入类与字符串常量（无真缺口/孤儿实现）。
- [阶段13][中][已关闭] crates/pine-python/src/outputs.rs (append_value/set_finite_f64) — 非有限浮点跨 host 分歧曾使 Python 输出 nan/inf、JSON 输出非法 token — 当前非有限 Float 统一转 None，与 JSON null 收敛。
- [阶段13][低] crates/pine-python/src/lib.rs — compile_script/run_script 失败把诊断拼成单一字符串抛 PyValueError，丢失结构化 code/severity/span，调用方需另行 analyze_script 二次分析 — 评估让异常携带结构化诊断。
- [阶段13][低] crates/pine-python/src/lib.rs — compile/run 对任意严重度诊断都拒绝（!diagnostics.is_empty()），与 analyze_script 的 executable=hir.is_some() 不对齐；未来 warning/info 诊断会致 executable=True 但 compile 抛错（当前 sema 不发非 error 诊断故不可达，三 host 一致） — 改为按 has_errors() 门控。
- [阶段13][信息] crates/pine-python/src/lib.rs — Python 无 profile API（CLI 有 --profile→profiled JSON，WASM 亦无）；run 全程持 GIL 未 allow_threads；value_to_py 每标量分配单元素 PyList 取 item0（长序列 O(n) 额外分配） — 评估补 profile 入口 + allow_threads + 直接构造对象。
- [阶段13][信息] crates/pine-python/src/lib.rs — bar 输入已拒绝非有限 OHLCV；主 bars 仍不校验 time 单调，dict 路径静默忽略多余键、sequence 路径严格 6 元宽严不一；深递归栈溢出主线已由 core 深度预算关闭 — 剩余输入形态差异可后续治理。
- [阶段14][中][已关闭] crates/pine-wasm/src/run.rs + output/json.rs — 非有限浮点在 WASM 字符串边界曾放大为浏览器 JSON.parse 失败 — 当前 run 输出非有限→null，CSV 非有限 OHLCV 被拒绝，并有 WASM 回归。
- [阶段14][中][已关闭] crates/pine-wasm/src/run.rs (parse_bars_csv/parse_f64_column) — 与 CLI 同源，f64 parse 曾接受 NaN/inf/infinity 注入运行时 — 当前 CSV 边界拒绝非有限。
- [阶段14][低] crates/pine-wasm/src/request_bars.rs + library_sources.rs — serde_json 解析对象时重复 SYMBOL:TIMEFRAME / 库源键被静默坍缩为最后一个（测试已文档化），不触发 provider DuplicateKey；而 CLI 多 --request-bars 同键会报错 — 跨 host 去重语义不一致，统一为显式拒绝或文档明示。
- [阶段14][信息] crates/pine-wasm/src/lib.rs + pine-cli/src/bars_csv.rs + 三处 json_escape — parse_bars_csv 在 wasm/cli 完全复制、json_escape 在 runtime/cli/wasm 三份（承接阶段12[信息]）；analysis 报告 WASM 手写 JSON 与 Python dict 双序列化器需手工同步（run 输出共用 public_runtime_result_json 无此问题） — 提取共享模块/收敛单一 writer。
- [阶段14][信息] crates/pine-wasm/Cargo.toml + src/request/chart.rs — WASM 无 profile API（同 Python 缺、CLI 有）；深递归栈溢出主线已关闭，但未设 console_error_panic_hook 仍影响意外 panic 可观测性；chart 上下文三 host 均硬编码 ChartContext::default()（NASDAQ:AAPL）不可配置 — 评估补 profile 入口/panic hook/可配置 chart 上下文（阶段16）。
- [阶段15][中] crates/pine-cli/src/conformance.rs — conformance 状态准确性无机器校验：validate_fixture_paths 仅查文件存在，无测试验证 fixture 真用了所声明 feature、status(supported/partial/unsupported) 与实现一致；115 个 partial 无边界断言 — 加 feature↔fixture 语义链接校验/partial 边界回归。
- [阶段15][中] crates/pine-runtime/tests/incremental.rs — 全部 runtime fixture 仅断言「无诊断+增量==全量」不验数值；ta.*/math.* 大量指标 fixture(alma/ao/cci/dmi/sar/supertrend/tsi/vwap…) 无 golden 数值快照，承接阶段7 暖机偏差无法被捕获 — 为高风险递归指标补 golden 值/数值基准。
- [阶段15][低][已关闭] tests/fixtures — 整数坍缩(阶段6/7)曾无回归 fixture；当前已补计算循环上界、数组下标/尺寸、`ta.*`/`math.*` 计算长度用例 — 后续保留这些 fixture 作为回归守护。
- [阶段15][低][已关闭] crates/pine-syntax/tests/fixtures.rs — 语法层 fixture 回归曾仅 1 个 test；当前已补 deep_expression_limit、utf8_diagnostic_column、parse_error_recovery、malformed_number_recovery、soft_keyword_export_identifier 等 fixture。
- [阶段15][信息] tests/fixtures/sema/unsupported_strategy_exit_{stop,stop_limit,stop_profit,limit_loss,profit_loss,profit_qty,qty_stop,trailing_partial_quantity}.pine — 8 个死 fixture 引用于零处(对应组合现已 supported，旧 unsupported 版残留) — 清理或纳入测试。
- [阶段15][信息][已关闭] tests/fixtures — 非有限 Float→非法 JSON/不可 JSON.parse(阶段11/12/14) 曾无对应 fixture；当前已补 runtime JSON、CLI CSV、WASM CSV、Python 输出/输入回归；f64 Display 跨平台稳定性仍无跨架构快照矩阵。
- [阶段16][中] docs/DIAGNOSTIC_CODES.md — 实测 22 个已发射诊断码未登记(E_LEX_INDENT/E_PARSE_BLOCK/FOR/FUNCTION/E_LOOP_*4/E_SCRIPT_DECL_*2/E_STRATEGY_MODE/PRICE/QTY/E_STRATEGY_EXIT_*5/E_UNKNOWN_FUNCTION/METHOD/COLOR/E_METHOD_RECEIVER_TYPE)，含 5 个 broker 运行时码；诊断码为公开 DX 契约 — 全部补登。
- [阶段16][信息·确定性通过] core 五 crate 实测无时钟/随机/网络/文件/env 调用，chrono 关 clock；HashMap 仅按键控存储不入输出顺序；增量==全量 parity 覆盖全 runtime fixture — 残留 f64 Display 跨平台无 CI 快照矩阵。
- [阶段16][信息·安全] runtime+builtins 执行路径实测仅 1 处守卫式 unreachable、无可达 unwrap，DoS 上限齐备；历史系统性崩溃面=无界递归栈溢出(阶段1/3/4/6)已由 parser/sema/lowering/runtime 深度预算关闭 — 继续保留深嵌套回归。
- [阶段16][信息·合规通过] COMPATIBILITY_AND_LEGAL.md clean-room 政策完备且被遵守，代码仅 1 处注释陈述 Pine == 语义，无品牌/错误文案复制 — 轻微：包元数据 repository 空且无非关联声明(承接阶段0)。
- [阶段16][汇总] 历史 P0 整数坍缩(高,正确性根因)、P1-a 无界递归崩溃面(中) 与 P1-b 非有限边界(中) 已关闭并有回归守护；后续优先修复排序转为 P1 ta.* 历史耦合(中) → P2 TradingView 口径分歧 → P3 工程文档清理；全部 16 阶段审查完成。
