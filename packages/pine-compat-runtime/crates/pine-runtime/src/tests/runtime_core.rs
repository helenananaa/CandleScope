use pine_ir::{
    CallSiteId, HirBinaryOp, HirCallArg, HirExpr, HirExprKind, HirLiteral, HirStmt, HirStmtKind,
    PineType, Qualifier, SymbolId, ValueKind,
};
use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn reports_unsupported_runtime_call_from_top_level_dispatcher() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("unsupported dispatch")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let program = analysis.hir.expect("HIR");
    let mut runtime = HistoricalRuntime::new(&program);

    let error = runtime
        .eval_call("runtime.unknown", CallSiteId(999), &[])
        .expect_err("unsupported runtime call should fail");

    assert_eq!(error.message, "unsupported runtime call `runtime.unknown`");
}

#[test]
fn runtime_error_stops_at_reached_udf_call_with_series_message() {
    let source = SourceFile::new(
        "test.pine",
        r#"//@version=6
indicator("runtime error")
fail(string message) =>
    runtime.error(message)
if bar_index == 2
    fail(str.format("invalid bar {0}", bar_index))
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect_err("reached runtime.error should stop execution");

    assert_eq!(error.message, "invalid bar 2");
}

#[test]
fn runtime_error_normalizes_na_string_message() {
    let source = SourceFile::new(
        "test.pine",
        r#"//@version=6
indicator("runtime error na")
string message = na
runtime.error(message=message)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("runtime.error should stop execution");

    assert_eq!(error.message, "NaN");
}

#[test]
fn rejects_hir_expression_past_runtime_eval_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("runtime depth")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let mut program = analysis.hir.expect("HIR");
    program.statements = vec![HirStmt {
        kind: HirStmtKind::Expr(nested_unary_expr(MAX_RUNTIME_EVAL_DEPTH + 1)),
    }];

    let error =
        run_historical(&program, &[bar(1.0)]).expect_err("deep runtime expression should fail");

    assert_eq!(
        error.message,
        "runtime expression evaluation exceeded maximum depth"
    );
}

#[test]
fn evaluates_hir_while_expression_zero_iteration_as_na() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("runtime while expression zero")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let mut program = analysis.hir.expect("HIR");
    replace_first_plot_arg(
        &mut program,
        while_expr(bool_expr(false), Vec::new(), int_expr(1)),
    );

    let result = run_historical(&program, &[bar(1.0)]).expect("while expression runtime result");

    assert_eq!(result.plots[0].values, vec![PineValue::Na]);
}

#[test]
fn evaluates_hir_while_expression_latest_result() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("runtime while expression")
x = 0
plot(x)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let mut program = analysis.hir.expect("HIR");
    let x = program
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol")
        .id;
    let increment = HirStmt {
        kind: HirStmtKind::Reassign {
            symbol: x,
            value: binary_expr(HirBinaryOp::Add, symbol_expr(x, int_type()), int_expr(1)),
        },
    };
    let condition = binary_expr(HirBinaryOp::Lt, symbol_expr(x, int_type()), int_expr(3));
    replace_first_plot_arg(
        &mut program,
        while_expr(condition, vec![increment], symbol_expr(x, int_type())),
    );

    let result = run_historical(&program, &[bar(1.0)]).expect("while expression runtime result");

    assert_eq!(result.plots[0].values, vec![PineValue::Int(3)]);
}

#[test]
fn evaluates_hir_while_expression_loop_control_result() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("runtime while expression control")
x = 0
plot(x)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let mut program = analysis.hir.expect("HIR");
    let x = program
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol")
        .id;
    let increment = HirStmt {
        kind: HirStmtKind::Reassign {
            symbol: x,
            value: binary_expr(HirBinaryOp::Add, symbol_expr(x, int_type()), int_expr(1)),
        },
    };
    let continue_at_two = HirStmt {
        kind: HirStmtKind::If {
            condition: binary_expr(HirBinaryOp::Eq, symbol_expr(x, int_type()), int_expr(2)),
            then_branch: vec![HirStmt {
                kind: HirStmtKind::Continue,
            }],
            else_branch: Vec::new(),
        },
    };
    let break_at_four = HirStmt {
        kind: HirStmtKind::If {
            condition: binary_expr(HirBinaryOp::Eq, symbol_expr(x, int_type()), int_expr(4)),
            then_branch: vec![HirStmt {
                kind: HirStmtKind::Break,
            }],
            else_branch: Vec::new(),
        },
    };
    let condition = binary_expr(HirBinaryOp::Lt, symbol_expr(x, int_type()), int_expr(5));
    let result_expr = binary_expr(HirBinaryOp::Mul, symbol_expr(x, int_type()), int_expr(10));
    replace_first_plot_arg(
        &mut program,
        while_expr(
            condition,
            vec![increment, continue_at_two, break_at_four],
            result_expr,
        ),
    );

    let result = run_historical(&program, &[bar(1.0)]).expect("while expression runtime result");

    assert_eq!(result.plots[0].values, vec![PineValue::Int(30)]);
}

fn nested_unary_expr(depth: u32) -> HirExpr {
    let mut expr = int_expr(1);
    for _ in 0..depth {
        expr = HirExpr {
            kind: HirExprKind::Unary {
                op: pine_ir::HirUnaryOp::Plus,
                expr: Box::new(expr),
            },
            pine_type: int_type(),
            series_id: None,
        };
    }
    expr
}

fn bool_expr(value: bool) -> HirExpr {
    HirExpr {
        kind: HirExprKind::Literal(HirLiteral::Bool(value)),
        pine_type: PineType::new(Qualifier::Const, ValueKind::Bool),
        series_id: None,
    }
}

fn int_expr(value: i64) -> HirExpr {
    HirExpr {
        kind: HirExprKind::Literal(HirLiteral::Int(value)),
        pine_type: int_type(),
        series_id: None,
    }
}

fn symbol_expr(symbol: SymbolId, pine_type: PineType) -> HirExpr {
    HirExpr {
        kind: HirExprKind::Symbol(symbol),
        pine_type,
        series_id: None,
    }
}

fn binary_expr(op: HirBinaryOp, left: HirExpr, right: HirExpr) -> HirExpr {
    HirExpr {
        kind: HirExprKind::Binary {
            op,
            left: Box::new(left),
            right: Box::new(right),
        },
        pine_type: match op {
            HirBinaryOp::Eq
            | HirBinaryOp::NotEq
            | HirBinaryOp::Gt
            | HirBinaryOp::Gte
            | HirBinaryOp::Lt
            | HirBinaryOp::Lte
            | HirBinaryOp::And
            | HirBinaryOp::Or => PineType::new(Qualifier::Series, ValueKind::Bool),
            _ => PineType::new(Qualifier::Series, ValueKind::Int),
        },
        series_id: None,
    }
}

fn while_expr(condition: HirExpr, statements: Vec<HirStmt>, result: HirExpr) -> HirExpr {
    HirExpr {
        kind: HirExprKind::While {
            condition: Box::new(condition),
            statements,
            result: Box::new(result),
        },
        pine_type: int_type(),
        series_id: None,
    }
}

fn replace_first_plot_arg(program: &mut pine_ir::HirProgram, value: HirExpr) {
    for statement in &mut program.statements {
        let HirStmtKind::Expr(HirExpr {
            kind: HirExprKind::Call { callee, args, .. },
            ..
        }) = &mut statement.kind
        else {
            continue;
        };
        if callee == "plot" {
            args[0] = HirCallArg { name: None, value };
            return;
        }
    }
    panic!("expected plot call");
}

fn int_type() -> PineType {
    PineType::new(Qualifier::Const, ValueKind::Int)
}

#[test]
fn preserves_var_state_across_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("var")
var x = 0
x := x + 1
plot(close + x)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(2.0),
            PineValue::Float(4.0),
            PineValue::Float(6.0),
        ]
    );
}

#[test]
fn numeric_equality_uses_exact_pine_comparison() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("exact equality")
plot(0.1 + 0.2 == 0.3 ? 99 : 1)
plot(1 == 1.0 ? 1 : 0)
plot(na(0 / 0) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[1.0]);
    assert_values_close(&result.plots[1].values, &[1.0]);
    assert_values_close(&result.plots[2].values, &[1.0]);
}

#[test]
fn profiles_runtime_storage() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("profile")
ma = ta.sma(close, 2)
plot(ma)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.profile.bars, 3);
    assert_eq!(profiled.profile.series_buffers, 0);
    assert_eq!(profiled.profile.series_values, 0);
    assert!(profiled.profile.series_capacity >= profiled.profile.series_values);
    assert_eq!(profiled.profile.max_series_depth, 0);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 0);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
    assert_eq!(profiled.profile.rolling_window_slots, 1);
    assert_eq!(profiled.profile.rolling_window_values, 2);
    assert!(
        profiled.profile.rolling_window_value_capacity >= profiled.profile.rolling_window_values
    );
    assert_eq!(profiled.profile.plots, 1);
    assert_eq!(profiled.profile.plot_values, 3);
    assert!(profiled.profile.plot_capacity >= profiled.profile.plot_values);
    assert_eq!(profiled.profile.plot_shapes, 0);
    assert_eq!(profiled.profile.plot_arrows, 0);
    assert_eq!(profiled.profile.plot_bars, 0);
    assert_eq!(profiled.profile.plot_candles, 0);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[1..], &[1.5, 2.5]);
}

#[test]
fn trims_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history")
plot(close[2])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_constant_expression_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history expression")
plot(close[1 + 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_multiplicative_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history multiplication")
plot(close[1 * 2])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_modulo_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history modulo")
plot(close[5 % 3])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_ternary_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history ternary")
plot(close[false ? 1 : 2])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_constant_ta_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf constant ta")
length() => 2
plot(ta.mom(close, length()))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[2.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_constant_argument_ta_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf constant argument ta")
length(value) => value
plot(ta.mom(close, length(2)))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[2.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_derived_constant_argument_ta_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf derived constant argument ta")
length(value) => value + 1
plot(ta.mom(close, length(1)))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[2.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_local_derived_constant_argument_ta_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf local derived constant argument ta")
length(value) =>
    adjusted = value + 1
    adjusted
plot(ta.mom(close, length(1)))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[2.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_local_constant_after_expr_statement_ta_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf local constant after expr statement ta")
length() =>
    value = 2
    close
    value
plot(ta.mom(close, length()))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[2.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_local_constant_after_unrelated_if_statement_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf local constant after unrelated if")
length() =>
    value = 2
    if close > open
        other = 1
    value
plot(close[length()])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_branch_invariant_local_constant_dynamic_condition_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf branch invariant dynamic condition")
length() =>
    value = 2
    close > open ? value : value
plot(close[length()])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_selector_switch_local_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf selector switch local constant")
length() =>
    mode = 1
    value = 2
    switch mode
        1 => value
        => value + 1
plot(close[length()])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_for_expression_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf for expression constant")
length() =>
    for i = 0 to 1
        2
plot(close[length()])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_tuple_destructured_local_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf tuple destructured local constant")
length() =>
    [value, ignored] = [2, 99]
    value
plot(close[length()])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_user_type_field_constant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf user type field constant")
type Settings
    int length
length() =>
    settings = Settings.new(2)
    settings.length
plot(close[length()])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_user_type_field_branch_invariant_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf user type field branch invariant")
type Settings
    int length
length() =>
    settings = close > open ? Settings.new(2) : Settings.new(2)
    settings.length
plot(close[length()])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_udf_string_constant_argument_predicate_ta_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history udf string constant argument predicate ta")
is_a(value) => value == "A"
plot(ta.mom(close, is_a("A") ? 2 : 1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[2.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_boolean_expression_ternary_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history boolean ternary")
plot(close[(true and false) ? 1 : 2])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_short_circuit_and_dynamic_rhs_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history short circuit and dynamic rhs")
plot(close[(false and close > open) ? 1 : 2])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_bool_ternary_condition_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history bool ternary condition")
plot(close[((true ? true : false) ? 2 : 1)])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_comparison_ternary_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history comparison ternary")
plot(close[(1 + 1 == 2) ? 2 : 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_division_comparison_ternary_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history division comparison ternary")
plot(close[(4 / 2 == 2) ? 2 : 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_string_comparison_ternary_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history string comparison ternary")
plot(close[("A" == "A") ? 2 : 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_named_string_constant_value_comparison_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history named string constant value comparison")
plot(close[(adjustment.none == "none") ? 2 : 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_string_value_ternary_ta_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history string value ternary ta")
plot(ta.mom(close, ((true ? "A" : "B") == "A") ? 2 : 1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[2.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_color_comparison_ternary_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history color comparison ternary")
plot(close[(color.red == color.red) ? 2 : 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_color_value_ternary_comparison_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history color value ternary comparison")
plot(close[((true ? color.red : color.green) == color.red) ? 2 : 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn trims_named_numeric_comparison_ternary_history_to_required_depth() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("static history named numeric comparison ternary")
plot(close[(math.pi > 3) ? 2 : 1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.profile.series_values, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 2);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(!profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn keeps_full_history_when_dynamic_offsets_exist() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("dynamic history retention")
length = input.int(1, "Length")
plot(close[length])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Na);
    assert_values_close(&profiled.result.plots[0].values[1..], &[1.0, 2.0, 3.0]);
    assert_eq!(profiled.profile.max_series_depth, 4);
    assert!(profiled.profile.series_values >= 4);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::DynamicFull
    );
    assert_eq!(profiled.profile.history_max_constant_offset, 0);
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert!(profiled.profile.history_has_dynamic_offsets);
}

#[test]
fn max_bars_back_bounds_dynamic_history_retention() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("dynamic history retention", max_bars_back=2)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn max_bars_back_constant_expression_bounds_dynamic_history_retention() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("dynamic history retention", max_bars_back=1 + 1)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn max_bars_back_multiplicative_constant_expression_bounds_dynamic_history_retention() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("dynamic history retention", max_bars_back=1 * 2)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn strategy_max_bars_back_bounds_dynamic_history_retention() {
    let source = SourceFile::new(
        "test.pine",
        r#"strategy("dynamic history retention", max_bars_back=2)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn strategy_max_bars_back_constant_expression_bounds_dynamic_history_retention() {
    let source = SourceFile::new(
        "test.pine",
        r#"strategy("dynamic history retention", max_bars_back=3 - 1)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn max_bars_back_function_bounds_only_declared_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("series max_bars_back")
max_bars_back(close, 2)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
plot(open[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 2);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.result.plots[1].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[1].values[1], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[2], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[3], PineValue::Float(1.0));
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn max_bars_back_function_constant_expression_bounds_declared_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("series max_bars_back")
max_bars_back(close, 1 + 1)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
plot(open[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 2);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.result.plots[1].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[1].values[1], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[2], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[3], PineValue::Float(1.0));
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn max_bars_back_function_bounds_declared_series_variable() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("series variable max_bars_back")
src = close
max_bars_back(src, 2)
offset = bar_index == 0 ? 0 : 3
plot(src[offset])
plot(open[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 2);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.result.plots[1].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[1].values[1], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[2], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[3], PineValue::Float(1.0));
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn max_bars_back_function_bounds_derived_series_variable() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("derived series variable max_bars_back")
src = close + 100
max_bars_back(src, 2)
offset = bar_index == 0 ? 0 : 3
plot(src[offset])
plot(open[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 2);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(101.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.result.plots[1].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[1].values[1], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[2], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[3], PineValue::Float(1.0));
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn max_bars_back_function_repeated_series_uses_largest_bound() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("repeated series max_bars_back")
src = close
max_bars_back(src, 2)
max_bars_back(src, 4)
offset = bar_index == 0 ? 0 : 3
plot(src[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[2], PineValue::Na);
    assert_eq!(profiled.result.plots[0].values[3], PineValue::Float(1.0));
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 0);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        None
    );
}

#[test]
fn max_bars_back_diagnostic_reports_effective_series_bound() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("series max_bars_back diagnostic", max_bars_back=10)
max_bars_back(close, 2)
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn append_bar_matches_full_historical_run() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("incremental")
ma = ta.sma(close, 3)
e = ta.ema(close, 2)
plot(ma)
plot(e)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];

    let full = run_historical(&hir, &bars).expect("full result");
    let mut runtime = HistoricalRuntime::new(&hir);
    for (index, bar) in bars.iter().copied().enumerate() {
        runtime.append_bar(bar).expect("append result");
        assert_eq!(runtime.profile().bars, index + 1);
    }
    let incremental = runtime.result();

    assert_eq!(incremental, full);
}

#[test]
fn bar_update_model_marks_committing_updates() {
    let bar = bar(1.0);

    assert!(BarUpdate::historical(bar).commits_series());
    assert!(BarUpdate::confirmed(bar).commits_series());
    assert!(!BarUpdate::forming(bar).commits_series());
}

#[test]
fn runs_barstate_isfirst_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("barstate")
plot(barstate.isfirst ? 1 : 0)
plot(barstate.islast ? 1 : 0)
plot(barstate.islastconfirmedhistory ? 1 : 0)
plot(barstate.isnew ? 1 : 0)
plot(barstate.isconfirmed ? 1 : 0)
plot(barstate.ishistory ? 1 : 0)
plot(barstate.isrealtime ? 1 : 0)
plot(session.ismarket ? 1 : 0)
plot(session.ispremarket ? 1 : 0)
plot(session.ispostmarket ? 1 : 0)
plot(session.ismarket and not session.ispremarket and not session.ispostmarket ? 1 : 0)
plot(session.isfirstbar ? 1 : 0)
plot(session.islastbar ? 1 : 0)
plot(session.isfirstbar_regular ? 1 : 0)
plot(session.islastbar_regular ? 1 : 0)
plot(syminfo.session == session.regular ? 1 : 0)
plot(syminfo.session == session.extended ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(3.0)])
        .expect("runtime result");

    assert_values_close(&result.plots[0].values, &[1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[4].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[5].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[6].values, &[0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[7].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[8].values, &[0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[9].values, &[0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[10].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[11].values, &[1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[12].values, &[0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[13].values, &[1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[14].values, &[0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[15].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[16].values, &[0.0, 0.0, 0.0]);
}

#[test]
fn append_bar_treats_current_open_ended_historical_bar_as_last() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("barstate append")
plot(barstate.islast ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let hir = analysis.hir.expect("HIR");
    let mut runtime = HistoricalRuntime::new(&hir);
    runtime.append_bar(bar(1.0)).expect("first append");
    runtime.append_bar(bar(2.0)).expect("second append");
    let result = runtime.result();

    assert_values_close(&result.plots[0].values, &[1.0, 1.0]);
}
