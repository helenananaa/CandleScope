use pine_ir::{
    HirCallArg, HirExpr, HirExprKind, HirLiteral, HirProgram, HirStmt, HirStmtKind, PineType,
    Qualifier, ScriptMode, ValueKind,
};
use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn strategy_declaration_emits_empty_strategy_result() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("empty")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.script_mode, ScriptMode::Strategy);

    let result = run_historical(&hir, &[bar(1.0), bar(2.0)]).expect("runtime result");

    assert!(result.strategy.is_some());
    let strategy = result.strategy.expect("strategy output");
    assert!(strategy.orders.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.position.is_empty());
    assert_eq!(strategy.equity.len(), 2);
    assert_eq!(strategy.equity[0].bar_index, 0);
    assert_eq!(strategy.equity[0].cash, 100_000.0);
    assert_eq!(strategy.equity[0].market_value, 0.0);
    assert_eq!(strategy.equity[0].equity, 100_000.0);
    assert_eq!(strategy.equity[0].net_profit, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(1.0), PineValue::Float(2.0)]
    );
}

#[test]
fn indicator_result_does_not_include_strategy_output() {
    let source = SourceFile::new(
        "indicator.pine",
        r#"indicator("plain")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert!(result.strategy.is_none());
}

fn const_float_arg(name: &str, value: f64) -> HirCallArg {
    HirCallArg {
        name: Some(name.to_owned()),
        value: HirExpr {
            kind: HirExprKind::Literal(HirLiteral::Float(value)),
            pine_type: PineType::new(Qualifier::Const, ValueKind::Float),
            series_id: None,
        },
    }
}

fn strategy_exit_args_mut(program: &mut HirProgram) -> &mut Vec<HirCallArg> {
    fn find_in_stmts(statements: &mut [HirStmt]) -> Option<&mut Vec<HirCallArg>> {
        for statement in statements {
            match &mut statement.kind {
                HirStmtKind::Expr(expr) => {
                    if let Some(args) = find_in_expr(expr) {
                        return Some(args);
                    }
                }
                HirStmtKind::If {
                    then_branch,
                    else_branch,
                    ..
                } => {
                    if let Some(args) = find_in_stmts(then_branch) {
                        return Some(args);
                    }
                    if let Some(args) = find_in_stmts(else_branch) {
                        return Some(args);
                    }
                }
                _ => {}
            }
        }
        None
    }

    fn find_in_expr(expr: &mut HirExpr) -> Option<&mut Vec<HirCallArg>> {
        if let HirExprKind::Call { callee, args, .. } = &mut expr.kind
            && callee == "strategy.exit"
        {
            return Some(args);
        }
        None
    }

    find_in_stmts(&mut program.statements).expect("strategy.exit call")
}

#[test]
fn strategy_entry_opens_long_position_at_next_bar_open() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry")
if bar_index == 1
    strategy.entry("L", strategy.long, qty=2)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [
        Bar {
            time: 10,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 30,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].time, 30);
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].qty, 2.0);
    assert_eq!(strategy.orders[0].price, 3.0);
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.position[0].bar_index, 2);
    assert_eq!(strategy.position[0].size, 2.0);
    assert_eq!(strategy.position[0].avg_price, Some(3.0));
    assert_eq!(strategy.equity[2].cash, 99_994.0);
    assert_eq!(strategy.equity[2].market_value, 6.0);
    assert_eq!(strategy.equity[2].equity, 100_000.0);
}

#[test]
fn strategy_entry_limit_fills_on_later_low_crossing_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry limit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, limit=2)
plot(strategy.position_size)
plot(strategy.position_avg_price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(5.0, 5.0, 5.0, 5.0),
            bar_ohlc(4.0, 4.0, 3.0, 4.0),
            bar_ohlc(3.0, 3.0, 2.0, 3.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].qty, 2.0);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.position[0].bar_index, 2);
    assert_eq!(strategy.position[0].size, 2.0);
    assert_eq!(strategy.position[0].avg_price, Some(2.0));
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Na, PineValue::Na, PineValue::Float(2.0),]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_entry_limit_allows_same_calculation_absolute_exit_attachment() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry limit exit attachment")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, limit=2)
    strategy.exit("XL", "L", stop=1.5)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar_ohlc(5.0, 5.0, 5.0, 5.0), bar_ohlc(3.0, 3.0, 1.0, 2.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.orders[1].id, "XL");
    assert_eq!(strategy.orders[1].bar_index, 1);
    assert_eq!(strategy.orders[1].direction, "strategy.exit");
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 1.5);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 1.5);
    assert_eq!(strategy.trades[0].profit, -1.0);
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(0.0), PineValue::Float(2.0),]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(0), PineValue::Int(0),]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_cancel_cancels_pending_entry_before_fill() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("cancel entry")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, limit=2)
    strategy.cancel("L")
plot(strategy.position_size)
plot(strategy.position_avg_price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar_ohlc(5.0, 5.0, 5.0, 5.0), bar_ohlc(2.0, 2.0, 2.0, 2.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.trades.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(0.0), PineValue::Float(0.0)]
    );
    assert_eq!(result.plots[1].values, vec![PineValue::Na, PineValue::Na]);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_cancel_unknown_cancelled_and_filled_ids_are_noop() {
    let source = SourceFile::new(
        "strategy_cancel_noop.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_noop.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(1.0, 1.0, 1.0, 1.0),
            bar_ohlc(2.0, 2.0, 2.0, 2.0),
            bar_ohlc(3.0, 3.0, 3.0, 3.0),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 2.0);
    assert!(strategy.trades.is_empty());
    assert_eq!(strategy.position.last().unwrap().size, 2.0);
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_entry_stop_fills_on_later_high_crossing_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry stop")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, stop=3)
plot(strategy.position_size)
plot(strategy.position_avg_price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(1.0, 1.0, 1.0, 1.0),
            bar_ohlc(2.0, 2.0, 1.0, 2.0),
            bar_ohlc(3.0, 3.0, 3.0, 3.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].qty, 2.0);
    assert_eq!(strategy.orders[0].price, 3.0);
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.position[0].bar_index, 2);
    assert_eq!(strategy.position[0].size, 2.0);
    assert_eq!(strategy.position[0].avg_price, Some(3.0));
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Na, PineValue::Na, PineValue::Float(3.0),]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_entry_stop_allows_same_calculation_absolute_exit_attachment() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry stop exit attachment")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, stop=3)
    strategy.exit("XL", "L", limit=3.5)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar_ohlc(1.0, 1.0, 1.0, 1.0), bar_ohlc(3.0, 3.5, 2.5, 3.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].price, 3.0);
    assert_eq!(strategy.orders[1].id, "XL");
    assert_eq!(strategy.orders[1].bar_index, 1);
    assert_eq!(strategy.orders[1].direction, "strategy.exit");
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 3.5);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].entry_price, 3.0);
    assert_eq!(strategy.trades[0].exit_price, 3.5);
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(0.0), PineValue::Float(2.0),]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(0), PineValue::Int(0),]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_cancel_cancels_pending_exit_before_fill() {
    let source = SourceFile::new(
        "strategy_cancel_exit.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_exit.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(1.0, 1.0, 1.0, 1.0),
            bar_ohlc(2.0, 2.0, 2.0, 2.0),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.position[0].size, 2.0);
    assert!(strategy.trades.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_cancel_all_cancels_pending_entry_and_attached_exit_before_fill() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("cancel all entry exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, limit=2)
    strategy.exit("XL", "L", stop=1.5)
    strategy.cancel_all()
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar_ohlc(5.0, 5.0, 5.0, 5.0), bar_ohlc(2.0, 2.0, 1.0, 2.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.trades.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(0.0), PineValue::Float(0.0)]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(0), PineValue::Int(0)]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_cancel_all_cancels_pending_exit_before_fill() {
    let source = SourceFile::new(
        "strategy_cancel_all_exit.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_all_exit.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(1.0, 1.0, 1.0, 1.0),
            bar_ohlc(2.0, 2.0, 2.0, 2.0),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.position[0].size, 2.0);
    assert!(strategy.trades.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_entry_stop_limit_activates_then_fills_on_later_low_crossing_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry stop limit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, stop=3, limit=2)
plot(strategy.position_size)
plot(strategy.position_avg_price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(1.0, 1.0, 1.0, 1.0),
            bar_ohlc(3.0, 3.0, 2.0, 3.0),
            bar_ohlc(2.0, 2.5, 2.0, 2.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].qty, 2.0);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.position[0].bar_index, 2);
    assert_eq!(strategy.position[0].size, 2.0);
    assert_eq!(strategy.position[0].avg_price, Some(2.0));
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Na, PineValue::Na, PineValue::Float(2.0),]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_entry_stop_limit_orders_triggered_together_can_exceed_pyramiding_limit() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry")
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1, stop=11, limit=10)
    strategy.entry("L2", strategy.long, qty=3, stop=11, limit=10)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.position_avg_price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(11.0, 11.0, 10.0, 11.0),
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L1");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 10.0);
    assert_eq!(strategy.orders[1].id, "L2");
    assert_eq!(strategy.orders[1].direction, "strategy.long");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].qty, 3.0);
    assert_eq!(strategy.orders[1].price, 10.0);
    assert_eq!(strategy.position.last().unwrap().size, 4.0);
    assert_eq!(strategy.position.last().unwrap().avg_price, Some(10.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(10.0),
            PineValue::Float(10.0),
        ]
    );
}

#[test]
fn strategy_entry_stop_limit_allows_same_calculation_absolute_exit_attachment() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry stop limit exit attachment")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, stop=3, limit=2)
    strategy.exit("XL", "L", stop=1.5)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(1.0, 1.0, 1.0, 1.0),
            bar_ohlc(3.0, 3.0, 2.0, 3.0),
            bar_ohlc(2.0, 2.0, 1.0, 1.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.orders[1].id, "XL");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].direction, "strategy.exit");
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 1.5);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 1.5);
    assert_eq!(strategy.trades[0].profit, -1.0);
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(0), PineValue::Int(0), PineValue::Int(0),]
    );
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_entry_ignores_repeated_entry_without_pyramiding() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry")
strategy.entry("L1", strategy.long, qty=1)
strategy.entry("L2", strategy.long, qty=1)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L1");
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.position[0].bar_index, 1);
    assert_eq!(strategy.position[0].size, 1.0);
    assert_eq!(strategy.position[0].avg_price, Some(2.0));
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_order_market_long_adds_to_existing_long_without_pyramiding() {
    let source = SourceFile::new(
        "strategy_order_market_long.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_market_long.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(4.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "E");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.orders[1].id, "O");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 4.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[0].size, 1.0);
    assert_eq!(strategy.position[0].avg_price, Some(2.0));
    assert_eq!(strategy.position[1].size, 3.0);
    assert_eq!(strategy.position[1].avg_price, Some(10.0 / 3.0));
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(10.0 / 3.0),
        ]
    );
}

#[test]
fn strategy_order_market_long_uses_default_qty_when_qty_is_absent() {
    for (name, declaration, bars, expected_qty, expected_price) in [
        (
            "fixed",
            r#"strategy("order", default_qty_type=strategy.fixed, default_qty_value=3)"#,
            vec![bar(2.0), bar(4.0)],
            3.0,
            4.0,
        ),
        (
            "cash",
            r#"strategy("order", initial_capital=1000, default_qty_type=strategy.cash, default_qty_value=100)"#,
            vec![bar(10.0), bar(20.0)],
            10.0,
            20.0,
        ),
        (
            "percent",
            r#"strategy("order", initial_capital=1000, default_qty_type=strategy.percent_of_equity, default_qty_value=25)"#,
            vec![bar(10.0), bar(20.0)],
            25.0,
            20.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_order_default_{name}.pine"),
            format!(
                r#"{declaration}
if bar_index == 0
    strategy.order("D", strategy.long)
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name} diagnostics: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 1, "{name}");
        assert_eq!(strategy.orders[0].id, "D", "{name}");
        assert_eq!(strategy.orders[0].direction, "strategy.long", "{name}");
        assert_eq!(strategy.orders[0].qty, expected_qty, "{name}");
        assert_eq!(strategy.orders[0].price, expected_price, "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_order_limit_long_adds_to_existing_long_without_pyramiding() {
    let source = SourceFile::new(
        "strategy_order_limit_long.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_limit_long.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(11.0), bar(9.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "E");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 11.0);
    assert_eq!(strategy.orders[1].id, "O");
    assert_eq!(strategy.orders[1].direction, "strategy.long");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 9.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[0].size, 1.0);
    assert_eq!(strategy.position[0].avg_price, Some(11.0));
    assert_eq!(strategy.position[1].size, 3.0);
    assert_eq!(strategy.position[1].avg_price, Some(29.0 / 3.0));
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Float(11.0),
            PineValue::Float(29.0 / 3.0),
        ]
    );
}

#[test]
fn strategy_cancel_cancels_pending_limit_strategy_order_before_fill() {
    let source = SourceFile::new(
        "strategy_order_cancel_limit.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_cancel_limit.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(5.0), bar(2.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(0.0), PineValue::Float(0.0)]
    );
    assert_eq!(result.plots[1].values, vec![PineValue::Na, PineValue::Na]);
}

#[test]
fn strategy_order_metadata_survives_price_order_and_reduce_fill() {
    let source = SourceFile::new(
        "strategy_order_metadata.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_metadata.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(11.0), bar(9.0), bar(12.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].price, 9.0);
    assert_eq!(strategy.orders[1].id, "R");
    assert_eq!(strategy.orders[1].direction, "strategy.short");
    assert_eq!(strategy.orders[1].bar_index, 3);
    assert_eq!(strategy.orders[1].price, 12.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "R");
    assert_eq!(strategy.alerts.len(), 2);
    assert_eq!(strategy.alerts[0].id, "L");
    assert_eq!(strategy.alerts[0].message, "limit alert");
    assert_eq!(strategy.alerts[0].entry_id.as_deref(), Some("L"));
    assert_eq!(strategy.alerts[0].exit_id, None);
    assert_eq!(strategy.alerts[1].id, "R");
    assert_eq!(strategy.alerts[1].message, "reduce alert");
    assert_eq!(strategy.alerts[1].entry_id, None);
    assert_eq!(strategy.alerts[1].exit_id.as_deref(), Some("R"));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Int(1),
        ]
    );
}

#[test]
fn strategy_order_stop_long_adds_to_existing_long_without_pyramiding() {
    let source = SourceFile::new(
        "strategy_order_stop_long.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_stop_long.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(11.0), bar(12.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "E");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 11.0);
    assert_eq!(strategy.orders[1].id, "O");
    assert_eq!(strategy.orders[1].direction, "strategy.long");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 12.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[0].size, 1.0);
    assert_eq!(strategy.position[0].avg_price, Some(11.0));
    assert_eq!(strategy.position[1].size, 3.0);
    assert_eq!(strategy.position[1].avg_price, Some(35.0 / 3.0));
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Float(11.0),
            PineValue::Float(35.0 / 3.0),
        ]
    );
}

#[test]
fn strategy_cancel_all_cancels_pending_stop_strategy_order_before_fill() {
    let source = SourceFile::new(
        "strategy_order_cancel_all_stop.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_cancel_all_stop.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(3.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(0.0), PineValue::Float(0.0)]
    );
    assert_eq!(result.plots[1].values, vec![PineValue::Na, PineValue::Na]);
}

#[test]
fn strategy_order_stop_limit_long_adds_after_activation_without_pyramiding() {
    let source = SourceFile::new(
        "strategy_order_stop_limit_long.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_stop_limit_long.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(11.0), bar(12.0), bar(10.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "E");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 11.0);
    assert_eq!(strategy.orders[1].id, "O");
    assert_eq!(strategy.orders[1].direction, "strategy.long");
    assert_eq!(strategy.orders[1].bar_index, 3);
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 10.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[0].size, 1.0);
    assert_eq!(strategy.position[0].avg_price, Some(11.0));
    assert_eq!(strategy.position[1].size, 3.0);
    assert_eq!(strategy.position[1].avg_price, Some(31.0 / 3.0));
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Float(11.0),
            PineValue::Float(11.0),
            PineValue::Float(31.0 / 3.0),
        ]
    );
}

#[test]
fn strategy_cancel_cancels_pending_stop_limit_strategy_order_before_activation() {
    let source = SourceFile::new(
        "strategy_order_cancel_stop_limit.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_cancel_stop_limit.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(3.0), bar(2.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Na, PineValue::Na, PineValue::Na]
    );
}

#[test]
fn strategy_order_market_short_reduces_existing_long_without_reversal() {
    let source = SourceFile::new(
        "strategy_order_reduce_long.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_reduce_long.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(4.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "E");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.orders[1].id, "R");
    assert_eq!(strategy.orders[1].direction, "strategy.short");
    assert_eq!(strategy.orders[1].qty, 0.5);
    assert_eq!(strategy.orders[1].price, 4.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[1].size, 0.5);
    assert_eq!(strategy.position[1].avg_price, Some(2.0));
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "E");
    assert_eq!(strategy.trades[0].exit_id, "R");
    assert_eq!(strategy.trades[0].qty, 0.5);
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(0.5),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(1.0),
        ]
    );
}

#[test]
fn strategy_order_market_short_is_noop_while_flat() {
    let source = SourceFile::new(
        "strategy_order_short_flat_noop.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_order_short_flat_noop.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(4.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(0), PineValue::Int(0), PineValue::Int(0),]
    );
}

#[test]
fn strategy_entry_pyramiding_allows_multiple_long_market_entries() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.entry("L3", strategy.long, qty=5)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.position_avg_price)
plot(strategy.max_contracts_held_long)
plot(strategy.opentrades.entry_price(1))
plot(strategy.opentrades.size(1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .expect("HIR")
            .strategy_settings
            .pyramiding_limit,
        2
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(8.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L1");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 2.0);
    assert_eq!(strategy.orders[1].id, "L2");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].qty, 3.0);
    assert_eq!(strategy.orders[1].price, 4.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[0].size, 1.0);
    assert_eq!(strategy.position[0].avg_price, Some(2.0));
    assert_eq!(strategy.position[1].size, 4.0);
    assert_eq!(strategy.position[1].avg_price, Some(3.5));
    assert!(strategy.trades.is_empty());
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(3.5),
            PineValue::Float(3.5),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[4].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[5].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Float(3.0),
        ]
    );
}

#[test]
fn strategy_entry_limit_orders_triggered_together_can_exceed_pyramiding_limit() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry")
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1, limit=9)
    strategy.entry("L2", strategy.long, qty=3, limit=9)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.position_avg_price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(9.0), bar(9.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L1");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 9.0);
    assert_eq!(strategy.orders[1].id, "L2");
    assert_eq!(strategy.orders[1].direction, "strategy.long");
    assert_eq!(strategy.orders[1].bar_index, 1);
    assert_eq!(strategy.orders[1].qty, 3.0);
    assert_eq!(strategy.orders[1].price, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 4.0);
    assert_eq!(strategy.position.last().unwrap().avg_price, Some(9.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Int(0), PineValue::Int(2), PineValue::Int(2)]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![PineValue::Na, PineValue::Float(9.0), PineValue::Float(9.0),]
    );
}

#[test]
fn strategy_entry_stop_orders_triggered_together_can_exceed_pyramiding_limit() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry")
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1, stop=11)
    strategy.entry("L2", strategy.long, qty=3, stop=11)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.position_avg_price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(11.0), bar(11.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[0].id, "L1");
    assert_eq!(strategy.orders[0].direction, "strategy.long");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 11.0);
    assert_eq!(strategy.orders[1].id, "L2");
    assert_eq!(strategy.orders[1].direction, "strategy.long");
    assert_eq!(strategy.orders[1].bar_index, 1);
    assert_eq!(strategy.orders[1].qty, 3.0);
    assert_eq!(strategy.orders[1].price, 11.0);
    assert_eq!(strategy.position.last().unwrap().size, 4.0);
    assert_eq!(strategy.position.last().unwrap().avg_price, Some(11.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Int(0), PineValue::Int(2), PineValue::Int(2)]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Na,
            PineValue::Float(11.0),
            PineValue::Float(11.0),
        ]
    );
}

#[test]
fn strategy_close_pyramiding_entry_id_closes_matching_open_trade() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("close", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.close("L1")
if bar_index == 3
    strategy.close("L2")
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.position_avg_price)
plot(strategy.closedtrades)
plot(strategy.opentrades.entry_id(0) == "L2" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(8.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "L1");
    assert_eq!(strategy.trades[0].entry_bar_index, 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "L2");
    assert_eq!(strategy.trades[1].entry_bar_index, 2);
    assert_eq!(strategy.trades[1].exit_bar_index, 3);
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 8.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 12.0);
    assert_eq!(strategy.position.len(), 4);
    assert_eq!(strategy.position[1].size, 4.0);
    assert_eq!(strategy.position[1].avg_price, Some(3.5));
    assert_eq!(strategy.position[2].size, 3.0);
    assert_eq!(strategy.position[2].avg_price, Some(4.0));
    assert_eq!(strategy.position[3].size, 0.0);
    assert_eq!(strategy.position[3].avg_price, None);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(4.0),
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[4].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_close_all_pyramiding_flattens_all_open_trades() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("close_all", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.close_all()
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(8.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "L1");
    assert_eq!(strategy.trades[0].entry_bar_index, 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "L2");
    assert_eq!(strategy.trades[1].entry_bar_index, 2);
    assert_eq!(strategy.trades[1].exit_bar_index, 2);
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 4.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 0.0);
    assert_eq!(strategy.position.len(), 3);
    assert_eq!(strategy.position[1].size, 4.0);
    assert_eq!(strategy.position[1].avg_price, Some(3.5));
    assert_eq!(strategy.position[2].size, 0.0);
    assert_eq!(strategy.position[2].avg_price, None);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_close_entries_rule_fifo_preserves_default_allocation_order() {
    let close_all_source = SourceFile::new(
        "strategy_close_entries_rule_fifo_close_all.pine",
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_close_entries_rule_fifo_close_all.pine"
        ),
    );
    let close_all_analysis = analyze_source(&close_all_source);
    assert!(
        close_all_analysis.diagnostics.is_empty(),
        "{:?}",
        close_all_analysis.diagnostics
    );
    assert_eq!(
        close_all_analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Fifo
    );

    let close_all_result = run_historical(
        &close_all_analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(5.0)],
    )
    .expect("runtime result");
    let close_all_strategy = close_all_result.strategy.expect("strategy output");

    assert_eq!(close_all_strategy.trades.len(), 2);
    assert_eq!(close_all_strategy.trades[0].id, "L1");
    assert_eq!(close_all_strategy.trades[0].exit_id, "L1");
    assert_eq!(close_all_strategy.trades[0].entry_bar_index, 1);
    assert_eq!(close_all_strategy.trades[0].exit_bar_index, 2);
    assert_eq!(close_all_strategy.trades[0].entry_price, 2.0);
    assert_eq!(close_all_strategy.trades[0].exit_price, 4.0);
    assert_eq!(close_all_strategy.trades[0].qty, 1.0);
    assert_eq!(close_all_strategy.trades[0].profit, 2.0);
    assert_eq!(close_all_strategy.trades[1].id, "L2");
    assert_eq!(close_all_strategy.trades[1].exit_id, "L2");
    assert_eq!(close_all_strategy.trades[1].entry_bar_index, 2);
    assert_eq!(close_all_strategy.trades[1].exit_bar_index, 2);
    assert_eq!(close_all_strategy.trades[1].entry_price, 4.0);
    assert_eq!(close_all_strategy.trades[1].exit_price, 4.0);
    assert_eq!(close_all_strategy.trades[1].qty, 3.0);
    assert_eq!(close_all_strategy.trades[1].profit, 0.0);
    assert_eq!(close_all_strategy.position.last().unwrap().size, 0.0);
    assert!(close_all_strategy.diagnostics.is_empty());
    assert_eq!(
        close_all_result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    for plot_index in 1..=2 {
        assert_eq!(
            close_all_result.plots[plot_index].values.last(),
            Some(&PineValue::Int(1))
        );
    }

    let exit_source = SourceFile::new(
        "strategy_close_entries_rule_fifo.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_close_entries_rule_fifo.pine"),
    );
    let exit_analysis = analyze_source(&exit_source);
    assert!(
        exit_analysis.diagnostics.is_empty(),
        "{:?}",
        exit_analysis.diagnostics
    );
    assert_eq!(
        exit_analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Fifo
    );

    let exit_result = run_historical(
        &exit_analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(5.0), bar(5.0)],
    )
    .expect("runtime result");
    let exit_strategy = exit_result.strategy.expect("strategy output");

    assert_eq!(exit_strategy.trades.len(), 2);
    assert_eq!(exit_strategy.trades[0].id, "L1");
    assert_eq!(exit_strategy.trades[0].exit_id, "XL");
    assert_eq!(exit_strategy.trades[0].entry_price, 2.0);
    assert_eq!(exit_strategy.trades[0].exit_price, 5.0);
    assert_eq!(exit_strategy.trades[0].qty, 1.0);
    assert_eq!(exit_strategy.trades[0].profit, 3.0);
    assert_eq!(exit_strategy.trades[1].id, "L2");
    assert_eq!(exit_strategy.trades[1].exit_id, "XL");
    assert_eq!(exit_strategy.trades[1].entry_price, 4.0);
    assert_eq!(exit_strategy.trades[1].exit_price, 5.0);
    assert_eq!(exit_strategy.trades[1].qty, 3.0);
    assert_eq!(exit_strategy.trades[1].profit, 3.0);
    assert_eq!(exit_strategy.position.last().unwrap().size, 0.0);
    assert!(exit_strategy.diagnostics.is_empty());
    assert_eq!(
        exit_result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
    for plot_index in 1..=2 {
        assert_eq!(
            exit_result.plots[plot_index].values.last(),
            Some(&PineValue::Int(1))
        );
    }
}

#[test]
fn strategy_close_entries_rule_any_uses_entry_id_allocation() {
    let close_source = SourceFile::new(
        "strategy_close_entries_rule_any_close.pine",
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_close_entries_rule_any_close.pine"
        ),
    );
    let close_analysis = analyze_source(&close_source);
    assert!(
        close_analysis.diagnostics.is_empty(),
        "{:?}",
        close_analysis.diagnostics
    );
    assert_eq!(
        close_analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );

    let close_result = run_historical(
        &close_analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(6.0)],
    )
    .expect("runtime result");
    let close_strategy = close_result.strategy.expect("strategy output");

    assert_eq!(close_strategy.trades.len(), 1);
    assert_eq!(close_strategy.trades[0].id, "target");
    assert_eq!(close_strategy.trades[0].exit_id, "target");
    assert_eq!(close_strategy.trades[0].entry_price, 4.0);
    assert_eq!(close_strategy.trades[0].exit_price, 4.0);
    assert_eq!(close_strategy.trades[0].qty, 2.0);
    assert_eq!(close_strategy.trades[0].profit, 0.0);
    assert_eq!(close_strategy.position.last().unwrap().size, 1.0);
    assert!(close_strategy.diagnostics.is_empty());
    assert_eq!(
        close_result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        close_result.plots[1].values.last(),
        Some(&PineValue::Int(1))
    );
    assert_eq!(
        close_result.plots[2].values.last(),
        Some(&PineValue::Float(1.0))
    );

    let exit_source = SourceFile::new(
        "strategy_close_entries_rule_any_exit_from_entry.pine",
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_close_entries_rule_any_exit_from_entry.pine"
        ),
    );
    let exit_analysis = analyze_source(&exit_source);
    assert!(
        exit_analysis.diagnostics.is_empty(),
        "{:?}",
        exit_analysis.diagnostics
    );
    assert_eq!(
        exit_analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );

    let exit_result = run_historical(
        &exit_analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(5.0), bar(5.0)],
    )
    .expect("runtime result");
    let exit_strategy = exit_result.strategy.expect("strategy output");

    assert_eq!(exit_strategy.trades.len(), 1);
    assert_eq!(exit_strategy.trades[0].id, "target");
    assert_eq!(exit_strategy.trades[0].exit_id, "XT");
    assert_eq!(exit_strategy.trades[0].entry_price, 4.0);
    assert_eq!(exit_strategy.trades[0].exit_price, 5.0);
    assert_eq!(exit_strategy.trades[0].qty, 2.0);
    assert_eq!(exit_strategy.trades[0].profit, 2.0);
    assert_eq!(exit_strategy.position.last().unwrap().size, 1.0);
    assert!(exit_strategy.diagnostics.is_empty());
    assert_eq!(
        exit_result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
    assert_eq!(exit_result.plots[1].values.last(), Some(&PineValue::Int(1)));
    assert_eq!(
        exit_result.plots[2].values.last(),
        Some(&PineValue::Float(1.0))
    );
}

#[test]
fn strategy_close_entries_rule_any_partial_exit_same_id_preserves_ledger_order() {
    let source = SourceFile::new(
        "strategy_close_entries_rule_any_exit_same_id_partial.pine",
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_close_entries_rule_any_exit_same_id_partial.pine"
        ),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(5.0), bar(5.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_bar_index, 1);
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 3.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_bar_index, 2);
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 5.0);
    assert_eq!(strategy.trades[1].qty, 0.5);
    assert_eq!(strategy.trades[1].profit, 0.5);
    assert_eq!(strategy.position.last().unwrap().size, 2.5);
    assert_eq!(strategy.position.last().unwrap().avg_price, Some(4.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
    assert_eq!(result.plots[1].values.last(), Some(&PineValue::Int(1)));
    assert_eq!(result.plots[2].values.last(), Some(&PineValue::Int(1)));
    assert_eq!(result.plots[3].values.last(), Some(&PineValue::Float(2.5)));
}

#[test]
fn strategy_exit_pyramiding_entry_id_closes_matching_open_trade() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XL1", "L1", limit=5)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(6.0), bar(8.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 3);
    assert_eq!(strategy.orders[2].id, "XL1");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XL1");
    assert_eq!(strategy.trades[0].entry_bar_index, 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 3);
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 3.0);
    assert_eq!(strategy.position.len(), 3);
    assert_eq!(strategy.position[1].size, 4.0);
    assert_eq!(strategy.position[1].avg_price, Some(3.5));
    assert_eq!(strategy.position[2].size, 3.0);
    assert_eq!(strategy.position[2].avg_price, Some(4.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
}

#[test]
fn strategy_exit_pyramiding_same_entry_id_closes_each_matching_trade() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XL", "L", limit=5)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(6.0), bar(8.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[1].id, "L");
    assert_eq!(strategy.orders[2].id, "XL");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XL");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 3);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 5.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 3.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 5.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 3.0);
    assert_eq!(strategy.position.len(), 3);
    assert_eq!(strategy.position[2].size, 0.0);
    assert_eq!(strategy.position[2].avg_price, None);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_pyramiding_profit_ticks_use_matching_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XP1", "L1", profit=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar(2.0),
            bar(4.0),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
            bar(5.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 3);
    assert_eq!(strategy.orders[2].id, "XP1");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XP1");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.position[2].size, 3.0);
    assert_eq!(strategy.position[2].avg_price, Some(4.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
}

#[test]
fn strategy_exit_pyramiding_bracket_ticks_use_matching_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB1", "L1", profit=200, loss=50)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar(2.0),
            bar(4.0),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
            bar(5.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 3);
    assert_eq!(strategy.orders[2].id, "XB1");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XB1");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.position[2].size, 3.0);
    assert_eq!(strategy.position[2].avg_price, Some(4.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
}

#[test]
fn strategy_exit_pyramiding_trail_points_use_matching_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XT1", "L1", trail_points=200, trail_offset=50)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar(2.0),
            bar(4.0),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
            bar_ohlc(4.0, 4.0, 3.5, 3.5),
            bar(3.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 3);
    assert_eq!(strategy.orders[2].id, "XT1");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 3.5);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XT1");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 3.5);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.5);
    assert_eq!(strategy.position[1].size, 4.0);
    assert_eq!(strategy.position[1].avg_price, Some(3.5));
    assert_eq!(strategy.position[2].size, 3.0);
    assert_eq!(strategy.position[2].avg_price, Some(4.0));
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_closes_current_open_entries() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XL", limit=5)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(5.0), bar(5.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XL");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XL");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 3);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 5.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 3.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 5.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 3.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_persists_for_later_entries() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XL", limit=10)
if bar_index == 2
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(4.0), bar(10.0), bar(10.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[0].id, "L1");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.orders[1].id, "L2");
    assert_eq!(strategy.orders[1].bar_index, 3);
    assert_eq!(strategy.orders[2].id, "XL");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 10.0);
    assert_eq!(strategy.orders[3].id, "XL");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 10.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 10.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 8.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 10.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 18.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_profit_uses_each_open_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XP", profit=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(4.0), bar(6.0), bar(6.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XP");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.0);
    assert_eq!(strategy.orders[3].id, "XP");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 6.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XP");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XP");
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 6.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 6.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_profit_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XP", profit=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(4.0), bar(4.0), bar(6.0), bar(6.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XP");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.0);
    assert_eq!(strategy.orders[3].id, "XP");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 6.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XP");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XP");
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 6.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 6.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_profit_persists_for_later_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XP", profit=300)
if bar_index == 2
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar(2.0),
            bar(4.0),
            bar(4.0),
            bar(5.0),
            bar(7.0),
            bar(7.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XP");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XP");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 7.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XP");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 3.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XP");
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 7.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_profit_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XP", profit=300)
if bar_index == 2
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar(2.0),
            bar(4.0),
            bar(4.0),
            bar(5.0),
            bar(7.0),
            bar(7.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XP");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XP");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 7.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XP");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 3.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XP");
    assert_eq!(strategy.trades[1].entry_price, 4.0);
    assert_eq!(strategy.trades[1].exit_price, 7.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_uses_each_open_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XL", loss=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(8.0), bar(6.0), bar(6.0), bar(4.0), bar(4.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XL");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 6.0);
    assert_eq!(strategy.orders[3].id, "XL");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 4.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 6.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 4.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, -6.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XL", loss=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(8.0), bar(6.0), bar(6.0), bar(4.0), bar(4.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XL");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 6.0);
    assert_eq!(strategy.orders[3].id, "XL");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 4.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 6.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 4.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, -6.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_persists_for_later_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XL", loss=300)
if bar_index == 2
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(5.0),
            bar(3.0),
            bar(3.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XL");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XL");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 3.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -3.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 3.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, -9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XL", loss=300)
if bar_index == 2
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(5.0),
            bar(3.0),
            bar(3.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XL");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XL");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 3.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -3.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XL");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 3.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, -9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_profit_bracket_uses_each_open_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", loss=200, profit=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar_ohlc(6.0, 6.0, 6.0, 6.0),
            bar_ohlc(6.0, 8.0, 6.0, 8.0),
            bar(8.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 6.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 8.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 6.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 8.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 6.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_profit_bracket_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", loss=200, profit=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar_ohlc(6.0, 6.0, 6.0, 6.0),
            bar_ohlc(6.0, 8.0, 6.0, 8.0),
            bar(8.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 6.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 8.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 6.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 8.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 6.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_profit_bracket_persists_for_later_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", loss=300, profit=300)
if bar_index == 2
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(5.0),
            bar(9.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -3.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_profit_bracket_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", loss=300, profit=300)
if bar_index == 2
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(5.0),
            bar(9.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -3.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_profit_bracket_uses_each_open_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", stop=5, profit=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar_ohlc(6.0, 8.0, 6.0, 8.0),
            bar_ohlc(8.0, 8.0, 5.0, 5.0),
            bar(5.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 3.0);
    assert_eq!(strategy.orders[2].price, 8.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 1.0);
    assert_eq!(strategy.orders[3].price, 5.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L2");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 6.0);
    assert_eq!(strategy.trades[0].exit_price, 8.0);
    assert_eq!(strategy.trades[0].qty, 3.0);
    assert_eq!(strategy.trades[0].profit, 6.0);
    assert_eq!(strategy.trades[1].id, "L1");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 8.0);
    assert_eq!(strategy.trades[1].exit_price, 5.0);
    assert_eq!(strategy.trades[1].qty, 1.0);
    assert_eq!(strategy.trades[1].profit, -3.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(1.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_profit_bracket_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", stop=5, profit=200)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar_ohlc(6.0, 8.0, 6.0, 8.0),
            bar_ohlc(8.0, 8.0, 5.0, 5.0),
            bar(5.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 3.0);
    assert_eq!(strategy.orders[2].price, 8.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 1.0);
    assert_eq!(strategy.orders[3].price, 5.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 6.0);
    assert_eq!(strategy.trades[0].exit_price, 8.0);
    assert_eq!(strategy.trades[0].qty, 3.0);
    assert_eq!(strategy.trades[0].profit, 6.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 8.0);
    assert_eq!(strategy.trades[1].exit_price, 5.0);
    assert_eq!(strategy.trades[1].qty, 1.0);
    assert_eq!(strategy.trades[1].profit, -3.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(1.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_profit_bracket_persists_for_later_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", stop=5, profit=300)
if bar_index == 2
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(9.0),
            bar(5.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 3.0);
    assert_eq!(strategy.orders[2].price, 9.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 1.0);
    assert_eq!(strategy.orders[3].price, 5.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L2");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 6.0);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].qty, 3.0);
    assert_eq!(strategy.trades[0].profit, 9.0);
    assert_eq!(strategy.trades[1].id, "L1");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 8.0);
    assert_eq!(strategy.trades[1].exit_price, 5.0);
    assert_eq!(strategy.trades[1].qty, 1.0);
    assert_eq!(strategy.trades[1].profit, -3.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(1.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_profit_bracket_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", stop=5, profit=300)
if bar_index == 2
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(9.0),
            bar(5.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 3.0);
    assert_eq!(strategy.orders[2].price, 9.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 1.0);
    assert_eq!(strategy.orders[3].price, 5.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 6.0);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].qty, 3.0);
    assert_eq!(strategy.trades[0].profit, 9.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 8.0);
    assert_eq!(strategy.trades[1].exit_price, 5.0);
    assert_eq!(strategy.trades[1].qty, 1.0);
    assert_eq!(strategy.trades[1].profit, -3.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(1.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_limit_bracket_uses_each_open_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", loss=200, limit=9)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar_ohlc(6.0, 6.0, 6.0, 6.0),
            bar_ohlc(6.0, 9.0, 6.0, 9.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 6.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 6.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_limit_bracket_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", loss=200, limit=9)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar_ohlc(6.0, 6.0, 6.0, 6.0),
            bar_ohlc(6.0, 9.0, 6.0, 9.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 6.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 6.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_limit_bracket_persists_for_later_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", loss=300, limit=9)
if bar_index == 2
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(5.0),
            bar(9.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -3.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_loss_limit_bracket_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", loss=300, limit=9)
if bar_index == 2
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar(8.0),
            bar(6.0),
            bar(6.0),
            bar(5.0),
            bar(9.0),
            bar(9.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 5.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 5);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 5.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, -3.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_limit_bracket_closes_all_open_entries() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", stop=5, limit=9)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(8.0), bar(6.0), bar(9.0), bar(9.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 9.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 3);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_limit_bracket_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XB", stop=5, limit=9)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(8.0), bar(6.0), bar(9.0), bar(9.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 3);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 9.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 3);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_limit_bracket_persists_for_later_entry() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", stop=5, limit=9)
if bar_index == 2
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(8.0), bar(6.0), bar(6.0), bar(9.0), bar(9.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 9.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_stop_limit_bracket_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XB", stop=5, limit=9)
if bar_index == 2
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(8.0), bar(6.0), bar(6.0), bar(9.0), bar(9.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XB");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 9.0);
    assert_eq!(strategy.orders[3].id, "XB");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 9.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XB");
    assert_eq!(strategy.trades[0].entry_price, 8.0);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XB");
    assert_eq!(strategy.trades[1].entry_price, 6.0);
    assert_eq!(strategy.trades[1].exit_price, 9.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 9.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_price_closes_all_open_entries() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XT", trail_price=2.5, trail_offset=50)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 3.0, 1.5, 2.0),
            bar_ohlc(3.0, 4.0, 2.8, 3.0),
            bar_ohlc(3.5, 4.0, 3.6, 3.8),
            bar_ohlc(3.5, 3.5, 3.5, 3.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 3.5);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 3.5);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 3.5);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.5);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 3.5);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 1.5);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_price_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XT", trail_price=2.5, trail_offset=50)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 3.0, 1.5, 2.0),
            bar_ohlc(3.0, 4.0, 2.8, 3.0),
            bar_ohlc(3.5, 4.0, 3.6, 3.8),
            bar_ohlc(3.5, 3.5, 3.5, 3.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 3.5);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 3.5);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 3.5);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.5);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 3.5);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 1.5);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_price_persists_for_later_entry() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XT", trail_price=4.5, trail_offset=50)
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 2.2, 1.8, 2.0),
            bar_ohlc(3.0, 3.2, 2.8, 3.0),
            bar_ohlc(4.5, 5.0, 4.7, 4.8),
            bar_ohlc(4.6, 4.6, 4.5, 4.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.5);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 4.5);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.5);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.5);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 4.5);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 4.5);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_price_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XT", trail_price=4.5, trail_offset=50)
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 2.2, 1.8, 2.0),
            bar_ohlc(3.0, 3.2, 2.8, 3.0),
            bar_ohlc(4.5, 5.0, 4.7, 4.8),
            bar_ohlc(4.6, 4.6, 4.5, 4.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.5);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 4.5);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.5);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.5);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 4.5);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 4.5);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_points_uses_each_open_entry_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XT", trail_points=100, trail_offset=50)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 3.0, 1.5, 2.0),
            bar_ohlc(3.0, 4.0, 2.8, 3.0),
            bar_ohlc(3.5, 4.0, 3.6, 3.8),
            bar_ohlc(3.5, 3.5, 3.5, 3.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 3.5);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 3.5);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 3.5);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.5);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 3.5);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 1.5);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_points_handles_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=3)
if bar_index == 2
    strategy.exit("XT", trail_points=100, trail_offset=50)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 3.0, 1.5, 2.0),
            bar_ohlc(3.0, 4.0, 2.8, 3.0),
            bar_ohlc(3.5, 4.0, 3.6, 3.8),
            bar_ohlc(3.5, 3.5, 3.5, 3.5),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 3.5);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 3.5);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 3.5);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 1.5);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 3.5);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 1.5);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_points_persists_for_later_entry() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XT", trail_points=100, trail_offset=50)
    strategy.entry("L2", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 2.2, 1.8, 2.0),
            bar_ohlc(3.0, 3.2, 2.8, 3.0),
            bar_ohlc(4.5, 4.5, 4.2, 4.5),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.0);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 4.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L1");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.trades[1].id, "L2");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 4.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 3.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_exit_omitted_from_entry_trail_points_persists_for_later_same_entry_id() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit", pyramiding=2)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 1
    strategy.exit("XT", trail_points=100, trail_offset=50)
    strategy.entry("L", strategy.long, qty=3)
plot(strategy.opentrades)
plot(strategy.position_size)
plot(strategy.closedtrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar_ohlc(2.0, 2.2, 1.8, 2.0),
            bar_ohlc(3.0, 3.2, 2.8, 3.0),
            bar_ohlc(4.5, 4.5, 4.2, 4.5),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 4);
    assert_eq!(strategy.orders[2].id, "XT");
    assert_eq!(strategy.orders[2].direction, "strategy.exit");
    assert_eq!(strategy.orders[2].bar_index, 4);
    assert_eq!(strategy.orders[2].qty, 1.0);
    assert_eq!(strategy.orders[2].price, 4.0);
    assert_eq!(strategy.orders[3].id, "XT");
    assert_eq!(strategy.orders[3].direction, "strategy.exit");
    assert_eq!(strategy.orders[3].bar_index, 4);
    assert_eq!(strategy.orders[3].qty, 3.0);
    assert_eq!(strategy.orders[3].price, 4.0);
    assert_eq!(strategy.trades.len(), 2);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XT");
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 4.0);
    assert_eq!(strategy.trades[0].qty, 1.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.trades[1].id, "L");
    assert_eq!(strategy.trades[1].exit_id, "XT");
    assert_eq!(strategy.trades[1].entry_price, 3.0);
    assert_eq!(strategy.trades[1].exit_price, 4.0);
    assert_eq!(strategy.trades[1].qty, 3.0);
    assert_eq!(strategy.trades[1].profit, 3.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
            PineValue::Float(4.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_entry_uses_fixed_default_qty_when_qty_is_absent() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry", default_qty_type=strategy.fixed, default_qty_value=3)
if bar_index == 0
    strategy.entry("D", strategy.long)
if bar_index == 1
    strategy.entry("E", strategy.long, qty=5)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .default_entry_qty(100_000.0, 2.0),
        Some(3.0)
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(2.0), bar(4.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "D");
    assert_eq!(strategy.orders[0].qty, 3.0);
    assert_eq!(strategy.orders[0].price, 4.0);
    assert_eq!(strategy.position[0].size, 3.0);
    assert_eq!(strategy.equity[0].cash, 100_000.0);
    assert_eq!(strategy.equity[0].market_value, 0.0);
    assert_eq!(strategy.equity[1].cash, 99_988.0);
    assert_eq!(strategy.equity[1].market_value, 12.0);
    assert_eq!(strategy.equity[1].equity, 100_000.0);
}

#[test]
fn strategy_entry_uses_builtin_default_qty_when_qty_is_absent() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry")
if bar_index == 0
    strategy.entry("D", strategy.long)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .default_entry_qty(100_000.0, 2.0),
        Some(1.0)
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(2.0), bar(3.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "D");
    assert_eq!(strategy.orders[0].qty, 1.0);
    assert_eq!(strategy.orders[0].price, 3.0);
}

#[test]
fn strategy_default_entry_qty_supports_direct_udf_named_and_history_reads() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("default qty helper", default_qty_type=strategy.fixed, default_qty_value=3)
identity(value) => value
if bar_index == 0
    strategy.entry("L", strategy.long, qty=10)
plot(strategy.default_entry_qty(close))
plot(identity(strategy.default_entry_qty(fill_price=close * 2)))
plot(strategy.default_entry_qty(close)[1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");

    let expected = vec![
        PineValue::Float(3.0),
        PineValue::Float(3.0),
        PineValue::Float(3.0),
        PineValue::Float(3.0),
    ];
    assert_eq!(result.plots[0].values, expected.clone());
    assert_eq!(result.plots[1].values, expected);
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Float(3.0),
            PineValue::Float(3.0),
        ]
    );
}

#[test]
fn strategy_currency_conversions_are_identity_in_default_currency() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("currency conversion", currency=currency.NONE)
identity(value) => value
plot(strategy.convert_to_account(close))
plot(identity(strategy.convert_to_symbol(value=close * 2)))
plot(strategy.convert_to_account(7))
plot(strategy.convert_to_symbol(close)[1])
plot(strategy.convert_to_account(float(na)))
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

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(1.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0)
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(2.0),
            PineValue::Float(4.0),
            PineValue::Float(6.0)
        ]
    );
    assert_eq!(result.plots[2].values, vec![PineValue::Float(7.0); 3]);
    assert_eq!(
        result.plots[3].values,
        vec![PineValue::Na, PineValue::Float(1.0), PineValue::Float(2.0)]
    );
    assert_eq!(result.plots[4].values, vec![PineValue::Na; 3]);
}

#[test]
fn strategy_default_entry_qty_reuses_cash_and_percent_of_equity_sizing() {
    let cash_source = SourceFile::new(
        "cash.pine",
        r#"strategy("cash helper", default_qty_type=strategy.cash, default_qty_value=100)
plot(strategy.default_entry_qty(close))
plot(strategy.default_entry_qty(bar_index == 0 ? na : 0))
"#,
    );
    let cash_analysis = analyze_source(&cash_source);
    assert!(
        cash_analysis.diagnostics.is_empty(),
        "{:?}",
        cash_analysis.diagnostics
    );
    let cash_result = run_historical(
        &cash_analysis.hir.expect("cash HIR"),
        &[bar(10.0), bar(20.0)],
    )
    .expect("cash runtime result");
    assert_eq!(
        cash_result.plots[0].values,
        vec![PineValue::Float(10.0), PineValue::Float(5.0)]
    );
    assert_eq!(
        cash_result.plots[1].values,
        vec![PineValue::Na, PineValue::Na]
    );

    let percent_source = SourceFile::new(
        "percent.pine",
        r#"strategy("percent helper", initial_capital=1000, default_qty_type=strategy.percent_of_equity, default_qty_value=25)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=100)
plot(strategy.default_entry_qty(10))
"#,
    );
    let percent_analysis = analyze_source(&percent_source);
    assert!(
        percent_analysis.diagnostics.is_empty(),
        "{:?}",
        percent_analysis.diagnostics
    );
    let percent_result = run_historical(
        &percent_analysis.hir.expect("percent HIR"),
        &[bar(10.0), bar(20.0), bar(10.0), bar(30.0)],
    )
    .expect("percent runtime result");
    assert_eq!(
        percent_result.plots[0].values,
        vec![
            PineValue::Float(25.0),
            PineValue::Float(25.0),
            PineValue::Na,
            PineValue::Float(50.0),
        ]
    );
}

#[test]
fn strategy_entry_uses_percent_of_equity_default_qty_when_qty_is_absent() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry", initial_capital=1000, default_qty_type=strategy.percent_of_equity, default_qty_value=25)
if bar_index == 0
    strategy.entry("D", strategy.long)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .default_entry_qty(1000.0, 10.0),
        Some(25.0)
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(10.0), bar(20.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "D");
    assert_eq!(strategy.orders[0].qty, 25.0);
    assert_eq!(strategy.orders[0].price, 20.0);
    assert_eq!(strategy.position[0].size, 25.0);
    assert_eq!(strategy.equity[1].cash, 500.0);
    assert_eq!(strategy.equity[1].market_value, 500.0);
    assert_eq!(strategy.equity[1].equity, 1000.0);
}

#[test]
fn strategy_entry_uses_cash_default_qty_when_qty_is_absent() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry", initial_capital=1000, default_qty_type=strategy.cash, default_qty_value=100)
if bar_index == 0
    strategy.entry("D", strategy.long)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .default_entry_qty(1000.0, 10.0),
        Some(10.0)
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(10.0), bar(20.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "D");
    assert_eq!(strategy.orders[0].qty, 10.0);
    assert_eq!(strategy.orders[0].price, 20.0);
    assert_eq!(strategy.position[0].size, 10.0);
    assert_eq!(strategy.equity[1].cash, 800.0);
    assert_eq!(strategy.equity[1].market_value, 200.0);
    assert_eq!(strategy.equity[1].equity, 1000.0);
}

#[test]
fn strategy_limit_entry_uses_cash_default_qty_at_placement_close() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry", initial_capital=1000, default_qty_type=strategy.cash, default_qty_value=100)
if bar_index == 0
    strategy.entry("D", strategy.long, limit=20)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(10.0), bar(20.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "D");
    assert_eq!(strategy.orders[0].qty, 10.0);
    assert_eq!(strategy.orders[0].price, 20.0);
}

#[test]
fn strategy_entry_explicit_qty_overrides_fixed_default_qty() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("entry", default_qty_type=strategy.fixed, default_qty_value=3)
if bar_index == 0
    strategy.entry("E", strategy.long, qty=5)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(2.0), bar(3.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "E");
    assert_eq!(strategy.orders[0].qty, 5.0);
    assert_eq!(strategy.position[0].size, 5.0);
    assert_eq!(strategy.equity[1].cash, 99_985.0);
}

#[test]
fn strategy_close_records_closed_trade_and_flat_position() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("close")
if bar_index == 1
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 2
    strategy.close("L")
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [
        Bar {
            time: 10,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 30,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].entry_bar_index, 2);
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].entry_time, 30);
    assert_eq!(strategy.trades[0].exit_time, 30);
    assert_eq!(strategy.trades[0].entry_price, 3.0);
    assert_eq!(strategy.trades[0].exit_price, 3.0);
    assert_eq!(strategy.trades[0].qty, 2.0);
    assert_eq!(strategy.trades[0].profit, 0.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[1].size, 0.0);
    assert_eq!(strategy.position[1].avg_price, None);
    assert_eq!(strategy.equity[2].cash, 100_000.0);
    assert_eq!(strategy.equity[2].market_value, 0.0);
    assert_eq!(strategy.equity[2].equity, 100_000.0);
    assert_eq!(strategy.equity[2].net_profit, 0.0);
}

#[test]
fn strategy_close_all_records_closed_trade_and_flat_position() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("close_all")
if bar_index == 0
    strategy.close_all()
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 2
    strategy.close_all()
if bar_index == 3
    strategy.close_all()
plot(strategy.position_size)
plot(strategy.closedtrades)
plot(strategy.opentrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_values_close(&result.plots[0].values, &[0.0, 2.0, 0.0, 0.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 0.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 1.0, 0.0, 0.0]);
    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].id, "L");
    assert_eq!(strategy.orders[0].bar_index, 1);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "L");
    assert_eq!(strategy.trades[0].entry_bar_index, 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].entry_price, 2.0);
    assert_eq!(strategy.trades[0].exit_price, 3.0);
    assert_eq!(strategy.trades[0].qty, 2.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[0].size, 2.0);
    assert_eq!(strategy.position[1].size, 0.0);
    assert_eq!(strategy.equity[2].cash, 100_002.0);
    assert_eq!(strategy.equity[2].market_value, 0.0);
    assert_eq!(strategy.equity[2].equity, 100_002.0);
    assert_eq!(strategy.equity[2].net_profit, 2.0);
}

#[test]
fn strategy_close_all_cancels_pending_exit_before_evaluation() {
    let source = SourceFile::new(
        "strategy_close_all_exit.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_close_all_exit.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].exit_price, 3.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
}

#[test]
fn strategy_close_cancels_pending_limit_exit_fixture() {
    let source = SourceFile::new(
        "strategy_close_exit.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_close_exit.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "L");
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].exit_price, 3.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.position.last().unwrap().size, 0.0);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_stop_stages_pending_exit_without_public_fill() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
strategy.entry("L", strategy.long, qty=1)
strategy.exit("XL", "L", stop=low)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(2.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 0);
    assert!(strategy.trades.is_empty());
    assert_eq!(strategy.position.len(), 0);
    assert_eq!(strategy.equity.len(), 1);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_stop_without_matching_entry_is_noop() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
strategy.exit("XL", "L", stop=low)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(2.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.position.is_empty());
    assert_eq!(strategy.equity.len(), 1);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_trailing_hir_without_matching_entry_is_noop() {
    let source = SourceFile::new(
        "strategy_exit_trailing_dispatch_hir.pine",
        r#"strategy("exit")
strategy.exit("XT", "L", stop=95)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let mut hir = analysis.hir.expect("HIR");
    let args = strategy_exit_args_mut(&mut hir);
    let stop_arg = args
        .iter_mut()
        .find(|arg| arg.name.as_deref() == Some("stop"))
        .expect("stop arg");
    stop_arg.name = Some("trail_price".to_owned());
    args.push(const_float_arg("trail_offset", 50.0));

    let result = run_historical(&hir, &[bar(100.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_malformed_trailing_hir_is_guarded_before_fixed_exit() {
    let source = SourceFile::new(
        "strategy_exit_trailing_guard_hir.pine",
        r#"strategy("exit")
strategy.exit("XT", "L", stop=95)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let mut hir = analysis.hir.expect("HIR");
    let args = strategy_exit_args_mut(&mut hir);
    args.push(const_float_arg("trail_price", 100.0));
    args.push(const_float_arg("trail_offset", 50.0));

    let result = run_historical(&hir, &[bar(100.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.orders.is_empty());
    assert!(strategy.trades.is_empty());
    assert!(strategy.position.is_empty());
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_stop_fills_on_later_low_crossing_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("XL", "L", stop=9)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [
        Bar {
            time: 10,
            open: 10.0,
            high: 10.0,
            low: 8.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 11.0,
            high: 12.0,
            low: 8.0,
            close: 11.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "XL");
    assert_eq!(strategy.orders[1].bar_index, 1);
    assert_eq!(strategy.orders[1].direction, "strategy.exit");
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 9.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].entry_bar_index, 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 1);
    assert_eq!(strategy.trades[0].entry_price, 11.0);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].qty, 2.0);
    assert_eq!(strategy.trades[0].profit, -4.0);
    assert_eq!(strategy.position.len(), 2);
    assert_eq!(strategy.position[1].size, 0.0);
    assert_eq!(strategy.equity[1].cash, 99_996.0);
    assert_eq!(strategy.equity[1].market_value, 0.0);
    assert_eq!(strategy.equity[1].net_profit, -4.0);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_qty_single_trigger_forms_dispatch_partial_quantity() {
    for (name, exit_call, high, low, expected_price) in [
        (
            "stop",
            r#"strategy.exit("XQ", "L", stop=95, qty=0.75)"#,
            100.0,
            94.0,
            95.0,
        ),
        (
            "limit",
            r#"strategy.exit("XQ", "L", limit=110, qty=0.75)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "profit",
            r#"strategy.exit("XQ", "L", profit=1000, qty=0.75)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "loss",
            r#"strategy.exit("XQ", "L", loss=500, qty=0.75)"#,
            100.0,
            94.0,
            95.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_exit_qty_{name}.pine"),
            format!(
                r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    {exit_call}
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name}: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(
            &analysis.hir.expect("HIR"),
            &[
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, high, low, 100.0),
            ],
        )
        .expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 2, "{name}");
        assert_eq!(strategy.orders[1].id, "XQ", "{name}");
        assert_eq!(strategy.orders[1].qty, 0.75, "{name}");
        assert_eq!(strategy.orders[1].price, expected_price, "{name}");
        assert_eq!(strategy.trades.len(), 1, "{name}");
        assert_eq!(strategy.trades[0].qty, 0.75, "{name}");
        assert_eq!(strategy.trades[0].exit_price, expected_price, "{name}");
        assert_eq!(strategy.position[1].size, 1.25, "{name}");
        assert_eq!(strategy.position[1].avg_price, Some(100.0), "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_exit_qty_percent_single_trigger_forms_dispatch_partial_quantity() {
    for (name, exit_call, high, low, expected_price) in [
        (
            "stop",
            r#"strategy.exit("XP", "L", stop=95, qty_percent=37.5)"#,
            100.0,
            94.0,
            95.0,
        ),
        (
            "limit",
            r#"strategy.exit("XP", "L", limit=110, qty_percent=37.5)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "profit",
            r#"strategy.exit("XP", "L", profit=1000, qty_percent=37.5)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "loss",
            r#"strategy.exit("XP", "L", loss=500, qty_percent=37.5)"#,
            100.0,
            94.0,
            95.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_exit_qty_percent_{name}.pine"),
            format!(
                r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    {exit_call}
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name}: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(
            &analysis.hir.expect("HIR"),
            &[
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, high, low, 100.0),
            ],
        )
        .expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 2, "{name}");
        assert_eq!(strategy.orders[1].id, "XP", "{name}");
        assert_eq!(strategy.orders[1].qty, 0.75, "{name}");
        assert_eq!(strategy.orders[1].price, expected_price, "{name}");
        assert_eq!(strategy.trades.len(), 1, "{name}");
        assert_eq!(strategy.trades[0].qty, 0.75, "{name}");
        assert_eq!(strategy.position[1].size, 1.25, "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_exit_qty_and_qty_percent_single_trigger_forms_use_qty() {
    for (name, exit_call, high, low, expected_price) in [
        (
            "stop",
            r#"strategy.exit("XQP", "L", stop=95, qty=0.75, qty_percent=25)"#,
            100.0,
            94.0,
            95.0,
        ),
        (
            "limit",
            r#"strategy.exit("XQP", "L", limit=110, qty=0.75, qty_percent=25)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "profit",
            r#"strategy.exit("XQP", "L", profit=1000, qty=0.75, qty_percent=25)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "loss",
            r#"strategy.exit("XQP", "L", loss=500, qty=0.75, qty_percent=25)"#,
            100.0,
            94.0,
            95.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_exit_qty_and_qty_percent_{name}.pine"),
            format!(
                r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    {exit_call}
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name}: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(
            &analysis.hir.expect("HIR"),
            &[
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, high, low, 100.0),
            ],
        )
        .expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 2, "{name}");
        assert_eq!(strategy.orders[1].id, "XQP", "{name}");
        assert_eq!(strategy.orders[1].qty, 0.75, "{name}");
        assert_eq!(strategy.orders[1].price, expected_price, "{name}");
        assert_eq!(strategy.trades.len(), 1, "{name}");
        assert_eq!(strategy.trades[0].qty, 0.75, "{name}");
        assert_eq!(strategy.position[1].size, 1.25, "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_exit_stop_not_reached_keeps_position_open() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("XL", "L", stop=9)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [
        Bar {
            time: 10,
            open: 10.0,
            high: 10.0,
            low: 10.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 11.0,
            high: 12.0,
            low: 10.0,
            close: 11.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert!(strategy.trades.is_empty());
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.equity[1].market_value, 11.0);
    assert_eq!(strategy.equity[1].net_profit, 0.0);
}

#[test]
fn strategy_exit_stop_replacement_uses_updated_stop_on_later_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("XL", "L", stop=8)
if bar_index == 1
    strategy.exit("XL", "L", stop=9)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [
        Bar {
            time: 10,
            open: 10.0,
            high: 10.0,
            low: 10.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 10.0,
            high: 10.0,
            low: 8.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 30,
            open: 10.0,
            high: 10.0,
            low: 8.0,
            close: 10.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.orders[1].price, 9.0);
}

#[test]
fn strategy_close_cancels_pending_stop_before_evaluation() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("XL", "L", stop=9)
if bar_index == 1
    strategy.close("L")
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [
        Bar {
            time: 10,
            open: 10.0,
            high: 10.0,
            low: 10.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 11.0,
            high: 11.0,
            low: 8.0,
            close: 11.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_price, 11.0);
    assert_eq!(strategy.trades[0].profit, 0.0);
}

#[test]
fn strategy_exit_limit_fills_on_later_high_crossing_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("XL", "L", limit=12)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [
        Bar {
            time: 10,
            open: 10.0,
            high: 12.0,
            low: 10.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 11.0,
            high: 12.0,
            low: 10.0,
            close: 11.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "XL");
    assert_eq!(strategy.orders[1].bar_index, 1);
    assert_eq!(strategy.orders[1].direction, "strategy.exit");
    assert_eq!(strategy.orders[1].price, 12.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XL");
    assert_eq!(strategy.trades[0].exit_price, 12.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
    assert_eq!(strategy.position[1].size, 0.0);
    assert_eq!(strategy.equity[1].cash, 100_002.0);
}

#[test]
fn strategy_exit_limit_not_reached_keeps_position_open() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("XL", "L", limit=12)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(11.0, 11.0, 10.0, 11.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert!(strategy.trades.is_empty());
    assert_eq!(strategy.position.len(), 1);
    assert_eq!(strategy.equity[1].market_value, 11.0);
}

#[test]
fn strategy_exit_limit_replacement_uses_updated_limit_on_later_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("XL", "L", limit=12)
if bar_index == 1
    strategy.exit("XL", "L", limit=11)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(10.0, 11.0, 10.0, 10.0),
            bar_ohlc(10.0, 11.0, 10.0, 10.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_bar_index, 2);
    assert_eq!(strategy.trades[0].exit_price, 11.0);
}

#[test]
fn strategy_exit_profit_ticks_fill_through_converted_limit() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.exit("XP", "L", profit=200)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(10.0, 12.0, 10.0, 11.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "XP");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].direction, "strategy.exit");
    assert_eq!(strategy.orders[1].price, 12.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_price, 12.0);
    assert_eq!(strategy.trades[0].profit, 4.0);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_loss_ticks_fill_through_converted_stop() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.exit("XL", "L", loss=100)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(10.0, 10.0, 9.0, 10.0),
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(10.0, 10.0, 9.0, 10.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "XL");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].direction, "strategy.exit");
    assert_eq!(strategy.orders[1].price, 9.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_price, 9.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_bracket_forms_dispatch_to_bracket_pending_exit() {
    for (name, exit_call, high, low, expected_price) in [
        (
            "stop_limit",
            r#"strategy.exit("XB", "L", stop=95, limit=110)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "stop_profit",
            r#"strategy.exit("XB", "L", stop=95, profit=1000)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "loss_limit",
            r#"strategy.exit("XB", "L", loss=500, limit=110)"#,
            111.0,
            94.0,
            95.0,
        ),
        (
            "loss_profit",
            r#"strategy.exit("XB", "L", loss=500, profit=1000)"#,
            111.0,
            94.0,
            95.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_exit_bracket_{name}.pine"),
            format!(
                r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    {exit_call}
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name}: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(
            &analysis.hir.expect("HIR"),
            &[
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, high, low, 100.0),
            ],
        )
        .expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 2, "{name}");
        assert_eq!(strategy.orders[1].id, "XB", "{name}");
        assert_eq!(strategy.orders[1].bar_index, 2, "{name}");
        assert_eq!(strategy.orders[1].direction, "strategy.exit", "{name}");
        assert_eq!(strategy.orders[1].price, expected_price, "{name}");
        assert_eq!(strategy.trades.len(), 1, "{name}");
        assert_eq!(strategy.trades[0].id, "L", "{name}");
        assert_eq!(strategy.trades[0].exit_price, expected_price, "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_exit_qty_bracket_forms_dispatch_partial_quantity() {
    for (name, exit_call, high, low, expected_price) in [
        (
            "stop_limit",
            r#"strategy.exit("BQ", "L", stop=95, limit=110, qty=0.5)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "stop_profit",
            r#"strategy.exit("BQ", "L", stop=95, profit=1000, qty=0.5)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "loss_limit",
            r#"strategy.exit("BQ", "L", loss=500, limit=110, qty=0.5)"#,
            111.0,
            94.0,
            95.0,
        ),
        (
            "loss_profit",
            r#"strategy.exit("BQ", "L", loss=500, profit=1000, qty=0.5)"#,
            111.0,
            94.0,
            95.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_exit_qty_bracket_{name}.pine"),
            format!(
                r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    {exit_call}
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name}: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(
            &analysis.hir.expect("HIR"),
            &[
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, high, low, 100.0),
            ],
        )
        .expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 2, "{name}");
        assert_eq!(strategy.orders[1].id, "BQ", "{name}");
        assert_eq!(strategy.orders[1].qty, 0.5, "{name}");
        assert_eq!(strategy.orders[1].price, expected_price, "{name}");
        assert_eq!(strategy.trades.len(), 1, "{name}");
        assert_eq!(strategy.trades[0].qty, 0.5, "{name}");
        assert_eq!(strategy.trades[0].exit_price, expected_price, "{name}");
        assert_eq!(strategy.position[1].size, 1.5, "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_exit_qty_percent_bracket_forms_dispatch_partial_quantity() {
    for (name, exit_call, high, low, expected_price) in [
        (
            "stop_limit",
            r#"strategy.exit("BP", "L", stop=95, limit=110, qty_percent=25)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "stop_profit",
            r#"strategy.exit("BP", "L", stop=95, profit=1000, qty_percent=25)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "loss_limit",
            r#"strategy.exit("BP", "L", loss=500, limit=110, qty_percent=25)"#,
            111.0,
            94.0,
            95.0,
        ),
        (
            "loss_profit",
            r#"strategy.exit("BP", "L", loss=500, profit=1000, qty_percent=25)"#,
            111.0,
            94.0,
            95.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_exit_qty_percent_bracket_{name}.pine"),
            format!(
                r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    {exit_call}
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name}: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(
            &analysis.hir.expect("HIR"),
            &[
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, high, low, 100.0),
            ],
        )
        .expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 2, "{name}");
        assert_eq!(strategy.orders[1].id, "BP", "{name}");
        assert_eq!(strategy.orders[1].qty, 0.5, "{name}");
        assert_eq!(strategy.orders[1].price, expected_price, "{name}");
        assert_eq!(strategy.trades.len(), 1, "{name}");
        assert_eq!(strategy.trades[0].qty, 0.5, "{name}");
        assert_eq!(strategy.position[1].size, 1.5, "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_exit_qty_and_qty_percent_bracket_forms_use_qty() {
    for (name, exit_call, high, low, expected_price) in [
        (
            "stop_limit",
            r#"strategy.exit("BQP", "L", stop=95, limit=110, qty=0.75, qty_percent=25)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "stop_profit",
            r#"strategy.exit("BQP", "L", stop=95, profit=1000, qty=0.75, qty_percent=25)"#,
            111.0,
            100.0,
            110.0,
        ),
        (
            "loss_limit",
            r#"strategy.exit("BQP", "L", loss=500, limit=110, qty=0.75, qty_percent=25)"#,
            111.0,
            94.0,
            95.0,
        ),
        (
            "loss_profit",
            r#"strategy.exit("BQP", "L", loss=500, profit=1000, qty=0.75, qty_percent=25)"#,
            111.0,
            94.0,
            95.0,
        ),
    ] {
        let source = SourceFile::new(
            format!("strategy_exit_qty_and_qty_percent_bracket_{name}.pine"),
            format!(
                r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    {exit_call}
"#
            ),
        );
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{name}: {:?}",
            analysis.diagnostics
        );

        let result = run_historical(
            &analysis.hir.expect("HIR"),
            &[
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, 100.0, 100.0, 100.0),
                bar_ohlc(100.0, high, low, 100.0),
            ],
        )
        .expect("runtime result");
        let strategy = result.strategy.expect("strategy output");

        assert_eq!(strategy.orders.len(), 2, "{name}");
        assert_eq!(strategy.orders[1].id, "BQP", "{name}");
        assert_eq!(strategy.orders[1].qty, 0.75, "{name}");
        assert_eq!(strategy.orders[1].price, expected_price, "{name}");
        assert_eq!(strategy.trades.len(), 1, "{name}");
        assert_eq!(strategy.trades[0].qty, 0.75, "{name}");
        assert_eq!(strategy.position[1].size, 1.25, "{name}");
        assert!(strategy.diagnostics.is_empty(), "{name}");
    }
}

#[test]
fn strategy_exit_qty_trailing_dispatches_partial_quantity() {
    let source = SourceFile::new(
        "strategy_exit_qty_trailing.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.exit("TQ", "L", trail_points=100, trail_offset=50, qty=0.5)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(100.0, 100.0, 100.0, 100.0),
            bar_ohlc(100.0, 102.0, 101.75, 102.0),
            bar_ohlc(102.0, 102.0, 101.0, 101.25),
            bar_ohlc(101.25, 101.25, 101.0, 101.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "TQ");
    assert_eq!(strategy.orders[1].bar_index, 3);
    assert_eq!(strategy.orders[1].qty, 0.5);
    assert_eq!(strategy.orders[1].price, 101.5);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].qty, 0.5);
    assert_eq!(strategy.trades[0].exit_price, 101.5);
    assert_eq!(strategy.position[1].size, 1.5);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_qty_percent_trailing_dispatches_partial_quantity() {
    let source = SourceFile::new(
        "strategy_exit_qty_percent_trailing.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.exit("TP", "L", trail_points=100, trail_offset=50, qty_percent=25)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(100.0, 100.0, 100.0, 100.0),
            bar_ohlc(100.0, 102.0, 101.75, 102.0),
            bar_ohlc(102.0, 102.0, 101.0, 101.25),
            bar_ohlc(101.25, 101.25, 101.0, 101.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "TP");
    assert_eq!(strategy.orders[1].bar_index, 3);
    assert_eq!(strategy.orders[1].qty, 0.5);
    assert_eq!(strategy.orders[1].price, 101.5);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].qty, 0.5);
    assert_eq!(strategy.position[1].size, 1.5);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_qty_and_qty_percent_trailing_uses_qty() {
    let source = SourceFile::new(
        "strategy_exit_qty_and_qty_percent_trailing.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.exit("TQP", "L", trail_points=100, trail_offset=50, qty=0.75, qty_percent=25)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(100.0, 100.0, 100.0, 100.0),
            bar_ohlc(100.0, 102.0, 101.75, 102.0),
            bar_ohlc(102.0, 102.0, 101.0, 101.25),
            bar_ohlc(101.25, 101.25, 101.0, 101.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "TQP");
    assert_eq!(strategy.orders[1].bar_index, 3);
    assert_eq!(strategy.orders[1].qty, 0.75);
    assert_eq!(strategy.orders[1].price, 101.5);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].qty, 0.75);
    assert_eq!(strategy.trades[0].exit_price, 101.5);
    assert_eq!(strategy.position[1].size, 1.25);
    assert!(strategy.diagnostics.is_empty());
}

#[test]
fn strategy_exit_bracket_invalid_downside_price_preempts_upside_tick_diagnostic() {
    let source = SourceFile::new(
        "strategy_exit_bracket_invalid_order.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.exit("XB", "L", stop=close / (close - close), profit=0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(100.0), bar(100.0)])
        .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.trades.is_empty());
    assert_eq!(strategy.diagnostics.len(), 1);
    assert_eq!(strategy.diagnostics[0].code, "E_STRATEGY_EXIT_PRICE");
}

#[test]
fn strategy_exit_invalid_bracket_preserves_existing_pending_exit() {
    let source = SourceFile::new(
        "strategy_exit_bracket_invalid_preserves_pending.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("KEEP", "L", limit=120)
if bar_index == 1
    strategy.exit("BAD", "L", stop=95, profit=0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(100.0, 100.0, 100.0, 100.0),
            bar_ohlc(100.0, 110.0, 100.0, 100.0),
            bar_ohlc(100.0, 121.0, 100.0, 100.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "KEEP");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].price, 120.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_price, 120.0);
    assert_eq!(strategy.diagnostics.len(), 1);
    assert_eq!(strategy.diagnostics[0].code, "E_STRATEGY_EXIT_TICKS");
}

#[test]
fn strategy_exit_invalid_qty_preserves_existing_pending_exit() {
    let source = SourceFile::new(
        "strategy_exit_invalid_qty_preserves_pending.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("KEEP", "L", limit=120)
if bar_index == 1
    strategy.exit("BAD", "L", stop=95, qty=0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(100.0, 100.0, 100.0, 100.0),
            bar_ohlc(100.0, 110.0, 100.0, 100.0),
            bar_ohlc(100.0, 121.0, 94.0, 100.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "KEEP");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 120.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_price, 120.0);
    assert_eq!(strategy.diagnostics.len(), 1);
    assert_eq!(strategy.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn strategy_exit_invalid_qty_percent_preserves_existing_pending_exit() {
    let source = SourceFile::new(
        "strategy_exit_invalid_qty_percent_preserves_pending.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("KEEP", "L", limit=120)
if bar_index == 1
    strategy.exit("BAD", "L", stop=95, qty_percent=0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(100.0, 100.0, 100.0, 100.0),
            bar_ohlc(100.0, 110.0, 100.0, 100.0),
            bar_ohlc(100.0, 121.0, 94.0, 100.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].id, "KEEP");
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].qty, 2.0);
    assert_eq!(strategy.orders[1].price, 120.0);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_price, 120.0);
    assert_eq!(strategy.diagnostics.len(), 1);
    assert_eq!(strategy.diagnostics[0].code, "E_STRATEGY_EXIT_QTY_PERCENT");
}

#[test]
fn strategy_exit_bracket_runtime_json_uses_existing_strategy_shape() {
    let source = SourceFile::new(
        "strategy_exit_bracket_json_shape.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("XB", "L", stop=95, limit=110)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(100.0, 100.0, 100.0, 100.0),
            bar_ohlc(100.0, 111.0, 100.0, 100.0),
        ],
    )
    .expect("runtime result");
    let output = public_runtime_result_json(&result);

    assert!(output.contains(r#""strategy":{"orders":"#));
    assert!(!output.contains("pending"));
    assert!(!output.contains("bracket"));
    assert!(!output.contains("leg"));
    assert!(!output.contains("exitReason"));
}

#[test]
fn strategy_close_cancels_pending_limit_before_evaluation() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("XL", "L", limit=12)
if bar_index == 1
    strategy.close("L")
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(11.0, 12.0, 10.0, 11.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].exit_price, 11.0);
}

#[test]
fn strategy_initial_capital_and_equity_mark_open_position_to_close() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("equity", initial_capital=1000)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=10)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .initial_capital,
        1000.0
    );

    let bars = [
        Bar {
            time: 10,
            open: 10.0,
            high: 10.0,
            low: 10.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 20,
            open: 9.0,
            high: 9.0,
            low: 9.0,
            close: 9.0,
            volume: 1.0,
        },
        Bar {
            time: 30,
            open: 12.0,
            high: 12.0,
            low: 12.0,
            close: 12.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(strategy.equity.len(), 3);
    assert_eq!(strategy.equity[0].cash, 1000.0);
    assert_eq!(strategy.equity[0].market_value, 0.0);
    assert_eq!(strategy.equity[0].equity, 1000.0);
    assert_eq!(strategy.equity[1].cash, 910.0);
    assert_eq!(strategy.equity[1].market_value, 90.0);
    assert_eq!(strategy.equity[1].equity, 1000.0);
    assert_eq!(strategy.equity[1].net_profit, 0.0);
    assert_eq!(strategy.equity[2].cash, 910.0);
    assert_eq!(strategy.equity[2].market_value, 120.0);
    assert_eq!(strategy.equity[2].equity, 1030.0);
    assert_eq!(strategy.equity[2].net_profit, 30.0);
}

#[test]
fn strategy_cash_per_contract_commission_updates_profit_and_trade_fields() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("commission", commission_type=strategy.commission.cash_per_contract, commission_value=0.5)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 2
    strategy.close("L")
plot(strategy.opentrades.commission(0))
plot(strategy.closedtrades.commission(0))
plot(strategy.netprofit)
plot(strategy.equity)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis.hir.as_ref().unwrap().strategy_settings.commission,
        Some(pine_ir::StrategyCommission::CashPerContract(0.5))
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
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
            Bar {
                time: 4,
                open: 4.0,
                high: 4.0,
                low: 4.0,
                close: 4.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Na,
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Float(100_000.0),
            PineValue::Float(99_999.0),
            PineValue::Float(100_000.0),
            PineValue::Float(100_000.0),
        ]
    );

    let strategy = result.strategy.expect("strategy output");
    assert_eq!(strategy.trades[0].profit, 0.0);
    assert_eq!(strategy.equity[1].cash, 99_995.0);
    assert_eq!(strategy.equity[1].equity, 99_999.0);
    assert_eq!(strategy.equity[2].cash, 100_000.0);
}

#[test]
fn strategy_cash_per_order_commission_updates_profit_and_trade_fields() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("commission", commission_type=strategy.commission.cash_per_order, commission_value=1.5)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 2
    strategy.close("L")
plot(strategy.opentrades.commission(0))
plot(strategy.closedtrades.commission(0))
plot(strategy.netprofit)
plot(strategy.equity)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis.hir.as_ref().unwrap().strategy_settings.commission,
        Some(pine_ir::StrategyCommission::CashPerOrder(1.5))
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
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
            Bar {
                time: 4,
                open: 4.0,
                high: 4.0,
                low: 4.0,
                close: 4.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Float(1.5),
            PineValue::Na,
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(-1.0),
            PineValue::Float(-1.0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Float(100_000.0),
            PineValue::Float(99_998.5),
            PineValue::Float(99_999.0),
            PineValue::Float(99_999.0),
        ]
    );

    let strategy = result.strategy.expect("strategy output");
    assert_eq!(strategy.trades[0].profit, -1.0);
    assert_eq!(strategy.equity[1].cash, 99_994.5);
    assert_eq!(strategy.equity[1].equity, 99_998.5);
    assert_eq!(strategy.equity[2].cash, 99_999.0);
}

#[test]
fn strategy_percent_commission_updates_profit_and_trade_fields() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("commission", commission_type=strategy.commission.percent, commission_value=10)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 2
    strategy.close("L")
plot(strategy.opentrades.commission(0))
plot(strategy.closedtrades.commission(0))
plot(strategy.netprofit)
plot(strategy.equity)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis.hir.as_ref().unwrap().strategy_settings.commission,
        Some(pine_ir::StrategyCommission::Percent(10.0))
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.4),
            PineValue::Na,
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Float(100_000.0),
            PineValue::Float(99_999.6),
            PineValue::Float(100_001.0),
            PineValue::Float(100_001.0),
        ]
    );

    let strategy = result.strategy.expect("strategy output");
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert_eq!(strategy.equity[1].cash, 99_995.6);
    assert_eq!(strategy.equity[1].equity, 99_999.6);
    assert_eq!(strategy.equity[2].cash, 100_001.0);
}

#[test]
fn strategy_slippage_updates_fill_prices_profit_and_equity() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("slippage", slippage=100)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 2
    strategy.close("L")
plot(strategy.closedtrades.entry_price(0))
plot(strategy.closedtrades.exit_price(0))
plot(strategy.closedtrades.profit(0))
plot(strategy.equity)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .slippage_ticks,
        100.0
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
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
            Bar {
                time: 4,
                open: 4.0,
                high: 4.0,
                low: 4.0,
                close: 4.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(-2.0),
            PineValue::Float(-2.0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Float(100_000.0),
            PineValue::Float(99_998.0),
            PineValue::Float(99_998.0),
            PineValue::Float(99_998.0),
        ]
    );

    let strategy = result.strategy.expect("strategy output");
    assert_eq!(strategy.orders[0].price, 3.0);
    assert_eq!(strategy.trades[0].entry_price, 3.0);
    assert_eq!(strategy.trades[0].exit_price, 2.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
}

#[test]
fn strategy_slippage_updates_pending_exit_fill_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("exit slippage", slippage=100)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("XL", "L", limit=3)
plot(strategy.closedtrades.exit_price(0))
plot(strategy.closedtrades.profit(0))
plot(strategy.equity)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
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
            Bar {
                time: 4,
                open: 4.0,
                high: 4.0,
                low: 4.0,
                close: 4.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(-2.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(100_000.0),
            PineValue::Float(99_998.0),
            PineValue::Float(100_000.0),
            PineValue::Float(99_998.0),
        ]
    );

    let strategy = result.strategy.expect("strategy output");
    assert_eq!(strategy.orders[0].price, 3.0);
    assert_eq!(strategy.orders[1].price, 2.0);
    assert_eq!(strategy.trades[0].entry_price, 3.0);
    assert_eq!(strategy.trades[0].exit_price, 2.0);
    assert_eq!(strategy.trades[0].profit, -2.0);
}

#[test]
fn strategy_limit_verification_delays_limit_entry_until_price_moves_past_limit() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("limit verification", backtest_fill_limits_assumption=100)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2, limit=100)
plot(strategy.position_size)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert_eq!(
        analysis
            .hir
            .as_ref()
            .unwrap()
            .strategy_settings
            .backtest_fill_limit_ticks,
        100.0
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            Bar {
                time: 1,
                open: 101.0,
                high: 101.0,
                low: 101.0,
                close: 101.0,
                volume: 1.0,
            },
            Bar {
                time: 2,
                open: 100.0,
                high: 101.0,
                low: 99.5,
                close: 100.0,
                volume: 1.0,
            },
            Bar {
                time: 3,
                open: 100.0,
                high: 100.0,
                low: 99.0,
                close: 100.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    let strategy = result.strategy.expect("strategy output");
    assert_eq!(strategy.orders.len(), 1);
    assert_eq!(strategy.orders[0].bar_index, 2);
    assert_eq!(strategy.orders[0].price, 100.0);
    assert!(strategy.trades.is_empty());
}

#[test]
fn strategy_limit_verification_delays_limit_exit_but_keeps_limit_fill_price() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("limit verification", backtest_fill_limits_assumption=100)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("XL", "L", limit=12)
plot(strategy.closedtrades.exit_price(0))
plot(strategy.closedtrades.profit(0))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            Bar {
                time: 1,
                open: 10.0,
                high: 10.0,
                low: 10.0,
                close: 10.0,
                volume: 1.0,
            },
            Bar {
                time: 2,
                open: 11.0,
                high: 12.0,
                low: 10.0,
                close: 11.0,
                volume: 1.0,
            },
            Bar {
                time: 3,
                open: 12.0,
                high: 13.0,
                low: 11.0,
                close: 12.0,
                volume: 1.0,
            },
            Bar {
                time: 4,
                open: 12.0,
                high: 12.0,
                low: 12.0,
                close: 12.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(12.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
        ]
    );
    let strategy = result.strategy.expect("strategy output");
    assert_eq!(strategy.orders.len(), 2);
    assert_eq!(strategy.orders[1].bar_index, 2);
    assert_eq!(strategy.orders[1].price, 12.0);
    assert_eq!(strategy.trades[0].exit_price, 12.0);
    assert_eq!(strategy.trades[0].profit, 2.0);
}

#[test]
fn strategy_close_without_matching_position_is_noop() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("close")
strategy.close("L")
strategy.entry("L", strategy.long, qty=1)
strategy.close("other")
strategy.close("L")
strategy.close("L")
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert!(strategy.trades.is_empty());
    assert!(strategy.position.is_empty());
}

#[test]
fn strategy_account_currency_inherits_default_symbol_currency() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("account currency")
identity(value) => value
plot(strategy.account_currency == "USD" ? 1 : 0)
plot(identity(strategy.account_currency) == "USD" ? 1 : 0)
plot(na(strategy.account_currency[1]) ? na : strategy.account_currency[1] == "USD" ? 1 : 0)
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

    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Int(1), PineValue::Int(1), PineValue::Int(1)]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(1), PineValue::Int(1), PineValue::Int(1)]
    );
    assert_eq!(
        result.plots[2].values,
        vec![PineValue::Na, PineValue::Int(1), PineValue::Int(1)]
    );
}

#[test]
fn strategy_position_state_variables_follow_broker_mutations() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("position state")
identity(value) => value
position_entry_name = strategy.position_entry_name
position_entry_name_udf = identity(strategy.position_entry_name)
position_entry_name_history = strategy.position_entry_name[1]
plot(strategy.position_size)
plot(strategy.position_avg_price)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=2)
plot(strategy.position_size)
plot(strategy.position_avg_price)
independent_position_avg_price = strategy.position_avg_price * 0
position_avg_price_i = 0
while position_avg_price_i < 1
    independent_position_avg_price := strategy.position_avg_price
    position_avg_price_i := position_avg_price_i + 1
plot(independent_position_avg_price)
plot(identity(strategy.position_avg_price))
position_avg_price_history = strategy.position_avg_price[1]
if bar_index == 2
    strategy.close("L")
plot(strategy.position_size)
plot(strategy.position_avg_price)
plot(strategy.max_contracts_held_all)
plot(identity(strategy.max_contracts_held_all))
independent_max_contracts_held_all = strategy.max_contracts_held_all * 0
max_contracts_held_all_i = 0
while max_contracts_held_all_i < 1
    independent_max_contracts_held_all := strategy.max_contracts_held_all
    max_contracts_held_all_i := max_contracts_held_all_i + 1
plot(independent_max_contracts_held_all)
plot(strategy.max_contracts_held_long)
plot(identity(strategy.max_contracts_held_long))
independent_max_contracts_held_long = strategy.max_contracts_held_long * 0
max_contracts_held_long_i = 0
while max_contracts_held_long_i < 1
    independent_max_contracts_held_long := strategy.max_contracts_held_long
    max_contracts_held_long_i := max_contracts_held_long_i + 1
plot(independent_max_contracts_held_long)
plot(strategy.max_contracts_held_short)
plot(identity(strategy.max_contracts_held_short))
independent_max_contracts_held_short = strategy.max_contracts_held_short * 0
max_contracts_held_short_i = 0
while max_contracts_held_short_i < 1
    independent_max_contracts_held_short := strategy.max_contracts_held_short
    max_contracts_held_short_i := max_contracts_held_short_i + 1
plot(independent_max_contracts_held_short)
plot(position_avg_price_history)
plot(strategy.max_contracts_held_all[1])
plot(strategy.max_contracts_held_long[1])
plot(strategy.max_contracts_held_short[1])
plot(na(position_entry_name) ? na : position_entry_name == "L" ? 1 : 0)
plot(na(position_entry_name_udf) ? na : position_entry_name_udf == "L" ? 1 : 0)
plot(na(position_entry_name_history) ? na : position_entry_name_history == "L" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[4].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[5].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
            PineValue::Na,
        ]
    );
    assert_eq!(
        result.plots[6].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[7].values,
        vec![PineValue::Na, PineValue::Na, PineValue::Na, PineValue::Na,]
    );
    assert_eq!(
        result.plots[8].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[9].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[10].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[11].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[12].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[13].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[14].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[15].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[16].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[17].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        result.plots[18].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[19].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[20].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    let position_entry_name = vec![
        PineValue::Na,
        PineValue::Na,
        PineValue::Int(1),
        PineValue::Na,
    ];
    assert_eq!(result.plots[21].values, position_entry_name.clone());
    assert_eq!(result.plots[22].values, position_entry_name);
    assert_eq!(
        result.plots[23].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Int(1)
        ]
    );
}

#[test]
fn strategy_position_entry_name_tracks_the_continuous_net_position() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("position entry name", pyramiding=2)
if bar_index == 0
    strategy.entry("A", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("B", strategy.long, qty=1)
if bar_index == 2
    strategy.close("A")
if bar_index == 3
    strategy.close("B")
if bar_index == 4
    strategy.entry("C", strategy.long, qty=1)
plot(na(strategy.position_entry_name) ? na : strategy.position_entry_name == "A" ? 1 : strategy.position_entry_name == "C" ? 2 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0), bar(5.0), bar(6.0)],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Na,
            PineValue::Na,
            PineValue::Int(2),
        ]
    );
}

#[test]
fn strategy_capital_held_history_reads_follow_margin_state() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("margin capital held", margin_long=50)
identity(value) => value
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 3
    strategy.close("L")
plot(strategy.opentrades.capital_held)
independent_capital_held = strategy.opentrades.capital_held * 0
capital_held_i = 0
while capital_held_i < 1
    independent_capital_held := strategy.opentrades.capital_held
    capital_held_i := capital_held_i + 1
plot(independent_capital_held)
plot(identity(strategy.opentrades.capital_held))
plot(strategy.opentrades.capital_held[1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");

    let current_values = vec![
        PineValue::Float(0.0),
        PineValue::Float(2.0),
        PineValue::Float(3.0),
        PineValue::Float(0.0),
    ];
    assert_eq!(result.plots[0].values, current_values);
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0),
        ]
    );
}

#[test]
fn strategy_trade_count_variables_follow_entry_and_close_mutations() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("trade count state")
plot(strategy.closedtrades)
plot(strategy.opentrades)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=2)
plot(strategy.closedtrades)
plot(strategy.opentrades)
independent_opentrades = strategy.opentrades * 0
opentrades_i = 0
while opentrades_i < 1
    independent_opentrades := strategy.opentrades
    opentrades_i := opentrades_i + 1
if bar_index == 2
    strategy.close("L")
plot(strategy.closedtrades)
plot(strategy.opentrades)
independent_closedtrades = strategy.closedtrades * 0
closedtrades_i = 0
while closedtrades_i < 1
    independent_closedtrades := strategy.closedtrades
    closedtrades_i := closedtrades_i + 1
plot(independent_closedtrades)
plot(independent_opentrades)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[4].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[5].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[6].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[7].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_closed_trade_field_functions_read_recorded_trades() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("closed trade fields")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 1
    strategy.close("L")
plot(strategy.closedtrades.entry_price(0))
plot(strategy.closedtrades.entry_id(0) == "L" ? 1 : 0)
plot(strategy.closedtrades.exit_price(0))
plot(strategy.closedtrades.exit_id(0) == "L" ? 1 : 0)
plot(strategy.closedtrades.entry_bar_index(0))
plot(strategy.closedtrades.exit_bar_index(0))
plot(strategy.closedtrades.entry_time(0))
plot(strategy.closedtrades.exit_time(0))
plot(strategy.closedtrades.commission(0))
plot(strategy.closedtrades.size(0))
plot(strategy.closedtrades.profit(0))
plot(strategy.closedtrades.max_runup(0))
plot(strategy.closedtrades.max_drawdown(0))
plot(na(strategy.closedtrades.entry_id(1)) ? 1 : 0)
plot(na(strategy.closedtrades.exit_id(1)) ? 1 : 0)
plot(strategy.closedtrades.entry_price(1))
plot(strategy.closedtrades.entry_price(-1))
plot(strategy.closedtrades.entry_price(0.5))
plot(strategy.closedtrades.profit_percent(0))
plot(strategy.closedtrades.max_runup_percent(0))
plot(strategy.closedtrades.max_drawdown_percent(0))
plot(strategy.closedtrades.profit_percent(1))
plot(strategy.closedtrades.max_runup_percent(-1))
plot(strategy.closedtrades.max_drawdown_percent(0.5))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            Bar {
                time: 10,
                open: 1.0,
                high: 1.0,
                low: 1.0,
                close: 1.0,
                volume: 1.0,
            },
            Bar {
                time: 20,
                open: 2.0,
                high: 3.0,
                low: 1.0,
                close: 3.0,
                volume: 1.0,
            },
            Bar {
                time: 30,
                open: 4.0,
                high: 4.0,
                low: 4.0,
                close: 4.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Float(2.0),]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(0), PineValue::Int(1), PineValue::Int(1)]
    );
    assert_eq!(
        result.plots[2].values,
        vec![PineValue::Na, PineValue::Float(3.0), PineValue::Float(3.0),]
    );
    assert_eq!(
        result.plots[3].values,
        vec![PineValue::Int(0), PineValue::Int(1), PineValue::Int(1)]
    );
    assert_eq!(
        result.plots[4].values,
        vec![PineValue::Na, PineValue::Int(1), PineValue::Int(1)]
    );
    assert_eq!(
        result.plots[5].values,
        vec![PineValue::Na, PineValue::Int(1), PineValue::Int(1)]
    );
    assert_eq!(
        result.plots[6].values,
        vec![PineValue::Na, PineValue::Int(20), PineValue::Int(20)]
    );
    assert_eq!(
        result.plots[7].values,
        vec![PineValue::Na, PineValue::Int(20), PineValue::Int(20)]
    );
    assert_eq!(
        result.plots[8].values,
        vec![PineValue::Na, PineValue::Float(0.0), PineValue::Float(0.0),]
    );
    assert_eq!(
        result.plots[9].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Float(2.0),]
    );
    assert_eq!(
        result.plots[10].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Float(2.0),]
    );
    assert_eq!(
        result.plots[11].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Float(2.0),]
    );
    assert_eq!(
        result.plots[12].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Float(2.0),]
    );
    assert_eq!(
        result.plots[13].values,
        vec![PineValue::Int(1), PineValue::Int(1), PineValue::Int(1)]
    );
    assert_eq!(
        result.plots[14].values,
        vec![PineValue::Int(1), PineValue::Int(1), PineValue::Int(1)]
    );
    for values in result.plots[15..18].iter().map(|plot| &plot.values) {
        assert_eq!(values, &vec![PineValue::Na, PineValue::Na, PineValue::Na]);
    }
    for values in result.plots[18..21].iter().map(|plot| &plot.values) {
        assert_eq!(
            values,
            &vec![
                PineValue::Na,
                PineValue::Float(50.0),
                PineValue::Float(50.0),
            ]
        );
    }
    for values in result.plots[21..].iter().map(|plot| &plot.values) {
        assert_eq!(values, &vec![PineValue::Na, PineValue::Na, PineValue::Na]);
    }
}

#[test]
fn strategy_open_trade_fields_read_current_position() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("open trade fields")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 2
    strategy.close("L")
plot(strategy.opentrades.entry_price(0))
plot(na(strategy.opentrades.entry_id(0)) ? na : strategy.opentrades.entry_id(0) == "L" ? 1 : 0)
plot(strategy.opentrades.entry_bar_index(0))
plot(strategy.opentrades.entry_time(0))
plot(strategy.opentrades.size(0))
plot(strategy.opentrades.profit(0))
plot(strategy.opentrades.commission(0))
plot(strategy.opentrades.max_runup(0))
plot(strategy.opentrades.max_drawdown(0))
plot(strategy.opentrades.capital_held)
plot(strategy.opentrades.entry_price(1))
plot(na(strategy.opentrades.entry_id(1)) ? na : 0)
plot(strategy.opentrades.entry_bar_index(1))
plot(strategy.opentrades.entry_time(1))
plot(strategy.opentrades.size(1))
plot(strategy.opentrades.profit(1))
plot(strategy.opentrades.commission(1))
plot(strategy.opentrades.max_runup(1))
plot(strategy.opentrades.max_drawdown(1))
plot(strategy.opentrades.entry_price(-1))
plot(na(strategy.opentrades.entry_id(-1)) ? na : 0)
plot(strategy.opentrades.entry_bar_index(-1))
plot(strategy.opentrades.entry_time(-1))
plot(strategy.opentrades.size(-1))
plot(strategy.opentrades.profit(-1))
plot(strategy.opentrades.commission(-1))
plot(strategy.opentrades.max_runup(-1))
plot(strategy.opentrades.max_drawdown(-1))
plot(strategy.opentrades.entry_price(0.5))
plot(na(strategy.opentrades.entry_id(0.5)) ? na : 0)
plot(strategy.opentrades.entry_bar_index(0.5))
plot(strategy.opentrades.entry_time(0.5))
plot(strategy.opentrades.size(0.5))
plot(strategy.opentrades.profit(0.5))
plot(strategy.opentrades.commission(0.5))
plot(strategy.opentrades.max_runup(0.5))
plot(strategy.opentrades.max_drawdown(0.5))
plot(strategy.opentrades.profit_percent(0))
plot(strategy.opentrades.max_runup_percent(0))
plot(strategy.opentrades.max_drawdown_percent(0))
plot(strategy.opentrades.profit_percent(1))
plot(strategy.opentrades.max_runup_percent(-1))
plot(strategy.opentrades.max_drawdown_percent(0.5))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            Bar {
                time: 10,
                open: 1.0,
                high: 1.0,
                low: 1.0,
                close: 1.0,
                volume: 1.0,
            },
            Bar {
                time: 20,
                open: 2.0,
                high: 4.0,
                low: 1.0,
                close: 2.0,
                volume: 1.0,
            },
            Bar {
                time: 30,
                open: 3.0,
                high: 3.0,
                low: 3.0,
                close: 3.0,
                volume: 1.0,
            },
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Na, PineValue::Int(1), PineValue::Na]
    );
    assert_eq!(
        result.plots[2].values,
        vec![PineValue::Na, PineValue::Int(1), PineValue::Na]
    );
    assert_eq!(
        result.plots[3].values,
        vec![PineValue::Na, PineValue::Int(20), PineValue::Na]
    );
    assert_eq!(
        result.plots[4].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[5].values,
        vec![PineValue::Na, PineValue::Float(0.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[6].values,
        vec![PineValue::Na, PineValue::Float(0.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[7].values,
        vec![PineValue::Na, PineValue::Float(4.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[8].values,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[9].values,
        vec![PineValue::Na, PineValue::Na, PineValue::Na]
    );
    for plot in &result.plots[10..37] {
        assert_eq!(
            plot.values,
            vec![PineValue::Na, PineValue::Na, PineValue::Na]
        );
    }
    assert_eq!(
        result.plots[37].values,
        vec![PineValue::Na, PineValue::Float(0.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[38].values,
        vec![PineValue::Na, PineValue::Float(100.0), PineValue::Na]
    );
    assert_eq!(
        result.plots[39].values,
        vec![PineValue::Na, PineValue::Float(50.0), PineValue::Na]
    );
    for plot in &result.plots[40..] {
        assert_eq!(
            plot.values,
            vec![PineValue::Na, PineValue::Na, PineValue::Na]
        );
    }
}

#[test]
fn strategy_closed_trade_exit_id_reads_pending_exit_identity() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("closed trade exit id")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=2)
    strategy.exit("XL", "L", limit=12)
plot(strategy.closedtrades.exit_id(0) == "XL" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(10.0, 10.0, 10.0, 10.0),
            bar_ohlc(11.0, 12.0, 10.0, 11.0),
            bar_ohlc(13.0, 13.0, 13.0, 13.0),
        ],
    )
    .expect("runtime result");
    let strategy = result.strategy.expect("strategy output");

    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Int(0), PineValue::Int(0), PineValue::Int(1)]
    );
    assert_eq!(strategy.trades.len(), 1);
    assert_eq!(strategy.trades[0].id, "L");
    assert_eq!(strategy.trades[0].exit_id, "XL");
}

#[test]
fn strategy_trade_outcome_count_variables_follow_closed_trade_profits() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("trade outcome counts")
identity(value) => value
if bar_index == 0
    strategy.entry("W", strategy.long, qty=1)
if bar_index == 2
    strategy.close("W")
if bar_index == 3
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 5
    strategy.close("L")
if bar_index == 6
    strategy.entry("E", strategy.long, qty=1)
if bar_index == 8
    strategy.close("E")
plot(strategy.wintrades)
plot(strategy.losstrades)
plot(strategy.eventrades)
plot(strategy.closedtrades)
plot(strategy.grossprofit)
plot(strategy.grossloss)
plot(strategy.avg_trade)
plot(strategy.avg_trade_percent)
plot(strategy.avg_winning_trade)
plot(strategy.avg_winning_trade_percent)
plot(strategy.avg_losing_trade)
plot(strategy.avg_losing_trade_percent)
independent_wintrades = strategy.wintrades * 0
wintrades_i = 0
while wintrades_i < 1
    independent_wintrades := strategy.wintrades
    wintrades_i := wintrades_i + 1
plot(independent_wintrades)
independent_losstrades = strategy.losstrades * 0
losstrades_i = 0
while losstrades_i < 1
    independent_losstrades := strategy.losstrades
    losstrades_i := losstrades_i + 1
plot(independent_losstrades)
independent_eventrades = strategy.eventrades * 0
eventrades_i = 0
while eventrades_i < 1
    independent_eventrades := strategy.eventrades
    eventrades_i := eventrades_i + 1
plot(independent_eventrades)
independent_grossprofit = strategy.grossprofit * 0
grossprofit_i = 0
while grossprofit_i < 1
    independent_grossprofit := strategy.grossprofit
    grossprofit_i := grossprofit_i + 1
plot(independent_grossprofit)
independent_grossloss = strategy.grossloss * 0
grossloss_i = 0
while grossloss_i < 1
    independent_grossloss := strategy.grossloss
    grossloss_i := grossloss_i + 1
plot(independent_grossloss)
independent_avg_trade = strategy.avg_trade * 0
avg_trade_i = 0
while avg_trade_i < 1
    independent_avg_trade := strategy.avg_trade
    avg_trade_i := avg_trade_i + 1
plot(independent_avg_trade)
independent_avg_trade_percent = strategy.avg_trade_percent * 0
avg_trade_percent_i = 0
while avg_trade_percent_i < 1
    independent_avg_trade_percent := strategy.avg_trade_percent
    avg_trade_percent_i := avg_trade_percent_i + 1
plot(independent_avg_trade_percent)
independent_avg_winning_trade = strategy.avg_winning_trade * 0
avg_winning_trade_i = 0
while avg_winning_trade_i < 1
    independent_avg_winning_trade := strategy.avg_winning_trade
    avg_winning_trade_i := avg_winning_trade_i + 1
plot(independent_avg_winning_trade)
independent_avg_winning_trade_percent = strategy.avg_winning_trade_percent * 0
avg_winning_trade_percent_i = 0
while avg_winning_trade_percent_i < 1
    independent_avg_winning_trade_percent := strategy.avg_winning_trade_percent
    avg_winning_trade_percent_i := avg_winning_trade_percent_i + 1
plot(independent_avg_winning_trade_percent)
independent_avg_losing_trade = strategy.avg_losing_trade * 0
avg_losing_trade_i = 0
while avg_losing_trade_i < 1
    independent_avg_losing_trade := strategy.avg_losing_trade
    avg_losing_trade_i := avg_losing_trade_i + 1
plot(independent_avg_losing_trade)
independent_avg_losing_trade_percent = strategy.avg_losing_trade_percent * 0
avg_losing_trade_percent_i = 0
while avg_losing_trade_percent_i < 1
    independent_avg_losing_trade_percent := strategy.avg_losing_trade_percent
    avg_losing_trade_percent_i := avg_losing_trade_percent_i + 1
plot(independent_avg_losing_trade_percent)
plot(identity(strategy.grossprofit))
plot(identity(strategy.grossloss))
plot(identity(strategy.avg_trade))
plot(identity(strategy.avg_trade_percent))
plot(identity(strategy.avg_winning_trade))
plot(identity(strategy.avg_winning_trade_percent))
plot(identity(strategy.avg_losing_trade))
plot(identity(strategy.avg_losing_trade_percent))
plot(strategy.grossprofit[1])
plot(strategy.grossloss[1])
plot(strategy.avg_trade[1])
plot(strategy.avg_trade_percent[1])
plot(strategy.avg_winning_trade[1])
plot(strategy.avg_winning_trade_percent[1])
plot(strategy.avg_losing_trade[1])
plot(strategy.avg_losing_trade_percent[1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(1.0),
            bar(2.0),
            bar(3.0),
            bar(4.0),
            bar(4.0),
            bar(2.0),
            bar(3.0),
            bar(5.0),
            bar(5.0),
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(2),
            PineValue::Int(3),
        ]
    );
    assert_eq!(
        result.plots[4].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[5].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[6].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
            PineValue::Float(-1.0 / 3.0),
        ]
    );
    assert_eq!(
        result.plots[7].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[8].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[9].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    assert_eq!(
        result.plots[10].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[11].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    assert_eq!(
        result.plots[12].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[13].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[14].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[15].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[16].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[17].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
            PineValue::Float(-1.0 / 3.0),
        ]
    );
    assert_eq!(
        result.plots[18].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[19].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[20].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    assert_eq!(
        result.plots[21].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[22].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    assert_eq!(
        result.plots[23].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[24].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[25].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
            PineValue::Float(-1.0 / 3.0),
        ]
    );
    assert_eq!(
        result.plots[26].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[27].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[28].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    assert_eq!(
        result.plots[29].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[30].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    assert_eq!(
        result.plots[31].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[32].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[33].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
            PineValue::Float(-0.5),
        ]
    );
    assert_eq!(
        result.plots[34].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[35].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
            PineValue::Float(1.0),
        ]
    );
    assert_eq!(
        result.plots[36].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    assert_eq!(
        result.plots[37].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[38].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(50.0),
            PineValue::Float(50.0),
            PineValue::Float(50.0),
        ]
    );
    let strategy = result.strategy.as_ref().expect("strategy result");
    assert_eq!(strategy.trades.len(), 3);
    assert_eq!(strategy.trades[0].profit, 1.0);
    assert_eq!(strategy.trades[1].profit, -2.0);
    assert_eq!(strategy.trades[2].profit, 0.0);
}

#[test]
fn strategy_buy_and_hold_return_percent_uses_first_close_denominator() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("buy and hold")
identity(value) => value
plot(strategy.buy_and_hold_return_percent)
plot(identity(strategy.buy_and_hold_return_percent))
independent_buy_and_hold = strategy.buy_and_hold_return_percent * 0
buy_and_hold_i = 0
while buy_and_hold_i < 1
    independent_buy_and_hold := strategy.buy_and_hold_return_percent
    buy_and_hold_i := buy_and_hold_i + 1
plot(independent_buy_and_hold)
plot(strategy.buy_and_hold_return_percent[1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(2.0), bar(3.0), bar(5.0)])
        .expect("runtime result");
    let expected = vec![
        PineValue::Float(0.0),
        PineValue::Float(50.0),
        PineValue::Float(150.0),
    ];

    assert_eq!(result.plots[0].values, expected);
    assert_eq!(result.plots[1].values, result.plots[0].values);
    assert_eq!(result.plots[2].values, result.plots[0].values);
    assert_eq!(
        result.plots[3].values,
        vec![PineValue::Na, PineValue::Float(0.0), PineValue::Float(50.0)]
    );
}

#[test]
fn strategy_profit_percent_variables_use_documented_denominators() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("profit percent", initial_capital=1000)
identity(value) => value
openprofit_percent = strategy.openprofit_percent
openprofit_percent_udf = identity(strategy.openprofit_percent)
openprofit_percent_history = strategy.openprofit_percent[1]
if bar_index == 0
    strategy.entry("W", strategy.long, qty=1)
if bar_index == 2
    strategy.close("W")
if bar_index == 3
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 5
    strategy.close("L")
plot(strategy.netprofit_percent)
plot(identity(strategy.netprofit_percent))
plot(strategy.grossprofit_percent)
plot(strategy.grossloss_percent)
independent_netprofit_percent = strategy.netprofit_percent * 0
netprofit_percent_i = 0
while netprofit_percent_i < 1
    independent_netprofit_percent := strategy.netprofit_percent
    netprofit_percent_i := netprofit_percent_i + 1
plot(independent_netprofit_percent)
independent_grossprofit_percent = strategy.grossprofit_percent * 0
grossprofit_percent_i = 0
while grossprofit_percent_i < 1
    independent_grossprofit_percent := strategy.grossprofit_percent
    grossprofit_percent_i := grossprofit_percent_i + 1
plot(independent_grossprofit_percent)
independent_grossloss_percent = strategy.grossloss_percent * 0
grossloss_percent_i = 0
while grossloss_percent_i < 1
    independent_grossloss_percent := strategy.grossloss_percent
    grossloss_percent_i := grossloss_percent_i + 1
plot(independent_grossloss_percent)
plot(identity(strategy.grossprofit_percent))
plot(identity(strategy.grossloss_percent))
plot(strategy.netprofit_percent[1])
plot(strategy.grossprofit_percent[1])
plot(strategy.grossloss_percent[1])
plot(openprofit_percent)
plot(openprofit_percent_udf)
plot(openprofit_percent_history)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0), bar(4.0), bar(2.0)],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(-0.1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(-0.1),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.2),
        ]
    );
    assert_eq!(
        result.plots[4].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(-0.1),
        ]
    );
    assert_eq!(
        result.plots[5].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
        ]
    );
    assert_eq!(
        result.plots[6].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.2),
        ]
    );
    assert_eq!(
        result.plots[7].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
        ]
    );
    assert_eq!(
        result.plots[8].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.2),
        ]
    );
    assert_eq!(
        result.plots[9].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
        ]
    );
    assert_eq!(
        result.plots[10].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
            PineValue::Float(0.1),
        ]
    );
    assert_eq!(
        result.plots[11].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
    let open_profit_percent = vec![
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.1),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(-2.0 / 1001.0 * 100.0),
    ];
    assert_eq!(result.plots[12].values, open_profit_percent.clone());
    assert_eq!(result.plots[13].values, open_profit_percent);
    assert_eq!(
        result.plots[14].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.1),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
}

#[test]
fn strategy_openprofit_percent_is_na_without_positive_realized_equity() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("open profit percent denominator", initial_capital=1)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 2
    strategy.close("L")
plot(strategy.openprofit_percent)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(1.0), bar(0.0)])
        .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(0.0), PineValue::Float(0.0), PineValue::Na,]
    );
}

#[test]
fn strategy_trade_count_variables_observe_pending_exit_on_next_bar() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("pending exit trade counts")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("XL", "L", limit=2.5)
plot(strategy.closedtrades)
plot(strategy.opentrades)
plot(strategy.closedtrades[1])
plot(strategy.opentrades[1])
plot(strategy.closedtrades.first_index)
plot(strategy.closedtrades.first_index[1])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar_ohlc(1.0, 1.0, 1.0, 1.0),
            bar_ohlc(2.0, 2.0, 2.0, 2.0),
            bar_ohlc(3.0, 3.0, 3.0, 3.0),
            bar_ohlc(4.0, 4.0, 4.0, 4.0),
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(1),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Na,
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Na,
            PineValue::Int(0),
            PineValue::Int(1),
            PineValue::Int(1),
        ]
    );
    assert_eq!(result.plots[4].values, vec![PineValue::Int(0); 4]);
    assert_eq!(
        result.plots[5].values,
        vec![
            PineValue::Na,
            PineValue::Int(0),
            PineValue::Int(0),
            PineValue::Int(0),
        ]
    );
}

#[test]
fn strategy_profit_state_variables_follow_realized_and_open_profit() {
    let source = SourceFile::new(
        "strategy.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_profit_state.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(1.0), bar(4.0), bar(6.0)],
    )
    .expect("runtime result");

    let zero_series = vec![
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
    ];
    let open_profit = vec![
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(-4.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
    ];
    let net_profit = vec![
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(-4.0),
        PineValue::Float(-4.0),
    ];
    let net_profit_after_close = vec![
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(-4.0),
        PineValue::Float(-4.0),
        PineValue::Float(-4.0),
    ];
    let net_profit_after_close_history = vec![
        PineValue::Na,
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(-4.0),
        PineValue::Float(-4.0),
    ];
    let equity = vec![
        PineValue::Float(1000.0),
        PineValue::Float(1000.0),
        PineValue::Float(1000.0),
        PineValue::Float(996.0),
        PineValue::Float(996.0),
        PineValue::Float(996.0),
    ];
    let equity_history = vec![
        PineValue::Na,
        PineValue::Float(1000.0),
        PineValue::Float(1000.0),
        PineValue::Float(1000.0),
        PineValue::Float(996.0),
        PineValue::Float(996.0),
    ];
    let max_drawdown = vec![
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(4.0),
        PineValue::Float(4.0),
        PineValue::Float(4.0),
    ];
    let max_drawdown_history = vec![
        PineValue::Na,
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(4.0),
        PineValue::Float(4.0),
    ];
    let max_drawdown_percent = vec![
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(0.0),
        PineValue::Float(4.0 / 6.0 * 100.0),
        PineValue::Float(4.0 / 6.0 * 100.0),
        PineValue::Float(4.0 / 6.0 * 100.0),
    ];

    assert_eq!(result.plots[0].values, open_profit);
    assert_eq!(result.plots[1].values, net_profit.clone());
    assert_eq!(result.plots[2].values, equity.clone());
    assert_eq!(result.plots[3].values, zero_series.clone());
    assert_eq!(result.plots[4].values, zero_series.clone());
    assert_eq!(result.plots[5].values, max_drawdown.clone());
    assert_eq!(result.plots[6].values, max_drawdown_percent.clone());
    assert_eq!(result.plots[7].values, open_profit);
    assert_eq!(result.plots[8].values, zero_series.clone());
    assert_eq!(result.plots[9].values, net_profit_after_close.clone());
    assert_eq!(result.plots[10].values, net_profit_after_close.clone());
    assert_eq!(result.plots[11].values, equity.clone());
    assert_eq!(result.plots[12].values, zero_series.clone());
    assert_eq!(result.plots[13].values, zero_series);
    assert_eq!(result.plots[14].values, max_drawdown.clone());
    assert_eq!(result.plots[15].values, max_drawdown_percent);
    assert_eq!(result.plots[16].values, net_profit_after_close);
    assert_eq!(result.plots[17].values, max_drawdown);
    assert_eq!(result.plots[18].values, equity.clone());
    assert_eq!(result.plots[19].values, max_drawdown);
    assert_eq!(result.plots[20].values, equity);
    assert_eq!(result.plots[21].values, net_profit_after_close_history);
    assert_eq!(result.plots[22].values, equity_history);
    assert_eq!(result.plots[23].values, max_drawdown_history);
    let initial_capital = vec![PineValue::Float(1000.0); 6];
    assert_eq!(result.plots[24].values, initial_capital.clone());
    assert_eq!(result.plots[25].values, initial_capital);
    assert_eq!(
        result.plots[26].values,
        vec![
            PineValue::Na,
            PineValue::Float(1000.0),
            PineValue::Float(1000.0),
            PineValue::Float(1000.0),
            PineValue::Float(1000.0),
            PineValue::Float(1000.0),
        ]
    );
}

#[test]
fn strategy_max_drawdown_follows_intrabar_low_and_max_equity() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("drawdown", initial_capital=1000)
plot(strategy.max_drawdown)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=10)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(10.0), bar(12.0), bar(9.0), bar(11.0)],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(30.0),
            PineValue::Float(30.0),
        ]
    );
}

#[test]
fn strategy_max_drawdown_uses_intrabar_low() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("drawdown", initial_capital=1000)
plot(strategy.max_drawdown)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=10)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar_ohlc(10.0, 10.0, 8.0, 10.0),
            bar_ohlc(10.0, 12.0, 10.0, 12.0),
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(20.0),
            PineValue::Float(20.0),
        ]
    );
}

#[test]
fn strategy_max_runup_follows_intrabar_high_and_min_equity() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("runup", initial_capital=1000)
plot(strategy.max_runup)
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=10)
if bar_index == 2
    strategy.close("L1")
if bar_index == 3
    strategy.entry("L2", strategy.long, qty=10)
if bar_index == 5
    strategy.close("L2")
if bar_index == 6
    strategy.entry("L3", strategy.long, qty=10)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar_ohlc(10.0, 11.0, 10.0, 10.0),
            bar_ohlc(10.0, 10.0, 8.0, 8.0),
            bar(8.0),
            bar_ohlc(10.0, 12.0, 10.0, 12.0),
            bar_ohlc(12.0, 12.0, 12.0, 12.0),
            bar(12.0),
            bar_ohlc(10.0, 11.0, 10.0, 10.0),
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(10.0),
            PineValue::Float(10.0),
            PineValue::Float(10.0),
            PineValue::Float(20.0),
            PineValue::Float(20.0),
            PineValue::Float(20.0),
            PineValue::Float(30.0),
        ]
    );
}

#[test]
fn strategy_max_runup_and_drawdown_percent_use_trade_value_denominator() {
    let source = SourceFile::new(
        "strategy.pine",
        r#"strategy("percent", initial_capital=1000)
plot(strategy.max_runup_percent)
plot(strategy.max_drawdown_percent)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=10)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[
            bar(10.0),
            bar_ohlc(10.0, 12.0, 8.0, 10.0),
            bar_ohlc(10.0, 11.0, 9.0, 10.0),
        ],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(20.0),
            PineValue::Float(20.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(20.0),
            PineValue::Float(20.0),
        ]
    );
}

#[test]
fn strategy_variables_work_in_supported_expression_contexts() {
    let source = SourceFile::new(
        "strategy.pine",
        include_str!("../../../../tests/fixtures/runtime/strategy_variable_interactions.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(-1.0),
            PineValue::Float(-1.0),
            PineValue::Float(2.0),
            PineValue::Float(-1.0),
        ]
    );
    assert_eq!(
        result.plots[1].values,
        vec![
            PineValue::Float(-1.0),
            PineValue::Float(-1.0),
            PineValue::Float(2.0),
            PineValue::Float(-1.0),
        ]
    );
    assert_eq!(
        result.plots[2].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(4.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[3].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[4].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[5].values,
        vec![
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(20.0),
            PineValue::Float(0.0),
        ]
    );
    assert_eq!(
        result.plots[6].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(2.0),
        ]
    );
    assert_eq!(
        result.plots[7].values,
        vec![
            PineValue::Na,
            PineValue::Float(0.0),
            PineValue::Float(0.0),
            PineValue::Float(0.0),
        ]
    );
}
