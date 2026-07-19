use super::*;
use crate::analyzer::context::MAX_LOWERING_TEMP_SYMBOLS;

fn analyze_with_imported_udt_library(text: &str) -> Analysis {
    let library = SourceFile::new(
        "import_udt_lib.pine",
        r#"library("Imported UDT fixture")
export type Point
    float x
export type Wrapper
    Point nested
export typedPoint(Point p) => p
method nestedShift(Wrapper w, float delta) => w.nested.x + delta
method shift(Point p, float delta) => p.x + delta
method make(Point p, float value) => Point.new(value)
method makeBlock(Point p, float value) =>
    made = Point.new(value)
    made
method same(Point p) => p
method nestedAliasShift(Wrapper w, float delta) =>
    alias = w
    alias.nested.x + delta
method nestedFieldAliasShift(Wrapper w, float delta) =>
    nested = w.nested
    nested.x + delta
method nestedSource(Wrapper w) => w.nestedShift(1)
method otherNestedShift(Point p, Wrapper other, float delta) => other.nested.x + delta
method otherNestedSource(Point p, Wrapper other) => p.otherNestedShift(other, 1)
method otherNestedSourceNamed(Point p, Wrapper other, float delta) => p.otherNestedShift(delta=delta, other=other)
"#,
    );
    let input = AnalysisInput::with_library_sources(
        SourceFile::new("test.pine", text),
        vec![("user/udt/1".to_owned(), library)],
    )
    .expect("valid library source");
    crate::analyze_input(&input)
}

#[test]
fn dual_alias_nested_import_contexts_isolate_and_reuse_pure_series_for_max_bars_back_history() {
    let library = SourceFile::new(
        "dual_alias_source_context_lib.pine",
        r#"library("Dual alias source context")
export type Box
    float value

privateSource(Box box, float delta) =>
    aliased = box
    shifted = aliased.value + delta
    shifted

export exportedSource(Box box, float delta) => privateSource(box, delta)

method inner(Box box, float delta) => privateSource(box, delta)
method outer(Box box, float delta) => box.inner(delta)
"#,
    );
    let root = SourceFile::new(
        "dual_alias_source_context_root.pine",
        r#"//@version=6
import user/context/1 as left
import user/context/1 as right
indicator("Dual alias source context")

rootSource(float value, float delta) =>
    aliased = value
    shifted = aliased + delta
    shifted

length = input.int(1, "Length")
left_box = left.Box.new(close)
right_box = right.Box.new(open)

left_source = left.exportedSource(left_box, 1.0)
right_source = right_box.outer(delta=2.0)
root_source = rootSource(high, 3.0)
left_again_source = left.exportedSource(left_box, 1.0)
root_again_source = rootSource(high, 3.0)

max_bars_back(left_source, 3)
max_bars_back(right_source, 5)
max_bars_back(root_source, 7)

plot(left.exportedSource(left_box, 1.0)[length])
plot(right_box.outer(delta=2.0)[length])
plot(rootSource(high, 3.0)[length])
plot(left.exportedSource(left_box, 1.0)[length])
plot(rootSource(high, 3.0)[length])
"#,
    );
    let input =
        AnalysisInput::with_library_sources(root, vec![("user/context/1".to_owned(), library)])
            .expect("dual-alias library input should be valid");
    let analysis = crate::analyze_input(&input);

    assert!(
        analysis.diagnostics.is_empty(),
        "dual-alias diagnostics: {:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("dual-alias script should lower to HIR");
    let symbol_series_id = |name: &str| {
        hir.symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .and_then(|symbol| symbol.series_id)
            .unwrap_or_else(|| panic!("`{name}` should have a series id"))
    };

    let left_series = symbol_series_id("left_source");
    let right_series = symbol_series_id("right_source");
    let root_series = symbol_series_id("root_source");
    assert_eq!(
        symbol_series_id("left_again_source"),
        left_series,
        "the left alias should recover its pure-series identity after right/root calls"
    );
    assert_eq!(
        symbol_series_id("root_again_source"),
        root_series,
        "the root context should be restored after the final imported call"
    );
    assert_ne!(left_series, right_series);
    assert_ne!(left_series, root_series);
    assert_ne!(right_series, root_series);

    for (max_bars_back, expected_series) in [(3, left_series), (5, right_series), (7, root_series)]
    {
        let bound = hir
            .series_max_bars_back
            .iter()
            .find(|bound| bound.max_bars_back == max_bars_back)
            .unwrap_or_else(|| panic!("missing max_bars_back={max_bars_back} bound"));
        assert_eq!(bound.series_id, expected_series);
        let requirement = hir
            .series_history
            .iter()
            .find(|requirement| requirement.series_id == expected_series)
            .unwrap_or_else(|| {
                panic!("missing dynamic history requirement for max_bars_back={max_bars_back}")
            });
        assert!(
            requirement.has_dynamic_offsets,
            "max_bars_back={max_bars_back} should reuse the dynamically indexed series: {:?}",
            hir.series_history
        );
    }
}

#[test]
fn infers_history_requirements() {
    let analysis =
        analyze("len = input.int(1, \"Length\")\nplot(close[3])\nplot((close + open)[len])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 3);
    assert!(hir.history.has_dynamic_offsets);
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.max_constant_offset == 3),
        "{:?}",
        hir.series_history
    );
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_pure_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nmax_bars_back(close + open, 5)\nplot((close + open)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("expression max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same expression should carry the dynamic history requirement");

    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_decl_alias_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nspread = close + open\nmax_bars_back(spread, 5)\nplot((close + open)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let spread_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "spread")
        .and_then(|symbol| symbol.series_id)
        .expect("spread should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("aliased expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, spread_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_ternary_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = close > open ? close : open\nmax_bars_back(src, 5)\nplot((close > open ? close : open)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("ternary max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same ternary expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_qualified_builtin_ternary_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = barstate.isconfirmed ? close : open\nmax_bars_back(src, 5)\nplot((barstate.isconfirmed ? close : open)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("qualified ternary max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same qualified ternary expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_if_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = if close > open\n    base = close\n    base\nelse\n    open\nsame = if close > open\n    base = close\n    base\nelse\n    open\nmax_bars_back(src, 5)\nplot(same[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("if expression max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same if expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_switch_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = switch\n    close > open =>\n        base = close\n        base\n    =>\n        open\nsame = switch\n    close > open =>\n        base = close\n        base\n    =>\n        open\nmax_bars_back(src, 5)\nplot(same[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("switch expression max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same switch expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_for_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = for i = 0 to 1\n    base = close + i\n    base\nsame = for i = 0 to 1\n    base = close + i\n    base\nmax_bars_back(src, 5)\nplot(same[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("for expression max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same for expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_inline_array_from_for_in_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = for value in array.from(close, open)\n    base = value + 1\n    base\nsame = for value in array.from(close, open)\n    base = value + 1\n    base\nmax_bars_back(src, 5)\nplot(same[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("for-in expression max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same for-in expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_while_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = while false\n    base = close\n    base\nsame = while false\n    base = close\n    base\nmax_bars_back(src, 5)\nplot(same[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("while expression max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same while expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_direct_constructor_udt_field_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
len = input.int(1, "Length")
p = Point.new(close)
src = p.x + 1
max_bars_back(src, 5)
plot((p.x + 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("UDT field expression alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same UDT field expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_direct_constructor_udt_field_expression_after_receiver_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
src = p.x + 1
max_bars_back(src, 5)
plot((p.x + 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("UDT field expression alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_nested_direct_constructor_udt_field_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = w.inner.x + 1
max_bars_back(src, 5)
plot((w.inner.x + 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT field expression alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same nested UDT field expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_nested_direct_constructor_udt_field_expression_after_inner_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
w = Wrapper.new(p)
src = w.inner.x + 1
max_bars_back(src, 5)
plot((w.inner.x + 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT field expression alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_imported_direct_constructor_udt_field_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported UDT field max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
src = p.x + 1
max_bars_back(src, 5)
plot((p.x + 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("imported UDT field expression alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same imported UDT field expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_nested_direct_constructor_udt_field_expression_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported nested UDT field max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = w.nested.x + 1
max_bars_back(src, 5)
plot((w.nested.x + 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("imported nested UDT field expression alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported nested UDT field expression should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_imported_nested_direct_constructor_udt_field_expression_after_inner_reassignment()
{
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported nested reassigned UDT field max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
p := lib.Point.new(open)
w = lib.Wrapper.new(p)
src = w.nested.x + 1
max_bars_back(src, 5)
plot((w.nested.x + 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("imported nested UDT field expression alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_imported_nested_udt_arg_field_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported nested UDT arg UDF max_bars_back")
source(w) => w.nested.x + 1
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = source(w)
max_bars_back(src, 5)
plot(source(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported nested UDT arg field pure UDF call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported nested UDT arg field pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_receiver_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported receiver field method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = w.nestedShift(1)
max_bars_back(src, 5)
plot(w.nestedShift(1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported receiver field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported receiver field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_udt_arg_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported UDT arg field method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(open)
inner = lib.Point.new(close)
other = lib.Wrapper.new(inner)
src = p.otherNestedShift(other, 1)
max_bars_back(src, 5)
plot(p.otherNestedShift(other, 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported UDT arg field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported UDT arg field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_direct_nested_udt_arg_expr_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported direct nested UDT arg UDF max_bars_back")
source(w) => w.nested.x + 1
len = input.int(1, "Length")
src = source(lib.Wrapper.new(lib.Point.new(close)))
max_bars_back(src, 5)
plot(source(lib.Wrapper.new(lib.Point.new(close)))[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported direct nested UDT arg expr pure UDF call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported direct nested UDT arg expr pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_named_direct_nested_udt_arg_expr_pure_udf_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported named direct nested UDT arg UDF max_bars_back")
source(w, delta) => w.nested.x + delta
len = input.int(1, "Length")
src = source(delta=1, w=lib.Wrapper.new(lib.Point.new(close)))
max_bars_back(src, 5)
plot(source(w=lib.Wrapper.new(lib.Point.new(close)), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported named direct nested UDT arg expr pure UDF call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported named direct nested UDT arg expr pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_direct_nested_udt_arg_expr_nested_pure_udf_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported direct nested UDT arg nested UDF max_bars_back")
adjust(w) => w.nested.x + 1
source(w) => adjust(w)
len = input.int(1, "Length")
src = source(lib.Wrapper.new(lib.Point.new(close)))
max_bars_back(src, 5)
plot(source(lib.Wrapper.new(lib.Point.new(close)))[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported direct nested UDT arg expr nested pure UDF call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported direct nested UDT arg expr nested pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_nested_receiver_alias_field_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported nested receiver alias field method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = w.nestedAliasShift(1)
max_bars_back(src, 5)
plot(w.nestedAliasShift(1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported nested receiver alias field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported nested receiver alias field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_nested_receiver_field_alias_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported nested receiver field alias method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = w.nestedFieldAliasShift(1)
max_bars_back(src, 5)
plot(w.nestedFieldAliasShift(1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported nested receiver field alias pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported nested receiver field alias pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_nested_receiver_field_nested_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported nested receiver nested method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = w.nestedSource()
max_bars_back(src, 5)
plot(w.nestedSource()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported nested receiver field nested pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported nested receiver field nested pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_nested_udt_arg_field_nested_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported nested UDT arg nested method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(open)
inner = lib.Point.new(close)
other = lib.Wrapper.new(inner)
src = p.otherNestedSource(other)
max_bars_back(src, 5)
plot(p.otherNestedSource(other)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported nested UDT arg field nested pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported nested UDT arg field nested pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_named_direct_nested_udt_arg_expr_nested_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported named direct nested UDT arg nested method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(open)
src = p.otherNestedSourceNamed(delta=1, other=lib.Wrapper.new(lib.Point.new(close)))
max_bars_back(src, 5)
plot(p.otherNestedSourceNamed(other=lib.Wrapper.new(lib.Point.new(close)), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported named direct nested UDT arg expr nested pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported named direct nested UDT arg expr nested pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_receiver_field_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified receiver method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = lib.nestedShift(w, 1)
max_bars_back(src, 5)
plot(lib.nestedShift(w, 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified receiver field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified receiver field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_direct_receiver_expr_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified direct receiver expr method max_bars_back")
len = input.int(1, "Length")
src = lib.nestedShift(lib.Wrapper.new(lib.Point.new(close)), 1)
max_bars_back(src, 5)
plot(lib.nestedShift(lib.Wrapper.new(lib.Point.new(close)), 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified direct receiver expression pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified direct receiver expression pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_udt_arg_field_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified UDT arg method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(open)
inner = lib.Point.new(close)
other = lib.Wrapper.new(inner)
src = lib.otherNestedShift(p, other, 1)
max_bars_back(src, 5)
plot(lib.otherNestedShift(p, other, 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified UDT arg field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified UDT arg field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_direct_udt_arg_expr_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified direct UDT arg expr method max_bars_back")
len = input.int(1, "Length")
src = lib.otherNestedShift(lib.Point.new(open), lib.Wrapper.new(lib.Point.new(close)), 1)
max_bars_back(src, 5)
plot(lib.otherNestedShift(lib.Point.new(open), lib.Wrapper.new(lib.Point.new(close)), 1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified direct UDT arg expression pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified direct UDT arg expression pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_nested_receiver_field_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified nested receiver method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(close)
w = lib.Wrapper.new(p)
src = lib.nestedSource(w)
max_bars_back(src, 5)
plot(lib.nestedSource(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified nested receiver field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified nested receiver field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_nested_udt_arg_field_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified nested UDT arg method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(open)
inner = lib.Point.new(close)
other = lib.Wrapper.new(inner)
src = lib.otherNestedSource(p, other)
max_bars_back(src, 5)
plot(lib.otherNestedSource(p, other)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified nested UDT arg field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified nested UDT arg field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_named_udt_arg_field_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified named UDT arg method max_bars_back")
len = input.int(1, "Length")
p = lib.Point.new(open)
inner = lib.Point.new(close)
other = lib.Wrapper.new(inner)
src = lib.otherNestedShift(p, delta=1, other=other)
max_bars_back(src, 5)
plot(lib.otherNestedShift(p, other=other, delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified named UDT arg field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified named UDT arg field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_named_direct_udt_arg_expr_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified named direct UDT arg expr method max_bars_back")
len = input.int(1, "Length")
src = lib.otherNestedShift(lib.Point.new(open), delta=1, other=lib.Wrapper.new(lib.Point.new(close)))
max_bars_back(src, 5)
plot(lib.otherNestedShift(lib.Point.new(open), other=lib.Wrapper.new(lib.Point.new(close)), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified named direct UDT arg expression pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified named direct UDT arg expression pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_alias_qualified_named_direct_nested_udt_arg_expr_nested_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported alias-qualified named direct nested UDT arg nested method max_bars_back")
len = input.int(1, "Length")
src = lib.otherNestedSourceNamed(lib.Point.new(open), delta=1, other=lib.Wrapper.new(lib.Point.new(close)))
max_bars_back(src, 5)
plot(lib.otherNestedSourceNamed(lib.Point.new(open), other=lib.Wrapper.new(lib.Point.new(close)), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported alias-qualified named direct nested UDT arg expression nested pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported alias-qualified named direct nested UDT arg expression nested pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_math_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = math.max(close, open)\nmax_bars_back(src, 5)\nplot(math.max(close, open)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("math call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same math call expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_pure_math_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = math.pow(base=close, exponent=open)\nmax_bars_back(src, 5)\nplot(math.pow(exponent=open, base=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("named math call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same named math call expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_numeric_cast_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = float(close)\nmax_bars_back(src, 5)\nplot(float(close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("numeric cast call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same numeric cast call expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_nz_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = nz(close)\nmax_bars_back(src, 5)\nplot(nz(close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nz call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same nz call expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_reordered_nz_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = nz(x=close, replacement=open)\nmax_bars_back(src, 5)\nplot(nz(replacement=open, x=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("named/reordered nz call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same named/reordered nz call expression should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_variadic_math_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = math.max(a=close, b=open)\nmax_bars_back(src, 5)\nplot(math.max(b=open, a=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("named variadic math call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same named variadic math call should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_mixed_named_variadic_math_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = math.max(close, b=open)\nmax_bars_back(src, 5)\nplot(math.max(a=close, b=open)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("mixed named variadic math call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same mixed named variadic math call should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_fixnan_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = fixnan(close)\nmax_bars_back(src, 5)\nplot(fixnan(close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("fixnan call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same fixnan call expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_str_tonumber_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = str.tonumber(close > open ? \"1\" : \"2\")\nmax_bars_back(src, 5)\nplot(str.tonumber(close > open ? \"1\" : \"2\")[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("str.tonumber call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same str.tonumber call expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_str_length_call_expression_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = str.length(close > open ? \"long\" : \"s\")\nmax_bars_back(src, 5)\nplot(str.length(close > open ? \"long\" : \"s\")[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("str.length call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same str.length call expression should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_history_and_stateless_scalar_call_series_ids_for_max_bars_back_history() {
    let analysis = analyze(
        r#"offset = bar_index % 3
shade = close >= open ? color.red : color.green
text = close >= open ? "alpha" : "beta"
lagged = close[1]
red = color.r(shade)
green = color.g(shade)
blue = color.b(shade)
transparency = color.t(shade)
position = str.pos(text, "p")
max_bars_back(lagged, 2)
max_bars_back(red, 2)
max_bars_back(green, 2)
max_bars_back(blue, 2)
max_bars_back(transparency, 2)
max_bars_back(position, 2)
plot((close[1])[offset])
plot(color.r(shade)[offset])
plot(color.g(shade)[offset])
plot(color.b(shade)[offset])
plot(color.t(shade)[offset])
plot(str.pos(text, "p")[offset])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bounds = hir
        .series_max_bars_back
        .iter()
        .filter(|bound| bound.max_bars_back == 2)
        .collect::<Vec<_>>();

    assert_eq!(bounds.len(), 6, "{:?}", hir.series_max_bars_back);
    for bound in bounds {
        assert!(
            hir.series_history.iter().any(|requirement| {
                requirement.series_id == bound.series_id && requirement.has_dynamic_offsets
            }),
            "bound {bound:?} did not match a dynamic history read: {:?}",
            hir.series_history
        );
    }
}

#[test]
fn does_not_reuse_pure_expression_series_id_across_reassigned_dependency() {
    let analysis = analyze(
        "x = close\nsource = x + 1\nmax_bars_back(source, 1)\nx := open\nplot((x + 1)[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|bound| bound.max_bars_back == 1)
        .expect("source max_bars_back should be inferred");

    assert!(
        hir.series_history.iter().all(|requirement| {
            requirement.series_id != bound.series_id || !requirement.has_dynamic_offsets
        }),
        "reassigned dependency must keep the later expression on a distinct series: {:?}",
        hir.series_history
    );
}

#[test]
fn does_not_reuse_pure_expression_series_id_across_udf_local_reassignment() {
    let analysis = analyze(
        "f() =>\n    x = close\n    before = (x + 1)[1]\n    x := open\n    after = (x + 1)[1]\n    before - after\nplot(f())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let history_series = hir
        .series_history
        .iter()
        .filter(|requirement| requirement.max_constant_offset == 1)
        .map(|requirement| requirement.series_id)
        .collect::<std::collections::HashSet<_>>();

    assert_eq!(
        history_series.len(),
        2,
        "UDF-local reassignment must keep the before/after history sources distinct: {:?}",
        hir.series_history
    );
}

#[test]
fn reuses_parameterized_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsource(a, b) => a + b\nsrc = source(close, open)\nmax_bars_back(src, 5)\nplot(source(b=open, a=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("parameterized pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same parameterized pure UDF call should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_block_local_parameterized_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsource(a, b) =>\n    value = a + b\n    value\nsrc = source(close, open)\nmax_bars_back(src, 5)\nplot(source(b=open, a=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("block-local pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same block-local pure UDF call should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_typed_block_local_parameterized_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsource(a, b) =>\n    float value = a + b\n    value\nsrc = source(close, open)\nmax_bars_back(src, 5)\nplot(source(b=open, a=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("typed block-local pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same typed block-local pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_pure_expr_prefix_block_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsource(a, b) =>\n    a + b\n    value = a + b\n    value\nsrc = source(close, open)\nmax_bars_back(src, 5)\nplot(source(b=open, a=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("pure expr prefix block UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same pure expr prefix block UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_udt_arg_field_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
source(p) => p.x + 1
len = input.int(1, "Length")
p = Point.new(close)
src = source(p)
max_bars_back(src, 5)
plot(source(p)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("UDT arg field pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same UDT arg field pure UDF call should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_direct_udt_arg_expr_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
source(p) => p.x + 1
len = input.int(1, "Length")
src = source(Point.new(close))
max_bars_back(src, 5)
plot(source(Point.new(close))[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("direct UDT arg expr pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same direct UDT arg expr pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_direct_udt_arg_expr_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
source(p, delta) => p.x + delta
len = input.int(1, "Length")
src = source(delta=1, p=Point.new(close))
max_bars_back(src, 5)
plot(source(p=Point.new(close), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("named direct UDT arg expr pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same named direct UDT arg expr pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_udt_arg_field_pure_udf_series_id_after_arg_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
source(p) => p.x + 1
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
src = source(p)
max_bars_back(src, 5)
plot(source(p)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("UDT arg field pure UDF call alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_nested_udt_arg_field_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
source(w) => w.inner.x + 1
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = source(w)
max_bars_back(src, 5)
plot(source(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT arg field pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested UDT arg field pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_nested_udt_arg_field_pure_udf_series_id_after_inner_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
source(w) => w.inner.x + 1
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
w = Wrapper.new(p)
src = source(w)
max_bars_back(src, 5)
plot(source(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT arg field pure UDF call alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_parameterized_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method source(Point p, float value) => value + 1
len = input.int(1, "Length")
p = Point.new(close)
src = p.source(close)
max_bars_back(src, 5)
plot(p.source(value=close)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("parameterized pure user method call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same parameterized pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_receiver_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method source(Point p) => p.x + 1
len = input.int(1, "Length")
p = Point.new(close)
src = p.source()
max_bars_back(src, 5)
plot(p.source()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("receiver field pure user method call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same receiver field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_receiver_field_pure_user_method_series_id_after_receiver_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
method source(Point p) => p.x + 1
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
src = p.source()
max_bars_back(src, 5)
plot(p.source()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("receiver field pure user method call alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_receiver_alias_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method source(Point p) =>
    q = p
    q.x + 1
len = input.int(1, "Length")
p = Point.new(close)
src = p.source()
max_bars_back(src, 5)
plot(p.source()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "receiver alias field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same receiver alias field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_nested_receiver_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method source(Wrapper w) => w.inner.x + 1
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = w.source()
max_bars_back(src, 5)
plot(w.source()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "nested receiver field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested receiver field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_nested_receiver_alias_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method source(Wrapper w) =>
    alias = w
    alias.inner.x + 1
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = w.source()
max_bars_back(src, 5)
plot(w.source()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "nested receiver alias field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested receiver alias field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_nested_udt_field_alias_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
source(w) =>
    inner = w.inner
    inner.x + 1
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = source(w)
max_bars_back(src, 5)
plot(source(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT field alias pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested UDT field alias pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_nested_udt_field_alias_pure_udf_series_id_after_inner_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
source(w) =>
    inner = w.inner
    inner.x + 1
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
w = Wrapper.new(p)
src = source(w)
max_bars_back(src, 5)
plot(source(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT field alias pure UDF call alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_nested_receiver_field_alias_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method source(Wrapper w) =>
    inner = w.inner
    inner.x + 1
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = w.source()
max_bars_back(src, 5)
plot(w.source()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "nested receiver field alias pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested receiver field alias pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_named_direct_nested_udt_arg_expr_nested_pure_udf_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported named direct nested UDT arg nested UDF max_bars_back")
adjust(w, delta) => w.nested.x + delta
source(w, delta) => adjust(delta=delta, w=w)
len = input.int(1, "Length")
src = source(delta=1, w=lib.Wrapper.new(lib.Point.new(close)))
max_bars_back(src, 5)
plot(source(w=lib.Wrapper.new(lib.Point.new(close)), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported named direct nested UDT arg expr nested pure UDF call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported named direct nested UDT arg expr nested pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_udt_arg_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method source(Point p, Point other) => other.x + 1
len = input.int(1, "Length")
p = Point.new(open)
other = Point.new(close)
src = p.source(other)
max_bars_back(src, 5)
plot(p.source(other)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("UDT arg field pure user method call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same UDT arg field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_local_constructor_receiver_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method shift(Point p, float delta) => p.x + delta
len = input.int(1, "Length")
src = Point.new(close).shift(1)
max_bars_back(src, 5)
plot(Point.new(close).shift(1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "local constructor receiver pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same local constructor receiver pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_local_method_result_receiver_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method make(Point p, float value) => Point.new(value)
method read(Point p) => p.x
len = input.int(1, "Length")
src = Point.new(close).make(open).read()
max_bars_back(src, 5)
plot(Point.new(close).make(open).read()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "local method-result receiver pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same local method-result receiver pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_method_result_receiver_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported method-result receiver max_bars_back")
len = input.int(1, "Length")
src = lib.Point.new(close).make(open).shift(1)
max_bars_back(src, 5)
plot(lib.Point.new(close).make(open).shift(1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported method-result receiver pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported method-result receiver pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_local_block_method_result_receiver_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze(
        r#"type Point
    float x
method makeBlock(Point p, float value) =>
    made = Point.new(value)
    made
method read(Point p) => p.x
len = input.int(1, "Length")
src = Point.new(close).makeBlock(open).read()
max_bars_back(src, 5)
plot(Point.new(close).makeBlock(open).read()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "local block method-result receiver pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same local block method-result receiver pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_block_method_result_receiver_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported block method-result receiver max_bars_back")
len = input.int(1, "Length")
src = lib.Point.new(close).makeBlock(open).shift(1)
max_bars_back(src, 5)
plot(lib.Point.new(close).makeBlock(open).shift(1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "imported block method-result receiver pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported block method-result receiver pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_local_udf_result_udt_arg_field_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
make(float value) => Point.new(value)
read(Point p) => p.x
len = input.int(1, "Length")
src = read(make(open))
max_bars_back(src, 5)
plot(read(make(open))[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("local UDF-result UDT arg pure UDF call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same local UDF-result UDT arg pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_imported_udf_result_udt_arg_field_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze_with_imported_udt_library(
        r#"//@version=5
import user/udt/1 as lib
indicator("Imported UDF-result UDT arg max_bars_back")
read(lib.Point p) => p.x
len = input.int(1, "Length")
src = read(lib.typedPoint(lib.Point.new(open)))
max_bars_back(src, 5)
plot(read(lib.typedPoint(lib.Point.new(open)))[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("imported UDF-result UDT arg pure UDF call max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same imported UDF-result UDT arg pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_udt_arg_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method shift(Point p, Point other, float delta) => other.x + delta
len = input.int(1, "Length")
p = Point.new(open)
other = Point.new(close)
src = p.shift(delta=1, other=other)
max_bars_back(src, 5)
plot(p.shift(other=other, delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("named UDT arg field pure user method call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same named UDT arg field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_direct_udt_arg_expr_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
method shift(Point p, Point other, float delta) => other.x + delta
len = input.int(1, "Length")
p = Point.new(open)
src = p.shift(delta=1, other=Point.new(close))
max_bars_back(src, 5)
plot(p.shift(other=Point.new(close), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "named direct UDT arg expr pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same named direct UDT arg expr pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_udt_arg_field_pure_user_method_series_id_after_arg_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
method source(Point p, Point other) => other.x + 1
len = input.int(1, "Length")
p = Point.new(open)
other = Point.new(close)
other := Point.new(high)
src = p.source(other)
max_bars_back(src, 5)
plot(p.source(other)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("UDT arg field pure user method call alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_nested_udt_arg_field_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method source(Point p, Wrapper other) => other.inner.x + 1
len = input.int(1, "Length")
p = Point.new(open)
inner = Point.new(close)
other = Wrapper.new(inner)
src = p.source(other)
max_bars_back(src, 5)
plot(p.source(other)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "nested UDT arg field pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested UDT arg field pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_nested_udt_arg_field_pure_user_method_series_id_after_inner_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method source(Point p, Wrapper other) => other.inner.x + 1
len = input.int(1, "Length")
p = Point.new(open)
inner = Point.new(close)
inner := Point.new(high)
other = Wrapper.new(inner)
src = p.source(other)
max_bars_back(src, 5)
plot(p.source(other)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "nested UDT arg field pure user method call alias max_bars_back should be inferred",
        );

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_nested_udt_arg_field_nested_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
adjust(w) => w.inner.x + 1
source(w) => adjust(w)
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = source(w)
max_bars_back(src, 5)
plot(source(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT arg field nested pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested UDT arg field nested pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_direct_nested_udt_arg_expr_nested_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
adjust(w) => w.inner.x + 1
source(w) => adjust(w)
len = input.int(1, "Length")
src = source(Wrapper.new(Point.new(close)))
max_bars_back(src, 5)
plot(source(Wrapper.new(Point.new(close)))[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "direct nested UDT arg expr nested pure UDF call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same direct nested UDT arg expr nested pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_direct_nested_udt_arg_expr_nested_pure_udf_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
adjust(w, delta) => w.inner.x + delta
source(w, delta) => adjust(delta=delta, w=w)
len = input.int(1, "Length")
src = source(delta=1, w=Wrapper.new(Point.new(close)))
max_bars_back(src, 5)
plot(source(w=Wrapper.new(Point.new(close)), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "named direct nested UDT arg expr nested pure UDF call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same named direct nested UDT arg expr nested pure UDF call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_named_direct_nested_udt_arg_expr_nested_pure_udf_series_id_after_inner_reassignment()
 {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
adjust(w, delta) => w.inner.x + delta
source(w, delta) => adjust(delta=delta, w=w)
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
src = source(delta=1, w=Wrapper.new(p))
max_bars_back(src, 5)
plot(source(w=Wrapper.new(p), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "named direct nested UDT arg expr nested pure UDF call alias max_bars_back should be inferred",
        );

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn does_not_reuse_nested_udt_arg_field_nested_pure_udf_series_id_after_inner_reassignment() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
adjust(w) => w.inner.x + 1
source(w) => adjust(w)
len = input.int(1, "Length")
p = Point.new(close)
p := Point.new(open)
w = Wrapper.new(p)
src = source(w)
max_bars_back(src, 5)
plot(source(w)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested UDT arg field nested pure UDF call alias max_bars_back should be inferred");

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_nested_receiver_field_nested_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method adjust(Wrapper w) => w.inner.x + 1
method source(Wrapper w) => w.adjust()
len = input.int(1, "Length")
p = Point.new(close)
w = Wrapper.new(p)
src = w.source()
max_bars_back(src, 5)
plot(w.source()[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "nested receiver field nested pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested receiver field nested pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_nested_udt_arg_field_nested_pure_user_method_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method adjust(Point p, Wrapper other) => other.inner.x + 1
method source(Point p, Wrapper other) => p.adjust(other)
len = input.int(1, "Length")
p = Point.new(open)
inner = Point.new(close)
other = Wrapper.new(inner)
src = p.source(other)
max_bars_back(src, 5)
plot(p.source(other)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "nested UDT arg field nested pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same nested UDT arg field nested pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn reuses_named_direct_nested_udt_arg_expr_nested_pure_user_method_call_series_id_for_max_bars_back_history()
 {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method adjust(Point p, Wrapper other, float delta) => other.inner.x + delta
method source(Point p, Wrapper other, float delta) => p.adjust(delta=delta, other=other)
len = input.int(1, "Length")
p = Point.new(open)
src = p.source(delta=1, other=Wrapper.new(Point.new(close)))
max_bars_back(src, 5)
plot(p.source(other=Wrapper.new(Point.new(close)), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "named direct nested UDT arg expr nested pure user method call alias max_bars_back should be inferred",
        );
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect(
            "same named direct nested UDT arg expr nested pure user method call should carry the dynamic history requirement",
        );

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_named_direct_nested_udt_arg_expr_nested_pure_user_method_series_id_after_inner_reassignment()
 {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point inner
method adjust(Point p, Wrapper other, float delta) => other.inner.x + delta
method source(Point p, Wrapper other, float delta) => p.adjust(delta=delta, other=other)
len = input.int(1, "Length")
p = Point.new(open)
inner = Point.new(close)
inner := Point.new(high)
src = p.source(delta=1, other=Wrapper.new(inner))
max_bars_back(src, 5)
plot(p.source(other=Wrapper.new(inner), delta=1)[len])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect(
            "named direct nested UDT arg expr nested pure user method call alias max_bars_back should be inferred",
        );

    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id
                || !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn reuses_nested_parameterized_pure_udf_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nadjust(value) => value + 1\nsource(a) => adjust(a)\nsrc = source(close)\nmax_bars_back(src, 5)\nplot(source(a=close)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("nested pure UDF call alias max_bars_back should be inferred");
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == bound.series_id)
        .expect("same nested pure UDF call should carry the dynamic history requirement");

    assert_eq!(bound.series_id, source_series);
    assert!(requirement.has_dynamic_offsets, "{:?}", hir.series_history);
}

#[test]
fn does_not_reuse_stateful_math_call_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nsrc = math.sum(close, 2)\nmax_bars_back(src, 5)\nplot(math.sum(close, 2)[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("math.sum alias max_bars_back should be inferred");
    assert_eq!(bound.series_id, source_series);
    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn does_not_reuse_stateful_qualified_builtin_series_id_for_max_bars_back_history() {
    let analysis = analyze(
        "strategy(\"Demo\")\nlen = input.int(1, \"Length\")\nsrc = strategy.position_avg_price\nmax_bars_back(src, 5)\nplot(strategy.position_avg_price[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let source_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("alias max_bars_back should be inferred");
    assert_eq!(bound.series_id, source_series);
    assert!(
        hir.series_history
            .iter()
            .all(|requirement| requirement.series_id != bound.series_id),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn keeps_reassigned_decl_series_id_distinct_from_initial_pure_expression() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nspread = close + open\nspread := high + low\nmax_bars_back(close + open, 5)\nplot(spread[len])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let spread_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "spread")
        .and_then(|symbol| symbol.series_id)
        .expect("spread should have a series id");
    let bound = hir
        .series_max_bars_back
        .iter()
        .find(|value| value.max_bars_back == 5)
        .expect("expression max_bars_back should be inferred");

    assert_ne!(bound.series_id, spread_series);
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.series_id == spread_series
                && requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn infers_implicit_builtin_history_requirements() {
    let analysis = analyze(
        "len = input.int(1, \"Length\")\nplot(ta.tr)\nplot(ta.tr())\nplot(ta.change(open, 2))\nplot(ta.change(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(hir.history.has_dynamic_offsets);
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.max_constant_offset == 2),
        "{:?}",
        hir.series_history
    );
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn infers_dynamic_momentum_builtin_length_history_requirements() {
    let analysis = analyze(
        "length = bar_index == 0 ? 1 : 2\nplot(ta.mom(close, length))\nplot(ta.roc(open, length))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
    assert_series_history(&hir, "open", 0, true);
}

#[test]
fn infers_named_const_builtin_length_history_requirement() {
    let analysis = analyze("length = 1 + 1\nplot(ta.mom(close, length))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.max_constant_offset == 2
                && !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn infers_alias_named_const_builtin_length_history_requirement() {
    let analysis = analyze("base = 1\nlength = base + 1\nplot(ta.mom(close, length))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.max_constant_offset == 2
                && !requirement.has_dynamic_offsets),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn infers_implicit_ta_history_requirements_by_series() {
    let analysis = analyze(
        r#"len = input.int(1, "Length")
plot(ta.tr())
plot(ta.atr(2))
[line, direction] = ta.supertrend(2, 3)
plot(line + direction)
[middle, upper, lower] = ta.kc(close, 2, 2)
plot(middle + upper + lower)
plot(ta.kcw(close, 2, 2))
[plus, minus, adx] = ta.dmi(3, 2)
plot(plus + minus + adx)
plot(ta.sar(0.02, 0.02, 0.2))
plot(ta.mfi(close, 3))
plot(ta.tsi(close, 2, 3))
plot(ta.cmo(close, 3))
plot(ta.change(open, 2))
plot(ta.change(close, len))
plot(ta.mom(high, 4))
plot(ta.roc(low, len))
plot(ta.cross(close, open) ? 1 : 0)
plot(ta.crossover(high, low) ? 1 : 0)
plot(ta.crossunder(close, low) ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");

    assert_eq!(hir.history.max_constant_offset, 4);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 1, true);
    assert_series_history(&hir, "open", 2, false);
    assert_series_history(&hir, "high", 4, false);
    assert_series_history(&hir, "low", 2, true);
}

#[test]
fn infers_explicit_source_extreme_window_history_requirements() {
    let analysis = analyze(
        r#"plot(ta.highest(close, 3))
plot(ta.lowest(open, 2))
plot(ta.highestbars(high, 4))
plot(ta.lowestbars(low, 5))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 4);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
    assert_series_history(&hir, "open", 1, false);
    assert_series_history(&hir, "high", 3, false);
    assert_series_history(&hir, "low", 4, false);
}

#[test]
fn infers_default_source_extreme_window_history_requirements() {
    let analysis = analyze(
        r#"plot(ta.highest(3))
plot(ta.lowest(2))
plot(ta.highestbars(4))
plot(ta.lowestbars(length=5))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 4);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "high", 3, false);
    assert_series_history(&hir, "low", 4, false);
}

#[test]
fn infers_trend_window_history_requirements() {
    let analysis = analyze(
        r#"plot(ta.rising(close, 3) ? 1 : 0)
plot(ta.falling(open, 2) ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 3);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 3, false);
    assert_series_history(&hir, "open", 2, false);
}

#[test]
fn infers_named_reordered_implicit_ta_history_requirements() {
    let analysis = analyze(
        r#"len = input.int(2, "Length")
plot(ta.change(length=2, source=open))
plot(ta.mom(length=3, source=close))
plot(ta.roc(length=len, source=high))
plot(ta.highest(length=5, source=low))
plot(ta.falling(length=4, source=volume) ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 4);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "open", 2, false);
    assert_series_history(&hir, "close", 3, false);
    assert_series_history(&hir, "high", 0, true);
    assert_series_history(&hir, "low", 4, false);
    assert_series_history(&hir, "volume", 4, false);
}

#[test]
fn infers_multiplicative_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, 1 * 2))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_modulo_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, 5 % 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_ternary_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, false ? 1 : 2))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_constant_length_implicit_ta_history_requirements() {
    let analysis = analyze("length() => 2\nplot(ta.mom(close, length()))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_local_constant_length_implicit_ta_history_requirements() {
    let analysis =
        analyze("length() =>\n    value = 2\n    value\nplot(ta.mom(close, length()))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_local_constant_after_expr_statement_implicit_ta_history_requirements() {
    let analysis = analyze(
        "length() =>\n    value = 2\n    close\n    value\nplot(ta.mom(close, length()))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_reassigned_local_length_dynamic_for_implicit_ta_history() {
    let analysis = analyze(
        "length() =>\n    value = 1\n    value := 2\n    value\nplot(ta.mom(close, length()))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_local_constant_after_unrelated_if_statement_history_offset() {
    let analysis = analyze(
        "length() =>\n    value = 2\n    if close > open\n        other = 1\n    value\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_local_constant_reassigned_in_if_statement_history_offset_dynamic() {
    let analysis = analyze(
        "length() =>\n    value = 2\n    if close > open\n        value := 3\n    value\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_branch_invariant_local_constant_dynamic_condition_history_offset() {
    let analysis = analyze(
        "length() =>\n    value = 2\n    close > open ? value : value\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_branch_variant_local_constant_dynamic_condition_history_offset_dynamic() {
    let analysis = analyze(
        "length() =>\n    value = 2\n    close > open ? value : value + 1\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_selector_switch_local_constant_history_offset() {
    let analysis = analyze(
        "length() =>\n    mode = 1\n    value = 2\n    switch mode\n        1 => value\n        => value + 1\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_condition_switch_branch_invariant_dynamic_condition_history_offset() {
    let analysis = analyze(
        "length() =>\n    value = 2\n    switch\n        close > open => value\n        => value\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_selector_switch_variant_dynamic_selector_history_offset_dynamic() {
    let analysis = analyze(
        "length() =>\n    value = 2\n    switch bar_index\n        1 => value\n        => value + 1\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_for_expression_constant_history_offset() {
    let analysis = analyze("length() =>\n    for i = 0 to 1\n        2\nplot(close[length()])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_for_expression_counter_history_offset_dynamic() {
    let analysis = analyze("length() =>\n    for i = 0 to 1\n        i\nplot(close[length()])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_tuple_destructured_local_constant_history_offset() {
    let analysis =
        analyze("length() =>\n    [value, ignored] = [2, 99]\n    value\nplot(close[length()])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_tuple_destructured_series_local_history_offset_dynamic() {
    let analysis = analyze(
        "length() =>\n    [value, ignored] = [2 + bar_index, 99]\n    value\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_user_type_field_constant_history_offset() {
    let analysis = analyze(
        "type Settings\n    int length\nlength() =>\n    settings = Settings.new(2)\n    settings.length\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_user_type_field_series_history_offset_dynamic() {
    let analysis = analyze(
        "type Settings\n    int length\nlength() =>\n    settings = Settings.new(2 + bar_index)\n    settings.length\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_user_type_field_branch_invariant_history_offset() {
    let analysis = analyze(
        "type Settings\n    int length\nlength() =>\n    settings = close > open ? Settings.new(2) : Settings.new(2)\n    settings.length\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_udf_user_type_field_branch_variant_history_offset_dynamic() {
    let analysis = analyze(
        "type Settings\n    int length\nlength() =>\n    settings = close > open ? Settings.new(2) : Settings.new(3)\n    settings.length\nplot(close[length()])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_udf_constant_argument_length_implicit_ta_history_requirements() {
    let analysis = analyze("length(value) => value\nplot(ta.mom(close, length(2)))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_derived_constant_argument_length_implicit_ta_history_requirements() {
    let analysis = analyze("length(value) => value + 1\nplot(ta.mom(close, length(1)))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_local_derived_constant_argument_length_implicit_ta_history_requirements() {
    let analysis = analyze(
        "length(value) =>\n    adjusted = value + 1\n    adjusted\nplot(ta.mom(close, length(1)))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_string_constant_argument_predicate_implicit_ta_history_requirements() {
    let analysis =
        analyze("is_a(value) => value == \"A\"\nplot(ta.mom(close, is_a(\"A\") ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_bool_constant_argument_predicate_implicit_ta_history_requirements() {
    let analysis =
        analyze("is_enabled(value) => value\nplot(ta.mom(close, is_enabled(true) ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_udf_color_constant_argument_predicate_implicit_ta_history_requirements() {
    let analysis = analyze(
        "is_red(value) => value == color.red\nplot(ta.mom(close, is_red(color.red) ? 2 : 1))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_boolean_expression_ternary_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (true and false) ? 1 : 2))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_short_circuit_and_dynamic_rhs_history_offset() {
    let analysis = analyze("plot(close[(false and close > open) ? 1 : 2])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_short_circuit_or_dynamic_rhs_history_offset() {
    let analysis = analyze("plot(close[(true or close > open) ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn keeps_non_short_circuit_dynamic_condition_history_offset_dynamic() {
    let analysis = analyze("plot(close[(true and close > open) ? 1 : 2])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 0, true);
}

#[test]
fn infers_bool_ternary_condition_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (true ? true : false) ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_comparison_ternary_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (1 + 1 == 2) ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_division_comparison_ternary_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (4 / 2 == 2) ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_string_comparison_ternary_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (\"A\" != \"B\") ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_string_value_ternary_comparison_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, ((true ? \"A\" : \"B\") == \"A\") ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_named_string_constant_value_comparison_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (adjustment.none == \"none\") ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_color_comparison_ternary_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (color.red == color.red) ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_color_value_ternary_comparison_implicit_ta_history_requirements() {
    let analysis =
        analyze("plot(ta.mom(close, ((true ? color.red : color.green) == color.red) ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_named_numeric_comparison_ternary_implicit_ta_history_requirements() {
    let analysis = analyze("plot(ta.mom(close, (math.pi > 3) ? 2 : 1))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert_series_history(&hir, "close", 2, false);
}

#[test]
fn infers_array_history_requirements() {
    let analysis = analyze(
        "values = array.new_float(1)\nvalues.set(0, close)\nprevious = values[1]\nplot(na(previous) ? na : previous.get(0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let values = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "values")
        .expect("values symbol should exist");
    let series_id = values
        .series_id
        .expect("array symbol should be tracked as a series");
    assert!(
        hir.series_history.iter().any(|requirement| {
            requirement.series_id == series_id && requirement.max_constant_offset == 1
        }),
        "{:?}",
        hir.series_history
    );
}

fn assert_series_history(
    hir: &pine_ir::HirProgram,
    symbol_name: &str,
    expected_offset: u32,
    expected_dynamic: bool,
) {
    let series_id = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == symbol_name)
        .and_then(|symbol| symbol.series_id)
        .unwrap_or_else(|| panic!("{symbol_name} should have a series id"));
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == series_id)
        .unwrap_or_else(|| panic!("{symbol_name} should have a history requirement"));

    assert_eq!(
        requirement.max_constant_offset, expected_offset,
        "{symbol_name} history requirement: {:?}",
        requirement
    );
    assert_eq!(
        requirement.has_dynamic_offsets, expected_dynamic,
        "{symbol_name} history requirement: {:?}",
        requirement
    );
}

#[test]
fn lowers_if_statement_to_hir() {
    let analysis = analyze("if close > open\n    plot(close)\nelse\n    plot(open)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "if")
    );
    let hir = analysis.hir.expect("if statement should lower");
    assert!(matches!(hir.statements[0].kind, HirStmtKind::If { .. }));
}

#[test]
fn lowers_valid_script_to_hir() {
    let analysis = analyze(
        r#"indicator("Demo", overlay=true)
length = input.int(20, "Length")
ma = ta.sma(close, length)
plot(ma)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("valid script should lower to HIR");
    assert_eq!(hir.statements.len(), 4);
    assert!(hir.next_call_site_id >= 3);
    assert!(hir.next_series_id > 10);
}

#[test]
fn lowers_var_declaration_to_var_slot() {
    let analysis = analyze("var x = 0\nx := x + 1\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("valid script should lower to HIR");
    let symbol = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol should exist");
    assert_eq!(symbol.persistence, PersistenceKind::Var);
    assert_eq!(symbol.var_slot_id, Some(VarSlotId(0)));
}

#[test]
fn lowers_plain_declaration_without_persistence() {
    let analysis = analyze("x = 0\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("valid script should lower to HIR");
    let symbol = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol should exist");
    assert_eq!(symbol.persistence, PersistenceKind::None);
    assert_eq!(symbol.var_slot_id, None);
}

#[test]
fn lowers_user_type_constructor_with_type_name_metadata() {
    let analysis = analyze(
        r#"type Point
    float x
p = Point.new(close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("UDT constructor script should lower");
    let value = hir
        .statements
        .iter()
        .find_map(|statement| match &statement.kind {
            HirStmtKind::Decl { value, .. } => Some(value),
            _ => None,
        })
        .expect("expected UDT declaration");

    let pine_ir::HirExprKind::UserTypeConstruct { identity, .. } = &value.kind else {
        panic!("expected UDT constructor HIR, got {:?}", value.kind);
    };
    assert_eq!(identity.source_id, 0);
    assert_eq!(identity.type_name, "Point");
}

#[test]
fn skips_hir_when_semantic_errors_exist() {
    let analysis = analyze("plot()\n");

    assert!(analysis.hir.is_none());
}

#[test]
fn lowers_tuple_assignment() {
    let analysis = analyze("[a, b] = [close, open]\nplot(a)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("valid tuple assignment should lower");
    assert!(
        hir.symbols
            .iter()
            .any(|symbol| symbol.name == "a" && symbol.series_id.is_some())
    );
}

#[test]
fn rejects_lowering_temp_symbol_budget_exhaustion() {
    let mut source = String::from("id(x) => x\n");
    for index in 0..=MAX_LOWERING_TEMP_SYMBOLS {
        source.push_str(&format!("x{index} = id(1)\n"));
    }

    let analysis = analyze(&source);

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_LOWERING_BUDGET"
                && diagnostic.message.contains("temporary symbols")
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}
