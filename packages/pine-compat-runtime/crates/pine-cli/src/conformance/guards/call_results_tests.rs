use super::*;
use crate::conformance::try_conformance_entries_from_tsv;

#[test]
fn rejects_local_udt_array_return_rows_without_current_fixture_set() {
    let fixtures =
        &LOCAL_UDT_ARRAY_CALL_RETURN_FIXTURES[..LOCAL_UDT_ARRAY_CALL_RETURN_FIXTURES.len() - 1];
    let error = validate_fixture_paths(1, "expression-body functions", fixtures)
        .expect_err("missing local UDT array call-return fixture should fail");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_local_user_type_array_call_result_chaining.pine"
    ));
}

#[test]
fn import_row_requires_imported_udt_array_return_fixture_set() {
    let error = validate_fixture_paths(1, "import", &[])
        .expect_err("import row must retain the imported UDT array return fixture set");

    assert!(error.contains("tests/fixtures/runtime/import_udt_array_udf_method_returns.pine"));
}

#[test]
fn rejects_udt_array_return_rows_without_imported_call_return_library_fixture() {
    let fixtures = &IMPORTED_UDT_ARRAY_CALL_RETURN_FIXTURES
        [..IMPORTED_UDT_ARRAY_CALL_RETURN_FIXTURES.len() - 1];
    let error =
        validate_imported_udt_array_call_return_fixture_paths(1, "user-defined methods", fixtures)
            .expect_err("UDT array return rows must retain the imported return library");

    assert!(error.contains("tests/fixtures/libraries/import_udt_array_return_lib.pine"));
}

#[test]
fn rejects_udt_array_helper_rows_without_call_result_fixture_set() {
    let fixtures =
        &UDT_ARRAY_CALL_RESULT_HELPER_FIXTURES[..UDT_ARRAY_CALL_RESULT_HELPER_FIXTURES.len() - 1];
    let error = validate_udt_array_call_result_helper_fixture_paths(1, "array.abs", fixtures)
        .expect_err("UDT-array helper rows must retain the call-result fixture set");

    assert!(error.contains("tests/fixtures/libraries/import_udt_array_return_lib.pine"));
}

#[test]
fn rejects_builtin_array_result_rows_without_comprehensive_fixture_set() {
    let fixtures =
        &BUILTIN_ARRAY_CALL_RESULT_FIXTURES[..BUILTIN_ARRAY_CALL_RESULT_FIXTURES.len() - 1];
    let error = validate_builtin_array_call_result_fixture_paths(
        1,
        "array.binary_search_leftmost",
        fixtures,
    )
    .expect_err("builtin array-result rows must retain the comprehensive fixture set");

    assert!(error.contains("tests/fixtures/sema/unsupported_builtin_array_call_result_reads.pine"));
}

#[test]
fn rejects_udt_identity_builtin_array_result_rows_without_local_import_fixture_set() {
    let fixtures =
        &UDT_ARRAY_CALL_RESULT_HELPER_FIXTURES[..UDT_ARRAY_CALL_RESULT_HELPER_FIXTURES.len() - 1];
    let error = validate_udt_identity_builtin_array_call_result_fixture_paths(
        1,
        "array.lastindexof",
        fixtures,
    )
    .expect_err("UDT-preserving builtin array-result rows must retain local/import fixtures");

    assert!(error.contains("tests/fixtures/libraries/import_udt_array_return_lib.pine"));
}

#[test]
fn rejects_namespace_array_result_row_without_negative_fixture() {
    let fixtures = &BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES
        [..BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.len() - 1];
    let tsv = format!(
        "feature\tstatus\tnotes\tfixtures\nstr.split\tsupported\tdirect array call-result reads\t{}\n",
        fixtures.join(";")
    );
    let error = try_conformance_entries_from_tsv(&tsv)
        .expect_err("namespace array-result rows must retain the negative boundary fixture");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine"
    ));
}

#[test]
fn rejects_namespace_array_result_row_without_runtime_fixture() {
    let fixtures = &BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES[1..];
    let tsv = format!(
        "feature\tstatus\tnotes\tfixtures\nmatrix.*\tpartial\tdirect array call-result reads\t{}\n",
        fixtures.join(";")
    );
    let error = try_conformance_entries_from_tsv(&tsv)
        .expect_err("namespace array-result rows must retain runtime evidence");

    assert!(
        error.contains("tests/fixtures/runtime/builtin_namespace_array_call_result_reads.pine")
    );
}

#[test]
fn rejects_array_includes_row_without_namespace_result_fixture_set() {
    let fixtures = &BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES
        [..BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.len() - 1];
    let error =
        validate_builtin_namespace_array_call_result_fixture_paths(1, "array.includes", fixtures)
            .expect_err("array.includes must retain cross-namespace call-result evidence");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine"
    ));
}

#[test]
fn rejects_array_indexof_row_without_namespace_result_fixture_set() {
    let fixtures = &BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES
        [..BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.len() - 1];
    let error =
        validate_builtin_namespace_array_call_result_fixture_paths(1, "array.indexof", fixtures)
            .expect_err("array.indexof must retain cross-namespace call-result evidence");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine"
    ));
}

#[test]
fn rejects_array_lastindexof_row_without_namespace_result_fixture_set() {
    let fixtures = &BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES
        [..BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.len() - 1];
    let error = validate_builtin_namespace_array_call_result_fixture_paths(
        1,
        "array.lastindexof",
        fixtures,
    )
    .expect_err("array.lastindexof must retain cross-namespace call-result evidence");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine"
    ));
}

#[test]
fn rejects_array_binary_search_row_without_namespace_result_fixture_set() {
    let fixtures = &BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES
        [..BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.len() - 1];
    let error = validate_builtin_namespace_array_call_result_fixture_paths(
        1,
        "array.binary_search",
        fixtures,
    )
    .expect_err("array.binary_search must retain cross-namespace call-result evidence");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine"
    ));
}

#[test]
fn rejects_extended_array_helper_rows_without_namespace_result_fixture_set() {
    let fixtures = &BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES
        [..BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.len() - 1];
    for feature in [
        "array.every",
        "array.some",
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
        "array.sort",
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
    ] {
        let error =
            validate_builtin_namespace_array_call_result_fixture_paths(1, feature, fixtures)
                .expect_err("extended array-helper rows must retain cross-namespace evidence");
        assert!(error.contains(
            "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine"
        ));
    }
}

#[test]
fn rejects_namespace_matrix_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture
                != "tests/fixtures/sema/unsupported_builtin_namespace_matrix_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("namespace matrix-result rows must retain the negative boundary fixture");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_builtin_namespace_matrix_call_result_reads.pine"
    ));
}

#[test]
fn rejects_namespace_matrix_result_row_without_runtime_fixture() {
    let fixtures = &BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES[1..];
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", fixtures)
            .expect_err("namespace matrix-result rows must retain runtime evidence");

    assert!(
        error.contains("tests/fixtures/runtime/builtin_namespace_matrix_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_copy_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_bound_matrix_copy_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.copy result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_bound_matrix_copy_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_copy_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_copy_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.copy result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_copy_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_transpose_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture
                != "tests/fixtures/sema/unsupported_bound_matrix_transpose_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err(
                "bound matrix.transpose result rows must retain the negative boundary fixture",
            );

    assert!(
        error.contains(
            "tests/fixtures/sema/unsupported_bound_matrix_transpose_call_result_reads.pine"
        )
    );
}

#[test]
fn rejects_bound_matrix_transpose_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_transpose_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.transpose result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_transpose_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_submatrix_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture
                != "tests/fixtures/sema/unsupported_bound_matrix_submatrix_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err(
                "bound matrix.submatrix result rows must retain the negative boundary fixture",
            );

    assert!(
        error.contains(
            "tests/fixtures/sema/unsupported_bound_matrix_submatrix_call_result_reads.pine"
        )
    );
}

#[test]
fn rejects_bound_matrix_submatrix_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_submatrix_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.submatrix result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_submatrix_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_kron_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_bound_matrix_kron_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.kron result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_bound_matrix_kron_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_kron_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_kron_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.kron result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_kron_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_diff_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_bound_matrix_diff_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.diff result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_bound_matrix_diff_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_diff_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_diff_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.diff result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_diff_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_pow_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_bound_matrix_pow_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.pow result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_bound_matrix_pow_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_pow_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_pow_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.pow result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_pow_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_inv_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_bound_matrix_inv_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.inv result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_bound_matrix_inv_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_inv_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_inv_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.inv result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_inv_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_pinv_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_bound_matrix_pinv_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.pinv result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_bound_matrix_pinv_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_pinv_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_pinv_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.pinv result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_pinv_call_result_reads.pine"));
}

#[test]
fn rejects_bound_matrix_eigenvectors_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
            .iter()
            .copied()
            .filter(|fixture| {
                *fixture
                    != "tests/fixtures/sema/unsupported_bound_matrix_eigenvectors_call_result_reads.pine"
            })
            .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err(
                "bound matrix.eigenvectors result rows must retain the negative boundary fixture",
            );

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_bound_matrix_eigenvectors_call_result_reads.pine"
    ));
}

#[test]
fn rejects_bound_matrix_eigenvectors_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_eigenvectors_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.eigenvectors result rows must retain runtime evidence");

    assert!(
        error.contains("tests/fixtures/runtime/bound_matrix_eigenvectors_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_mult_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_bound_matrix_mult_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.mult result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_bound_matrix_mult_call_result_reads.pine")
    );
}

#[test]
fn rejects_bound_matrix_mult_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/bound_matrix_mult_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("bound matrix.mult result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/bound_matrix_mult_call_result_reads.pine"));
}

#[test]
fn rejects_local_udf_matrix_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_local_udf_matrix_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("local UDF matrix-result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_local_udf_matrix_call_result_reads.pine")
    );
}

#[test]
fn rejects_local_udf_matrix_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/local_udf_matrix_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_builtin_namespace_matrix_call_result_fixture_paths(1, "matrix.*", &fixtures)
            .expect_err("local UDF matrix-result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/local_udf_matrix_call_result_reads.pine"));
}

#[test]
fn rejects_user_method_matrix_result_row_without_local_runtime_fixture() {
    let fixtures: Vec<_> = USER_METHOD_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/user_method_matrix_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_user_method_matrix_call_result_fixture_paths(1, "user-defined methods", &fixtures)
            .expect_err("user-method rows must retain local matrix runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/user_method_matrix_call_result_reads.pine"));
}

#[test]
fn rejects_user_method_matrix_result_row_without_imported_negative_fixture() {
    let fixtures: Vec<_> = USER_METHOD_MATRIX_CALL_RESULT_FIXTURES
            .iter()
            .copied()
            .filter(|fixture| {
                *fixture
                    != "tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine"
            })
            .collect();
    let error =
        validate_user_method_matrix_call_result_fixture_paths(1, "user-defined methods", &fixtures)
            .expect_err("user-method rows must retain imported matrix negative evidence");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine"
    ));
}

#[test]
fn rejects_import_row_without_imported_user_method_matrix_library_fixture() {
    let fixtures = &IMPORTED_USER_METHOD_MATRIX_CALL_RESULT_FIXTURES
        [..IMPORTED_USER_METHOD_MATRIX_CALL_RESULT_FIXTURES.len() - 1];
    let error =
        validate_imported_user_method_matrix_call_result_fixture_paths(1, "import", fixtures)
            .expect_err("import rows must retain the imported matrix method library");

    assert!(error.contains("tests/fixtures/libraries/import_udt_lib.pine"));
}

#[test]
fn rejects_import_row_without_imported_function_matrix_runtime_fixture() {
    let fixtures: Vec<_> = IMPORTED_FUNCTION_MATRIX_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/import_function_matrix_call_result_reads.pine"
        })
        .collect();
    let error = validate_imported_function_matrix_call_result_fixture_paths(1, "import", &fixtures)
        .expect_err("import rows must retain imported function matrix runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/import_function_matrix_call_result_reads.pine"));
}

#[test]
fn rejects_map_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_builtin_map_call_result_reads.pine"
        })
        .collect();
    let error = validate_builtin_map_call_result_fixture_paths(1, "map.*", &fixtures)
        .expect_err("map-result rows must retain the negative boundary fixture");

    assert!(error.contains("tests/fixtures/sema/unsupported_builtin_map_call_result_reads.pine"));
}

#[test]
fn rejects_map_result_row_without_runtime_fixture() {
    let fixtures = &BUILTIN_MAP_CALL_RESULT_FIXTURES[1..];
    let error = validate_builtin_map_call_result_fixture_paths(1, "map.*", fixtures)
        .expect_err("map-result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/builtin_map_call_result_reads.pine"));
}

#[test]
fn rejects_map_copy_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_builtin_map_copy_call_result_reads.pine"
        })
        .collect();
    let error = validate_builtin_map_call_result_fixture_paths(1, "map.*", &fixtures)
        .expect_err("map.copy result rows must retain the negative boundary fixture");

    assert!(
        error.contains("tests/fixtures/sema/unsupported_builtin_map_copy_call_result_reads.pine")
    );
}

#[test]
fn rejects_map_copy_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/builtin_map_copy_call_result_reads.pine"
        })
        .collect();
    let error = validate_builtin_map_call_result_fixture_paths(1, "map.*", &fixtures)
        .expect_err("map.copy result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/builtin_map_copy_call_result_reads.pine"));
}

#[test]
fn rejects_local_udf_map_result_row_without_negative_fixture() {
    let fixtures: Vec<_> = BUILTIN_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/sema/unsupported_local_udf_map_call_result_reads.pine"
        })
        .collect();
    let error = validate_builtin_map_call_result_fixture_paths(1, "map.*", &fixtures)
        .expect_err("local UDF map-result rows must retain the negative boundary fixture");

    assert!(error.contains("tests/fixtures/sema/unsupported_local_udf_map_call_result_reads.pine"));
}

#[test]
fn rejects_local_udf_map_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| *fixture != "tests/fixtures/runtime/local_udf_map_call_result_reads.pine")
        .collect();
    let error = validate_builtin_map_call_result_fixture_paths(1, "map.*", &fixtures)
        .expect_err("local UDF map-result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/local_udf_map_call_result_reads.pine"));
}

#[test]
fn rejects_local_user_method_map_result_row_without_runtime_fixture() {
    let fixtures: Vec<_> = BUILTIN_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/local_user_method_map_call_result_reads.pine"
        })
        .collect();
    let error = validate_builtin_map_call_result_fixture_paths(1, "map.*", &fixtures)
        .expect_err("local user-method map-result rows must retain runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/local_user_method_map_call_result_reads.pine"));
}

#[test]
fn rejects_user_method_map_result_row_without_imported_negative_fixture() {
    let fixtures: Vec<_> = USER_METHOD_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture
                != "tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine"
        })
        .collect();
    let error =
        validate_user_method_map_call_result_fixture_paths(1, "user-defined methods", &fixtures)
            .expect_err("user-method rows must retain imported-method negative boundaries");

    assert!(error.contains(
        "tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine"
    ));
}

#[test]
fn rejects_import_row_without_imported_user_method_map_runtime_fixture() {
    let fixtures: Vec<_> = IMPORTED_USER_METHOD_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/import_user_method_map_call_result_reads.pine"
        })
        .collect();
    let error = validate_imported_user_method_map_call_result_fixture_paths(1, "import", &fixtures)
        .expect_err("import rows must retain imported user-method map runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/import_user_method_map_call_result_reads.pine"));
}

#[test]
fn rejects_import_row_without_imported_function_map_runtime_fixture() {
    let fixtures: Vec<_> = IMPORTED_FUNCTION_MAP_CALL_RESULT_FIXTURES
        .iter()
        .copied()
        .filter(|fixture| {
            *fixture != "tests/fixtures/runtime/import_function_map_call_result_reads.pine"
        })
        .collect();
    let error = validate_imported_function_map_call_result_fixture_paths(1, "import", &fixtures)
        .expect_err("import rows must retain imported function map runtime evidence");

    assert!(error.contains("tests/fixtures/runtime/import_function_map_call_result_reads.pine"));
}
