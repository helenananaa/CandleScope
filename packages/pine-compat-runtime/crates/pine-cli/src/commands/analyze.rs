use pine_runtime::{PineValue, input_calls};
use pine_sema::{Analysis, PUBLIC_ANALYSIS_SCHEMA_VERSION, analyze_input};
use pine_syntax::{Diagnostic, Severity, SourceFile, Span};

use crate::json::json_escape;
use crate::library_sources::{
    LibrarySourceSpec, analysis_input_from_paths, parse_library_source_spec,
};
use crate::usage;

pub(crate) fn run(args: Vec<String>) -> Result<(), String> {
    let options = parse_options(&args)?;
    let input = analysis_input_from_paths(&options.path, &options.library_sources)?;
    let source = input.root().clone();
    let analysis = analyze_input(&input);
    match options.format {
        AnalyzeFormat::Text => print_text_report(&source, &analysis),
        AnalyzeFormat::Json => println!("{}", analysis_json(&source, &analysis)),
    }
    let has_errors = analysis
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == Severity::Error);
    if has_errors {
        return Err("analysis failed".to_owned());
    }
    Ok(())
}

#[derive(Debug)]
struct AnalyzeOptions {
    path: String,
    library_sources: Vec<LibrarySourceSpec>,
    format: AnalyzeFormat,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AnalyzeFormat {
    Text,
    Json,
}

fn parse_options(args: &[String]) -> Result<AnalyzeOptions, String> {
    let Some(path) = args.first() else {
        return Err(usage());
    };
    let mut options = AnalyzeOptions {
        path: path.clone(),
        library_sources: Vec::new(),
        format: AnalyzeFormat::Text,
    };
    let mut index = 1;
    while index < args.len() {
        match args[index].as_str() {
            "--library-source" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                options
                    .library_sources
                    .push(parse_library_source_spec(value)?);
            }
            "--format" => {
                index += 1;
                options.format = match args.get(index).map(String::as_str) {
                    Some("text") => AnalyzeFormat::Text,
                    Some("json") => AnalyzeFormat::Json,
                    _ => return Err(usage()),
                };
            }
            _ => return Err(usage()),
        }
        index += 1;
    }
    Ok(options)
}

fn print_text_report(source: &SourceFile, analysis: &Analysis) {
    println!("diagnostics: {}", analysis.diagnostics.len());
    println!(
        "supported: {}, unsupported: {}",
        analysis.compatibility.supported.len(),
        analysis.compatibility.unsupported.len()
    );
    let dialect = analysis
        .compatibility
        .dialect
        .map_or("invalid", |dialect| dialect.name());
    println!(
        "language: {} ({}), mode: {}",
        dialect,
        analysis.compatibility.language_version_origin.name(),
        analysis.compatibility.script_mode.name()
    );
    println!(
        "legacy: translations {}, emulations {}",
        analysis.compatibility.legacy_translations.len(),
        analysis.compatibility.legacy_emulations.len()
    );
    for diagnostic in &analysis.diagnostics {
        let line_col = source.line_col(diagnostic.span.start);
        println!(
            "{}:{:?}:{}:{}: {}",
            diagnostic.code,
            diagnostic.severity,
            line_col.line,
            line_col.column,
            diagnostic.message
        );
    }
}

pub(crate) fn analysis_json(source: &SourceFile, analysis: &Analysis) -> String {
    let compatibility = &analysis.compatibility;
    let language_version = compatibility
        .language_version
        .map_or_else(|| "null".to_owned(), |version| version.to_string());
    let dialect = compatibility.dialect.map_or_else(
        || "null".to_owned(),
        |dialect| format!("\"{}\"", dialect.name()),
    );
    format!(
        "{{\"schemaVersion\":{},\"languageVersion\":{},\"languageVersionOrigin\":\"{}\",\"dialect\":{},\"scriptMode\":\"{}\",\"executable\":{},\"diagnostics\":{},\"inputs\":{},\"compatibility\":{{\"supported\":{},\"unsupported\":{},\"legacyTranslations\":{},\"legacyEmulations\":{}}}}}",
        PUBLIC_ANALYSIS_SCHEMA_VERSION,
        language_version,
        compatibility.language_version_origin.name(),
        dialect,
        compatibility.script_mode.name(),
        analysis.hir.is_some(),
        diagnostics_json(source, &analysis.diagnostics),
        inputs_json(analysis),
        features_json(
            source,
            compatibility
                .supported
                .iter()
                .map(|feature| (&feature.feature, None, feature.span)),
        ),
        features_json(
            source,
            compatibility.unsupported.iter().map(|feature| (
                &feature.feature,
                Some(&feature.reason),
                feature.span
            )),
        ),
        legacy_translations_json(source, analysis),
        legacy_emulations_json(source, analysis),
    )
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

fn inputs_json(analysis: &Analysis) -> String {
    let Some(hir) = &analysis.hir else {
        return "[]".to_owned();
    };
    let mut output = String::from("[");
    for (index, input) in input_calls(hir).into_iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        let title = input.title.as_deref().map_or_else(
            || "null".to_owned(),
            |title| format!("\"{}\"", json_escape(title)),
        );
        output.push_str(&format!(
            "{{\"callSiteId\":{},\"name\":\"{}\",\"title\":{},\"default\":{}",
            input.call_site_id,
            json_escape(&input.name),
            title,
            input
                .default_value
                .as_ref()
                .map_or_else(|| "null".to_owned(), input_value_json)
        ));
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
        output.push_str(&format!(",\"span\":{}}}", span_json(source, span)));
    }
    output.push(']');
    output
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

#[cfg(test)]
mod tests {
    use super::{AnalyzeFormat, analysis_json, parse_options, run};
    use pine_sema::{PUBLIC_ANALYSIS_SCHEMA_VERSION, analyze_source};
    use pine_syntax::SourceFile;
    use std::{env, fs};

    #[test]
    fn parses_json_analysis_format() {
        let options = parse_options(&[
            "demo.pine".to_owned(),
            "--format".to_owned(),
            "json".to_owned(),
        ])
        .expect("options");

        assert_eq!(options.format, AnalyzeFormat::Json);
    }

    #[test]
    fn analysis_json_exposes_phase_one_dialect_contract() {
        let source = SourceFile::new(
            "test.pine",
            "//@version=6\nindicator(\"demo\")\nplot(close)\n",
        );
        let analysis = analyze_source(&source);

        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(
            parsed["schemaVersion"],
            serde_json::json!(PUBLIC_ANALYSIS_SCHEMA_VERSION)
        );
        assert_eq!(parsed["languageVersion"], serde_json::json!(6));
        assert_eq!(
            parsed["languageVersionOrigin"],
            serde_json::json!("explicit")
        );
        assert_eq!(parsed["dialect"], serde_json::json!("v6"));
        assert_eq!(parsed["scriptMode"], serde_json::json!("indicator"));
        assert_eq!(
            parsed["compatibility"]["legacyTranslations"],
            serde_json::json!([])
        );
        assert_eq!(
            parsed["compatibility"]["legacyEmulations"],
            serde_json::json!([])
        );
    }

    #[test]
    fn analysis_json_exposes_executable_implicit_v1_legacy_indicator() {
        let source = SourceFile::new("legacy.pine", "study(\"legacy\")\nplot(close)\n");
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["languageVersion"], serde_json::json!(1));
        assert_eq!(
            parsed["languageVersionOrigin"],
            serde_json::json!("implicit")
        );
        assert_eq!(parsed["dialect"], serde_json::json!("v1"));
        assert_eq!(parsed["scriptMode"], serde_json::json!("legacyIndicator"));
        assert_eq!(parsed["executable"], serde_json::json!(true));
        assert_eq!(parsed["diagnostics"], serde_json::json!([]));
        assert_eq!(
            parsed["compatibility"]["legacyTranslations"],
            serde_json::json!([{
                "sourceFeature": "study",
                "canonicalFeature": "indicator",
                "kind": "signatureReshape",
                "span": {"start": 0, "end": 5, "line": 1, "column": 1}
            }])
        );
        assert_eq!(
            parsed["compatibility"]["legacyEmulations"],
            serde_json::json!([])
        );
    }

    #[test]
    fn analysis_json_exposes_executable_v4_translations() {
        let source = SourceFile::new(
            "legacy-v4.pine",
            "//@version=4\nstudy(\"legacy\")\nplot(sma(close, 2))\n",
        );
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["languageVersion"], serde_json::json!(4));
        assert_eq!(parsed["dialect"], serde_json::json!("v4"));
        assert_eq!(parsed["scriptMode"], serde_json::json!("legacyIndicator"));
        assert_eq!(parsed["executable"], serde_json::json!(true));
        assert_eq!(parsed["diagnostics"], serde_json::json!([]));
        assert_eq!(
            parsed["compatibility"]["legacyTranslations"],
            serde_json::json!([
                {
                    "sourceFeature": "study",
                    "canonicalFeature": "indicator",
                    "kind": "signatureReshape",
                    "span": {"start": 13, "end": 18, "line": 2, "column": 1}
                },
                {
                    "sourceFeature": "sma",
                    "canonicalFeature": "ta.sma",
                    "kind": "exactAlias",
                    "span": {"start": 34, "end": 37, "line": 3, "column": 6}
                }
            ])
        );
    }

    #[test]
    fn analysis_json_exposes_executable_v3_names_constants_and_na_inference() {
        let source = SourceFile::new(
            "legacy-v3-core.pine",
            include_str!("../../../../tests/fixtures/legacy/v3/runtime/core_legacy.pine"),
        );
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["languageVersion"], serde_json::json!(3));
        assert_eq!(parsed["dialect"], serde_json::json!("v3"));
        assert_eq!(parsed["scriptMode"], serde_json::json!("legacyIndicator"));
        assert_eq!(parsed["executable"], serde_json::json!(true));
        assert_eq!(parsed["diagnostics"], serde_json::json!([]));
        let translations = parsed["compatibility"]["legacyTranslations"]
            .as_array()
            .expect("legacy translations");
        for (source_feature, canonical_feature) in [
            ("study", "indicator"),
            ("integer", "input.int"),
            ("color", "color.new"),
            ("n", "bar_index"),
            ("interval", "timeframe.multiplier"),
        ] {
            assert!(translations.iter().any(|item| {
                item["sourceFeature"] == source_feature
                    && item["canonicalFeature"] == canonical_feature
            }));
        }
        assert!(
            parsed["compatibility"]["legacyEmulations"]
                .as_array()
                .expect("legacy emulations")
                .iter()
                .any(|item| item["feature"] == "v3.untyped_na")
        );
    }

    #[test]
    fn analysis_json_exposes_v2_graph_and_conversion_emulations() {
        let source = SourceFile::new(
            "legacy-v2-core.pine",
            include_str!("../../../../tests/fixtures/legacy/v2/runtime/core_legacy.pine"),
        );
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["languageVersion"], serde_json::json!(2));
        assert_eq!(parsed["dialect"], serde_json::json!("v2"));
        assert_eq!(parsed["scriptMode"], serde_json::json!("legacyIndicator"));
        assert_eq!(parsed["executable"], serde_json::json!(true));
        assert_eq!(parsed["diagnostics"], serde_json::json!([]));
        let emulations = parsed["compatibility"]["legacyEmulations"]
            .as_array()
            .expect("legacy emulations");
        for feature in [
            "v2.self_reference",
            "v2.forward_reference",
            "v2.bool_arithmetic",
            "v2.numeric_to_bool",
        ] {
            assert!(emulations.iter().any(|item| item["feature"] == feature));
        }
    }

    #[test]
    fn analysis_json_exposes_v4_expression_desugars_and_emulations() {
        let source = SourceFile::new(
            "legacy-v4-expressions.pine",
            "//@version=4\nstudy(\"expressions\")\nplot(iff(close > open, high, low))\nplot(offset(close, 1))\nplot(rsi(close, open))\n",
        );
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["executable"], serde_json::json!(true));
        assert_eq!(parsed["diagnostics"], serde_json::json!([]));
        let translations = parsed["compatibility"]["legacyTranslations"]
            .as_array()
            .expect("legacy translations");
        for (source_feature, canonical_feature) in [
            ("iff", "eager select"),
            ("offset", "history access"),
            ("rsi", "legacy RSI two-series formula"),
        ] {
            assert!(translations.iter().any(|item| {
                item["sourceFeature"] == source_feature
                    && item["canonicalFeature"] == canonical_feature
                    && item["kind"] == "expressionDesugar"
            }));
        }
        let emulations = parsed["compatibility"]["legacyEmulations"]
            .as_array()
            .expect("legacy emulations");
        assert!(emulations.iter().any(|item| item["feature"] == "iff"));
        assert!(emulations.iter().any(|item| item["feature"] == "rsi"));
    }

    #[test]
    fn analysis_json_exposes_v4_security_routing() {
        let source = SourceFile::new(
            "legacy-v4-security.pine",
            "//@version=4\nstudy(\"security\")\nplot(security(syminfo.tickerid, timeframe.period, close))\n",
        );
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["executable"], serde_json::json!(true));
        assert_eq!(parsed["diagnostics"], serde_json::json!([]));
        let translations = parsed["compatibility"]["legacyTranslations"]
            .as_array()
            .expect("legacy translations");
        assert!(translations.iter().any(|item| {
            item["sourceFeature"] == "security"
                && item["canonicalFeature"] == "request.security"
                && item["kind"] == "signatureReshape"
        }));
        let emulations = parsed["compatibility"]["legacyEmulations"]
            .as_array()
            .expect("legacy emulations");
        assert!(emulations.iter().any(|item| {
            item["feature"] == "security.merge"
                && item["behavior"]
                    .as_str()
                    .is_some_and(|value| value.contains("gaps_off/lookahead_off"))
        }));
    }

    #[test]
    fn analysis_json_exposes_canonical_v4_input_metadata() {
        let source = SourceFile::new(
            "legacy-v4-inputs.pine",
            include_str!("../../../../tests/fixtures/legacy/v4/runtime/inputs_legacy.pine"),
        );
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["executable"], serde_json::json!(true));
        assert_eq!(parsed["diagnostics"], serde_json::json!([]));
        assert_eq!(parsed["inputs"].as_array().map(Vec::len), Some(11));
        assert_eq!(parsed["inputs"][0]["callSiteId"], serde_json::json!(1));
        assert_eq!(parsed["inputs"][0]["name"], serde_json::json!("input.int"));
        assert_eq!(parsed["inputs"][0]["title"], serde_json::json!("Length"));
        assert_eq!(parsed["inputs"][0]["default"], serde_json::json!(3));
        assert_eq!(parsed["inputs"][0]["min"], serde_json::json!(1));
        assert_eq!(parsed["inputs"][0]["max"], serde_json::json!(9));
        assert_eq!(parsed["inputs"][0]["step"], serde_json::json!(1));
        assert_eq!(parsed["inputs"][0]["options"], serde_json::json!([1, 3, 5]));
        assert!(
            parsed["compatibility"]["legacyTranslations"]
                .as_array()
                .expect("legacy translations")
                .iter()
                .any(|translation| {
                    translation["sourceFeature"] == "input.integer"
                        && translation["canonicalFeature"] == "input.int"
                        && translation["kind"] == "constantAlias"
                })
        );
    }

    #[test]
    fn analysis_json_exposes_one_legacy_strategy_hard_stop() {
        let source = SourceFile::new(
            "legacy-strategy.pine",
            "//@version=4\nstrategy(\"legacy\")\nstrategy.entry(\"L\", strategy.long)\n",
        );
        let analysis = analyze_source(&source);
        let parsed: serde_json::Value =
            serde_json::from_str(&analysis_json(&source, &analysis)).expect("analysis JSON");

        assert_eq!(parsed["languageVersion"], serde_json::json!(4));
        assert_eq!(parsed["scriptMode"], serde_json::json!("strategy"));
        assert_eq!(parsed["diagnostics"].as_array().map(Vec::len), Some(1));
        assert_eq!(
            parsed["diagnostics"][0]["code"],
            serde_json::json!("E_LEGACY_STRATEGY_OUT_OF_SCOPE")
        );
        assert_eq!(
            parsed["compatibility"]["unsupported"][0]["feature"],
            serde_json::json!("legacy strategy")
        );
    }

    #[test]
    fn analyze_returns_error_when_error_diagnostics_exist() {
        let path = env::temp_dir().join(format!(
            "pine_analyze_error_{}_{}.pine",
            std::process::id(),
            line!()
        ));
        fs::write(&path, "//@version=5\nindicator(\"bad\")\nplot(unknown)\n")
            .expect("write script");

        let result = run(vec![path.to_string_lossy().into_owned()]);

        fs::remove_file(&path).expect("remove script");
        assert_eq!(result, Err("analysis failed".to_owned()));
    }
}
