use pine_runtime::{PineValue, input_calls};
use pine_sema::{Analysis, AnalysisInput, PUBLIC_ANALYSIS_SCHEMA_VERSION, analyze_input};
use pine_syntax::{Diagnostic, Severity, SourceFile, Span};

pub(crate) fn analyze_input_json(input: AnalysisInput) -> String {
    let source_file = input.root().clone();
    let analysis = analyze_input(&input);
    analysis_json(&source_file, &analysis)
}

fn analysis_json(source: &SourceFile, analysis: &Analysis) -> String {
    let mut output = format!("{{\"schemaVersion\":{},", PUBLIC_ANALYSIS_SCHEMA_VERSION);
    output.push_str("\"languageVersion\":");
    match analysis.compatibility.language_version {
        Some(version) => output.push_str(&version.to_string()),
        None => output.push_str("null"),
    }
    output.push_str(&format!(
        ",\"languageVersionOrigin\":\"{}\"",
        analysis.compatibility.language_version_origin.name()
    ));
    output.push_str(",\"dialect\":");
    match analysis.compatibility.dialect {
        Some(dialect) => output.push_str(&format!("\"{}\"", dialect.name())),
        None => output.push_str("null"),
    }
    output.push_str(&format!(
        ",\"scriptMode\":\"{}\"",
        analysis.compatibility.script_mode.name()
    ));
    output.push_str(",\"executable\":");
    output.push_str(if analysis.hir.is_some() {
        "true"
    } else {
        "false"
    });
    output.push_str(",\"diagnostics\":");
    output.push_str(&diagnostics_json(source, &analysis.diagnostics));
    output.push_str(",\"inputs\":");
    output.push_str(&inputs_json(analysis));
    output.push_str(",\"compatibility\":{");
    output.push_str("\"supported\":");
    output.push_str(&features_json(
        source,
        analysis
            .compatibility
            .supported
            .iter()
            .map(|feature| (&feature.feature, None, feature.span)),
    ));
    output.push_str(",\"unsupported\":");
    output.push_str(&features_json(
        source,
        analysis
            .compatibility
            .unsupported
            .iter()
            .map(|feature| (&feature.feature, Some(&feature.reason), feature.span)),
    ));
    output.push_str(",\"legacyTranslations\":");
    output.push_str(&legacy_translations_json(source, analysis));
    output.push_str(",\"legacyEmulations\":");
    output.push_str(&legacy_emulations_json(source, analysis));
    output.push_str("}}");
    output
}

pub(crate) fn analysis_error_json(message: &str) -> String {
    format!(
        "{{\"schemaVersion\":{},\"languageVersion\":null,\"languageVersionOrigin\":null,\"dialect\":null,\"scriptMode\":null,\"executable\":false,\"diagnostics\":[{{\"code\":\"E_HOST_INPUT\",\"severity\":\"error\",\"message\":\"{}\",\"span\":{{\"start\":0,\"end\":0,\"line\":1,\"column\":1}}}}],\"inputs\":[],\"compatibility\":{{\"supported\":[],\"unsupported\":[],\"legacyTranslations\":[],\"legacyEmulations\":[]}}}}",
        PUBLIC_ANALYSIS_SCHEMA_VERSION,
        json_escape(message)
    )
}

fn legacy_translations_json(source: &SourceFile, analysis: &Analysis) -> String {
    let mut output = String::from("[");
    for (index, translation) in analysis
        .compatibility
        .legacy_translations
        .iter()
        .enumerate()
    {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"sourceFeature\":\"{}\",\"canonicalFeature\":\"{}\",\"kind\":\"{}\",\"span\":{}}}",
            json_escape(&translation.source_feature),
            json_escape(&translation.canonical_feature),
            translation.kind.name(),
            span_json(source, translation.span)
        ));
    }
    output.push(']');
    output
}

fn legacy_emulations_json(source: &SourceFile, analysis: &Analysis) -> String {
    let mut output = String::from("[");
    for (index, emulation) in analysis.compatibility.legacy_emulations.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"feature\":\"{}\",\"behavior\":\"{}\",\"span\":{}}}",
            json_escape(&emulation.feature),
            json_escape(&emulation.behavior),
            span_json(source, emulation.span)
        ));
    }
    output.push(']');
    output
}

fn inputs_json(analysis: &Analysis) -> String {
    let Some(hir) = &analysis.hir else {
        return "[]".to_owned();
    };
    let mut output = String::from("[");
    for (index, input) in input_calls(hir).into_iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"callSiteId\":{},\"name\":\"{}\",\"title\":",
            input.call_site_id,
            json_escape(&input.name)
        ));
        match input.title {
            Some(title) => output.push_str(&format!("\"{}\"", json_escape(&title))),
            None => output.push_str("null"),
        }
        output.push_str(",\"default\":");
        match &input.default_value {
            Some(value) => output.push_str(&input_value_json(value)),
            None => output.push_str("null"),
        }
        push_optional_input_value(&mut output, "min", input.min_value.as_ref());
        push_optional_input_value(&mut output, "max", input.max_value.as_ref());
        push_optional_input_value(&mut output, "step", input.step.as_ref());
        if !input.options.is_empty() {
            output.push_str(",\"options\":[");
            for (option_index, option) in input.options.iter().enumerate() {
                if option_index > 0 {
                    output.push(',');
                }
                output.push_str(&input_value_json(option));
            }
            output.push(']');
        }
        output.push('}');
    }
    output.push(']');
    output
}

fn push_optional_input_value(output: &mut String, name: &str, value: Option<&PineValue>) {
    if let Some(value) = value {
        output.push_str(&format!(",\"{name}\":{}", input_value_json(value)));
    }
}

fn input_value_json(value: &PineValue) -> String {
    match value {
        PineValue::Int(value) => value.to_string(),
        PineValue::Float(value) => value.to_string(),
        PineValue::Bool(value) => value.to_string(),
        PineValue::String(value) => format!("\"{}\"", json_escape(value)),
        _ => "null".to_owned(),
    }
}

fn features_json<'a>(
    source: &SourceFile,
    features: impl Iterator<Item = (&'a String, Option<&'a String>, Span)>,
) -> String {
    let mut output = String::from("[");
    for (index, (feature, reason, span)) in features.enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"feature\":\"{}\"", json_escape(feature)));
        if let Some(reason) = reason {
            output.push_str(&format!(",\"reason\":\"{}\"", json_escape(reason)));
        }
        output.push_str(",\"span\":");
        output.push_str(&span_json(source, span));
        output.push('}');
    }
    output.push(']');
    output
}

fn diagnostics_json(source: &SourceFile, diagnostics: &[Diagnostic]) -> String {
    let mut output = String::from("[");
    for (index, diagnostic) in diagnostics.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"code\":\"{}\",\"severity\":\"{}\",\"message\":\"{}\",\"span\":{}}}",
            json_escape(&diagnostic.code),
            severity_name(diagnostic.severity),
            json_escape(&diagnostic.message),
            span_json(source, diagnostic.span)
        ));
    }
    output.push(']');
    output
}

fn span_json(source: &SourceFile, span: Span) -> String {
    let line_col = source.line_col(span.start);
    format!(
        "{{\"start\":{},\"end\":{},\"line\":{},\"column\":{}}}",
        span.start, span.end, line_col.line, line_col.column
    )
}

fn severity_name(severity: Severity) -> &'static str {
    match severity {
        Severity::Error => "error",
        Severity::Warning => "warning",
        Severity::Info => "info",
    }
}

pub(crate) fn format_diagnostics(source: &SourceFile, diagnostics: &[Diagnostic]) -> String {
    diagnostics
        .iter()
        .map(|diagnostic| {
            let line_col = source.line_col(diagnostic.span.start);
            format!(
                "{}:{:?}:{}:{}: {}",
                diagnostic.code,
                diagnostic.severity,
                line_col.line,
                line_col.column,
                diagnostic.message
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

pub(crate) fn json_escape(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            '\u{08}' => escaped.push_str("\\b"),
            '\u{0C}' => escaped.push_str("\\f"),
            ch if (ch as u32) < 0x20 => {
                escaped.push_str(&format!("\\u{:04x}", ch as u32));
            }
            ch => escaped.push(ch),
        }
    }
    escaped
}
