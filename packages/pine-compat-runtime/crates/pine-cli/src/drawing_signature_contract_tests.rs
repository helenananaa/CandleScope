use pine_builtins::{Accepts, ReturnSpec};
use std::{collections::BTreeSet, fs, path::PathBuf};

const SIGNATURE_PREFIXES: &[&str] = &[
    "chart.point.",
    "label.",
    "line.",
    "linefill.",
    "polyline.",
    "box.",
    "table.",
];

const DRAWING_ALL_VALUES: &[&str] = &[
    "label.all",
    "line.all",
    "linefill.all",
    "polyline.all",
    "box.all",
    "table.all",
];

const ARRAY_CONSTRUCTOR_NAMES: &[&str] = &[
    "array.new_float",
    "array.new_int",
    "array.new_bool",
    "array.new_string",
    "array.new_color",
    "array.new_label",
    "array.new_line",
    "array.new_linefill",
    "array.new_polyline",
    "array.new_box",
    "array.new_table",
    "array.new<chart.point>",
];

const ARRAY_TRUTHY_METHOD_NAMES: &[&str] = &["array.every", "array.some"];

const ARRAY_NUMERIC_ELEMENT_METHOD_NAMES: &[&str] = &[
    "array.min",
    "array.max",
    "array.sum",
    "array.range",
    "array.median",
    "array.mode",
    "array.percentile_nearest_rank",
];

const ARRAY_SERIES_FLOAT_METHOD_NAMES: &[&str] = &[
    "array.avg",
    "array.percentile_linear_interpolation",
    "array.percentrank",
    "array.covariance",
    "array.variance",
    "array.stdev",
];

const ARRAY_FLOAT_ARRAY_METHOD_NAMES: &[&str] = &["array.standardize"];

const ARRAY_VOID_ALL_ARRAY_METHOD_NAMES: &[&str] = &["array.reverse", "array.clear"];

const ARRAY_ORDERING_METHOD_NAMES: &[&str] = &["array.sort", "array.sort_indices"];

const ARRAY_JOIN_METHOD_NAMES: &[&str] = &["array.join"];

const ARRAY_ELEMENT_READER_METHOD_NAMES: &[&str] = &[
    "array.get",
    "array.pop",
    "array.remove",
    "array.shift",
    "array.first",
    "array.last",
];

const ARRAY_MUTATION_VALUE_METHOD_NAMES: &[&str] = &[
    "array.push",
    "array.set",
    "array.insert",
    "array.unshift",
    "array.fill",
];

const ARRAY_INCLUDES_METHOD_NAMES: &[&str] = &["array.includes"];

const ARRAY_SIZE_METHOD_NAMES: &[&str] = &["array.size"];

const ARRAY_FROM_METHOD_NAMES: &[&str] = &["array.from"];

const ARRAY_BINARY_SEARCH_METHOD_NAMES: &[&str] = &[
    "array.binary_search",
    "array.binary_search_leftmost",
    "array.binary_search_rightmost",
];

const ARRAY_INDEX_SEARCH_METHOD_NAMES: &[&str] = &["array.indexof", "array.lastindexof"];

const ARRAY_SAME_KIND_METHOD_NAMES: &[&str] =
    &["array.copy", "array.slice", "array.concat", "array.abs"];

const ALL_ARRAY_DOC: &str = "float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array";

#[test]
fn drawing_and_chart_point_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for signature in pine_builtins::PHASE_1_BUILTINS
        .iter()
        .filter(|signature| covered_signature_name(signature.name))
    {
        assert_signature_documented(&docs, signature);
    }

    for name in DRAWING_ALL_VALUES {
        let pine_type = pine_builtins::builtin_series_value_type(name)
            .unwrap_or_else(|| panic!("missing builtin series value for `{name}`"));
        let expected = format!("{name} -> {}", pine_type_doc(pine_type));
        assert!(
            docs.lines().any(|line| line == expected),
            "BUILTIN_SIGNATURES.md should document `{expected}`"
        );
    }
}

#[test]
fn array_constructor_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_CONSTRUCTOR_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_constructor_signature_documented(&docs, signature);
    }
}

#[test]
fn array_truthy_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_TRUTHY_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_truthy_signature_documented(&docs, signature);
    }
}

#[test]
fn array_numeric_element_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_NUMERIC_ELEMENT_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_numeric_element_signature_documented(&docs, signature);
    }
}

#[test]
fn array_series_float_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_SERIES_FLOAT_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_series_float_signature_documented(&docs, signature);
    }
}

#[test]
fn array_float_array_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_FLOAT_ARRAY_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_float_array_signature_documented(&docs, signature);
    }
}

#[test]
fn array_void_all_array_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_VOID_ALL_ARRAY_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_void_all_array_signature_documented(&docs, signature);
    }
}

#[test]
fn array_ordering_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_ORDERING_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_ordering_signature_documented(&docs, signature);
    }
}

#[test]
fn array_join_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_JOIN_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_join_signature_documented(&docs, signature);
    }
}

#[test]
fn array_element_reader_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_ELEMENT_READER_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_element_reader_signature_documented(&docs, signature);
    }
}

#[test]
fn array_mutation_value_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_MUTATION_VALUE_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_mutation_value_signature_documented(&docs, signature);
    }
}

#[test]
fn array_includes_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_INCLUDES_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_includes_signature_documented(&docs, signature);
    }
}

#[test]
fn array_size_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_SIZE_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_size_signature_documented(&docs, signature);
    }
}

#[test]
fn array_from_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_FROM_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_from_signature_documented(&docs, signature);
    }
}

#[test]
fn array_binary_search_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_BINARY_SEARCH_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_binary_search_signature_documented(&docs, signature);
    }
}

#[test]
fn array_index_search_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_INDEX_SEARCH_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_index_search_signature_documented(&docs, signature);
    }
}

#[test]
fn array_same_kind_builtin_signatures_stay_in_sync_with_docs() {
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));

    for name in ARRAY_SAME_KIND_METHOD_NAMES {
        let signature = pine_builtins::PHASE_1_BUILTINS
            .iter()
            .find(|signature| signature.name == *name)
            .unwrap_or_else(|| panic!("missing builtin signature for `{name}`"));
        assert_array_same_kind_signature_documented(&docs, signature);
    }
}

#[test]
fn array_builtin_signatures_stay_in_sync_with_docs_guards_cover_all_array_builtins() {
    let guarded = guarded_array_signature_names();
    let registered = pine_builtins::PHASE_1_BUILTINS
        .iter()
        .map(|signature| signature.name)
        .filter(|name| name.starts_with("array."))
        .collect::<BTreeSet<_>>();

    let missing = registered.difference(&guarded).copied().collect::<Vec<_>>();
    assert!(
        missing.is_empty(),
        "array builtin signature docs guards are missing entries: {missing:?}"
    );

    let stale = guarded.difference(&registered).copied().collect::<Vec<_>>();
    assert!(
        stale.is_empty(),
        "array builtin signature docs guards reference unknown builtins: {stale:?}"
    );
}

fn covered_signature_name(name: &str) -> bool {
    SIGNATURE_PREFIXES
        .iter()
        .any(|prefix| name.starts_with(prefix))
}

fn guarded_array_signature_names() -> BTreeSet<&'static str> {
    let mut names = BTreeSet::new();
    for group in [
        ARRAY_CONSTRUCTOR_NAMES,
        ARRAY_TRUTHY_METHOD_NAMES,
        ARRAY_NUMERIC_ELEMENT_METHOD_NAMES,
        ARRAY_SERIES_FLOAT_METHOD_NAMES,
        ARRAY_FLOAT_ARRAY_METHOD_NAMES,
        ARRAY_VOID_ALL_ARRAY_METHOD_NAMES,
        ARRAY_ORDERING_METHOD_NAMES,
        ARRAY_JOIN_METHOD_NAMES,
        ARRAY_ELEMENT_READER_METHOD_NAMES,
        ARRAY_MUTATION_VALUE_METHOD_NAMES,
        ARRAY_INCLUDES_METHOD_NAMES,
        ARRAY_SIZE_METHOD_NAMES,
        ARRAY_FROM_METHOD_NAMES,
        ARRAY_BINARY_SEARCH_METHOD_NAMES,
        ARRAY_INDEX_SEARCH_METHOD_NAMES,
        ARRAY_SAME_KIND_METHOD_NAMES,
    ] {
        for name in group {
            assert!(
                names.insert(*name),
                "array builtin signature docs guard duplicates `{name}`"
            );
        }
    }
    names
}

fn assert_signature_documented(docs: &str, signature: &pine_builtins::BuiltinSignature) {
    let expected = format_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_constructor_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_constructor_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_truthy_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_truthy_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_numeric_element_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_numeric_element_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_series_float_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_series_float_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_float_array_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_float_array_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_void_all_array_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_void_all_array_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_ordering_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_ordering_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_join_signature_documented(docs: &str, signature: &pine_builtins::BuiltinSignature) {
    let expected = format_array_join_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_includes_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_includes_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_element_reader_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_element_reader_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_mutation_value_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_mutation_value_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_size_signature_documented(docs: &str, signature: &pine_builtins::BuiltinSignature) {
    let expected = format_array_size_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_from_signature_documented(docs: &str, signature: &pine_builtins::BuiltinSignature) {
    let expected = format_array_from_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_binary_search_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_binary_search_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_index_search_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_index_search_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn assert_array_same_kind_signature_documented(
    docs: &str,
    signature: &pine_builtins::BuiltinSignature,
) {
    let expected = format_array_same_kind_signature(signature);
    assert!(
        docs.lines().any(|line| line == expected),
        "BUILTIN_SIGNATURES.md should document `{expected}`"
    );
}

fn format_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!("{}{}: {}", param.name, optional, accepts_doc(param.accepts))
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_constructor_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_constructor_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    let ReturnSpec::Fixed(pine_type) = signature.returns else {
        panic!(
            "array constructor should have fixed return {:?}",
            signature.returns
        );
    };
    format!(
        "{}({params}) -> {}",
        signature.name,
        array_constructor_return_doc(pine_type)
    )
}

fn format_array_truthy_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_truthy_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_numeric_element_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_numeric_element_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        array_numeric_element_return_doc(signature.returns)
    )
}

fn format_array_series_float_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_series_float_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_float_array_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_numeric_element_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        array_float_array_return_doc(signature.returns)
    )
}

fn format_array_void_all_array_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_all_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_ordering_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_ordering_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        array_ordering_return_doc(signature.returns)
    )
}

fn format_array_join_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_join_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_includes_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_index_search_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_element_reader_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_element_reader_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        array_element_reader_return_doc(signature.returns)
    )
}

fn format_array_mutation_value_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_mutation_value_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_size_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_all_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_from_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    assert!(
        signature.variadic,
        "array.from signature should remain variadic"
    );
    assert_eq!(
        signature.params.len(),
        1,
        "array.from should keep a single variadic parameter"
    );
    let param = signature.params[0];
    assert_eq!(
        param.accepts,
        Accepts::Any,
        "array.from variadic parameter should accept any value"
    );
    assert!(
        !param.optional,
        "array.from variadic parameter should remain required"
    );
    let return_doc = match signature.returns {
        ReturnSpec::ArrayFromArgs => "simple inferred scalar-or-object-array",
        other => panic!("unsupported array.from return {other:?}"),
    };
    format!("{}({}, ...) -> {return_doc}", signature.name, param.name)
}

fn format_array_binary_search_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_binary_search_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_index_search_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_index_search_accepts_doc(param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        return_doc(signature.returns)
    )
}

fn format_array_same_kind_signature(signature: &pine_builtins::BuiltinSignature) -> String {
    let params = signature
        .params
        .iter()
        .map(|param| {
            let optional = if param.optional { "?" } else { "" };
            format!(
                "{}{}: {}",
                param.name,
                optional,
                array_same_kind_accepts_doc(param.name, param.accepts)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{}({params}) -> {}",
        signature.name,
        array_same_kind_return_doc(signature.returns)
    )
}

fn accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::Exact(pine_type) => pine_type_doc(pine_type),
        Accepts::Numeric => "numeric",
        Accepts::SimpleInt => "simple int",
        Accepts::SimpleIntCompatible => "simple integer-compatible",
        Accepts::SimpleNumericCompatible => "simple numeric-compatible",
        Accepts::SimpleBoolCompatible => "simple bool-compatible",
        Accepts::ConstString => "const string",
        Accepts::ConstBool => "const bool",
        Accepts::ColorCompatible => "color-compatible",
        Accepts::StringCompatible => "string-compatible",
        Accepts::StringOrIntCompatible => "string-or-int-compatible",
        Accepts::NumericCompatible => "numeric-compatible",
        Accepts::IntCompatible => "int-compatible",
        Accepts::BoolCompatible => "bool-compatible",
        Accepts::LabelCompatible => "label-compatible",
        Accepts::LineCompatible => "line-compatible",
        Accepts::LineFillCompatible => "linefill-compatible",
        Accepts::PolylineCompatible => "polyline-compatible",
        Accepts::BoxCompatible => "box-compatible",
        Accepts::TableCompatible => "table-compatible",
        Accepts::ChartPointCompatible => "chart.point-compatible",
        other => panic!("unsupported drawing signature acceptor {other:?}"),
    }
}

fn array_index_search_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::Array => ALL_ARRAY_DOC,
        Accepts::Any => "element-compatible",
        other => accepts_doc(other),
    }
}

fn array_all_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::Array => ALL_ARRAY_DOC,
        other => accepts_doc(other),
    }
}

fn array_ordering_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::NumericOrStringArray => "float-array|int-array|string-array",
        other => accepts_doc(other),
    }
}

fn array_join_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::ScalarArray => "float-array|int-array|bool-array|string-array|color-array",
        other => accepts_doc(other),
    }
}

fn array_element_reader_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::Array => ALL_ARRAY_DOC,
        Accepts::SimpleInt => "simple int",
        other => accepts_doc(other),
    }
}

fn array_mutation_value_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::Array => ALL_ARRAY_DOC,
        Accepts::Any => "element-compatible",
        Accepts::SimpleInt => "simple int",
        other => accepts_doc(other),
    }
}

fn array_same_kind_accepts_doc(name: &str, accepts: Accepts) -> &'static str {
    match (name, accepts) {
        ("id2", Accepts::Array) => "same array kind",
        (_, Accepts::Array) => ALL_ARRAY_DOC,
        (_, Accepts::NumericArray) => "float-array|int-array",
        (_, Accepts::SimpleInt) => "simple int",
        (_, other) => accepts_doc(other),
    }
}

fn array_binary_search_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::NumericArray => "float-array|int-array",
        Accepts::Any => "element-compatible",
        other => accepts_doc(other),
    }
}

fn array_series_float_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::NumericArray => "float-array|int-array",
        Accepts::SeriesOrSimpleNumeric => "numeric-compatible",
        other => accepts_doc(other),
    }
}

fn array_numeric_element_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::NumericArray => "float-array|int-array",
        Accepts::SeriesOrSimpleNumeric => "numeric-compatible",
        other => accepts_doc(other),
    }
}

fn array_truthy_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::NumericOrBoolArray => "float-array|int-array|bool-array",
        other => accepts_doc(other),
    }
}

fn array_constructor_accepts_doc(accepts: Accepts) -> &'static str {
    match accepts {
        Accepts::ChartPointCompatible => "chart-point-compatible",
        other => accepts_doc(other),
    }
}

fn array_constructor_return_doc(pine_type: impl std::fmt::Debug) -> &'static str {
    match format!("{pine_type:?}").as_str() {
        "PineType { qualifier: Simple, kind: FloatArray }" => "simple float-array",
        "PineType { qualifier: Simple, kind: IntArray }" => "simple int-array",
        "PineType { qualifier: Simple, kind: BoolArray }" => "simple bool-array",
        "PineType { qualifier: Simple, kind: StringArray }" => "simple string-array",
        "PineType { qualifier: Simple, kind: ColorArray }" => "simple color-array",
        "PineType { qualifier: Simple, kind: LabelArray }" => "simple label-array",
        "PineType { qualifier: Simple, kind: LineArray }" => "simple line-array",
        "PineType { qualifier: Simple, kind: LineFillArray }" => "simple linefill-array",
        "PineType { qualifier: Simple, kind: PolylineArray }" => "simple polyline-array",
        "PineType { qualifier: Simple, kind: BoxArray }" => "simple box-array",
        "PineType { qualifier: Simple, kind: TableArray }" => "simple table-array",
        "PineType { qualifier: Simple, kind: ChartPointArray }" => "simple chart-point-array",
        other => panic!("unsupported array constructor return type {other}"),
    }
}

fn array_numeric_element_return_doc(returns: ReturnSpec) -> &'static str {
    match returns {
        ReturnSpec::ArrayNumeric(0) => "series element",
        other => panic!("unsupported array numeric element return {other:?}"),
    }
}

fn array_element_reader_return_doc(returns: ReturnSpec) -> &'static str {
    match returns {
        ReturnSpec::ArrayElement(0) => "series element",
        other => panic!("unsupported array element reader return {other:?}"),
    }
}

fn array_float_array_return_doc(returns: ReturnSpec) -> &'static str {
    match returns {
        ReturnSpec::Fixed(pine_type)
            if format!("{pine_type:?}") == "PineType { qualifier: Simple, kind: FloatArray }" =>
        {
            "float-array"
        }
        other => panic!("unsupported array float-array return {other:?}"),
    }
}

fn array_ordering_return_doc(returns: ReturnSpec) -> &'static str {
    match returns {
        ReturnSpec::Fixed(pine_type)
            if format!("{pine_type:?}") == "PineType { qualifier: Const, kind: Void }" =>
        {
            "void"
        }
        ReturnSpec::Fixed(pine_type)
            if format!("{pine_type:?}") == "PineType { qualifier: Simple, kind: IntArray }" =>
        {
            "int-array"
        }
        other => panic!("unsupported array ordering return {other:?}"),
    }
}

fn array_same_kind_return_doc(returns: ReturnSpec) -> &'static str {
    match returns {
        ReturnSpec::SameAsArg(0) => "same array kind",
        other => panic!("unsupported array same-kind return {other:?}"),
    }
}

fn return_doc(returns: ReturnSpec) -> &'static str {
    match returns {
        ReturnSpec::Fixed(pine_type) => pine_type_doc(pine_type),
        other => panic!("unsupported drawing signature return {other:?}"),
    }
}

fn pine_type_doc(pine_type: impl std::fmt::Debug) -> &'static str {
    match format!("{pine_type:?}").as_str() {
        "PineType { qualifier: Const, kind: Void }" => "void",
        "PineType { qualifier: Series, kind: Int }" => "series int",
        "PineType { qualifier: Series, kind: Float }" => "series float",
        "PineType { qualifier: Series, kind: Bool }" => "series bool",
        "PineType { qualifier: Series, kind: String }" => "series string",
        "PineType { qualifier: Series, kind: ChartPoint }" => "series chart.point",
        "PineType { qualifier: Series, kind: Label }" => "series label",
        "PineType { qualifier: Series, kind: Line }" => "series line",
        "PineType { qualifier: Series, kind: LineFill }" => "series linefill",
        "PineType { qualifier: Series, kind: Polyline }" => "series polyline",
        "PineType { qualifier: Series, kind: Box }" => "series box",
        "PineType { qualifier: Series, kind: Table }" => "series table",
        "PineType { qualifier: Simple, kind: Int }" => "simple int",
        "PineType { qualifier: Simple, kind: FloatArray }" => "simple float-array",
        "PineType { qualifier: Simple, kind: IntArray }" => "simple int-array",
        "PineType { qualifier: Simple, kind: BoolArray }" => "simple bool-array",
        "PineType { qualifier: Simple, kind: StringArray }" => "simple string-array",
        "PineType { qualifier: Simple, kind: ColorArray }" => "simple color-array",
        "PineType { qualifier: Simple, kind: ChartPointArray }" => "simple array<chart.point>",
        "PineType { qualifier: Simple, kind: LabelArray }" => "simple array<label>",
        "PineType { qualifier: Simple, kind: LineArray }" => "simple array<line>",
        "PineType { qualifier: Simple, kind: LineFillArray }" => "simple array<linefill>",
        "PineType { qualifier: Simple, kind: PolylineArray }" => "simple array<polyline>",
        "PineType { qualifier: Simple, kind: BoxArray }" => "simple array<box>",
        "PineType { qualifier: Simple, kind: TableArray }" => "simple array<table>",
        other => panic!("unsupported drawing signature type {other}"),
    }
}

fn workspace_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
