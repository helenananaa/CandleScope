use pine_syntax::SourceFile;

use super::*;

fn first_call_site_id(program: &pine_ir::HirProgram, callee: &str) -> u32 {
    fn find_in_stmts(statements: &[pine_ir::HirStmt], callee: &str) -> Option<u32> {
        for statement in statements {
            match &statement.kind {
                pine_ir::HirStmtKind::Expr(expr)
                | pine_ir::HirStmtKind::Decl { value: expr, .. }
                | pine_ir::HirStmtKind::Reassign { value: expr, .. }
                | pine_ir::HirStmtKind::FieldReassign { value: expr, .. }
                | pine_ir::HirStmtKind::TupleDecl { value: expr, .. } => {
                    if let Some(call_site_id) = find_in_expr(expr, callee) {
                        return Some(call_site_id);
                    }
                }
                pine_ir::HirStmtKind::ArrayFieldReassign {
                    array,
                    index,
                    value,
                    ..
                } => {
                    if let Some(call_site_id) = find_in_expr(array, callee)
                        .or_else(|| find_in_expr(index, callee))
                        .or_else(|| find_in_expr(value, callee))
                    {
                        return Some(call_site_id);
                    }
                }
                pine_ir::HirStmtKind::If {
                    condition,
                    then_branch,
                    else_branch,
                } => {
                    if let Some(call_site_id) = find_in_expr(condition, callee)
                        .or_else(|| find_in_stmts(then_branch, callee))
                        .or_else(|| find_in_stmts(else_branch, callee))
                    {
                        return Some(call_site_id);
                    }
                }
                pine_ir::HirStmtKind::Switch { selector, arms } => {
                    if let Some(call_site_id) = selector
                        .as_ref()
                        .and_then(|selector| find_in_expr(selector, callee))
                        .or_else(|| {
                            arms.iter().find_map(|arm| {
                                arm.condition
                                    .as_ref()
                                    .and_then(|condition| find_in_expr(condition, callee))
                                    .or_else(|| find_in_stmts(&arm.body, callee))
                            })
                        })
                    {
                        return Some(call_site_id);
                    }
                }
                pine_ir::HirStmtKind::For {
                    from,
                    to,
                    step,
                    body,
                    ..
                } => {
                    if let Some(call_site_id) = find_in_expr(from, callee)
                        .or_else(|| find_in_expr(to, callee))
                        .or_else(|| step.as_ref().and_then(|step| find_in_expr(step, callee)))
                        .or_else(|| find_in_stmts(body, callee))
                    {
                        return Some(call_site_id);
                    }
                }
                pine_ir::HirStmtKind::While { condition, body } => {
                    if let Some(call_site_id) =
                        find_in_expr(condition, callee).or_else(|| find_in_stmts(body, callee))
                    {
                        return Some(call_site_id);
                    }
                }
                pine_ir::HirStmtKind::ForIn { iterable, body, .. } => {
                    if let Some(call_site_id) =
                        find_in_expr(iterable, callee).or_else(|| find_in_stmts(body, callee))
                    {
                        return Some(call_site_id);
                    }
                }
                pine_ir::HirStmtKind::Break | pine_ir::HirStmtKind::Continue => {}
            }
        }
        None
    }

    fn find_in_expr(expr: &pine_ir::HirExpr, callee: &str) -> Option<u32> {
        match &expr.kind {
            pine_ir::HirExprKind::Call {
                callee: name,
                call_site_id,
                args,
            } => {
                if name == callee {
                    return Some(call_site_id.0);
                }
                args.iter().find_map(|arg| find_in_expr(&arg.value, callee))
            }
            pine_ir::HirExprKind::Unary { expr, .. }
            | pine_ir::HirExprKind::FieldAccess { value: expr, .. }
            | pine_ir::HirExprKind::History { expr, .. } => find_in_expr(expr, callee),
            pine_ir::HirExprKind::Binary { left, right, .. } => {
                find_in_expr(left, callee).or_else(|| find_in_expr(right, callee))
            }
            pine_ir::HirExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => find_in_expr(condition, callee)
                .or_else(|| find_in_expr(then_expr, callee))
                .or_else(|| find_in_expr(else_expr, callee)),
            pine_ir::HirExprKind::Switch { selector, arms } => selector
                .as_deref()
                .and_then(|selector| find_in_expr(selector, callee))
                .or_else(|| {
                    arms.iter().find_map(|arm| {
                        arm.condition
                            .as_ref()
                            .and_then(|condition| find_in_expr(condition, callee))
                            .or_else(|| find_in_expr(&arm.result, callee))
                    })
                }),
            pine_ir::HirExprKind::For {
                from,
                to,
                step,
                statements,
                result,
                ..
            } => find_in_expr(from, callee)
                .or_else(|| find_in_expr(to, callee))
                .or_else(|| step.as_deref().and_then(|step| find_in_expr(step, callee)))
                .or_else(|| find_in_stmts(statements, callee))
                .or_else(|| find_in_expr(result, callee)),
            pine_ir::HirExprKind::ForIn {
                iterable,
                statements,
                result,
                ..
            } => find_in_expr(iterable, callee)
                .or_else(|| find_in_stmts(statements, callee))
                .or_else(|| find_in_expr(result, callee)),
            pine_ir::HirExprKind::While {
                condition,
                statements,
                result,
            } => find_in_expr(condition, callee)
                .or_else(|| find_in_stmts(statements, callee))
                .or_else(|| find_in_expr(result, callee)),
            pine_ir::HirExprKind::Tuple(values)
            | pine_ir::HirExprKind::UserTypeConstruct { fields: values, .. }
            | pine_ir::HirExprKind::UserTypeArrayConstruct {
                elements: values, ..
            } => values.iter().find_map(|value| find_in_expr(value, callee)),
            pine_ir::HirExprKind::Block { statements, result } => {
                find_in_stmts(statements, callee).or_else(|| find_in_expr(result, callee))
            }
            pine_ir::HirExprKind::Literal(_)
            | pine_ir::HirExprKind::Symbol(_)
            | pine_ir::HirExprKind::Builtin(_) => None,
        }
    }

    find_in_stmts(&program.statements, callee).expect("input call should exist")
}

#[test]
fn runs_input_string_condition() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("input string")
mode = input.string("Close", "Mode")
plot(mode == "Close" ? close : open)
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

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
}

#[test]
fn runs_input_call_site_overrides() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("input override")
length = input.int(2, "Length")
scale = input.float(1.0, "Scale")
plot(ta.sma(close, length) * scale)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let program = analysis.hir.expect("HIR");
    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];

    let default_result = run_historical(&program, &bars).expect("default input result");
    assert_eq!(default_result.plots.len(), 1);
    assert_eq!(default_result.plots[0].values[0], PineValue::Na);
    assert_values_close(&default_result.plots[0].values[1..], &[1.5, 2.5]);

    let length_call_site = first_call_site_id(&program, "input.int");
    let scale_call_site = first_call_site_id(&program, "input.float");
    let overrides = InputOverrides::new()
        .with_value(length_call_site, PineValue::Int(1))
        .with_value(scale_call_site, PineValue::Float(2.0));
    let override_result =
        run_historical_with_input_overrides(&program, &bars, overrides).expect("override result");

    assert_eq!(override_result.plots.len(), 1);
    assert_values_close(&override_result.plots[0].values, &[2.0, 4.0, 6.0]);
}

#[test]
fn runs_additional_input_variants() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("more inputs")
threshold = input.price(2.5, "Price")
start = input.time(2, "Start")
symbol = input.symbol("AAPL", "Symbol")
timeframe = input.timeframe("D", "Timeframe")
session = input.session("0930-1600", "Session")
notes = input.text_area("Plan", "Notes")
enabled = time >= start and symbol == "AAPL" and timeframe == "D" and session == "0930-1600" and notes == "Plan"
plot(enabled ? math.max(close, threshold) : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 1,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 2,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 3,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[0.0, 2.5, 3.0]);
}

#[test]
fn runs_generic_input_variants() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("generic input")
length = input(2, "Length")
scale = input(1.5, "Scale")
enabled = input(true, "Enabled")
mode = input("SMA", "Mode")
shade = input(color.orange, "Shade")
plot(enabled and mode == "SMA" ? ta.sma(close, length) * scale : open, color=color.new(shade, 10))
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

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.25, 3.75]);
}

#[test]
fn runs_input_metadata_parameters() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("input metadata")
length = input.int(2, "Length", minval=1, maxval=20, step=1, options=[1, 2, 3], tooltip="Bars", inline="row", group="Settings", confirm=true, display=display.all)
scale = input.float(1.5, "Scale", minval=0.5, maxval=5.0, step=0.25, options=[1.0, 1.5], display=display.none)
enabled = input.bool(true, "Enabled", tooltip="Toggle", inline="row", group="Settings", confirm=false)
mode = input.string("SMA", "Mode", options=["SMA", "EMA"], tooltip="Mode")
shade = input.color(color.orange, "Shade", group="Style")
src = input.source(close, "Source", tooltip="Price", inline="src", group="Settings", confirm=true, display=display.all)
plot(enabled and mode == "SMA" ? math.max(src, length) * scale : close, color=shade)
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

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[3.0, 3.0, 4.5]);
}
