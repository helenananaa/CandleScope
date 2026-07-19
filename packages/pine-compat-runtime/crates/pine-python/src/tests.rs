use super::diagnostics_have_errors;
use pine_syntax::{Diagnostic, Severity, Span};

#[test]
fn diagnostics_have_errors_ignores_warning_and_info() {
    let diagnostics = vec![
        Diagnostic {
            code: "W_TEST".to_owned(),
            severity: Severity::Warning,
            message: "warning".to_owned(),
            span: Span { start: 0, end: 0 },
        },
        Diagnostic {
            code: "I_TEST".to_owned(),
            severity: Severity::Info,
            message: "info".to_owned(),
            span: Span { start: 0, end: 0 },
        },
    ];

    assert!(!diagnostics_have_errors(&diagnostics));
}

#[test]
fn diagnostics_have_errors_detects_errors() {
    let diagnostics = vec![Diagnostic::error(
        "E_TEST",
        "error",
        Span { start: 0, end: 0 },
    )];

    assert!(diagnostics_have_errors(&diagnostics));
}
