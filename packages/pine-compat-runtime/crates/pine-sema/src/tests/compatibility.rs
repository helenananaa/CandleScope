use super::*;
use std::collections::BTreeSet;

use pine_builtins::{Accepts, PHASE_1_BUILTINS, ReturnSpec};
use pine_ir::{PineType, Qualifier, ValueKind};

#[test]
fn reports_supported_phase_1_calls() {
    let analysis = analyze("plot(ta.sma(close, 20))\n");

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
            .any(|feature| feature.feature == "plot")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.sma")
    );
}

#[test]
fn builtin_collection_result_producer_parser_allowlists_match_registry() {
    let registered = PHASE_1_BUILTINS
        .iter()
        .filter(|signature| signature.name.starts_with("array."))
        .filter(|signature| match signature.returns {
            ReturnSpec::Fixed(pine_type) => crate::types::is_array_kind(pine_type.kind),
            ReturnSpec::ArrayFromArgs => true,
            ReturnSpec::SameAsArg(index) => signature.params.get(index).is_some_and(|param| {
                matches!(
                    param.accepts,
                    Accepts::Array | Accepts::NumericArray | Accepts::ScalarArray
                )
            }),
            _ => false,
        })
        .map(|signature| signature.name)
        .collect::<BTreeSet<_>>();
    let expected = BTreeSet::from([
        "array.abs",
        "array.concat",
        "array.copy",
        "array.from",
        "array.new<chart.point>",
        "array.new_bool",
        "array.new_box",
        "array.new_color",
        "array.new_float",
        "array.new_int",
        "array.new_label",
        "array.new_line",
        "array.new_linefill",
        "array.new_polyline",
        "array.new_string",
        "array.new_table",
        "array.slice",
        "array.sort_indices",
        "array.standardize",
    ]);
    assert_eq!(registered, expected);

    for name in &registered {
        let source = SourceFile::new("test.pine", format!("value = {name}().size()\n"));
        let parsed = pine_syntax::parse_source(&source);
        assert!(
            parsed.diagnostics.is_empty(),
            "registered array producer `{name}` was parser-gated: {:?}",
            parsed.diagnostics
        );
    }

    for signature in PHASE_1_BUILTINS.iter().filter(|signature| {
        signature.name.starts_with("array.") && !registered.contains(signature.name)
    }) {
        let source = SourceFile::new(
            "test.pine",
            format!("value = {}().size()\n", signature.name),
        );
        let parsed = pine_syntax::parse_source(&source);
        assert!(
            parsed
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_PARSE_EXPR"),
            "non-producer array builtin `{}` unexpectedly admitted a call-result method: {:?}",
            signature.name,
            parsed.diagnostics
        );
    }

    let registered_cross_namespace_array_capable = PHASE_1_BUILTINS
        .iter()
        .filter(|signature| !signature.name.starts_with("array."))
        .filter(|signature| match signature.returns {
            ReturnSpec::Fixed(pine_type) => crate::types::is_array_kind(pine_type.kind),
            ReturnSpec::MatrixArray(_) | ReturnSpec::MatrixMult => true,
            _ => false,
        })
        .map(|signature| signature.name)
        .collect::<BTreeSet<_>>();
    let expected_cross_namespace_array_capable = BTreeSet::from([
        "matrix.col",
        "matrix.eigenvalues",
        "matrix.mult",
        "matrix.row",
        "str.split",
        "ta.pivot_point_levels",
    ]);
    assert_eq!(
        registered_cross_namespace_array_capable,
        expected_cross_namespace_array_capable
    );

    for name in &registered_cross_namespace_array_capable {
        let source = SourceFile::new("test.pine", format!("value = {name}().size()\n"));
        let parsed = pine_syntax::parse_source(&source);
        assert!(
            parsed.diagnostics.is_empty(),
            "registered cross-namespace array-capable producer `{name}` was parser-gated: {:?}",
            parsed.diagnostics
        );
    }

    let registered_cross_namespace_matrix_capable = PHASE_1_BUILTINS
        .iter()
        .filter(|signature| !signature.name.starts_with("array."))
        .filter(|signature| match signature.returns {
            ReturnSpec::Fixed(pine_type) => crate::types::is_matrix_kind(pine_type.kind),
            ReturnSpec::SameAsArg(index) => signature.params.get(index).is_some_and(|param| {
                matches!(
                    param.accepts,
                    Accepts::FloatMatrix | Accepts::NumericMatrix | Accepts::Matrix
                )
            }),
            ReturnSpec::MatrixMult => true,
            _ => false,
        })
        .map(|signature| signature.name)
        .collect::<BTreeSet<_>>();
    let expected_matrix_call_result_producers = BTreeSet::from([
        "matrix.copy",
        "matrix.diff",
        "matrix.eigenvectors",
        "matrix.inv",
        "matrix.kron",
        "matrix.mult",
        "matrix.new<bool>",
        "matrix.new<color>",
        "matrix.new<float>",
        "matrix.new<int>",
        "matrix.new<string>",
        "matrix.pinv",
        "matrix.pow",
        "matrix.submatrix",
        "matrix.transpose",
    ]);
    assert!(
        expected_matrix_call_result_producers
            .iter()
            .all(|name| registered_cross_namespace_matrix_capable.contains(name)),
        "matrix call-result parser allowlist must stay within registered matrix-capable producers"
    );

    for name in &registered_cross_namespace_matrix_capable {
        let source = SourceFile::new("test.pine", format!("value = {name}().rows()\n"));
        let parsed = pine_syntax::parse_source(&source);
        if expected_matrix_call_result_producers.contains(name) {
            assert!(
                parsed.diagnostics.is_empty(),
                "registered matrix call-result producer `{name}` was parser-gated: {:?}",
                parsed.diagnostics
            );
        } else {
            assert!(
                parsed
                    .diagnostics
                    .iter()
                    .any(|diagnostic| diagnostic.code == "E_PARSE_EXPR"),
                "non-allowlisted matrix producer `{name}` unexpectedly admitted a call-result method: {:?}",
                parsed.diagnostics
            );
        }
    }

    for signature in PHASE_1_BUILTINS.iter().filter(|signature| {
        matches!(
            signature
                .name
                .split_once('.')
                .map(|(namespace, _)| namespace),
            Some("str" | "ta" | "matrix")
        ) && !registered_cross_namespace_array_capable.contains(signature.name)
            && !expected_matrix_call_result_producers.contains(signature.name)
    }) {
        let source = SourceFile::new(
            "test.pine",
            format!("value = {}().size()\n", signature.name),
        );
        let parsed = pine_syntax::parse_source(&source);
        assert!(
            parsed
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_PARSE_EXPR"),
            "non-producer cross-namespace builtin `{}` unexpectedly admitted a call-result method: {:?}",
            signature.name,
            parsed.diagnostics
        );
    }

    let custom_map_array_producers = BTreeSet::from(["map.keys", "map.values"]);
    for name in custom_map_array_producers {
        let source = SourceFile::new("test.pine", format!("value = {name}().size()\n"));
        let parsed = pine_syntax::parse_source(&source);
        assert!(
            parsed.diagnostics.is_empty(),
            "custom map array producer `{name}` was parser-gated: {:?}",
            parsed.diagnostics
        );
    }
}

#[test]
fn builtin_map_result_parser_template_allowlist_matches_supported_scalar_templates() {
    const SCALAR_TEMPLATES: &[&str] = &["int", "float", "bool", "string", "color"];

    for key_type in SCALAR_TEMPLATES {
        for value_type in SCALAR_TEMPLATES {
            let source = SourceFile::new(
                "test.pine",
                format!("value = map.new<{key_type},{value_type}>().size()\n"),
            );
            let parsed = pine_syntax::parse_source(&source);
            assert!(
                parsed.diagnostics.is_empty(),
                "supported map.new<{key_type},{value_type}> call-result was parser-gated: {:?}",
                parsed.diagnostics
            );
        }
    }

    for unsupported in ["line", "label", "chart.point"] {
        let source = SourceFile::new(
            "test.pine",
            format!("value = map.new<{unsupported},int>().size()\n"),
        );
        let parsed = pine_syntax::parse_source(&source);
        assert!(
            parsed
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_PARSE_EXPR"),
            "unsupported map.new<{unsupported},int> call-result escaped parser gate: {:?}",
            parsed.diagnostics
        );
    }
}

#[test]
fn reports_unsupported_drawing_namespace_without_unknown_function_noise() {
    let analysis = analyze("label.set_text_wrap(na, na)\nplot(close)\n");
    let codes: Vec<_> = analysis
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect();

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "label.set_text_wrap"
    );
    assert!(codes.contains(&"E_UNSUPPORTED_FEATURE"), "{codes:?}");
    assert!(!codes.contains(&"E_UNKNOWN_FUNCTION"), "{codes:?}");
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("partial drawing subset")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_unsupported_drawing_method_without_unknown_method_noise() {
    let analysis = analyze("id = label.new(bar_index, high, \"start\")\nid.set_text_wrap(na)\n");
    let codes: Vec<_> = analysis
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect();

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "label.set_text_wrap"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(codes.contains(&"E_UNSUPPORTED_FEATURE"), "{codes:?}");
    assert!(!codes.contains(&"E_UNKNOWN_METHOD"), "{codes:?}");
}

#[test]
fn reports_dynamic_history_offset_actual_float_type() {
    let analysis = analyze("plot(close[close])\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "dynamic_history_offset"
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("got series float")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_dynamic_history_offset_actual_bool_type() {
    let analysis = analyze("offset = close > open\nplot(close[offset])\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "dynamic_history_offset"
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("got series bool")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_builtin_call_argument_actual_series_type() {
    let analysis = analyze("plot(ta.ema(close, bar_index))\n");

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_TYPE"
                && diagnostic.message.contains(
                    "`ta.ema` argument `length` expects simple integer-compatible, got series int",
                )
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        !analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("Series Int")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_map_call_argument_actual_const_type() {
    let analysis = analyze("m = map.new<string, int>()\nmap.put(m, 1, 2)\n");

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_TYPE"
                && diagnostic
                    .message
                    .contains("`map.put` argument `key` expects string-compatible, got const int")
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        !analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("Const Int")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_for_in_statement_scalar_tree_udt_boundary() {
    let analysis = analyze("for value in close\n    plot(value)\n");

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_UNSUPPORTED_FEATURE"
                && diagnostic.message.contains("scalar-tree UDT arrays")
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        !analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("scalar-field UDT")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_for_in_expression_scalar_tree_udt_boundary() {
    let analysis = analyze("result = for value in close\n    value\nplot(1)\n");

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_UNSUPPORTED_FEATURE"
                && diagnostic.message.contains("scalar-tree UDT array")
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        !analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("scalar-field UDT")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn accepts_same_context_request_security() {
    let analysis = analyze("plot(request.security(syminfo.tickerid, timeframe.period, close))\n");

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_request_security_explicit_default_merge_args() {
    let analysis = analyze(
        "plot(request.security(syminfo.tickerid, timeframe.period, close, gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off))\nplot(request.security(syminfo.tickerid, timeframe.period, close, lookahead=barmerge.lookahead_off))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_global_scalar_varip_declaration() {
    let analysis = analyze("varip x = 0\nx := x + 1\nplot(x)\n");

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
            .any(|feature| feature.feature == "varip")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("varip script should lower");
    let symbol = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol should exist");
    assert_eq!(symbol.persistence, PersistenceKind::Varip);
    assert_eq!(symbol.var_slot_id, Some(VarSlotId(0)));
}

#[test]
fn accepts_local_scalar_varip_declaration() {
    let analysis = analyze("if close > open\n    varip x = 0\n    x := x + 1\n    plot(x)\n");

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
            .any(|feature| feature.feature == "varip")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("local varip script should lower");
    let symbol = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol should exist");
    assert_eq!(symbol.persistence, PersistenceKind::Varip);
    assert_eq!(symbol.var_slot_id, Some(VarSlotId(0)));
}

#[test]
fn accepts_scalar_array_varip_declarations() {
    let analysis = analyze(
        r#"varip float[] floats = array.new_float(0)
varip int[] ints = array.new_int(0)
varip bool[] flags = array.new_bool(0)
varip string[] words = array.new_string(0)
varip color[] colors = array.new_color(0)
plot(array.size(floats) + array.size(ints) + array.size(flags) + array.size(words) + array.size(colors))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("array varip script should lower");
    let symbols: Vec<_> = hir
        .symbols
        .iter()
        .filter(|symbol| {
            matches!(
                symbol.name.as_str(),
                "floats" | "ints" | "flags" | "words" | "colors"
            )
        })
        .collect();
    assert_eq!(symbols.len(), 5);
    assert!(
        symbols
            .iter()
            .all(|symbol| symbol.persistence == PersistenceKind::Varip)
    );
    assert!(symbols.iter().all(|symbol| symbol.var_slot_id.is_some()));
}

#[test]
fn accepts_scalar_map_varip_declarations() {
    let analysis = analyze(
        r#"varip map<string, float> typed = na
if na(typed)
    typed := map.new<string, float>()
varip inferred = map.new<string, float>()
typed.put("close", close)
inferred.put("open", open)
plot(typed.get("close") + inferred.get("open"))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("map varip script should lower");
    let symbols: Vec<_> = hir
        .symbols
        .iter()
        .filter(|symbol| matches!(symbol.name.as_str(), "typed" | "inferred"))
        .collect();
    assert_eq!(symbols.len(), 2);
    assert!(
        symbols
            .iter()
            .all(|symbol| symbol.persistence == PersistenceKind::Varip)
    );
    assert!(symbols.iter().all(|symbol| symbol.var_slot_id.is_some()));
}

#[test]
fn rejects_tuple_varip_declaration() {
    let analysis = analyze("varip values = [1, 2]\nplot(close)\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(analysis.compatibility.unsupported[0].feature, "varip");
    assert!(
        analysis.compatibility.unsupported[0]
            .reason
            .contains("tuples")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_drawing_id_varip_declarations() {
    for source in [
        "varip id = label.new(bar_index, high, \"x\")\nplot(close)\n",
        "varip id = line.new(bar_index, low, bar_index, high)\nplot(close)\n",
        "varip id = box.new(bar_index, high, bar_index, low)\nplot(close)\n",
        "varip id = table.new(position.top_right, 1, 1)\nplot(close)\n",
    ] {
        let analysis = analyze(source);

        assert_eq!(analysis.compatibility.unsupported.len(), 1, "{source}");
        assert_eq!(analysis.compatibility.unsupported[0].feature, "varip");
        assert!(
            analysis.compatibility.unsupported[0]
                .reason
                .contains("drawing object ids"),
            "{:?}",
            analysis.compatibility.unsupported
        );
        assert!(analysis.hir.is_none());
    }
}

#[test]
fn rejects_reassigning_drawing_id_into_na_varip() {
    let analysis = analyze("varip id = na\nid := label.new(bar_index, high, \"x\")\nplot(close)\n");

    assert!(analysis.hir.is_none());
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_ASSIGN_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn accepts_provider_backed_same_timeframe_request_security_source() {
    let analysis = analyze("plot(request.security(\"NYSE:IBM\", timeframe.period, close))\n");

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_same_timeframe_request_security_ta_variable() {
    let analysis = analyze(
        "plot(request.security(\"NYSE:IBM\", timeframe.period, ta.accdist + ta.iii + ta.nvi + ta.obv + ta.pvi + ta.pvt + ta.wvad))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_tuple_ta_call() {
    let analysis = analyze(
        "[macd, signal, hist] = request.security(syminfo.tickerid, timeframe.period, ta.macd(close, 2, 3, 2))\nplot(macd + signal + hist)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_tuple_literal_expression() {
    let analysis = analyze(
        "[last, spread, above] = request.security(syminfo.tickerid, timeframe.period, [close, high - low, close > open ? 1 : 0])\nplot(last + spread + above)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_bb_tuple_call() {
    let analysis = analyze(
        "[basis, upper, lower] = request.security(syminfo.tickerid, timeframe.period, ta.bb(close, 3, 2))\nplot(basis + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_kc_tuple_call() {
    let analysis = analyze(
        "[middle, upper, lower] = request.security(syminfo.tickerid, timeframe.period, ta.kc(close, 3, 2))\nplot(middle + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_supertrend_tuple_call() {
    let analysis = analyze(
        "[line, direction] = request.security(syminfo.tickerid, timeframe.period, ta.supertrend(2, 3))\nplot(line + direction)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_dmi_tuple_call() {
    let analysis = analyze(
        "[plus, minus, adx] = request.security(syminfo.tickerid, timeframe.period, ta.dmi(3, 2))\nplot(plus + minus + adx)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_vwap_bands_tuple_call() {
    let analysis = analyze(
        "[basis, upper, lower] = request.security(syminfo.tickerid, timeframe.period, ta.vwap(close, false, 2.0))\nplot(basis + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_same_timeframe_request_security_expression() {
    let analysis =
        analyze("plot(request.security(\"NYSE:IBM\", timeframe.period, close + open))\n");

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_same_timeframe_request_security_ta() {
    let analysis = analyze(
        "plot(request.security(\"NYSE:IBM\", timeframe.period, ta.sma(close, 2) + ta.ema(close, 2) + ta.dema(close, 2) + ta.tema(close, 2) + ta.rma(close, 2) + ta.cum(close) + ta.rsi(close, 3) + ta.tsi(close, 2, 3) + ta.cmo(close, 3) + ta.cci(close, 3) + ta.cog(close, 3) + nz(ta.bop()) + nz(ta.ao()) + ta.max(close) + ta.min(open) + ta.mfi(close, 3) + ta.stoch(close, high, low, 3) + ta.wpr(3) + ta.sar(0.02, 0.02, 0.2) + ta.tr() + nz(ta.tr(false)) + ta.atr(3) + ta.highest(high, 3) + nz(ta.highestbars(close, 3)) - ta.lowest(low, 3) + nz(ta.lowestbars(close, 3)) + ta.change(close) + ta.mom(close, 2) + ta.roc(close, 2) + ta.range(close, 3) + ta.dev(close, 3) + ta.vwap(close) + ta.bbw(close, 3, 2) + ta.kcw(close, 3, 2, false) + nz(ta.pivothigh(high, 1, 1)) - nz(ta.pivotlow(low, 1, 1)) + ta.correlation(close, high, 3) + ta.covariance(close, high, 3) + ta.median(close, 3) + ta.mode(close, 3) + ta.percentile_nearest_rank(close, 3, 50) + ta.percentile_linear_interpolation(close, 3, 50) + ta.percentrank(close, 3) + ta.stdev(close, 3) + ta.stdev(close, 3, false) + ta.variance(close, 3) + ta.variance(close, 3, false) + ta.wma(close, 3) + ta.vwma(close, 3) + ta.swma(close) + ta.hma(close, 4) + ta.alma(close, 4, 0.85, 6) + ta.linreg(close, 3, 0) + (ta.rising(close, 2) ? 1 : 0) - (ta.falling(close, 2) ? 1 : 0) + nz(ta.barssince(close > open)) + nz(ta.valuewhen(close > open, close, 1)) + (ta.cross(close, 20.5) ? 1 : 0) + (ta.crossover(close, 20.5) ? 1 : 0) - (ta.crossunder(close - time / 60000.0, 19.5) ? 1 : 0)))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_macd_tuple_call() {
    let analysis = analyze(
        "[macd, signal, hist] = request.security(\"NYSE:IBM\", timeframe.period, ta.macd(close, 2, 3, 2))\nplot(macd + signal + hist)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_macd_tuple_call() {
    let analysis = analyze(
        "[macd, signal, hist] = request.security(\"NYSE:IBM\", \"5\", ta.macd(close, 2, 3, 2))\nplot(macd + signal + hist)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_bb_tuple_call() {
    let analysis = analyze(
        "[basis, upper, lower] = request.security(\"NYSE:IBM\", timeframe.period, ta.bb(close, 3, 2))\nplot(basis + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_bb_tuple_call() {
    let analysis = analyze(
        "[basis, upper, lower] = request.security(\"NYSE:IBM\", \"5\", ta.bb(close, 2, 2))\nplot(basis + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_kc_tuple_call() {
    let analysis = analyze(
        "[middle, upper, lower] = request.security(\"NYSE:IBM\", timeframe.period, ta.kc(close, 3, 2))\nplot(middle + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_kc_tuple_call() {
    let analysis = analyze(
        "[middle, upper, lower] = request.security(\"NYSE:IBM\", \"5\", ta.kc(close, 2, 2))\nplot(middle + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_supertrend_tuple_call() {
    let analysis = analyze(
        "[line, direction] = request.security(\"NYSE:IBM\", timeframe.period, ta.supertrend(2, 3))\nplot(line + direction)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_supertrend_tuple_call() {
    let analysis = analyze(
        "[line, direction] = request.security(\"NYSE:IBM\", \"5\", ta.supertrend(2, 3))\nplot(line + direction)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_dmi_tuple_call() {
    let analysis = analyze(
        "[plus, minus, adx] = request.security(\"NYSE:IBM\", timeframe.period, ta.dmi(3, 2))\nplot(plus + minus + adx)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_dmi_tuple_call() {
    let analysis = analyze(
        "[plus, minus, adx] = request.security(\"NYSE:IBM\", \"5\", ta.dmi(2, 2))\nplot(plus + minus + adx)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_vwap_bands_tuple_call() {
    let analysis = analyze(
        "[basis, upper, lower] = request.security(\"NYSE:IBM\", timeframe.period, ta.vwap(close, false, 2.0))\nplot(basis + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_vwap_bands_tuple_call() {
    let analysis = analyze(
        "[basis, upper, lower] = request.security(\"NYSE:IBM\", \"5\", ta.vwap(close, false, 2.0))\nplot(basis + upper + lower)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_expression() {
    let analysis = analyze(
        "[last, shifted, above] = request.security(\"NYSE:IBM\", timeframe.period, [close, close + 1, close > open ? 1 : 0])\nplot(last + shifted + above)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_history_and_nz_expression() {
    let analysis = analyze(
        "[prior, fallback, delta] = request.security(\"NYSE:IBM\", timeframe.period, [close[1], nz(close[1], open), close - nz(close[1], close)])\nplot(nz(prior) + fallback + delta)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_math_expression() {
    let analysis = analyze(
        "[maxv, minv, spread] = request.security(\"NYSE:IBM\", timeframe.period, [math.max(close, open), math.min(close, open), math.abs(open - close)])\nplot(maxv + minv + spread)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_stateful_math_expression() {
    let analysis = analyze(
        "[sum_value, rounded] = request.security(\"NYSE:IBM\", timeframe.period, [math.sum(close, 2), math.round_to_mintick(close + 0.006)])\nplot(nz(sum_value) + rounded)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_stateless_math_expression() {
    let analysis = analyze(
        "[floored, ceiled, rounded] = request.security(\"NYSE:IBM\", timeframe.period, [math.floor(close / 3), math.ceil(open / 6), math.round(close / 7, 2)])\nplot(floored + ceiled + rounded)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_root_log_math_expression() {
    let analysis = analyze(
        "[sqrt_value, cbrt_value, log10_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.sqrt(close), math.cbrt(close), math.log10(close)])\nplot(sqrt_value + cbrt_value + log10_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_trig_math_expression() {
    let analysis = analyze(
        "[sin_value, cos_value, tan_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.sin(close / 100), math.cos(open / 100), math.tan((close - open) / 100)])\nplot(sin_value + cos_value + tan_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_power_log_math_expression() {
    let analysis = analyze(
        "[pow_value, hypot_value, log_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.pow(close / 100, 2), math.hypot(close / 100, open / 100), math.log(close)])\nplot(pow_value + hypot_value + log_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_inverse_trig_exp_math_expression() {
    let analysis = analyze(
        "[exp_value, acos_value, asin_value, atan_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.exp(close / 100), math.acos(close / 200), math.asin(close / 200), math.atan(close / 100)])\nplot(exp_value + acos_value + asin_value + atan_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_angle_scalar_math_expression() {
    let analysis = analyze(
        "[avg_value, trunc_value, sign_value, degrees_value, radians_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.avg(open, high, low, close), math.trunc(close / 3), math.sign(close - open), math.todegrees(close / 100), math.toradians(open / 10)])\nplot(avg_value + trunc_value + sign_value + degrees_value + radians_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_expression() {
    let analysis = analyze(
        "[avg, delta, total] = request.security(\"NYSE:IBM\", timeframe.period, [ta.sma(close, 2), ta.change(close), ta.cum(close)])\nplot(nz(avg) + nz(delta) + total)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_range_expression() {
    let analysis = analyze(
        "[tr_value, atr_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.tr(), ta.atr(2)])\nplot(nz(tr_value) + nz(atr_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_window_extrema_expression() {
    let analysis = analyze(
        "[highest_value, lowest_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highest(high, 2), ta.lowest(low, 2)])\nplot(nz(highest_value) + nz(lowest_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_momentum_expression() {
    let analysis = analyze(
        "[mom_value, roc_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.mom(close, 1), ta.roc(close, 1)])\nplot(nz(mom_value) + nz(roc_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_dispersion_window_expression() {
    let analysis = analyze(
        "[range_value, dev_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.range(close, 2), ta.dev(close, 2)])\nplot(nz(range_value) + nz(dev_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_core_momentum_expression() {
    let analysis = analyze(
        "[ema_value, rsi_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.ema(close, 2), ta.rsi(close, 1)])\nplot(nz(ema_value) + nz(rsi_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_band_width_expression() {
    let analysis = analyze(
        "[bbw_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.bbw(close, 2, 2)])\nplot(nz(bbw_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_default_extrema_expression() {
    let analysis = analyze(
        "[highest_value, lowest_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highest(2), ta.lowest(2)])\nplot(nz(highest_value) + nz(lowest_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_default_bar_offset_expression() {
    let analysis = analyze(
        "[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highestbars(2), ta.lowestbars(2)])\nplot(nz(highest_offset) + nz(lowest_offset))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_cross_expression() {
    let analysis = analyze(
        "[crossed, crossed_up, crossed_down] = request.security(\"NYSE:IBM\", timeframe.period, [ta.cross(close, 20.5) ? 1 : 0, ta.crossover(close, 20.5) ? 1 : 0, ta.crossunder(close - time / 60000.0, 19.5) ? 1 : 0])\nplot(crossed + crossed_up + crossed_down)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_trend_expression() {
    let analysis = analyze(
        "[rising, falling, flat_falling] = request.security(\"NYSE:IBM\", timeframe.period, [ta.rising(close, 2) ? 1 : 0, ta.falling(25 - close, 2) ? 1 : 0, ta.falling(open, 2) ? 1 : 0])\nplot(rising + falling + flat_falling)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_event_expression() {
    let analysis = analyze(
        "[since, prior] = request.security(\"NYSE:IBM\", timeframe.period, [ta.barssince(close > open), ta.valuewhen(close > 21, close, 1)])\nplot(nz(since) + nz(prior))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_bars_expression() {
    let analysis = analyze(
        "[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highestbars(close, 3), ta.lowestbars(close, 3)])\nplot(nz(highest_offset) + nz(lowest_offset))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_pivot_expression() {
    let analysis = analyze(
        "[pivot_high, pivot_low] = request.security(\"NYSE:IBM\", timeframe.period, [ta.pivothigh(0 - math.abs(close - 22), 1, 1), ta.pivotlow(math.abs(close - 22), 1, 1)])\nplot(nz(pivot_high) + nz(pivot_low))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_stat_expression() {
    let analysis = analyze(
        "[corr, cov] = request.security(\"NYSE:IBM\", timeframe.period, [ta.correlation(close, high, 3), ta.covariance(close, high, 3)])\nplot(nz(corr) + nz(cov))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_window_stat_expression() {
    let analysis = analyze(
        "[median_value, mode_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.median(close, 3), ta.mode(close, 3)])\nplot(nz(median_value) + nz(mode_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_percentile_expression() {
    let analysis = analyze(
        "[nearest_rank, linear] = request.security(\"NYSE:IBM\", timeframe.period, [ta.percentile_nearest_rank(close, 3, 50), ta.percentile_linear_interpolation(close, 3, 50)])\nplot(nz(nearest_rank) + nz(linear))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_percentrank_expression() {
    let analysis = analyze(
        "[rank, inverse_rank] = request.security(\"NYSE:IBM\", timeframe.period, [ta.percentrank(close, 3), ta.percentrank(25 - close, 3)])\nplot(nz(rank) + nz(inverse_rank))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_dispersion_expression() {
    let analysis = analyze(
        "[stdev_value, variance_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.stdev(close, 3), ta.variance(close, 3)])\nplot(nz(stdev_value) + nz(variance_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_weighted_average_expression() {
    let analysis = analyze(
        "[wma_value, vwma_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.wma(close, 3), ta.vwma(close, 3)])\nplot(nz(wma_value) + nz(vwma_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_smoothing_average_expression() {
    let analysis = analyze(
        "[swma_value, hma_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.swma(close), ta.hma(close, 4)])\nplot(nz(swma_value) + nz(hma_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_regression_average_expression() {
    let analysis = analyze(
        "[alma_value, linreg_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.alma(close, 4, 0.85, 6), ta.linreg(close, 3, 0)])\nplot(nz(alma_value) + nz(linreg_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_recursive_average_expression() {
    let analysis = analyze(
        "[rma_value, dema_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.rma(close, 3), ta.dema(close, 3)])\nplot(nz(rma_value) + nz(dema_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_momentum_average_expression() {
    let analysis = analyze(
        "[tema_value, tsi_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.tema(close, 3), ta.tsi(close, 2, 3)])\nplot(nz(tema_value) + nz(tsi_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_momentum_flow_expression() {
    let analysis = analyze(
        "[cmo_value, mfi_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.cmo(close, 3), ta.mfi(close, 3)])\nplot(nz(cmo_value) + nz(mfi_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_oscillator_expression() {
    let analysis = analyze(
        "[stoch_value, wpr_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.stoch(close, high, low, 3), ta.wpr(3)])\nplot(nz(stoch_value) + nz(wpr_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_trend_oscillator_expression() {
    let analysis = analyze(
        "[sar_value, cci_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.sar(0.02, 0.02, 0.2), ta.cci(close, 3)])\nplot(nz(sar_value) + nz(cci_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_shape_expression() {
    let analysis = analyze(
        "[cog_value, bop_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.cog(close, 3), ta.bop()])\nplot(nz(cog_value) + nz(bop_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_extrema_expression() {
    let analysis = analyze(
        "[max_value, min_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.max(close), ta.min(open)])\nplot(nz(max_value) + nz(min_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_channel_width_expression() {
    let analysis = analyze(
        "[kcw_value, vwap_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.kcw(close, 3, 2), ta.vwap(close)])\nplot(nz(kcw_value) + nz(vwap_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_variable_expression() {
    let analysis = analyze(
        "[accdist_value, iii_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.accdist, ta.iii])\nplot(nz(accdist_value) + nz(iii_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_volume_flow_variable_expression() {
    let analysis = analyze(
        "[nvi_value, obv_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.nvi, ta.obv])\nplot(nz(nvi_value) + nz(obv_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_price_volume_variable_expression() {
    let analysis = analyze(
        "[pvi_value, pvt_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.pvi, ta.pvt])\nplot(nz(pvi_value) + nz(pvt_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_tuple_literal_ta_final_flow_expression() {
    let analysis = analyze(
        "[wvad_value, ao_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.wvad, ta.ao()])\nplot(nz(wvad_value) + nz(ao_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_extrema_expression() {
    let analysis = analyze(
        "[max_value, min_value] = request.security(\"NYSE:IBM\", \"5\", [ta.max(close), ta.min(open)])\nplot(nz(max_value) + nz(min_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_variable_expression()
{
    let analysis = analyze(
        "[accdist_value, iii_value] = request.security(\"NYSE:IBM\", \"5\", [ta.accdist, ta.iii])\nplot(nz(accdist_value) + nz(iii_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_volume_flow_variable_expression()
 {
    let analysis = analyze(
        "[nvi_value, obv_value] = request.security(\"NYSE:IBM\", \"5\", [ta.nvi, ta.obv])\nplot(nz(nvi_value) + nz(obv_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_price_volume_variable_expression()
 {
    let analysis = analyze(
        "[pvi_value, pvt_value] = request.security(\"NYSE:IBM\", \"5\", [ta.pvi, ta.pvt])\nplot(nz(pvi_value) + nz(pvt_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_final_flow_expression()
 {
    let analysis = analyze(
        "[wvad_value, ao_value] = request.security(\"NYSE:IBM\", \"5\", [ta.wvad, ta.ao()])\nplot(nz(wvad_value) + nz(ao_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_smoothing_average_expression()
 {
    let analysis = analyze(
        "[swma_value, hma_value] = request.security(\"NYSE:IBM\", \"5\", [ta.swma(close), ta.hma(close, 4)])\nplot(nz(swma_value) + nz(hma_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_regression_average_expression()
 {
    let analysis = analyze(
        "[alma_value, linreg_value] = request.security(\"NYSE:IBM\", \"5\", [ta.alma(close, 4, 0.85, 6), ta.linreg(close, 3, 0)])\nplot(nz(alma_value) + nz(linreg_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_recursive_average_expression()
 {
    let analysis = analyze(
        "[rma_value, dema_value] = request.security(\"NYSE:IBM\", \"5\", [ta.rma(close, 3), ta.dema(close, 3)])\nplot(nz(rma_value) + nz(dema_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_momentum_average_expression()
 {
    let analysis = analyze(
        "[tema_value, tsi_value] = request.security(\"NYSE:IBM\", \"5\", [ta.tema(close, 3), ta.tsi(close, 2, 3)])\nplot(nz(tema_value) + nz(tsi_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_momentum_flow_expression()
 {
    let analysis = analyze(
        "[cmo_value, mfi_value] = request.security(\"NYSE:IBM\", \"5\", [ta.cmo(close, 1), ta.mfi(close, 2)])\nplot(nz(cmo_value) + nz(mfi_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_oscillator_expression()
 {
    let analysis = analyze(
        "[stoch_value, wpr_value] = request.security(\"NYSE:IBM\", \"5\", [ta.stoch(close, high, low, 2), ta.wpr(2)])\nplot(nz(stoch_value) + nz(wpr_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_trend_oscillator_expression()
 {
    let analysis = analyze(
        "[sar_value, cci_value] = request.security(\"NYSE:IBM\", \"5\", [ta.sar(0.02, 0.02, 0.2), ta.cci(close, 2)])\nplot(nz(sar_value) + nz(cci_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_shape_expression() {
    let analysis = analyze(
        "[cog_value, bop_value] = request.security(\"NYSE:IBM\", \"5\", [ta.cog(close, 2), ta.bop()])\nplot(nz(cog_value) + nz(bop_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_channel_width_expression()
 {
    let analysis = analyze(
        "[kcw_value, vwap_value] = request.security(\"NYSE:IBM\", \"5\", [ta.kcw(close, 2, 2), ta.vwap(close)])\nplot(nz(kcw_value) + nz(vwap_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_range_expression() {
    let analysis = analyze(
        "[tr_value, atr_value] = request.security(\"NYSE:IBM\", \"5\", [ta.tr(), ta.atr(2)])\nplot(nz(tr_value) + nz(atr_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_window_extrema_expression()
 {
    let analysis = analyze(
        "[highest_value, lowest_value] = request.security(\"NYSE:IBM\", \"5\", [ta.highest(high, 2), ta.lowest(low, 2)])\nplot(nz(highest_value) + nz(lowest_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_momentum_expression()
{
    let analysis = analyze(
        "[mom_value, roc_value] = request.security(\"NYSE:IBM\", \"5\", [ta.mom(close, 1), ta.roc(close, 1)])\nplot(nz(mom_value) + nz(roc_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_dispersion_window_expression()
 {
    let analysis = analyze(
        "[range_value, dev_value] = request.security(\"NYSE:IBM\", \"5\", [ta.range(close, 2), ta.dev(close, 2)])\nplot(nz(range_value) + nz(dev_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_core_momentum_expression()
 {
    let analysis = analyze(
        "[ema_value, rsi_value] = request.security(\"NYSE:IBM\", \"5\", [ta.ema(close, 2), ta.rsi(close, 1)])\nplot(nz(ema_value) + nz(rsi_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_band_width_expression()
 {
    let analysis = analyze(
        "[bbw_value] = request.security(\"NYSE:IBM\", \"5\", [ta.bbw(close, 2, 2)])\nplot(nz(bbw_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_default_extrema_expression()
 {
    let analysis = analyze(
        "[highest_value, lowest_value] = request.security(\"NYSE:IBM\", \"5\", [ta.highest(2), ta.lowest(2)])\nplot(nz(highest_value) + nz(lowest_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_default_bar_offset_expression()
 {
    let analysis = analyze(
        "[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", \"5\", [ta.highestbars(2), ta.lowestbars(2)])\nplot(nz(highest_offset) + nz(lowest_offset))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_expression() {
    let analysis = analyze(
        "[last, shifted, above] = request.security(\"NYSE:IBM\", \"5\", [close, close + 1, close > open ? 1 : 0])\nplot(last + shifted + above)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_history_and_nz_expression()
 {
    let analysis = analyze(
        "[prior, fallback, delta] = request.security(\"NYSE:IBM\", \"5\", [close[1], nz(close[1], open), close - nz(close[1], close)])\nplot(nz(prior) + fallback + delta)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_math_expression() {
    let analysis = analyze(
        "[maxv, minv, spread] = request.security(\"NYSE:IBM\", \"5\", [math.max(close, open), math.min(close, open), math.abs(open - close)])\nplot(maxv + minv + spread)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_stateless_math_expression()
 {
    let analysis = analyze(
        "[floored, ceiled, rounded] = request.security(\"NYSE:IBM\", \"5\", [math.floor(close / 3), math.ceil(open / 80), math.round(close / 3, 2)])\nplot(floored + ceiled + rounded)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_root_log_math_expression()
 {
    let analysis = analyze(
        "[sqrt_value, cbrt_value, log10_value] = request.security(\"NYSE:IBM\", \"5\", [math.sqrt(close), math.cbrt(close), math.log10(close)])\nplot(sqrt_value + cbrt_value + log10_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_trig_math_expression() {
    let analysis = analyze(
        "[sin_value, cos_value, tan_value] = request.security(\"NYSE:IBM\", \"5\", [math.sin(close / 100), math.cos(open / 100), math.tan((close - open) / 100)])\nplot(sin_value + cos_value + tan_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_power_log_math_expression()
 {
    let analysis = analyze(
        "[pow_value, hypot_value, log_value] = request.security(\"NYSE:IBM\", \"5\", [math.pow(close / 100, 2), math.hypot(close / 100, open / 100), math.log(close)])\nplot(pow_value + hypot_value + log_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_inverse_trig_exp_math_expression()
 {
    let analysis = analyze(
        "[exp_value, acos_value, asin_value, atan_value] = request.security(\"NYSE:IBM\", \"5\", [math.exp(close / 100), math.acos(close / 200), math.asin(close / 200), math.atan(close / 100)])\nplot(exp_value + acos_value + asin_value + atan_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_angle_scalar_math_expression()
 {
    let analysis = analyze(
        "[avg_value, trunc_value, sign_value, degrees_value, radians_value] = request.security(\"NYSE:IBM\", \"5\", [math.avg(open, high, low, close), math.trunc(close / 3), math.sign(close - open), math.todegrees(close / 100), math.toradians(open / 10)])\nplot(avg_value + trunc_value + sign_value + degrees_value + radians_value)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_stateful_math_expression()
 {
    let analysis = analyze(
        "[sum_value, rounded] = request.security(\"NYSE:IBM\", \"5\", [math.sum(close, 2), math.round_to_mintick(close + 0.006)])\nplot(nz(sum_value) + rounded)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_expression() {
    let analysis = analyze(
        "[avg, delta, total] = request.security(\"NYSE:IBM\", \"5\", [ta.sma(close, 2), ta.change(close), ta.cum(close)])\nplot(nz(avg) + nz(delta) + total)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_cross_expression() {
    let analysis = analyze(
        "[crossed, crossed_up, crossed_down] = request.security(\"NYSE:IBM\", \"5\", [ta.cross(close, 150) ? 1 : 0, ta.crossover(close, 150) ? 1 : 0, ta.crossunder(close - time / 2000.0, 75) ? 1 : 0])\nplot(crossed + crossed_up + crossed_down)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_trend_expression() {
    let analysis = analyze(
        "[rising, falling, flat_falling] = request.security(\"NYSE:IBM\", \"5\", [ta.rising(close, 1) ? 1 : 0, ta.falling(300 - close, 1) ? 1 : 0, ta.falling(open, 1) ? 1 : 0])\nplot(rising + falling + flat_falling)\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_event_expression() {
    let analysis = analyze(
        "[since, prior] = request.security(\"NYSE:IBM\", \"5\", [ta.barssince(close > open), ta.valuewhen(close > 90, close, 1)])\nplot(nz(since) + nz(prior))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_bars_expression() {
    let analysis = analyze(
        "[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", \"5\", [ta.highestbars(close, 2), ta.lowestbars(close, 2)])\nplot(nz(highest_offset) + nz(lowest_offset))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_pivot_expression() {
    let analysis = analyze(
        "[pivot_high, pivot_low] = request.security(\"NYSE:IBM\", \"5\", [ta.pivothigh(300 - close, 0, 1), ta.pivotlow(close, 0, 1)])\nplot(nz(pivot_high) + nz(pivot_low))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_stat_expression() {
    let analysis = analyze(
        "[corr, cov] = request.security(\"NYSE:IBM\", \"5\", [ta.correlation(close, high, 2), ta.covariance(close, high, 2)])\nplot(nz(corr) + nz(cov))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_window_stat_expression()
 {
    let analysis = analyze(
        "[median_value, mode_value] = request.security(\"NYSE:IBM\", \"5\", [ta.median(close, 2), ta.mode(close, 2)])\nplot(nz(median_value) + nz(mode_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_percentile_expression()
 {
    let analysis = analyze(
        "[nearest_rank, linear] = request.security(\"NYSE:IBM\", \"5\", [ta.percentile_nearest_rank(close, 2, 50), ta.percentile_linear_interpolation(close, 2, 50)])\nplot(nz(nearest_rank) + nz(linear))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_percentrank_expression()
 {
    let analysis = analyze(
        "[rank, inverse_rank] = request.security(\"NYSE:IBM\", \"5\", [ta.percentrank(close, 2), ta.percentrank(300 - close, 2)])\nplot(nz(rank) + nz(inverse_rank))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_dispersion_expression()
 {
    let analysis = analyze(
        "[stdev_value, variance_value] = request.security(\"NYSE:IBM\", \"5\", [ta.stdev(close, 2), ta.variance(close, 2)])\nplot(nz(stdev_value) + nz(variance_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security_tuple_literal_ta_weighted_average_expression()
 {
    let analysis = analyze(
        "[wma_value, vwma_value] = request.security(\"NYSE:IBM\", \"5\", [ta.wma(close, 2), ta.vwma(close, 2)])\nplot(nz(wma_value) + nz(vwma_value))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_math_extremes() {
    let analysis = analyze(
        "plot(request.security(\"NYSE:IBM\", timeframe.period, math.max(close, open) - math.min(close, open)))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_request_security_supported_math_calls() {
    let analysis = analyze(
        "plot(request.security(\"NYSE:IBM\", timeframe.period, math.abs(open - close) + math.avg(open, close) + math.floor(close) + math.ceil(open) + math.trunc(high) + math.sqrt(close) + math.cbrt(close) + math.log(close) + math.log10(close) + math.exp(1) + math.acos(0.5) + math.asin(0.5) + math.atan(close) + math.sign(close - open) + math.todegrees(close) + math.toradians(open) + math.sin(close) + math.cos(open) + math.tan(0) + math.pow(close, 2) + math.hypot(close, open) + math.round(close / 3, 2) + math.round_to_mintick(close + 0.006) + nz(math.sum(close, 2))))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_same_context_request_security_math_extremes() {
    let analysis = analyze(
        "plot(request.security(syminfo.tickerid, timeframe.period, math.max(close, open) - math.min(close, open)))\n",
    );

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_provider_backed_higher_timeframe_request_security() {
    let analysis = analyze("plot(request.security(\"NYSE:IBM\", \"5\", ta.sma(close, 2)))\n");

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
            .any(|feature| feature.feature == "request.security")
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn rejects_invalid_timeframe_request_security() {
    let analysis = analyze("x = request.security(\"AAPL\", close, close)\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNSUPPORTED_FEATURE")
    );
}

#[test]
fn rejects_provider_request_security_unsupported_call() {
    let analysis =
        analyze("x = request.security(\"NYSE:IBM\", timeframe.period, math.random(0, 1, 7))\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
}

#[test]
fn rejects_request_security_non_default_merge_args() {
    let analysis = analyze(
        "plot(request.security(syminfo.tickerid, timeframe.period, close, gaps=barmerge.gaps_on))\nplot(request.security(syminfo.tickerid, timeframe.period, close, gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_on))\n",
    );
    let codes = diagnostic_codes(&analysis);

    assert!(codes.contains(&"E_CALL_ARG_VALUE"), "{codes:?}");
    assert!(codes.contains(&"E_UNSUPPORTED_FEATURE"), "{codes:?}");
    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "request.security")
    );
}

#[test]
fn rejects_provider_request_security_tuple_literal_with_local_alias_expression() {
    let analysis = analyze(
        "src = close\n[first, second] = request.security(\"NYSE:IBM\", timeframe.period, [src, open])\n",
    );

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
}

#[test]
fn rejects_provider_request_security_local_variable_expression() {
    let analysis =
        analyze("src = close\nx = request.security(\"NYSE:IBM\", timeframe.period, src)\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
}

#[test]
fn rejects_higher_timeframe_request_security_local_variable_expression() {
    let analysis = analyze("src = close\nx = request.security(\"NYSE:IBM\", \"5\", src)\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
}

#[test]
fn rejects_request_security_side_effect_expression() {
    let analysis =
        analyze("x = request.security(syminfo.tickerid, timeframe.period, plot(close))\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
    assert!(
        analysis.compatibility.unsupported[0]
            .reason
            .contains("side-effecting requested expressions")
    );
}

#[test]
fn rejects_request_security_alertcondition_side_effect_expression() {
    let analysis = analyze(
        "x = request.security(syminfo.tickerid, timeframe.period, alertcondition(true, \"A\", \"B\"))\n",
    );

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
    assert!(
        analysis.compatibility.unsupported[0]
            .reason
            .contains("side-effecting requested expressions")
    );
}

#[test]
fn rejects_request_security_alert_side_effect_expression() {
    let analysis =
        analyze("x = request.security(syminfo.tickerid, timeframe.period, alert(\"A\"))\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
    assert!(
        analysis.compatibility.unsupported[0]
            .reason
            .contains("side-effecting requested expressions")
    );
}

#[test]
fn rejects_other_request_variants() {
    let analysis = analyze("x = request.financial(syminfo.tickerid, \"TOTAL_REVENUE\", \"FQ\")\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.financial"
    );
}

#[test]
fn rejects_request_security_lower_tf_api() {
    let analysis = analyze("x = request.security_lower_tf(\"NYSE:IBM\", \"30S\", close)\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security_lower_tf"
    );
}

#[test]
fn compile_cache_reuses_analysis_for_identical_source() {
    let source = SourceFile::new("test.pine", "plot(close)\n");
    let mut cache = CompileCache::new();

    let first = cache.analyze(&source);
    let second = cache.analyze(&source);

    assert_eq!(first, second);
    assert_eq!(
        cache.stats(),
        CompileCacheStats {
            entries: 1,
            hits: 1,
            misses: 1,
        }
    );
}

#[test]
fn compile_cache_keys_by_source_name_and_text() {
    let mut cache = CompileCache::new();

    cache.analyze(&SourceFile::new("one.pine", "plot(close)\n"));
    cache.analyze(&SourceFile::new("two.pine", "plot(close)\n"));
    cache.analyze(&SourceFile::new("one.pine", "plot(open)\n"));

    assert_eq!(
        cache.stats(),
        CompileCacheStats {
            entries: 3,
            hits: 0,
            misses: 3,
        }
    );
}

#[test]
fn compile_cache_keys_by_source_graph_library_sources() {
    let root = SourceFile::new("root.pine", "plot(close)\n");
    let library_one = SourceFile::new("lib.pine", "library(\"one\")\n");
    let library_two = SourceFile::new("lib.pine", "library(\"two\")\n");
    let first_input = AnalysisInput::with_library_sources(
        root.clone(),
        vec![("user/lib/1".to_owned(), library_one)],
    )
    .expect("first input");
    let second_input =
        AnalysisInput::with_library_sources(root, vec![("user/lib/1".to_owned(), library_two)])
            .expect("second input");
    let mut cache = CompileCache::new();

    cache.analyze_input(&first_input);
    cache.analyze_input(&first_input);
    cache.analyze_input(&second_input);

    assert_eq!(
        cache.stats(),
        CompileCacheStats {
            entries: 2,
            hits: 1,
            misses: 2,
        }
    );
}

#[test]
fn source_graph_input_reports_duplicate_library_key() {
    let error = AnalysisInput::with_library_sources(
        SourceFile::new("root.pine", "plot(close)\n"),
        vec![
            (
                "user/lib/1".to_owned(),
                SourceFile::new("one.pine", "library(\"one\")\n"),
            ),
            (
                "user/lib/1".to_owned(),
                SourceFile::new("two.pine", "library(\"two\")\n"),
            ),
        ],
    )
    .expect_err("duplicate keys should fail");

    assert_eq!(
        error,
        SourceGraphError::DuplicateLibraryKey {
            key: "user/lib/1".to_owned()
        }
    );
}

fn analyze_with_libraries(root: &str, libraries: Vec<(&str, &str)>) -> Analysis {
    let input = AnalysisInput::with_library_sources(
        SourceFile::new("root.pine", root),
        libraries
            .into_iter()
            .map(|(key, source)| {
                (
                    key.to_owned(),
                    SourceFile::new(format!("{key}.pine"), source),
                )
            })
            .collect(),
    )
    .expect("analysis input");
    crate::analyze_input(&input)
}

fn diagnostic_codes(analysis: &Analysis) -> Vec<&str> {
    analysis
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect()
}

#[test]
fn import_reports_missing_library_source() {
    let analysis = analyze_with_libraries("import user/lib/1 as lib\nplot(close)\n", vec![]);

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_MISSING_LIBRARY"), "{codes:?}");
}

#[test]
fn import_reports_duplicate_alias() {
    let analysis = analyze_with_libraries(
        "import user/one/1 as lib\nimport user/two/1 as lib\nplot(close)\n",
        vec![
            ("user/one/1", "library(\"one\")\n"),
            ("user/two/1", "library(\"two\")\n"),
        ],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_DUPLICATE_ALIAS"), "{codes:?}");
}

#[test]
fn import_reports_invalid_library_declaration() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(close)\n",
        vec![("user/lib/1", "export value = 1\n")],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_INVALID_LIBRARY"), "{codes:?}");
}

#[test]
fn import_reports_duplicate_exports() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(close)\n",
        vec![(
            "user/lib/1",
            "library(\"lib\")\nexport value = 1\nexport value = 2\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_DUPLICATE_EXPORT"), "{codes:?}");
}

#[test]
fn import_reports_duplicate_exported_user_types() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_import_duplicate_exported_udt.pine"
        ),
        vec![(
            "user/duplicate_udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_duplicate_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_DUPLICATE_EXPORT"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_reports_duplicate_exported_user_type_and_const_names() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_import_duplicate_exported_udt_const.pine"
        ),
        vec![(
            "user/duplicate_udt_const/1",
            include_str!(
                "../../../../tests/fixtures/libraries/import_duplicate_udt_const_lib.pine"
            ),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_DUPLICATE_EXPORT"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_reports_duplicate_exported_user_type_and_function_names() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_import_duplicate_exported_udt_function.pine"
        ),
        vec![(
            "user/duplicate_udt_function/1",
            include_str!(
                "../../../../tests/fixtures/libraries/import_duplicate_udt_function_lib.pine"
            ),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_DUPLICATE_EXPORT"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_reports_dependency_cycle() {
    let analysis = analyze_with_libraries(
        "import user/one/1 as one\nplot(close)\n",
        vec![
            ("user/one/1", "library(\"one\")\nimport user/two/1 as two\n"),
            ("user/two/1", "library(\"two\")\nimport user/one/1 as one\n"),
        ],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_CYCLE"), "{codes:?}");
}

#[test]
fn import_reports_unknown_export_and_private_access() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(lib.missing)\nplot(lib.private)\n",
        vec![(
            "user/lib/1",
            "library(\"lib\")\nexport value = 1\nprivate = 2\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_UNKNOWN_EXPORT"), "{codes:?}");
    assert!(codes.contains(&"E_IMPORT_PRIVATE_SYMBOL"), "{codes:?}");
}

#[test]
fn import_accepts_exported_constant_and_pure_function_subset() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(lib.scale(close) + lib.offset)\n",
        vec![(
            "user/lib/1",
            "library(\"lib\")\nexport offset = 2\nexport scale(value) => value * offset\n",
        )],
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn import_reports_missing_alias_for_executable_subset() {
    let analysis = analyze_with_libraries(
        "import user/lib/1\nplot(close)\n",
        vec![("user/lib/1", "library(\"lib\")\nexport value = 1\n")],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_ALIAS_REQUIRED"), "{codes:?}");
}

#[test]
fn import_rejects_exported_series_constant() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(close)\n",
        vec![("user/lib/1", "library(\"lib\")\nexport value = close\n")],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_CONST_VALUE"), "{codes:?}");
}

#[test]
fn import_rejects_exported_function_side_effects() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(close)\n",
        vec![(
            "user/lib/1",
            "library(\"lib\")\nexport draw(value) => plot(value)\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(
        codes.contains(&"E_IMPORT_FUNCTION_SIDE_EFFECT"),
        "{codes:?}"
    );
}

#[test]
fn import_rejects_exported_function_switch_loop_side_effects() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(close)\n",
        vec![(
            "user/lib/1",
            "library(\"lib\")\nexport choose(flag, value) =>\n    switch\n        flag =>\n            for i = 0 to 0\n                plot(value)\n        =>\n            value\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(
        codes.contains(&"E_IMPORT_FUNCTION_SIDE_EFFECT"),
        "{codes:?}"
    );
}

#[test]
fn import_rejects_recursive_exported_functions() {
    let analysis = analyze_with_libraries(
        "import user/lib/1 as lib\nplot(lib.loop(close))\n",
        vec![(
            "user/lib/1",
            "library(\"lib\")\nexport loop(value) => value > 0 ? loop(value - 1) : value\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_RECURSIVE_FUNCTION"), "{codes:?}");
}

#[test]
fn import_accepts_scalar_imported_user_type_constructors() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\np = lib.Point.new(close)\nplot(p.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "user-defined types")
    );
}

#[test]
fn import_accepts_nested_imported_user_type_history_references() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\np = lib.Point.new(close)\nwrapped = lib.Wrapper.new(p)\nprior = wrapped[1]\nplot(prior.nested.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\nexport type Wrapper\n    Point nested\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_nested_imported_user_type_typed_declarations_and_reassignment() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\nlib.Wrapper typed = lib.Wrapper.new(lib.Point.new(close))\ntyped := lib.Wrapper.new(lib.Point.new(open))\nplot(typed.nested.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\nexport type Wrapper\n    Point nested\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "lib.Wrapper typed declarations")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_typed_declarations() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\nlib.Point p = lib.Point.new(close)\np := lib.Point.new(open)\nplot(p.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "lib.Point typed declarations")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_var_declarations() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_var.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_rejects_scalar_imported_user_type_var_identity_mismatch() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/sema/unsupported_imported_udt_var_identity.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UDT_ASSIGN_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_accepts_scalar_imported_user_type_varip_declarations() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_varip.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_rejects_scalar_imported_user_type_varip_identity_mismatch() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UDT_ASSIGN_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_rejects_private_dependency_imported_user_type_varip_constructor_arg() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/sema/unsupported_imported_udt_varip.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UDT_CONSTRUCTOR_ARG"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_accepts_scalar_imported_user_type_field_mutation() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_field_mutation.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "user-defined type field mutation")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_control_flow_field_mutation() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/runtime/import_udt_field_mutation_control_flow.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_rejects_scalar_imported_user_type_field_mutation_type() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_udt_field_mutation_type.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_ASSIGN_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_rejects_scalar_imported_user_type_parameter_field_mutation() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_udt_parameter_field_mutation.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UNSUPPORTED_FEATURE"), "{codes:?}");
    assert!(
        analysis.compatibility.unsupported.iter().any(|feature| {
            feature.feature == "function_side_effect" && feature.reason.contains("parameter fields")
        }),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn import_rejects_scalar_imported_user_type_global_field_mutation() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_udt_global_field_mutation.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UNSUPPORTED_FEATURE"), "{codes:?}");
    assert!(
        analysis.compatibility.unsupported.iter().any(|feature| {
            feature.feature == "function_side_effect"
                && feature.reason.contains("global user-defined type values")
        }),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn import_accepts_scalar_imported_user_type_dynamic_history() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_history.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_exported_user_type_history_with_private_scalar_dependency_metadata() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/supported_imported_udt_private_dependency_history.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_rejects_nested_imported_user_type_field_mutation() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_udt_nested_field_mutation.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UNSUPPORTED_FEATURE"), "{codes:?}");
    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "nested field mutation"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn import_accepts_imported_user_type_array_typed_declarations() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_array_typed_declarations.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_scalar_tree_user_type_array_declaration() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/sema/supported_imported_udt_array_decl.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_scalar_tree_user_type_array_alias_declaration() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/supported_imported_udt_array_alias_decl.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_user_type_array_varip_declaration() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_array_varip.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_scalar_tree_user_type_array_varip_declaration() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/supported_imported_udt_array_varip_nested_decl.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_user_type_array_from_inference() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_array_from.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_scalar_imported_user_type_ternary() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\np = close > open ? lib.Point.new(close) : lib.Point.new(open)\nlib.Point typed = close > open ? p : lib.Point.new(high)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_scalar_imported_user_type_if_expression_history() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_if_expression.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_passthrough_and_history_reads() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\npassthrough(p) => p\np = passthrough(lib.Point.new(close))\nlib.Point typed = passthrough(lib.Point.new(open))\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_nested_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\ninner(p) => p\nouter(p) => inner(p)\np = outer(lib.Point.new(close))\nlib.Point typed = outer(lib.Point.new(open))\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_ternary_alias_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\naliasTernary(p, flip) =>\n    copy = p\n    flip ? copy : p\np = aliasTernary(lib.Point.new(close), bar_index % 2 == 0)\nlib.Point typed = aliasTernary(lib.Point.new(open), bar_index % 2 == 0)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_nested_ternary_alias_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\ninnerTernary(p, flip) =>\n    copy = p\n    flip ? copy : p\nouterTernary(p) => innerTernary(p, bar_index % 2 == 0)\np = outerTernary(lib.Point.new(close))\nlib.Point typed = outerTernary(lib.Point.new(open))\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_final_while_and_switch_alias_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\naliasWhile(p) =>\n    active = true\n    while active\n        copy = p\n        active := false\n        copy\naliasSwitch(p, selector) =>\n    switch selector\n        0 =>\n            copy = p\n            copy\n        =>\n            copy = p\n            copy\np = aliasWhile(lib.Point.new(close))\nlib.Point typed = aliasSwitch(lib.Point.new(open), bar_index % 2)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_block_alias_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\naliasBlock(p) =>\n    copy = p\n    copy\np = aliasBlock(lib.Point.new(close))\nlib.Point typed = aliasBlock(lib.Point.new(open))\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_final_if_and_for_alias_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\naliasIf(p, flip) =>\n    if flip\n        copy = p\n        copy\n    else\n        copy = p\n        copy\naliasFor(p, count) =>\n    for i = 0 to count\n        copy = p\n        copy\np = aliasIf(lib.Point.new(close), bar_index % 2 == 0)\nlib.Point typed = aliasFor(lib.Point.new(open), 2)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_final_for_in_alias_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\naliasForIn(p, values) =>\n    for value in values\n        copy = p\n        copy\nvalues = array.from(1, 2)\np = aliasForIn(lib.Point.new(close), values)\nlib.Point typed = aliasForIn(lib.Point.new(open), values)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_nested_final_while_and_switch_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\ninnerWhile(p) =>\n    active = true\n    while active\n        copy = p\n        active := false\n        copy\ninnerSwitch(p, selector) =>\n    switch selector\n        0 =>\n            copy = p\n            copy\n        =>\n            copy = p\n            copy\nouterWhile(p) => innerWhile(p)\nouterSwitch(p, selector) => innerSwitch(p, selector)\np = outerWhile(lib.Point.new(close))\nlib.Point typed = outerSwitch(lib.Point.new(open), bar_index % 2)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_nested_final_if_and_for_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\ninnerIf(p, flip) =>\n    if flip\n        copy = p\n        copy\n    else\n        copy = p\n        copy\ninnerFor(p, count) =>\n    for i = 0 to count\n        copy = p\n        copy\nouterIf(p) => innerIf(p, bar_index % 2 == 0)\nouterFor(p) => innerFor(p, 2)\np = outerIf(lib.Point.new(close))\nlib.Point typed = outerFor(lib.Point.new(open))\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_nested_block_alias_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\ninnerBlock(p) =>\n    copy = p\n    copy\nouterBlock(p) => innerBlock(p)\np = outerBlock(lib.Point.new(close))\nlib.Point typed = outerBlock(lib.Point.new(open))\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_nested_final_for_in_passthrough() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\ninnerForIn(p, values) =>\n    for value in values\n        copy = p\n        copy\nouterForIn(p, values) => innerForIn(p, values)\nvalues = array.from(1, 2)\np = outerForIn(lib.Point.new(close), values)\nlib.Point typed = outerForIn(lib.Point.new(open), values)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_constructor_return() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\nmakePoint(x) => lib.Point.new(x)\np = makePoint(close)\nlib.Point typed = makePoint(open)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_imported_user_type_udf_control_flow_constructor_returns_and_history_reads() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_udf_constructor_return.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_local_field_mutation() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_udf_local_field_mutation.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_scalar_imported_user_type_udf_nested_constructor_return() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\nmakePoint(x) => lib.Point.new(x)\nouter(x) => makePoint(x)\np = outer(close)\nlib.Point typed = outer(open)\nplot(p.x + typed.x)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "function")
    );
}

#[test]
fn import_accepts_imported_user_type_udf_nested_control_flow_constructor_returns_and_history_reads()
{
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/runtime/import_udt_udf_nested_constructor_return.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_rejects_private_dependency_imported_user_type_constructor_arg() {
    let analysis = analyze_with_libraries(
        "import user/udt/1 as lib\np = lib.Wrapper.new(na)\nplot(close)\n",
        vec![(
            "user/udt/1",
            "library(\"udt\")\nexport type Wrapper\n    Point nested\ntype Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UDT_CONSTRUCTOR_ARG"), "{codes:?}");
    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_UDT_CONSTRUCTOR_ARG"
                && diagnostic
                    .message
                    .contains("cannot assign const na to imported field `nested`")
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn import_rejects_private_user_type_constructors() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_private_udt_constructor.pine"
        ),
        vec![(
            "user/private_udt/1",
            "library(\"private udt\")\ntype Point\n    float x\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_IMPORT_PRIVATE_SYMBOL"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_accepts_while_expression_imported_user_type_result_history() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_while_expression.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_rejects_while_expression_imported_user_type_identity_mismatch() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_udt_while_identity.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UDT_ASSIGN_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_accepts_for_expression_imported_user_type_result_history() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_for_expression.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_for_in_expression_imported_user_type_result_history() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_for_in_expression.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_rejects_for_in_expression_imported_user_type_identity_mismatch() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_udt_for_in_identity.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UDT_ASSIGN_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_rejects_for_expression_imported_user_type_identity_mismatch() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/sema/unsupported_imported_udt_for_identity.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_UDT_ASSIGN_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_accepts_switch_block_imported_user_type_result_history() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_switch_statement_block.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_method_local_field_mutation() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/runtime/import_udt_method_local_field_mutation.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| { feature.feature == "user-defined type field mutation" })
    );
}

#[test]
fn import_accepts_alias_qualified_imported_user_methods() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_method_qualified.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_method_ternary_while_and_switch_returns() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/runtime/import_udt_method_while_switch_return.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_method_final_for_in_alias_returns_and_history_reads() {
    let analysis = analyze_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_udt_method_return.pine"),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}: {:?}", analysis.diagnostics);
    assert!(analysis.hir.is_some());
}

#[test]
fn import_accepts_imported_method_control_flow_constructor_returns_and_history_reads() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/runtime/import_udt_method_constructor_return.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    assert!(analysis.hir.is_some());
}

#[test]
fn import_tuple_destructuring_preserves_alias_qualified_method_returned_input_and_simple_values() {
    let analysis = analyze_with_libraries(
        "import user/tuple/1 as lib\nbox = lib.Box.new(1)\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = lib.pair(box, length, tf)\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
        vec![(
            "user/tuple/1",
            "library(\"Tuple method fixture\")\nexport type Box\n    int seed\nmethod pair(Box this, int length, string tf) =>\n    [length, tf]\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn import_tuple_destructuring_preserves_udf_param_alias_qualified_method_returned_input_and_simple_values()
 {
    let analysis = analyze_with_libraries(
        "import user/tuple/1 as lib\nforward(box, length, tf) => lib.pair(box, length, tf)\nbox = lib.Box.new(1)\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = forward(box, length, tf)\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
        vec![(
            "user/tuple/1",
            "library(\"Tuple method fixture\")\nexport type Box\n    int seed\nmethod pair(Box this, int length, string tf) =>\n    [length, tf]\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.is_empty(), "{codes:?}");
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn import_tuple_destructuring_rejects_alias_qualified_method_returned_series_int_for_simple_param()
{
    let analysis = analyze_with_libraries(
        "import user/tuple/1 as lib\nbox = lib.Box.new(1)\nlength = input.int(2, \"Length\")\n[len] = lib.seriesPair(box, length)\nplot(ta.ema(close, len))\n",
        vec![(
            "user/tuple/1",
            "library(\"Tuple method fixture\")\nexport type Box\n    int seed\nmethod seriesPair(Box this, int length) =>\n    [length + bar_index]\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_CALL_ARG_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_tuple_destructuring_rejects_udf_param_alias_qualified_method_returned_series_int_for_simple_param()
 {
    let analysis = analyze_with_libraries(
        "import user/tuple/1 as lib\nforward(box, length) => lib.seriesPair(box, length)\nbox = lib.Box.new(1)\nlength = input.int(2, \"Length\")\n[len] = forward(box, length)\nplot(ta.ema(close, len))\n",
        vec![(
            "user/tuple/1",
            "library(\"Tuple method fixture\")\nexport type Box\n    int seed\nmethod seriesPair(Box this, int length) =>\n    [length + bar_index]\n",
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_CALL_ARG_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn import_rejects_alias_qualified_imported_user_method_receiver_type() {
    let analysis = analyze_with_libraries(
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_imported_method_qualified_receiver.pine"
        ),
        vec![(
            "user/udt/1",
            include_str!("../../../../tests/fixtures/libraries/import_udt_lib.pine"),
        )],
    );

    let codes = diagnostic_codes(&analysis);
    assert!(codes.contains(&"E_METHOD_ARG_TYPE"), "{codes:?}");
    assert!(analysis.hir.is_none());
}

#[test]
fn compile_cache_clear_drops_entries_and_stats() {
    let source = SourceFile::new("test.pine", "plot(close)\n");
    let mut cache = CompileCache::new();

    cache.analyze(&source);
    cache.analyze(&source);
    cache.clear();

    assert_eq!(
        cache.stats(),
        CompileCacheStats {
            entries: 0,
            hits: 0,
            misses: 0,
        }
    );
}
