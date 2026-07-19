pub(super) const LOCAL_UDT_ARRAY_CALL_RETURN_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/user_type_array_scalar_tree.pine",
    "tests/fixtures/sema/supported_user_type_array_udf_method_returns.pine",
    "tests/fixtures/sema/unsupported_user_type_array_udf_method_return_identities.pine",
    "tests/fixtures/runtime/user_type_array_tuple_returns.pine",
    "tests/fixtures/sema/supported_user_type_array_tuple_returns.pine",
    "tests/fixtures/sema/unsupported_user_type_array_tuple_return_identities.pine",
    "tests/fixtures/sema/unsupported_user_type_array_tuple_alias_mutation.pine",
    "tests/fixtures/sema/unsupported_local_user_type_array_call_result_chaining.pine",
];

pub(super) const IMPORTED_UDT_ARRAY_CALL_RETURN_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/import_udt_array_udf_method_returns.pine",
    "tests/fixtures/sema/supported_imported_user_type_array_udf_method_returns.pine",
    "tests/fixtures/sema/unsupported_imported_user_type_array_udf_method_return_identities.pine",
    "tests/fixtures/runtime/import_udt_array_tuple_returns.pine",
    "tests/fixtures/sema/supported_imported_user_type_array_tuple_returns.pine",
    "tests/fixtures/sema/unsupported_imported_user_type_array_tuple_return_identities.pine",
    "tests/fixtures/sema/unsupported_imported_user_type_array_tuple_alias_mutation.pine",
    "tests/fixtures/sema/unsupported_imported_user_type_array_call_result_chaining.pine",
    "tests/fixtures/libraries/import_udt_array_return_lib.pine",
];

const UDT_ARRAY_CALL_RESULT_HELPER_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/user_type_array_scalar_tree.pine",
    "tests/fixtures/sema/supported_user_type_array_udf_method_returns.pine",
    "tests/fixtures/sema/unsupported_local_user_type_array_call_result_chaining.pine",
    "tests/fixtures/runtime/import_udt_array_udf_method_returns.pine",
    "tests/fixtures/sema/supported_imported_user_type_array_udf_method_returns.pine",
    "tests/fixtures/sema/unsupported_imported_user_type_array_call_result_chaining.pine",
    "tests/fixtures/libraries/import_udt_array_return_lib.pine",
];

pub(super) const BUILTIN_ARRAY_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/builtin_array_call_result_reads.pine",
    "tests/fixtures/sema/supported_builtin_array_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_builtin_array_call_result_reads.pine",
];

const BUILTIN_ARRAY_CALL_RESULT_FEATURES: &[&str] = &[
    "array.new_float",
    "array.new_int",
    "array.new_bool",
    "array.new_string",
    "array.new_color",
    "array.new_line",
    "array.new_linefill",
    "array.new_polyline",
    "array.new_label",
    "array.new_box",
    "array.new_table",
    "array.new<chart.point>",
    "array.new<UDT>",
    "array.from",
    "array.size",
    "array.get",
    "array.first",
    "array.last",
    "array.copy",
    "array.includes",
    "array.every",
    "array.some",
    "array.indexof",
    "array.lastindexof",
    "array.binary_search",
    "array.binary_search_leftmost",
    "array.binary_search_rightmost",
    "array.abs",
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
    "array.sort_indices",
    "array.join",
    "array.slice",
    "array.concat",
    "array.clear",
    "array.reverse",
    "array.pop",
    "array.shift",
    "array.remove",
    "array.push",
    "array.unshift",
    "array.insert",
    "array.set",
    "array.fill",
    "array.sort",
    "array method calls",
    "expression-body functions",
    "multi-statement functions",
    "typed declarations",
    "array.*",
    "import",
    "user-defined types",
    "user-defined methods",
];

const UDT_IDENTITY_BUILTIN_ARRAY_CALL_RESULT_FEATURES: &[&str] = &[
    "array.new<UDT>",
    "array.from",
    "array.copy",
    "array.sort_indices",
    "array.includes",
    "array.indexof",
    "array.lastindexof",
    "array.join",
    "array.slice",
    "array.clear",
    "array.reverse",
    "array.pop",
    "array.shift",
    "array.remove",
    "array.push",
    "array.unshift",
    "array.insert",
    "array.set",
    "array.fill",
    "array.sort",
    "array.concat",
];

pub(super) const BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/builtin_namespace_array_call_result_reads.pine",
    "tests/fixtures/sema/supported_builtin_namespace_array_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine",
];

pub(super) const BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/builtin_namespace_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_builtin_namespace_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_builtin_namespace_matrix_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_copy_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_copy_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_copy_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_transpose_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_transpose_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_transpose_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_submatrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_submatrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_submatrix_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_kron_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_kron_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_kron_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_diff_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_diff_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_diff_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_pow_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_pow_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_pow_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_inv_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_inv_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_inv_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_pinv_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_pinv_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_pinv_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_eigenvectors_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_eigenvectors_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_eigenvectors_call_result_reads.pine",
    "tests/fixtures/runtime/bound_matrix_mult_call_result_reads.pine",
    "tests/fixtures/sema/supported_bound_matrix_mult_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_bound_matrix_mult_call_result_reads.pine",
    "tests/fixtures/runtime/local_udf_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_local_udf_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_local_udf_matrix_call_result_reads.pine",
    "tests/fixtures/runtime/user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/runtime/import_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/runtime/import_function_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_function_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_function_matrix_call_result_reads.pine",
    "tests/fixtures/libraries/import_udt_lib.pine",
];

const USER_METHOD_MATRIX_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/runtime/import_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine",
];

const IMPORTED_USER_METHOD_MATRIX_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/import_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine",
    "tests/fixtures/libraries/import_udt_lib.pine",
];

const IMPORTED_FUNCTION_MATRIX_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/import_function_matrix_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_function_matrix_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_function_matrix_call_result_reads.pine",
    "tests/fixtures/libraries/import_udt_lib.pine",
];

pub(super) const BUILTIN_MAP_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/builtin_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_builtin_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_builtin_map_call_result_reads.pine",
    "tests/fixtures/runtime/builtin_map_copy_call_result_reads.pine",
    "tests/fixtures/sema/supported_builtin_map_copy_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_builtin_map_copy_call_result_reads.pine",
    "tests/fixtures/runtime/local_udf_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_local_udf_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_local_udf_map_call_result_reads.pine",
    "tests/fixtures/runtime/local_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_local_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_local_user_method_map_call_result_reads.pine",
    "tests/fixtures/runtime/import_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine",
    "tests/fixtures/runtime/import_function_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_function_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_function_map_call_result_reads.pine",
];

const USER_METHOD_MAP_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/local_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_local_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_local_user_method_map_call_result_reads.pine",
    "tests/fixtures/runtime/import_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine",
];

const IMPORTED_USER_METHOD_MAP_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/import_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine",
    "tests/fixtures/libraries/import_udt_lib.pine",
];

const IMPORTED_FUNCTION_MAP_CALL_RESULT_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/import_function_map_call_result_reads.pine",
    "tests/fixtures/sema/supported_imported_function_map_call_result_reads.pine",
    "tests/fixtures/sema/unsupported_imported_function_map_call_result_reads.pine",
    "tests/fixtures/libraries/import_udt_lib.pine",
];

const BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FEATURES: &[&str] = &[
    "str.split",
    "ta.pivot_point_levels",
    "array.size",
    "array.get",
    "array.first",
    "array.last",
    "array.copy",
    "array.includes",
    "array.every",
    "array.some",
    "array.indexof",
    "array.lastindexof",
    "array.binary_search",
    "array.binary_search_leftmost",
    "array.binary_search_rightmost",
    "array.abs",
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
    "array.sort_indices",
    "array.join",
    "array.slice",
    "array.concat",
    "array.clear",
    "array.reverse",
    "array.pop",
    "array.shift",
    "array.remove",
    "array.push",
    "array.unshift",
    "array.insert",
    "array.set",
    "array.fill",
    "array.sort",
    "array method calls",
    "expression-body functions",
    "multi-statement functions",
    "typed declarations",
    "array.*",
    "map.*",
    "matrix.*",
];

const BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FEATURES: &[&str] = &[
    "expression-body functions",
    "multi-statement functions",
    "typed declarations",
    "matrix.*",
];

const BUILTIN_MAP_CALL_RESULT_FEATURES: &[&str] = &[
    "expression-body functions",
    "multi-statement functions",
    "typed declarations",
    "map.*",
];

pub(super) fn validate_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    validate_local_udt_array_call_return_fixture_paths(line_number, feature, fixtures)?;
    validate_imported_udt_array_call_return_fixture_paths(line_number, feature, fixtures)?;
    validate_builtin_array_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_udt_identity_builtin_array_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_udt_array_call_result_helper_fixture_paths(line_number, feature, fixtures)?;
    validate_builtin_namespace_array_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_builtin_namespace_matrix_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_user_method_matrix_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_imported_user_method_matrix_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_imported_function_matrix_call_result_fixture_paths(line_number, feature, fixtures)
}

pub(super) fn validate_map_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    validate_builtin_map_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_user_method_map_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_imported_user_method_map_call_result_fixture_paths(line_number, feature, fixtures)?;
    validate_imported_function_map_call_result_fixture_paths(line_number, feature, fixtures)
}

fn validate_local_udt_array_call_return_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !matches!(
        feature,
        "array.new<UDT>"
            | "array.from"
            | "array.*"
            | "expression-body functions"
            | "multi-statement functions"
            | "typed declarations"
            | "user-defined types"
            | "user-defined methods"
    ) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        LOCAL_UDT_ARRAY_CALL_RETURN_FIXTURES,
        "fixture-backed local UDF/user-method UDT array return and per-slot tuple-return identity",
    )
}

fn validate_imported_udt_array_call_return_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !matches!(
        feature,
        "array.new<UDT>"
            | "array.from"
            | "array.*"
            | "expression-body functions"
            | "multi-statement functions"
            | "typed declarations"
            | "import"
            | "user-defined types"
            | "user-defined methods"
    ) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        IMPORTED_UDT_ARRAY_CALL_RETURN_FIXTURES,
        "fixture-backed imported UDF/user-method UDT array return and per-slot tuple-return identity plus retained call-result-chaining boundaries",
    )
}

fn validate_udt_array_call_result_helper_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !matches!(
        feature,
        "array.size"
            | "array.get"
            | "array.first"
            | "array.last"
            | "array.copy"
            | "array.includes"
            | "array.every"
            | "array.some"
            | "array.indexof"
            | "array.lastindexof"
            | "array.binary_search"
            | "array.binary_search_leftmost"
            | "array.binary_search_rightmost"
            | "array.abs"
            | "array.min"
            | "array.max"
            | "array.sum"
            | "array.avg"
            | "array.range"
            | "array.median"
            | "array.mode"
            | "array.percentile_nearest_rank"
            | "array.percentile_linear_interpolation"
            | "array.percentrank"
            | "array.covariance"
            | "array.standardize"
            | "array.variance"
            | "array.stdev"
            | "array.sort_indices"
            | "array.join"
            | "array.slice"
            | "array.clear"
            | "array.reverse"
            | "array.pop"
            | "array.shift"
            | "array.remove"
            | "array.push"
            | "array.unshift"
            | "array.insert"
            | "array.set"
            | "array.fill"
            | "array.sort"
    ) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        UDT_ARRAY_CALL_RESULT_HELPER_FIXTURES,
        "fixture-backed qualified user-defined and unqualified local-UDF array/scalar-UDT call-result dispatch plus retained fail-closed boundaries",
    )
}

fn validate_builtin_array_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !BUILTIN_ARRAY_CALL_RESULT_FEATURES.contains(&feature) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        BUILTIN_ARRAY_CALL_RESULT_FIXTURES,
        "fixture-backed static-array builtin/template call-result size/get/first/last/copy/includes/every/some/indexof/lastindexof/binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev/sort_indices dispatch and retained producer/helper boundaries",
    )
}

fn validate_udt_identity_builtin_array_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !UDT_IDENTITY_BUILTIN_ARRAY_CALL_RESULT_FEATURES.contains(&feature) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        UDT_ARRAY_CALL_RESULT_HELPER_FIXTURES,
        "fixture-backed local/imported UDT identity through static-array builtin/template call-result dispatch",
    )
}

fn validate_builtin_namespace_array_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FEATURES.contains(&feature) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES,
        "fixture-backed non-array-namespace array-capable producer call-result size/get/first/last/copy/includes/every/some/indexof/lastindexof/binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev/sort_indices dispatch and retained result-type/helper boundaries",
    )
}

fn validate_builtin_namespace_matrix_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FEATURES.contains(&feature) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES,
        "fixture-backed exact matrix.new<float|int|bool|string|color> templates, namespace matrix.mult/matrix.copy/matrix.transpose/matrix.submatrix/matrix.kron/matrix.diff/matrix.pow/matrix.inv/matrix.pinv/matrix.eigenvectors results, bound matrix-receiver copy/transpose/submatrix/kron/diff/pow/inv/pinv/eigenvectors/matrix-valued-mult results, and concrete unqualified local-UDF, local/imported user-method, plus registered imported pure-function matrix results with rows/columns/elements_count/get/copy/row/col dispatch, terminal set/fill/reverse/reshape/add_row/add_col/swap_rows/swap_columns/remove_row/remove_col plus numeric-only sort mutation, numeric-only eigenvalues and terminal is_zero/is_binary/is_diagonal/is_identity/is_symmetric dispatch, all-kind terminal is_square dispatch, fresh element-kind-preserving row/column arrays and float eigenvalue arrays, plus retained result-type/helper/unregistered-function boundaries",
    )
}

fn validate_user_method_matrix_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "user-defined methods" {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        USER_METHOD_MATRIX_CALL_RESULT_FIXTURES,
        "fixture-backed concrete local/imported user-method matrix-result rows/columns/elements_count/get/copy/row/col plus numeric-only eigenvalues and terminal is_zero/is_binary/is_diagonal/is_identity/is_symmetric dispatch, all-kind terminal is_square dispatch, fresh row/column and float eigenvalue arrays, and retained helper/result-type/mutation boundaries",
    )
}

fn validate_imported_user_method_matrix_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "import" {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        IMPORTED_USER_METHOD_MATRIX_CALL_RESULT_FIXTURES,
        "fixture-backed imported user-method matrix-result rows/columns/elements_count/get/copy/row/col plus numeric-only eigenvalues and terminal is_zero/is_binary/is_diagonal/is_identity/is_symmetric dispatch, all-kind terminal is_square dispatch with fresh row/column and float eigenvalue arrays, dual-alias isolation, and retained helper/result-type/mutation boundaries",
    )
}

fn validate_imported_function_matrix_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "import" {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        IMPORTED_FUNCTION_MATRIX_CALL_RESULT_FIXTURES,
        "fixture-backed imported pure-function matrix-result rows/columns/elements_count/get/copy/row/col plus numeric-only eigenvalues and terminal is_zero/is_binary/is_diagonal/is_identity/is_symmetric dispatch, all-kind terminal is_square dispatch with fresh row/column and float eigenvalue arrays, dual-alias isolation, and retained helper/result-type/mutation boundaries",
    )
}

fn validate_builtin_map_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !BUILTIN_MAP_CALL_RESULT_FEATURES.contains(&feature) {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        BUILTIN_MAP_CALL_RESULT_FIXTURES,
        "fixture-backed exact scalar map.new template, namespace map.copy result, concrete local/imported user-function and user-method map results with the complete scalar map helper set including terminal put/clear/remove/put_all dispatch, fresh key/value-kind array reads, and retained template/terminal-reader boundaries",
    )
}

fn validate_user_method_map_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "user-defined methods" {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        USER_METHOD_MAP_CALL_RESULT_FIXTURES,
        "fixture-backed concrete local/imported user-method map-result complete scalar map helper dispatch including terminal put/clear/remove/put_all, fresh key/value-kind array reads, and retained template/terminal-reader boundaries",
    )
}

fn validate_imported_user_method_map_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "import" {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        IMPORTED_USER_METHOD_MAP_CALL_RESULT_FIXTURES,
        "fixture-backed imported user-method map-result complete scalar map helper dispatch including terminal put/clear/remove/put_all with fresh key/value-kind arrays, dual-alias isolation, and retained template/terminal-reader boundaries",
    )
}

fn validate_imported_function_map_call_result_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "import" {
        return Ok(());
    }

    require_fixtures(
        line_number,
        feature,
        fixtures,
        IMPORTED_FUNCTION_MAP_CALL_RESULT_FIXTURES,
        "fixture-backed imported pure-function map-result complete scalar map helper dispatch including terminal put/clear/remove/put_all with fresh key/value-kind arrays, dual-alias isolation, and retained template/terminal-reader boundaries",
    )
}

fn require_fixtures(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
    required: &[&str],
    reason: &str,
) -> Result<(), String> {
    for fixture in required {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `{feature}` must reference `{fixture}` for {reason}"
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "call_results_tests.rs"]
mod tests;
