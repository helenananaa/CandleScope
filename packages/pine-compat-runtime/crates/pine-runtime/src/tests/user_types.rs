use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn runs_local_user_type_constructors_and_field_reads() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("udt")
type Point
    float x
    float y
p = Point.new(close, open)
plot(p.x + p.y)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 1.0, 1.0, 2.0), bar_ohlc(3.0, 3.0, 3.0, 4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[3.0, 7.0]);
}

#[test]
fn runs_branch_local_user_type_values() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("udt branch")
type Point
    float x
    float y
if close > open
    p = Point.new(close, open)
    plot(p.x - p.y)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 1.0, 1.0, 3.0), bar_ohlc(4.0, 4.0, 4.0, 2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(2.0), PineValue::Na]
    );
}

#[test]
fn var_user_type_values_persist_historically() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("udt var")
type Point
    float x
var p = Point.new(close)
plot(p.x)
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
    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn user_type_value_history_reads_previous_scalar_fields() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("udt history")
type Point
    float x
p = Point.new(close)
prior = p[1]
plot(prior.x)
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
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Na, PineValue::Float(1.0), PineValue::Float(2.0)]
    );
}

#[test]
fn var_user_type_value_history_reads_persisted_previous_value() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("var udt history")
type Point
    float x
var Point p = Point.new(close)
prior = p[1]
plot(prior.x)
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
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Na, PineValue::Float(1.0), PineValue::Float(1.0)]
    );
}

#[test]
fn nested_user_type_value_history_reads_previous_scalar_fields() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("nested udt history")
type Point
    float x
type Wrapper
    Point point
point = Point.new(close)
wrapper = Wrapper.new(point)
prior = wrapper[1]
plot(prior.point.x)
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
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Na, PineValue::Float(1.0), PineValue::Float(2.0)]
    );
}
