use super::*;
use pine_ir::{PineType, Qualifier, ValueKind};

#[test]
fn rejects_reassignment_to_unknown_symbol() {
    let analysis = analyze("x := x + 1\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_SYMBOL")
    );
}

#[test]
fn accepts_reassignment_to_declared_symbol() {
    let analysis = analyze("x = close\nx := x + 1\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reassignment_does_not_narrow_existing_series_symbol() {
    let analysis = analyze("x = close\nx := 1\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let symbol = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol");
    assert_eq!(
        symbol.pine_type,
        PineType::new(Qualifier::Series, ValueKind::Float)
    );
}

#[test]
fn reassignment_promotes_weaker_scalar_qualifier() {
    let analysis = analyze("x = 1\nx := bar_index\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let symbol = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "x")
        .expect("x symbol");
    assert_eq!(
        symbol.pine_type,
        PineType::new(Qualifier::Series, ValueKind::Int)
    );
}

#[test]
fn accepts_block_local_declaration_in_if() {
    let analysis = analyze("if close > open\n    x = high - low\n    plot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_if_expression_with_branch_local_declarations() {
    let analysis = analyze(
        "x = if close > open\n    spread = high - low\n    spread\nelse\n    open\nplot(x)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn rejects_block_local_declaration_escape() {
    let analysis = analyze("if close > open\n    x = close\nplot(x)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_SYMBOL")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_if_reassignment_to_declared_symbol() {
    let analysis = analyze("x = close\nif close > open\n    x := high\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_block_local_tuple_declaration_in_if() {
    let analysis = analyze("if close > open\n    [x, y] = [high, low]\n    plot(x - y)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_block_local_tuple_declaration_escape() {
    let analysis = analyze("if close > open\n    [x, y] = [high, low]\nplot(x)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_SYMBOL")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_condition_switch_expression() {
    let analysis = analyze(
        "x = switch\n    close > open => high\n    close < open => low\n    => close\nplot(x)\n",
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
            .any(|feature| feature.feature == "switch")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_selector_switch_expression() {
    let analysis = analyze(
        "direction = 1\nx = switch direction\n    1 => high\n    -1 => low\n    => close\nplot(x)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_v5_numeric_condition_switch_arm_via_explicit_hir_coercion() {
    let analysis = analyze("x = switch\n    close => high\n    => low\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(
        analysis
            .compatibility
            .legacy_emulations
            .iter()
            .any(|emulation| emulation.feature == "v5.numeric_to_bool")
    );
}

#[test]
fn rejects_incompatible_switch_arm_results() {
    let analysis = analyze("x = switch\n    close > open => high\n    => true\nplot(x)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_BRANCH_TYPE"
                && diagnostic
                    .message
                    .contains("switch arms have incompatible types float and bool")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_incompatible_ternary_branch_results() {
    let analysis = analyze("x = close > open ? high : true\nplot(x)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_BRANCH_TYPE"
                && diagnostic
                    .message
                    .contains("ternary branches have incompatible types float and bool")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_condition_switch_statement_block_arm() {
    let analysis = analyze("x = switch\n    close > open =>\n        high\n    => close\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_expression_body_function() {
    let analysis = analyze("double(x) => x * 2\nplot(double(close))\n");

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
            .any(|feature| feature.feature == "function")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_named_function_arguments() {
    let analysis = analyze("spread(hi, lo) => hi - lo\nplot(spread(lo=low, hi=high))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_duplicate_named_function_argument() {
    let analysis = analyze("spread(hi, lo) => hi - lo\nplot(spread(high, hi=low))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_FUNCTION_ARG_DUPLICATE")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_positional_function_argument_after_named_argument() {
    let analysis = analyze("spread(hi, lo) => hi - lo\nplot(spread(hi=high, low))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_FUNCTION_ARG_ORDER")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_unknown_named_function_argument() {
    let analysis = analyze("double(x) => x * 2\nplot(double(src=close))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_FUNCTION_ARG_NAME")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_block_body_function() {
    let analysis = analyze("double(x) =>\n    y = x * 2\n    y\nplot(double(close))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_if_reassignment_inside_block_body_function() {
    let analysis = analyze(
        "select(x, y) =>\n    result = y\n    if x > y\n        result := x\n    result\nplot(select(high, low))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_local_var_declarations_in_blocks_and_functions() {
    let analysis = analyze(
        "counter() =>\n    var value = 0\n    value := value + 1\n    value\nif close > open\n    var seen = 10\n    seen := seen + 1\n    plot(counter() + seen)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_function_local_declaration_shadowing_parameter() {
    let analysis = analyze("bump(x) =>\n    x = x + 1\n    x\nplot(bump(close))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_function_loop_counter_shadowing_parameter() {
    let analysis = analyze(
        "mix(x) =>\n    total = 0\n    for x = 0 to 2\n        total := total + x\n    total + x\nplot(mix(close))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_block_body_function_final_if_expression_return() {
    let analysis = analyze(
        "choose(flag) =>\n    if flag\n        1\n    else\n        2\nplot(choose(close > open))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_block_body_function_final_if_branch_block_return() {
    let analysis = analyze(
        "choose(src, flag) =>\n    if flag\n        v = src + 1\n        v\n    else\n        v = src + 10\n        v\nplot(choose(close, close > open))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_block_body_function_final_for_expression_return() {
    let analysis = analyze("loopLast(n) =>\n    for i = 0 to n\n        i\nplot(loopLast(2))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_block_body_function_without_final_expression() {
    let analysis = analyze("double(x) =>\n    y = x * 2\nplot(double(close))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_FUNCTION_RETURN")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_block_body_function_final_if_branch_without_final_expression() {
    let analysis = analyze(
        "choose(src, flag) =>\n    if flag\n        v = src + 1\n    else\n        src\nplot(choose(close, close > open))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_FUNCTION_RETURN"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_recursive_function() {
    let analysis = analyze("loop(x) => loop(x)\nplot(loop(close))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_RECURSIVE_FUNCTION")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_deep_acyclic_function_call_chain() {
    let mut source = String::new();
    for index in 0..70 {
        source.push_str(&format!("f{index}(x) => f{}(x)\n", index + 1));
    }
    source.push_str("f70(x) => x\nplot(f0(close))\n");
    let analysis = analyze(&source);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_FUNCTION_CALL_DEPTH"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_wrong_function_arity() {
    let analysis = analyze("double(x) => x * 2\nplot(double(close, open))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_FUNCTION_ARITY")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_output_call_inside_function() {
    let analysis = analyze("draw(x) => plot(x)\ndraw(close)\n");

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_global_reassignment_inside_function() {
    let analysis = analyze("x = close\nbump(v) =>\n    x := v\n    x\nplot(bump(high))\n");

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_stateful_call_as_function_argument() {
    let analysis = analyze("double(x) => x * 2\nplot(double(ta.sma(close, 2)))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_for_loop_statement() {
    let analysis = analyze("sum = 0\nfor i = 0 to 4 by 2\n    sum := sum + i\nplot(sum)\n");

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
            .any(|feature| feature.feature == "for")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_for_loop_with_series_bounds_and_signed_step() {
    let analysis = analyze(
        "sum = close > 0 ? 0 : 0\nlimit = close > 1 ? 3 : na\nfor i = 0 to limit by -2\n    sum := sum + i\nplot(sum)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_for_statement_counter_as_simple_arg_with_series_step() {
    let analysis = analyze(
        "step = close > open ? 1 : 1\nfor i = 0 to 2 by step\n    plot(ta.ema(close, i))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains(
                "`ta.ema` argument `length` expects simple integer-compatible, got series int"
            )),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_for_expression_counter_as_simple_arg_with_series_step() {
    let analysis = analyze(
        "step = close > open ? 1 : 1\nvalue = for i = 0 to 2 by step\n    ta.ema(close, i)\nplot(value)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains(
                "`ta.ema` argument `length` expects simple integer-compatible, got series int"
            )),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_non_int_for_loop_range() {
    let analysis = analyze("for i = 0.5 to 2\n    plot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_LOOP_RANGE_TYPE")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_non_int_for_loop_step() {
    let analysis = analyze("for i = 0 to 2 by 0.5\n    plot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_LOOP_RANGE_TYPE")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_zero_for_loop_step() {
    let analysis = analyze("for i = 0 to 2 by 0\n    plot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_LOOP_STEP")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_named_const_zero_for_loop_step() {
    let analysis = analyze("base = 0\nstep = base\nfor i = 0 to 2 by step\n    plot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_LOOP_STEP"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_loop_control_inside_for_loop() {
    let analysis = analyze(
        "sum = 0\nfor i = 0 to 5\n    if i == 2\n        continue\n    if i == 4\n        break\n    sum := sum + i\nplot(sum)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_while_loop_statement() {
    let analysis =
        analyze("i = 0\nsum = 0\nwhile i < 5\n    i := i + 1\n    sum := sum + i\nplot(sum)\n");

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
            .any(|feature| feature.feature == "while")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_loop_control_inside_while_loop() {
    let analysis = analyze(
        "i = 0\nwhile i < 5\n    i := i + 1\n    if i == 2\n        continue\n    if i == 4\n        break\nplot(i)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_while_loop_with_na_condition_and_local_var() {
    let analysis = analyze(
        "i = 0\nsum = close > 0 ? 0 : 0\nwhile close > 1 ? i < 3 : na\n    var seen = 0\n    seen := seen + 1\n    sum := sum + seen\n    i := i + 1\nplot(sum)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_while_expression_scope() {
    let analysis = analyze("x = while close > open\n    close\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_branch_loop_interactions() {
    let analysis = analyze(
        "repeat(src, limit) =>\n    i = 0\n    total = src * 0.0\n    while i < limit\n        total := total + src\n        i := i + 1\n    total\nsum = close > 0 ? 0.0 : 0.0\nif close > 1\n    for i = 0 to 2\n        value = switch i\n            0 => close\n            1 => high\n            => low\n        sum := sum + value\nelse\n    j = 0\n    while j < 2\n        sum := sum + open\n        j := j + 1\nplot(sum + repeat(close, 2))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_array_helper_mutation_inside_udf() {
    let analysis = analyze(
        "add(values, value) =>\n    values.unshift(value)\n    values.shift()\nvalues = array.new_float()\nplot(add(values, close))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_array_ordering_mutation_inside_udf() {
    let analysis = analyze(
        "order(values) =>\n    values.sort()\n    values.reverse()\n    values.size()\nvalues = array.new_float()\nplot(order(values))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_readonly_float_array_udf_parameter() {
    let analysis = analyze(
        "first(values) => array.get(values, 0)\nvalues = array.new_float(1, close)\nplot(first(values) + array.size(values))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_readonly_int_array_udf_parameter() {
    let analysis = analyze(
        "first(values) => array.get(values, 0)\nvalues = array.new_int(1, bar_index)\nplot(first(values) + array.size(values))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_readonly_bool_array_udf_parameter() {
    let analysis = analyze(
        "first(values) => array.get(values, 0)\nvalues = array.new_bool(1, true)\nplot(first(values) ? array.size(values) : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_readonly_string_array_udf_parameter() {
    let analysis = analyze(
        "first(values) => array.get(values, 0)\nvalues = array.new_string(1, \"seed\")\nplot(first(values) == \"seed\" ? array.size(values) : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_readonly_color_array_udf_parameter() {
    let analysis = analyze(
        "first(values) => array.get(values, 0)\nvalues = array.new_color(1, color.red)\nplot(first(values) == color.red ? array.size(values) : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_readonly_float_array_method_udf_parameter() {
    let analysis = analyze(
        "first(values) => values.get(0)\nvalues = array.new_float(1, close)\nplot(first(values) + values.size())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_array_mutation_inside_udf() {
    let analysis = analyze(
        "add(values, value) =>\n    array.push(values, value)\n    array.size(values)\nvalues = array.new_float()\nplot(add(values, close))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_array_method_mutation_inside_udf() {
    let analysis = analyze(
        "add(values, value) =>\n    values.push(value)\n    values.size()\nvalues = array.new_float()\nplot(add(values, close))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_array_mutation_as_udf_argument() {
    let analysis = analyze(
        "identity(value) => value\nvalues = array.new_float(1, close)\nplot(identity(array.pop(values)))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_array_method_mutation_as_udf_argument() {
    let analysis = analyze(
        "identity(value) => value\nvalues = array.new_float(1, close)\nplot(identity(values.pop()))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_loop_control_outside_for_loop() {
    let analysis = analyze("break\ncontinue\n");

    let loop_control_errors = analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_LOOP_CONTROL")
        .count();
    assert_eq!(loop_control_errors, 2, "{:?}", analysis.diagnostics);
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_for_counter_escape() {
    let analysis = analyze("for i = 0 to 2\n    plot(close)\nplot(i)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_SYMBOL"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_for_body_local_declaration_escape() {
    let analysis = analyze("for i = 0 to 2\n    x = i\nplot(x)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_SYMBOL"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_nested_for_counter_shadowing() {
    let analysis =
        analyze("sum = 0\nfor i = 0 to 1\n    for i = 0 to 1\n        sum := sum + i\nplot(sum)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_for_expression_result() {
    let analysis = analyze("x = for i = 0 to 2\n    i * 2\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_tuple_for_expression_result() {
    let analysis = analyze("[x, y] = for i = 0 to 2\n    [i, i * 2]\nplot(x + y)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_tuple_while_expression_result() {
    let analysis =
        analyze("i = 0\n[x, y] = while i < 2\n    i := i + 1\n    [i, i * 2]\nplot(x + y)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_for_expression_without_final_expression() {
    let analysis = analyze("x = for i = 0 to 2\n    y = i\nplot(x)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_LOOP_RETURN"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}
