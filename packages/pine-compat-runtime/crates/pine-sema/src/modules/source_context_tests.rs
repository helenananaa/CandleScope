use super::*;

fn parsed_decl_value(expression: &str) -> Expr {
    let source = pine_syntax::SourceFile::new("expression.pine", format!("value = {expression}\n"));
    let parsed = parse_source(&source);
    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let statement = parsed
        .program
        .statements
        .first()
        .expect("declaration statement");
    let StmtKind::Decl { value, .. } = &statement.kind else {
        panic!("expected declaration, got {:?}", statement.kind);
    };
    value.clone()
}

#[test]
fn imported_const_expressions_remain_metadata_neutral() {
    for expression in [
        "1",
        "math.pi",
        "-math.pi",
        "1 + 2 * 3",
        "true ? color.red : color.blue",
    ] {
        let value = parsed_decl_value(expression);
        assert!(
            is_const_import_expr(&value),
            "expected metadata-neutral imported const expression: {expression}"
        );
    }

    for (category, expression) in [
        ("identifier", "named"),
        ("user call", "helper(1)"),
        ("builtin call", "math.abs(1)"),
        ("tuple", "[1, 2]"),
        ("history", "close[1]"),
        ("UDT constructor", "Point.new(1)"),
        ("map constructor", "map.new<string, float>()"),
    ] {
        let value = parsed_decl_value(expression);
        assert!(
            !is_const_import_expr(&value),
            "{category} must retain expression provenance: {expression}"
        );
    }
}

#[test]
fn import_plan_assigns_context_per_alias_and_shares_it_across_callables() {
    let input = AnalysisInput::with_library_sources(
        pine_syntax::SourceFile::new(
            "root.pine",
            "import user/context/1 as left\nimport user/context/1 as right\n",
        ),
        vec![(
            "user/context/1".to_owned(),
            pine_syntax::SourceFile::new(
                "context.pine",
                r#"library("context")
export type Point
    float x

helper(float value) => value
export passthrough(float value) => helper(value)
method shift(Point self, float delta) => helper(self.x + delta)
"#,
            ),
        )],
    )
    .expect("valid source graph");

    let validation = validate_modules(&input);

    assert!(
        validation.diagnostics.is_empty(),
        "{:?}",
        validation.diagnostics
    );
    let left_export = validation
        .imported_functions
        .get("left.passthrough")
        .expect("left exported function");
    let left_private = validation
        .imported_functions
        .get("__import_left_helper")
        .expect("left private function");
    let left_method = validation
        .imported_methods
        .get(&("left.Point".to_owned(), "shift".to_owned()))
        .expect("left imported method");
    let right_export = validation
        .imported_functions
        .get("right.passthrough")
        .expect("right exported function");
    let right_private = validation
        .imported_functions
        .get("__import_right_helper")
        .expect("right private function");
    let right_method = validation
        .imported_methods
        .get(&("right.Point".to_owned(), "shift".to_owned()))
        .expect("right imported method");

    assert_eq!(
        left_export.source_context_id,
        left_private.source_context_id
    );
    assert_eq!(left_export.source_context_id, left_method.source_context_id);
    assert_eq!(
        right_export.source_context_id,
        right_private.source_context_id
    );
    assert_eq!(
        right_export.source_context_id,
        right_method.source_context_id
    );
    assert_ne!(
        left_export.source_context_id,
        right_export.source_context_id
    );
    assert_eq!(left_export.source_id, right_export.source_id);
    assert_eq!(left_private.source_id, right_private.source_id);
    assert_eq!(left_method.source_id, right_method.source_id);
}
