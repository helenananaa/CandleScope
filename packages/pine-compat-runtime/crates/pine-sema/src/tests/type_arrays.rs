use super::*;

#[test]
fn accepts_float_array_operations() {
    let analysis = analyze(
        "values = array.new_float(2, close)\narray.push(values, high)\narray.set(values, 0, low)\nfirst = array.get(values, 0)\nlast = array.pop(values)\narray.clear(values)\nplot(first + last + array.size(values))\n",
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
            .any(|feature| feature.feature == "array.new_float")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "array.size")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_float_array_method_calls() {
    let analysis = analyze(
        "values = array.new_float(2, close)\nvalues.push(high)\nvalues.set(0, low)\nfirst = values.get(0)\nlast = values.pop()\nvalues.clear()\nplot(first + last + values.size())\n",
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
            .any(|feature| feature.feature == "array.push")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_int_array_operations() {
    let analysis = analyze(
        "values = array.new_int(2, bar_index)\narray.push(values, 10)\narray.set(values, 0, 3)\nfirst = array.get(values, 0)\nlast = array.pop(values)\narray.clear(values)\nplot(first + last + array.size(values))\n",
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
            .any(|feature| feature.feature == "array.new_int")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_int_array_method_calls() {
    let analysis = analyze(
        "values = array.new_int(2, bar_index)\nvalues.push(10)\nvalues.set(0, 3)\nfirst = values.get(0)\nlast = values.pop()\nvalues.clear()\nplot(first + last + values.size())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_bool_array_operations() {
    let analysis = analyze(
        "values = array.new_bool(2, close > open)\narray.push(values, true)\narray.set(values, 0, false)\nfirst = array.get(values, 0)\nlast = array.pop(values)\narray.clear(values)\nplot((first or last) ? 1 : array.size(values))\n",
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
            .any(|feature| feature.feature == "array.new_bool")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_bool_array_method_calls() {
    let analysis = analyze(
        "values = array.new_bool(2, close > open)\nvalues.push(true)\nvalues.set(0, false)\nfirst = values.get(0)\nlast = values.pop()\nvalues.clear()\nplot((first or last) ? 1 : values.size())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_string_array_operations() {
    let analysis = analyze(
        "values = array.new_string(2, \"seed\")\narray.push(values, \"tail\")\narray.set(values, 0, \"head\")\nfirst = array.get(values, 0)\nlast = array.pop(values)\narray.clear(values)\nplot(first == \"head\" and last == \"tail\" ? array.size(values) : 0)\n",
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
            .any(|feature| feature.feature == "array.new_string")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_string_array_method_calls() {
    let analysis = analyze(
        "values = array.new_string(2, \"seed\")\nvalues.push(\"tail\")\nvalues.set(0, \"head\")\nfirst = values.get(0)\nlast = values.pop()\nvalues.clear()\nplot(first == \"head\" and last == \"tail\" ? values.size() : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_color_array_operations() {
    let analysis = analyze(
        "values = array.new_color(2, color.red)\narray.push(values, color.green)\narray.set(values, 0, color.blue)\nfirst = array.get(values, 0)\nlast = array.pop(values)\narray.clear(values)\nplot(first == color.blue and last == color.green ? array.size(values) : 0)\n",
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
            .any(|feature| feature.feature == "array.new_color")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_color_array_method_calls() {
    let analysis = analyze(
        "values = array.new_color(2, color.red)\nvalues.push(color.green)\nvalues.set(0, color.blue)\nfirst = values.get(0)\nlast = values.pop()\nvalues.clear()\nplot(first == color.blue and last == color.green ? values.size() : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_line_array_operations() {
    let analysis = analyze(
        "values = array.new_line()\nid = line.new(bar_index, low, bar_index + 1, high)\narray.push(values, id)\nfirst = array.get(values, 0)\nline.set_color(first, color.green)\ncopy = array.copy(values)\nline.set_width(copy.get(0), 2)\nplot(array.size(values) + copy.size())\n",
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
            .any(|feature| feature.feature == "array.new_line")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_line_array_from_constructor() {
    let analysis = analyze(
        "first = line.new(bar_index, low, bar_index + 1, high)\nsecond = line.copy(first)\nvalues = array.from(first, second)\nline.set_width(values.get(1), 2)\nplot(values.size())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_label_array_operations() {
    let analysis = analyze(
        "values = array.new_label()\nid = label.new(bar_index, high, \"start\")\narray.push(values, id)\nfirst = array.get(values, 0)\nlabel.set_text(first, \"array\")\ncopy = array.copy(values)\nlabel.set_color(copy.get(0), color.green)\nplot(array.size(values) + copy.size())\n",
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
            .any(|feature| feature.feature == "array.new_label")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_label_array_from_constructor() {
    let analysis = analyze(
        "first = label.new(bar_index, high, \"first\")\nsecond = label.copy(first)\nvalues = array.from(first, second)\nlabel.set_text(values.get(1), \"copy\")\nplot(values.size())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_box_array_operations() {
    let analysis = analyze(
        "values = array.new_box()\nid = box.new(bar_index, high, bar_index + 1, low)\narray.push(values, id)\nfirst = array.get(values, 0)\nbox.set_text(first, \"array\")\ncopy = array.copy(values)\nbox.set_bgcolor(copy.get(0), color.green)\nplot(array.size(values) + copy.size())\n",
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
            .any(|feature| feature.feature == "array.new_box")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_box_array_from_constructor() {
    let analysis = analyze(
        "first = box.new(bar_index, high, bar_index + 1, low)\nsecond = box.copy(first)\nvalues = array.from(first, second)\nbox.set_text(values.get(1), \"copy\")\nplot(values.size())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_table_array_operations() {
    let analysis = analyze(
        "values = array.new_table()\nid = table.new(position.top_right, 1, 1)\narray.push(values, id)\nfirst = array.get(values, 0)\ntable.cell(first, 0, 0, \"array\")\ncopy = array.copy(values)\ntable.set_bgcolor(copy.get(0), color.green)\nplot(array.size(values) + copy.size())\n",
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
            .any(|feature| feature.feature == "array.new_table")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_table_array_from_constructor() {
    let analysis = analyze(
        "first = table.new(position.top_right, 1, 1)\nsecond = table.new(position.bottom_left, 1, 1)\nvalues = array.from(first, second)\ntable.cell(values.get(1), 0, 0, \"copy\")\nplot(values.size())\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_helper_operations() {
    let analysis = analyze(
        "values = array.new_int()\narray.unshift(values, 2)\narray.unshift(values, 1)\nfirst = array.first(values)\nlast = array.last(values)\nshifted = array.shift(values)\nplot(first + last + shifted + array.size(values))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in ["array.unshift", "array.first", "array.last", "array.shift"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} missing from supported features: {:?}",
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_insert_remove_operations() {
    let analysis = analyze(
        "values = array.new_int()\nvalues.push(1)\narray.insert(values, 1, 2)\nvalues.insert(-1, 3)\nremoved = values.remove(-2)\nplot(removed + values.get(-1))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in ["array.insert", "array.remove"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} missing from supported features: {:?}",
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_fill_operations() {
    let analysis = analyze(
        "values = array.new_string(3, \"a\")\narray.fill(values, \"b\", 1, 3)\nints = array.new_int(2, 1)\nints.fill(2)\nplot(values.get(1) == \"b\" and ints.get(0) == 2 ? 1 : 0)\n",
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
            .any(|supported| supported.feature == "array.fill"),
        "{:?}",
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_from_operations() {
    let analysis = analyze(
        "ints = array.from(1, 2, 3)\nfloats = array.from(1, close, na)\nflags = array.from(true, false)\nwords = array.from(\"a\", \"b\")\ncolors = array.from(color.red, color.green)\nplot(ints.sum() + floats.avg() + (flags.get(0) ? 1 : 0) + (words.join(\"|\") == \"a|b\" ? 1 : 0) + (colors.get(0) == color.red ? 1 : 0))\n",
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
            .any(|supported| supported.feature == "array.from"),
        "{:?}",
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_while_expression_result() {
    let analysis = analyze(
        "i = 0\nitems = while i < 2\n    i := i + 1\n    array.from(close + i, i)\nplot(array.size(items) + array.get(items, 0) + items.get(1))\n",
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
fn accepts_array_while_expression_result_mutation() {
    let analysis = analyze(
        "i = 0\nitems = while i < 2\n    i := i + 1\n    array.from(close + i, i)\nitems.set(0, items.get(0) + 10)\nplot(array.size(items) + items.get(0) + items.get(1))\n",
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
fn accepts_array_while_expression_alias_result() {
    let analysis = analyze(
        "source = array.from(close, open)\ni = 0\nitems = while i < 2\n    i := i + 1\n    source\nitems.set(0, items.get(0) + 10)\nplot(source.get(0) + items.get(0))\n",
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
fn rejects_while_expression_nested_array_result() {
    let source = SourceFile::new(
        "tests/fixtures/sema/unsupported_while_expression_nested_array_result.pine",
        include_str!(
            "../../../../tests/fixtures/sema/unsupported_while_expression_nested_array_result.pine"
        ),
    );
    let analysis = analyze_source(&source);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"
                && diagnostic.message.contains(
                    "`array.from` expects one supported array element kind, got simple array<float>"
                )),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_array_helper_method_calls() {
    let analysis = analyze(
        "values = array.new_string()\nvalues.unshift(\"tail\")\nvalues.unshift(\"head\")\nfirst = values.first()\nlast = values.last()\nshifted = values.shift()\nplot(first == \"head\" and last == \"tail\" and shifted == \"head\" ? values.size() : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_copy_operations() {
    let analysis = analyze(
        "source = array.new_int()\nalias = source\ncopy = array.copy(source)\nmethod_copy = source.copy()\narray.push(alias, 1)\narray.push(copy, 2)\nmethod_copy.push(3)\nplot(array.size(source) + array.size(copy) + method_copy.size())\n",
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
            .any(|feature| feature.feature == "array.copy"),
        "{:?}",
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_search_operations() {
    let analysis = analyze(
        "values = array.new_string()\narray.push(values, \"a\")\narray.push(values, \"b\")\narray.push(values, \"a\")\nhas_a = array.includes(values, \"a\")\nfirst = array.indexof(values, \"a\")\nlast = array.lastindexof(values, \"a\")\nmissing = values.indexof(\"z\")\nnums = array.from(1, 2, 2, 4)\nfound = array.binary_search(nums, 2)\nleft = nums.binary_search_leftmost(3)\nright = nums.binary_search_rightmost(3)\nflags = array.from(true, false)\nplot(has_a and values.includes(\"b\") and flags.some() and not flags.every() ? first + last + missing + found + left + right : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "array.includes",
        "array.every",
        "array.some",
        "array.indexof",
        "array.lastindexof",
        "array.binary_search",
        "array.binary_search_leftmost",
        "array.binary_search_rightmost",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} missing from supported features: {:?}",
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_numeric_array_statistics() {
    let analysis = analyze(
        "ints = array.new_int()\narray.push(ints, 1)\narray.push(ints, 3)\narray.push(ints, 3)\nabs_ints = ints.abs()\nstandard_ints = ints.standardize()\nfloats = array.new_float()\nfloats.push(close)\nfloats.push(high)\nplot(array.min(ints) + array.max(ints) + array.sum(ints) + ints.range() + ints.median() + array.mode(ints) + ints.percentile_nearest_rank(50) + array.percentile_linear_interpolation(ints, 75) + array.percentrank(ints, 1) + ints.covariance(standard_ints) + ints.variance(false) + array.avg(floats) + floats.max() + array.range(floats) + array.stdev(floats) + array.sum(abs_ints) + standard_ints.get(0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "array.min",
        "array.max",
        "array.sum",
        "array.avg",
        "array.range",
        "array.median",
        "array.mode",
        "array.percentile_nearest_rank",
        "array.percentile_linear_interpolation",
        "array.percentrank",
        "array.covariance",
        "array.standardize",
        "array.variance",
        "array.stdev",
        "array.abs",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} missing from supported features: {:?}",
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_ordering_operations() {
    let analysis = analyze(
        "values = array.new_int()\narray.push(values, 3)\narray.push(values, 1)\nindices = values.sort_indices(order.descending)\narray.sort(values, order.descending)\nvalues.reverse()\nwords = array.from(\"b\", \"a\")\nword_indices = words.sort_indices(order.ascending)\nwords.sort(order.ascending)\nplot(values.get(0) + values.get(1) + indices.get(0) + word_indices.get(0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in ["array.sort", "array.sort_indices", "array.reverse"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} missing from supported features: {:?}",
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_join_operations() {
    let analysis = analyze(
        "values = array.new_string()\nvalues.push(\"a\")\nvalues.push(\"b\")\ntext = array.join(values, \"|\")\nints = array.new_int()\nints.push(1)\nints.push(2)\nplot(text == \"a|b\" and ints.join() == \"1,2\" ? 1 : 0)\n",
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
            .any(|supported| supported.feature == "array.join"),
        "{:?}",
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_array_slice_concat_operations() {
    let analysis = analyze(
        "values = array.new_int()\nvalues.push(1)\nvalues.push(2)\nvalues.push(3)\npart = array.slice(values, 1, 3)\nmore = array.new_int()\nmore.push(4)\nreturned = values.concat(more)\nplot(part.size() + array.size(returned) + values.get(3))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in ["array.slice", "array.concat"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} missing from supported features: {:?}",
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_float_value_for_int_array_mutation() {
    let analysis = analyze("values = array.new_int()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_bool_array_mutation() {
    let analysis = analyze("values = array.new_bool()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_bool_array_unshift() {
    let analysis =
        analyze("values = array.new_bool()\narray.unshift(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_bool_array_insert() {
    let analysis =
        analyze("values = array.new_bool()\narray.insert(values, 0, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_bool_array_fill() {
    let analysis = analyze("values = array.new_bool(2)\narray.fill(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_mixed_array_from_element_kinds() {
    let analysis = analyze("values = array.from(1, \"two\")\nplot(array.size(values))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_untyped_na_array_from() {
    let analysis = analyze("values = array.from(na, na)\nplot(array.size(values))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_bool_array_search() {
    let analysis = analyze("values = array.new_bool()\nplot(array.indexof(values, close))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_bool_array_binary_search() {
    let analysis = analyze("values = array.new_bool()\nplot(array.binary_search(values, 1))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_float_value_for_int_array_binary_search() {
    let analysis = analyze("values = array.new_int()\nplot(values.binary_search(close))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_string_array_truth_helpers() {
    let analysis = analyze("values = array.new_string()\nplot(array.every(values))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_bool_array_statistics() {
    let analysis = analyze("values = array.new_bool()\nplot(array.stdev(values))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_bool_array_sort() {
    let analysis = analyze("values = array.new_bool()\nvalues.push(true)\narray.sort(values)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_array_sort_order() {
    let analysis = analyze("values = array.new_int()\narray.sort(values, close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_bool_array_sort_indices() {
    let analysis = analyze("values = array.new_bool()\nvalues.push(true)\nvalues.sort_indices()\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_array_sort_indices_order() {
    let analysis = analyze("values = array.new_int()\narray.sort_indices(values, close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_separator_for_array_join() {
    let analysis = analyze("values = array.new_string()\nplot(array.join(values, close))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_mismatched_array_concat_kind() {
    let analysis = analyze(
        "ints = array.new_int()\nfloats = array.new_float()\nplot(array.size(array.concat(ints, floats)))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_series_array_slice_index() {
    let analysis =
        analyze("values = array.new_string()\nplot(array.size(values.slice(0, bar_index)))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_string_array_mutation() {
    let analysis = analyze("values = array.new_string()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_color_array_mutation() {
    let analysis = analyze("values = array.new_color()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_line_array_mutation() {
    let analysis = analyze("values = array.new_line()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_line_array_join() {
    let analysis = analyze("values = array.new_line()\ntext = array.join(values)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_label_array_mutation() {
    let analysis = analyze("values = array.new_label()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_label_array_join() {
    let analysis = analyze("values = array.new_label()\ntext = array.join(values)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_box_array_mutation() {
    let analysis = analyze("values = array.new_box()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_box_array_join() {
    let analysis = analyze("values = array.new_box()\ntext = array.join(values)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_numeric_value_for_table_array_mutation() {
    let analysis = analyze("values = array.new_table()\narray.push(values, close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_table_array_join() {
    let analysis = analyze("values = array.new_table()\ntext = array.join(values)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_array_method_call_on_namespace_like_variable_name() {
    let analysis =
        analyze("strategy = array.new_float()\nstrategy.push(close)\nplot(strategy.size())\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_unknown_float_array_method() {
    let analysis = analyze("values = array.new_float()\nvalues.unsupported(close)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_METHOD"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_linefill_array_constructor() {
    let analysis = analyze(
        "upper = line.new(bar_index, high, bar_index + 1, high)\nlower = line.new(bar_index, low, bar_index + 1, low)\nfill = linefill.new(upper, lower, color.green)\nvalues = array.new_linefill(1, fill)\nfrom_values = array.from(fill)\narray.push(values, na)\nfirst = array.get(values, 0)\nplot(line.get_x1(linefill.get_line1(first)) + array.size(values) + array.size(from_values))\n",
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
            .any(|feature| feature.feature == "array.new_linefill")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_polyline_array_constructor() {
    let analysis = analyze(
        "points = array.new<chart.point>()\narray.push(points, chart.point.from_index(bar_index, close))\nid = polyline.new(points)\nvalues = array.new_polyline(1, id)\nfrom_values = array.from(id)\narray.push(values, na)\nfirst = array.get(values, 0)\nplot(array.size(values) + array.size(from_values) + (first == id ? 1 : 0))\n",
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
            .any(|feature| feature.feature == "array.new_polyline")
    );
    assert!(analysis.hir.is_some());
}
