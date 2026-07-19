use std::{fs, path::PathBuf};

use pine_syntax::{ExprKind, LineCol, SourceFile, StmtKind, parse_source};

fn workspace_fixture(path: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(path)
}

#[test]
fn parses_phase_1_basic_fixture() {
    let (source, parsed) = parse_fixture("tests/fixtures/syntax/phase1_basic.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(
        parsed.program.version.map(|version| version.version),
        Some(5)
    );
    assert_eq!(parsed.program.statements.len(), 6);
    assert_eq!(
        source.name(),
        workspace_fixture("tests/fixtures/syntax/phase1_basic.pine")
            .display()
            .to_string()
    );
}

#[test]
fn parses_soft_keyword_export_identifier_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/soft_keyword_export_identifier.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 3);
}

#[test]
fn parses_single_quoted_string_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/single_quoted_strings.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 7);
}

#[test]
fn parses_line_wrapped_single_line_string_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/line_wrapped_strings.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 6);
}

#[test]
fn parses_parenthesized_line_wrapping_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/parenthesized_line_wrapping.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 6);
}

#[test]
fn parses_legacy_line_wrapping_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/legacy_line_wrapping.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 11);
}

#[test]
fn rejects_multiple_of_four_legacy_line_wrapping_indentation() {
    let (_, parsed) =
        parse_fixture("tests/fixtures/syntax/invalid_legacy_line_wrapping_indentation.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_PARSE_EXPR"));
}

#[test]
fn reports_unterminated_single_quoted_string_fixture_and_recovers() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/unterminated_single_quoted_string.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_LEX_STRING"));
    assert!(parsed.program.statements.len() >= 2);
}

#[test]
fn parses_multiline_string_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/multiline_strings.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 11);
}

#[test]
fn reports_unterminated_multiline_string_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/unterminated_multiline_string.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_LEX_STRING"));
    assert!(parsed.program.statements.len() >= 2);
}

#[test]
fn reports_oversized_string_literal_fixture_without_parse_cascade() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/string_literal_limit.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_LEX_STRING_LIMIT"));
    assert_eq!(parsed.program.statements.len(), 3);
}

#[test]
fn parses_compound_assignment_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/compound_assignments.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 12);
}

#[test]
fn recovers_after_parse_error_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/parse_error_recovery.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_PARSE_EXPR"));
    assert_eq!(parsed.program.statements.len(), 3);
}

#[test]
fn reports_malformed_number_fixture_and_recovers() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/malformed_number_recovery.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_LEX_INT"));
    assert_eq!(parsed.program.statements.len(), 3);
}

#[test]
fn reports_malformed_float_fixture_and_recovers() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/malformed_float_recovery.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_LEX_FLOAT"));
    assert_eq!(parsed.program.statements.len(), 3);
}

#[test]
fn reports_utf8_diagnostic_columns_in_characters() {
    let (source, parsed) = parse_fixture("tests/fixtures/syntax/utf8_diagnostic_column.pine");
    let diagnostic = parsed
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == "E_LEX_CHAR")
        .expect("unexpected-character diagnostic");

    assert_eq!(
        source.line_col(diagnostic.span.start),
        LineCol { line: 3, column: 9 }
    );
}

#[test]
fn rejects_deep_expression_limit_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/deep_expression_limit.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_PARSE_EXPR_DEPTH"));
}

#[test]
fn parses_for_in_iteration_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/unsupported_for_in.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::ForIn {
        index,
        value,
        iterable,
        body,
    } = &parsed.program.statements[2].kind
    else {
        panic!("expected for...in statement");
    };
    assert_eq!(index, &None);
    assert_eq!(value, "value");
    assert!(matches!(
        iterable.kind,
        pine_syntax::ExprKind::Identifier(_)
    ));
    assert_eq!(body.len(), 1);
}

#[test]
fn parses_for_in_index_value_iteration_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/for_in_index_value.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::ForIn {
        index,
        value,
        iterable,
        body,
    } = &parsed.program.statements[2].kind
    else {
        panic!("expected for...in statement");
    };
    assert_eq!(index.as_deref(), Some("index"));
    assert_eq!(value, "value");
    assert!(matches!(
        iterable.kind,
        pine_syntax::ExprKind::Identifier(_)
    ));
    assert_eq!(body.len(), 1);
}

#[test]
fn rejects_for_in_multi_value_iteration_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/unsupported_for_in_index_value.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_PARSE_FOR"));
}

#[test]
fn parses_for_in_expression_index_value_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/for_in_expression_index_value.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
}

#[test]
fn parses_while_expression_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/while_expression.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let value = parsed
        .program
        .statements
        .iter()
        .find_map(|statement| match &statement.kind {
            StmtKind::Decl { name, value, .. } if name == "result" => Some(value),
            _ => None,
        })
        .expect("expected result declaration");
    let ExprKind::While { condition, body } = &value.kind else {
        panic!("expected while expression AST");
    };
    assert!(matches!(condition.kind, ExprKind::Binary { .. }));
    assert_eq!(body.len(), 2);
}

#[test]
fn rejects_array_new_udt_template_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/unsupported_array_new_udt.pine");

    assert!(has_diagnostic(&parsed.diagnostics, "E_PARSE_EXPR"));
}

#[test]
fn parses_imported_udt_array_new_template_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/imported_udt_array_new.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
}

#[test]
fn parses_udt_array_chained_field_mutation_fixture() {
    let (_, parsed) = parse_fixture("tests/fixtures/syntax/udt_array_chained_field_mutation.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
}

#[test]
fn parses_imported_method_call_result_receiver_fixture() {
    let (_, parsed) =
        parse_fixture("tests/fixtures/syntax/imported_method_call_result_receiver.pine");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
}

fn parse_fixture(path: &str) -> (SourceFile, pine_syntax::Parse) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let parsed = parse_source(&source);
    (source, parsed)
}

fn has_diagnostic(diagnostics: &[pine_syntax::Diagnostic], code: &str) -> bool {
    diagnostics.iter().any(|diagnostic| diagnostic.code == code)
}
