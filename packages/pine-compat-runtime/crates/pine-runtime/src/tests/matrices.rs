use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use crate::builtins::matrices::MatrixElementKind;

use super::*;

fn runtime_program() -> pine_ir::HirProgram {
    let source = SourceFile::new("test.pine", "indicator(\"matrix runtime scaffold\")\n");
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    analysis.hir.expect("HIR")
}

#[test]
fn allocates_rectangular_matrix_storage() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let value = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(1.5))
        .expect("matrix allocation");

    let PineValue::Matrix(id) = value else {
        panic!("expected matrix id, got {value:?}");
    };
    assert_eq!(runtime.matrix_shape(id), Some((2, 3)));
    assert_eq!(runtime.matrix_elements_count(id), Some(6));
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 1, 2)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(1.5))
    );
    let profile = runtime.matrix_store_profile();
    assert_eq!(profile.slots, 1);
    assert_eq!(profile.cells, 6);
    assert!(profile.capacity >= profile.slots);
    assert!(profile.cell_capacity >= profile.cells);
}

#[test]
fn allocates_and_copies_int_matrix_storage() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Int, 2, 3, PineValue::Int(7))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    assert_eq!(runtime.matrix_shape(id), Some((2, 3)));
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 1, 2)
            .expect("matrix get should succeed"),
        Some(PineValue::Int(7))
    );

    let PineValue::Matrix(copy_id) = runtime.copy_matrix(id) else {
        panic!("expected copy id");
    };
    assert_eq!(
        runtime
            .matrix_get_cloned(copy_id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Int(7))
    );

    let PineValue::Matrix(transposed_id) = runtime.matrix_transpose(id) else {
        panic!("expected transpose id");
    };
    assert_eq!(runtime.matrix_shape(transposed_id), Some((3, 2)));
    assert_eq!(
        runtime
            .matrix_get_cloned(transposed_id, 2, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Int(7))
    );

    let PineValue::Matrix(slice_id) = runtime
        .matrix_submatrix(id, 0, 1, 1, 3)
        .expect("submatrix should succeed")
    else {
        panic!("expected submatrix id");
    };
    assert_eq!(runtime.matrix_shape(slice_id), Some((1, 2)));
    assert_eq!(
        runtime
            .matrix_get_cloned(slice_id, 0, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Int(7))
    );
}

#[test]
fn concatenates_matrix_rows_in_place_and_preserves_source() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(target_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Float(1.0))
        .expect("target matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(target_id, 0, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    let PineValue::Matrix(source_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(3.0))
        .expect("source matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(source_id, 0, 1, PineValue::Float(4.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(source_id, 1, 0, PineValue::Float(5.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(source_id, 1, 1, PineValue::Float(6.0))
        .expect("matrix set should succeed");

    assert_eq!(
        runtime
            .matrix_concat(target_id, source_id)
            .expect("matrix concat should succeed"),
        Some(target_id)
    );
    assert_eq!(runtime.matrix_shape(target_id), Some((3, 2)));
    assert_eq!(runtime.matrix_shape(source_id), Some((2, 2)));
    for (row, column, expected) in [
        (0, 0, 1.0),
        (0, 1, 2.0),
        (1, 0, 3.0),
        (1, 1, 4.0),
        (2, 0, 5.0),
        (2, 1, 6.0),
    ] {
        assert_eq!(
            runtime
                .matrix_get_cloned(target_id, row, column)
                .expect("matrix get should succeed"),
            Some(PineValue::Float(expected))
        );
    }
    assert_eq!(
        runtime
            .matrix_get_cloned(source_id, 1, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(6.0))
    );

    assert_eq!(
        runtime
            .matrix_concat(target_id, target_id)
            .expect("self concat should succeed"),
        Some(target_id)
    );
    assert_eq!(runtime.matrix_shape(target_id), Some((6, 2)));
    assert_eq!(
        runtime
            .matrix_get_cloned(target_id, 5, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(6.0))
    );

    let PineValue::Matrix(zero_target_id) = runtime
        .new_matrix(MatrixElementKind::Bool, 2, 0, PineValue::Na)
        .expect("zero-column target allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(zero_source_id) = runtime
        .new_matrix(MatrixElementKind::Bool, 3, 0, PineValue::Na)
        .expect("zero-column source allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime
            .matrix_concat(zero_target_id, zero_source_id)
            .expect("zero-column concat should succeed"),
        Some(zero_target_id)
    );
    assert_eq!(runtime.matrix_shape(zero_target_id), Some((5, 0)));

    let PineValue::Matrix(mismatched_columns_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 3, PineValue::Float(0.0))
        .expect("mismatched-column matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let error = runtime
        .matrix_concat(source_id, mismatched_columns_id)
        .expect_err("mismatched columns should fail");
    assert_eq!(
        error.message,
        "matrix.concat column count 2 must match source column count 3"
    );
    assert_eq!(runtime.matrix_shape(source_id), Some((2, 2)));

    let PineValue::Matrix(int_id) = runtime
        .new_matrix(MatrixElementKind::Int, 1, 2, PineValue::Int(1))
        .expect("integer matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime
            .matrix_concat(target_id, int_id)
            .expect("kind mismatch should not be a runtime error"),
        None
    );
    assert_eq!(runtime.matrix_shape(target_id), Some((6, 2)));
    assert_eq!(
        runtime
            .matrix_concat(u32::MAX, source_id)
            .expect("missing target should not be a runtime error"),
        None
    );
    assert_eq!(
        runtime
            .matrix_concat(target_id, u32::MAX)
            .expect("missing source should not be a runtime error"),
        None
    );

    let PineValue::Matrix(large_target_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 50_001, PineValue::Float(0.0))
        .expect("large target allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(large_source_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 50_001, PineValue::Float(0.0))
        .expect("large source allocation")
    else {
        panic!("expected matrix id");
    };
    let error = runtime
        .matrix_concat(large_target_id, large_source_id)
        .expect_err("matrix cell limit should fail");
    assert_eq!(error.message, "matrix cell count cannot exceed 100000");
    assert_eq!(runtime.matrix_shape(large_target_id), Some((1, 50_001)));
}

#[test]
fn reports_square_matrix_shape() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(square_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("square matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(rectangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("rectangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_square_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    assert_eq!(runtime.matrix_is_square(square_id), Some(true));
    assert_eq!(runtime.matrix_is_square(rectangular_id), Some(false));
    assert_eq!(runtime.matrix_is_square(empty_square_id), Some(true));
}

#[test]
fn reports_zero_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(zero_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("zero matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_zero_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("non-zero matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 1, PineValue::Na)
        .expect("na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(non_zero_id, 1, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_zero(zero_id), Some(true));
    assert_eq!(runtime.matrix_is_zero(non_zero_id), Some(false));
    assert_eq!(runtime.matrix_is_zero(na_id), Some(false));
    assert_eq!(runtime.matrix_is_zero(empty_id), Some(true));
}

#[test]
fn reports_binary_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(binary_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("binary matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_binary_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(1.0))
        .expect("non-binary matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 1, PineValue::Na)
        .expect("na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(binary_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_binary_id, 1, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_binary(binary_id), Some(true));
    assert_eq!(runtime.matrix_is_binary(non_binary_id), Some(false));
    assert_eq!(runtime.matrix_is_binary(na_id), Some(false));
    assert_eq!(runtime.matrix_is_binary(empty_id), Some(true));
}

#[test]
fn reports_diagonal_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(square_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("square matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(rectangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("rectangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_diagonal_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("non-diagonal matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(off_diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("off-diagonal na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("diagonal na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(square_id, 0, 0, PineValue::Float(5.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(square_id, 1, 1, PineValue::Float(7.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(rectangular_id, 0, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(rectangular_id, 1, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_diagonal_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(off_diagonal_na_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_na_id, 0, 0, PineValue::Na)
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_diagonal(square_id), Some(true));
    assert_eq!(runtime.matrix_is_diagonal(rectangular_id), Some(true));
    assert_eq!(runtime.matrix_is_diagonal(non_diagonal_id), Some(false));
    assert_eq!(runtime.matrix_is_diagonal(off_diagonal_na_id), Some(false));
    assert_eq!(runtime.matrix_is_diagonal(diagonal_na_id), Some(true));
    assert_eq!(runtime.matrix_is_diagonal(empty_id), Some(true));
}

#[test]
fn reports_antidiagonal_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(antidiagonal_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Float(0.0))
        .expect("antidiagonal matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(rectangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("rectangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_antidiagonal_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Float(0.0))
        .expect("non-antidiagonal matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(outside_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("outside-na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("diagonal-na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(int_id) = runtime
        .new_matrix(MatrixElementKind::Int, 2, 2, PineValue::Int(0))
        .expect("integer antidiagonal matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(antidiagonal_id, 0, 2, PineValue::Float(5.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(antidiagonal_id, 1, 1, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(antidiagonal_id, 2, 0, PineValue::Float(7.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_antidiagonal_id, 0, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(outside_na_id, 0, 0, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_na_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(int_id, 0, 1, PineValue::Int(1))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(int_id, 1, 0, PineValue::Int(2))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_antidiagonal(antidiagonal_id), Some(true));
    assert_eq!(runtime.matrix_is_antidiagonal(rectangular_id), Some(false));
    assert_eq!(
        runtime.matrix_is_antidiagonal(non_antidiagonal_id),
        Some(false)
    );
    assert_eq!(runtime.matrix_is_antidiagonal(outside_na_id), Some(false));
    assert_eq!(runtime.matrix_is_antidiagonal(diagonal_na_id), Some(true));
    assert_eq!(runtime.matrix_is_antidiagonal(int_id), Some(true));
    assert_eq!(runtime.matrix_is_antidiagonal(empty_id), Some(true));
    assert_eq!(runtime.matrix_is_antidiagonal(u32::MAX), None);
}

#[test]
fn reports_triangular_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(upper_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Float(0.0))
        .expect("upper-triangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(lower_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Float(0.0))
        .expect("lower-triangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_triangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("non-triangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(rectangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("rectangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("diagonal-na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(one_side_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("one-side-na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(two_side_invalid_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("two-side-invalid matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(int_id) = runtime
        .new_matrix(MatrixElementKind::Int, 2, 2, PineValue::Int(0))
        .expect("integer triangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(upper_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(upper_id, 0, 2, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(upper_id, 1, 2, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(lower_id, 1, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(lower_id, 2, 0, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(lower_id, 2, 1, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_triangular_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_triangular_id, 1, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_na_id, 0, 0, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(one_side_na_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(two_side_invalid_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(two_side_invalid_id, 1, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(int_id, 1, 0, PineValue::Int(2))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_triangular(upper_id), Some(true));
    assert_eq!(runtime.matrix_is_triangular(lower_id), Some(true));
    assert_eq!(runtime.matrix_is_triangular(non_triangular_id), Some(false));
    assert_eq!(runtime.matrix_is_triangular(rectangular_id), Some(false));
    assert_eq!(runtime.matrix_is_triangular(diagonal_na_id), Some(true));
    assert_eq!(runtime.matrix_is_triangular(one_side_na_id), Some(true));
    assert_eq!(
        runtime.matrix_is_triangular(two_side_invalid_id),
        Some(false)
    );
    assert_eq!(runtime.matrix_is_triangular(int_id), Some(true));
    assert_eq!(runtime.matrix_is_triangular(empty_id), Some(true));
    assert_eq!(runtime.matrix_is_triangular(u32::MAX), None);
}

#[test]
fn reports_identity_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(identity_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("identity matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(rectangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("rectangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(diagonal_two_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("diagonal-two matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(off_diagonal_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("off-diagonal matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("diagonal na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(off_diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("off-diagonal na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    for id in [
        identity_id,
        rectangular_id,
        diagonal_two_id,
        off_diagonal_id,
        diagonal_na_id,
        off_diagonal_na_id,
    ] {
        runtime
            .matrix_set_value(id, 0, 0, PineValue::Float(1.0))
            .expect("matrix set should succeed");
        runtime
            .matrix_set_value(id, 1, 1, PineValue::Float(1.0))
            .expect("matrix set should succeed");
    }
    runtime
        .matrix_set_value(diagonal_two_id, 1, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(off_diagonal_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_na_id, 0, 0, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(off_diagonal_na_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_identity(identity_id), Some(true));
    assert_eq!(runtime.matrix_is_identity(rectangular_id), Some(false));
    assert_eq!(runtime.matrix_is_identity(diagonal_two_id), Some(false));
    assert_eq!(runtime.matrix_is_identity(off_diagonal_id), Some(false));
    assert_eq!(runtime.matrix_is_identity(diagonal_na_id), Some(false));
    assert_eq!(runtime.matrix_is_identity(off_diagonal_na_id), Some(false));
    assert_eq!(runtime.matrix_is_identity(empty_id), Some(true));
}

#[test]
fn reports_symmetric_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(symmetric_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Float(0.0))
        .expect("symmetric matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(rectangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("rectangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_symmetric_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("non-symmetric matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("diagonal na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(mirror_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("mirror na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(symmetric_id, 0, 2, PineValue::Float(4.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(symmetric_id, 2, 0, PineValue::Float(4.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_symmetric_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_symmetric_id, 1, 0, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_na_id, 0, 0, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(mirror_na_id, 0, 1, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(mirror_na_id, 1, 0, PineValue::Na)
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_symmetric(symmetric_id), Some(true));
    assert_eq!(runtime.matrix_is_symmetric(rectangular_id), Some(false));
    assert_eq!(runtime.matrix_is_symmetric(non_symmetric_id), Some(false));
    assert_eq!(runtime.matrix_is_symmetric(diagonal_na_id), Some(false));
    assert_eq!(runtime.matrix_is_symmetric(mirror_na_id), Some(false));
    assert_eq!(runtime.matrix_is_symmetric(empty_id), Some(true));
}

#[test]
fn reports_antisymmetric_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(antisymmetric_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Float(0.0))
        .expect("antisymmetric matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(rectangular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("rectangular matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_antisymmetric_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("non-antisymmetric matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(non_zero_diagonal_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("non-zero diagonal matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(diagonal_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("diagonal na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(mirror_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("mirror na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(antisymmetric_id, 0, 2, PineValue::Float(4.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(antisymmetric_id, 2, 0, PineValue::Float(-4.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_antisymmetric_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_antisymmetric_id, 1, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(non_zero_diagonal_id, 0, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_na_id, 0, 0, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(mirror_na_id, 0, 1, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(mirror_na_id, 1, 0, PineValue::Na)
        .expect("matrix set should succeed");

    assert_eq!(
        runtime.matrix_is_antisymmetric(antisymmetric_id),
        Some(true)
    );
    assert_eq!(runtime.matrix_is_antisymmetric(rectangular_id), Some(false));
    assert_eq!(
        runtime.matrix_is_antisymmetric(non_antisymmetric_id),
        Some(false)
    );
    assert_eq!(
        runtime.matrix_is_antisymmetric(non_zero_diagonal_id),
        Some(false)
    );
    assert_eq!(runtime.matrix_is_antisymmetric(diagonal_na_id), Some(false));
    assert_eq!(runtime.matrix_is_antisymmetric(mirror_na_id), Some(false));
    assert_eq!(runtime.matrix_is_antisymmetric(empty_id), Some(true));
}

#[test]
fn reports_stochastic_matrix_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(row_stochastic_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("row-stochastic matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(column_stochastic_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 2, PineValue::Float(0.0))
        .expect("column-stochastic matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(negative_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Float(0.0))
        .expect("negative matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(bad_sum_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.25))
        .expect("bad-sum matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 1, PineValue::Na)
        .expect("na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(row_stochastic_id, 0, 0, PineValue::Float(0.25))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(row_stochastic_id, 0, 1, PineValue::Float(0.75))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(row_stochastic_id, 1, 2, PineValue::Float(1.0))
        .expect("matrix set should succeed");

    runtime
        .matrix_set_value(column_stochastic_id, 0, 0, PineValue::Float(0.5))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(column_stochastic_id, 1, 0, PineValue::Float(0.5))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(column_stochastic_id, 1, 1, PineValue::Float(0.25))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(column_stochastic_id, 2, 1, PineValue::Float(0.75))
        .expect("matrix set should succeed");

    runtime
        .matrix_set_value(negative_id, 0, 0, PineValue::Float(1.25))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(negative_id, 0, 1, PineValue::Float(-0.25))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_is_stochastic(row_stochastic_id), Some(true));
    assert_eq!(
        runtime.matrix_is_stochastic(column_stochastic_id),
        Some(true)
    );
    assert_eq!(runtime.matrix_is_stochastic(negative_id), Some(false));
    assert_eq!(runtime.matrix_is_stochastic(bad_sum_id), Some(false));
    assert_eq!(runtime.matrix_is_stochastic(na_id), Some(false));
    assert_eq!(runtime.matrix_is_stochastic(empty_id), Some(false));
}

#[test]
fn writes_matrix_cells_without_changing_shape() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Int, 2, 2, PineValue::Int(0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(id, 1, 0, PineValue::Int(42))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((2, 2)));
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 1, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Int(42))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Int(0))
    );
}

#[test]
fn fills_matrix_cells_without_changing_shape() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime.matrix_fill_value(id, PineValue::Float(7.5));

    assert_eq!(runtime.matrix_shape(id), Some((2, 2)));
    for row in 0..2 {
        for column in 0..2 {
            assert_eq!(
                runtime
                    .matrix_get_cloned(id, row, column)
                    .expect("matrix get should succeed"),
                Some(PineValue::Float(7.5))
            );
        }
    }
}

#[test]
fn summarizes_numeric_matrix_cells_and_ignores_na() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(id, 0, 0, PineValue::Float(1.5))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(id, 1, 1, PineValue::Int(2))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_sum(id), Some(PineValue::Float(3.5)));
    assert_eq!(runtime.matrix_avg(id), Some(PineValue::Float(1.75)));
    assert_eq!(runtime.matrix_min(id), Some(PineValue::Float(1.5)));
    assert_eq!(runtime.matrix_max(id), Some(PineValue::Float(2.0)));
    assert_eq!(runtime.matrix_mode(id), None);

    runtime
        .matrix_set_value(id, 0, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    assert_eq!(runtime.matrix_mode(id), Some(PineValue::Float(2.0)));

    runtime
        .matrix_set_value(id, 1, 0, PineValue::Float(1.5))
        .expect("matrix set should succeed");
    assert_eq!(
        runtime.matrix_mode(id),
        Some(PineValue::Float(1.5)),
        "equal-frequency mode ties should select the smaller value"
    );

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(runtime.matrix_sum(empty_id), None);
    assert_eq!(runtime.matrix_avg(empty_id), None);
    assert_eq!(runtime.matrix_min(empty_id), None);
    assert_eq!(runtime.matrix_max(empty_id), None);
    assert_eq!(runtime.matrix_mode(empty_id), None);
}

#[test]
fn calculates_matrix_medians_by_element_kind_and_ignores_na() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(float_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("float matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (column, value) in (0_i64..).zip([4.0, 1.0, 3.0]) {
        runtime
            .matrix_set_value(float_id, 0, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }
    runtime
        .matrix_set_value(float_id, 1, 0, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    assert_eq!(runtime.matrix_median(float_id), Some(PineValue::Float(2.5)));

    let PineValue::Matrix(int_positive_id) = runtime
        .new_matrix(MatrixElementKind::Int, 1, 2, PineValue::Na)
        .expect("positive integer matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(int_positive_id, 0, 0, PineValue::Int(1))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(int_positive_id, 0, 1, PineValue::Int(2))
        .expect("matrix set should succeed");
    assert_eq!(
        runtime.matrix_median(int_positive_id),
        Some(PineValue::Int(1)),
        "positive integer midpoint averages should truncate toward zero"
    );

    let PineValue::Matrix(int_negative_id) = runtime
        .new_matrix(MatrixElementKind::Int, 1, 2, PineValue::Na)
        .expect("negative integer matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(int_negative_id, 0, 0, PineValue::Int(-2))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(int_negative_id, 0, 1, PineValue::Int(-1))
        .expect("matrix set should succeed");
    assert_eq!(
        runtime.matrix_median(int_negative_id),
        Some(PineValue::Int(-1)),
        "negative integer midpoint averages should truncate toward zero"
    );

    let PineValue::Matrix(int_odd_id) = runtime
        .new_matrix(MatrixElementKind::Int, 1, 3, PineValue::Na)
        .expect("odd integer matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (column, value) in (0_i64..).zip([5, 1, 3]) {
        runtime
            .matrix_set_value(int_odd_id, 0, column, PineValue::Int(value))
            .expect("matrix set should succeed");
    }
    assert_eq!(runtime.matrix_median(int_odd_id), Some(PineValue::Int(3)));

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(all_na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Na)
        .expect("all-na matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(runtime.matrix_median(empty_id), None);
    assert_eq!(runtime.matrix_median(all_na_id), None);
    assert_eq!(runtime.matrix_median(u32::MAX), None);
}

#[test]
fn traces_numeric_matrix_diagonal_and_ignores_na() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(square_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    runtime
        .matrix_set_value(square_id, 0, 0, PineValue::Float(1.5))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(square_id, 1, 1, PineValue::Int(2))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(square_id, 2, 2, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(square_id, 0, 2, PineValue::Float(100.0))
        .expect("matrix set should succeed");

    assert_eq!(runtime.matrix_trace(square_id), Some(PineValue::Float(6.5)));

    let PineValue::Matrix(rectangle_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("rectangle matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(rectangle_id, 0, 0, PineValue::Float(4.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(rectangle_id, 1, 1, PineValue::Float(5.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(rectangle_id, 1, 2, PineValue::Float(6.0))
        .expect("matrix set should succeed");

    assert_eq!(
        runtime.matrix_trace(rectangle_id),
        Some(PineValue::Float(9.0))
    );

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(runtime.matrix_trace(empty_id), None);
}

#[test]
fn computes_square_matrix_determinants() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_det(empty_id).expect("determinant"),
        Some(PineValue::Float(1.0))
    );

    let PineValue::Matrix(one_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 1, PineValue::Float(7.5))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_det(one_id).expect("determinant"),
        Some(PineValue::Float(7.5))
    );

    let PineValue::Matrix(two_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 1.0), (0, 1, 2.0), (1, 0, 3.0), (1, 1, 4.0)] {
        runtime
            .matrix_set_value(two_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }
    assert_eq!(
        runtime.matrix_det(two_id).expect("determinant"),
        Some(PineValue::Float(-2.0))
    );

    let PineValue::Matrix(three_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [
        (0, 0, 0.0),
        (0, 1, 2.0),
        (0, 2, 1.0),
        (1, 0, 3.0),
        (1, 1, 0.0),
        (1, 2, 0.0),
        (2, 0, 5.0),
        (2, 1, 1.0),
        (2, 2, 1.0),
    ] {
        runtime
            .matrix_set_value(three_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }
    assert_eq!(
        runtime.matrix_det(three_id).expect("determinant"),
        Some(PineValue::Float(-3.0))
    );

    let PineValue::Matrix(singular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_det(singular_id).expect("determinant"),
        Some(PineValue::Float(0.0))
    );

    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_det(na_id).expect("determinant"),
        Some(PineValue::Na)
    );

    let PineValue::Matrix(rectangle_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_det(rectangle_id)
        .expect_err("non-square determinant should fail");
    assert_eq!(err.message, "matrix determinant requires a square matrix");
}

fn assert_matrix_float_cell(
    runtime: &HistoricalRuntime<'_>,
    id: u32,
    row: i64,
    column: i64,
    expected: f64,
) {
    let actual = runtime
        .matrix_get_cloned(id, row, column)
        .expect("matrix get should succeed")
        .expect("matrix cell should exist")
        .as_f64()
        .expect("matrix cell should be numeric");
    assert!(
        (actual - expected).abs() < 1e-9,
        "expected matrix[{row}, {column}] to be {expected}, got {actual}"
    );
}

fn assert_array_float_cell(runtime: &HistoricalRuntime<'_>, id: u32, index: i64, expected: f64) {
    let actual = runtime
        .array_get_cloned(id, index)
        .expect("array get should succeed")
        .expect("array cell should exist")
        .as_f64()
        .expect("array cell should be numeric");
    assert!(
        (actual - expected).abs() < 1e-9,
        "expected array[{index}] to be {expected}, got {actual}"
    );
}

#[test]
fn computes_matrix_kronecker_product_independently() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 1.0), (0, 1, 2.0), (1, 0, 3.0), (1, 1, 4.0)] {
        runtime
            .matrix_set_value(left_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }

    let PineValue::Matrix(right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 1, PineValue::Na)
        .expect("right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(right_id, 0, 0, PineValue::Float(5.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(right_id, 1, 0, PineValue::Float(6.0))
        .expect("matrix set should succeed");

    let PineValue::Matrix(kron_id) = runtime.matrix_kron(left_id, right_id).expect("matrix kron")
    else {
        panic!("expected kronecker matrix id");
    };

    assert_ne!(left_id, kron_id);
    assert_eq!(runtime.matrix_shape(kron_id), Some((4, 2)));
    assert_matrix_float_cell(&runtime, kron_id, 0, 0, 5.0);
    assert_matrix_float_cell(&runtime, kron_id, 0, 1, 10.0);
    assert_matrix_float_cell(&runtime, kron_id, 1, 0, 6.0);
    assert_matrix_float_cell(&runtime, kron_id, 1, 1, 12.0);
    assert_matrix_float_cell(&runtime, kron_id, 2, 0, 15.0);
    assert_matrix_float_cell(&runtime, kron_id, 2, 1, 20.0);
    assert_matrix_float_cell(&runtime, kron_id, 3, 0, 18.0);
    assert_matrix_float_cell(&runtime, kron_id, 3, 1, 24.0);

    runtime
        .matrix_set_value(left_id, 0, 0, PineValue::Float(99.0))
        .expect("source mutation should succeed");
    assert_matrix_float_cell(&runtime, kron_id, 0, 0, 5.0);
}

#[test]
fn matrix_kronecker_product_handles_na_zero_dimensions_and_cell_budget() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(na_left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Float(2.0))
        .expect("left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(na_left_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    let PineValue::Matrix(right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 1, PineValue::Float(3.0))
        .expect("right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(na_kron_id) = runtime
        .matrix_kron(na_left_id, right_id)
        .expect("matrix kron")
    else {
        panic!("expected kronecker matrix id");
    };
    assert_matrix_float_cell(&runtime, na_kron_id, 0, 0, 6.0);
    assert_eq!(
        runtime
            .matrix_get_cloned(na_kron_id, 0, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_kron_id) =
        runtime.matrix_kron(empty_id, right_id).expect("empty kron")
    else {
        panic!("expected empty kronecker matrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_kron_id), Some((0, 2)));

    let PineValue::Matrix(large_left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 500, 1, PineValue::Float(1.0))
        .expect("large left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(large_right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 201, 1, PineValue::Float(1.0))
        .expect("large right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_kron(large_left_id, large_right_id)
        .expect_err("oversized kron should fail");
    assert_eq!(err.message, "matrix cell count cannot exceed 100000");
}

#[test]
fn computes_matrix_multiplication_independently() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [
        (0, 0, 1.0),
        (0, 1, 2.0),
        (0, 2, 3.0),
        (1, 0, 4.0),
        (1, 1, 5.0),
        (1, 2, 6.0),
    ] {
        runtime
            .matrix_set_value(left_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }

    let PineValue::Matrix(right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 2, PineValue::Na)
        .expect("right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [
        (0, 0, 7.0),
        (0, 1, 8.0),
        (1, 0, 9.0),
        (1, 1, 10.0),
        (2, 0, 11.0),
        (2, 1, 12.0),
    ] {
        runtime
            .matrix_set_value(right_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }

    let PineValue::Matrix(product_id) = runtime
        .matrix_mult(left_id, right_id)
        .expect("matrix multiplication")
    else {
        panic!("expected product matrix id");
    };

    assert_ne!(left_id, product_id);
    assert_ne!(right_id, product_id);
    assert_eq!(runtime.matrix_shape(product_id), Some((2, 2)));
    assert_matrix_float_cell(&runtime, product_id, 0, 0, 58.0);
    assert_matrix_float_cell(&runtime, product_id, 0, 1, 64.0);
    assert_matrix_float_cell(&runtime, product_id, 1, 0, 139.0);
    assert_matrix_float_cell(&runtime, product_id, 1, 1, 154.0);

    runtime
        .matrix_set_value(left_id, 0, 0, PineValue::Float(99.0))
        .expect("source mutation should succeed");
    assert_matrix_float_cell(&runtime, product_id, 0, 0, 58.0);

    let PineValue::Matrix(scalar_product_id) = runtime
        .matrix_mult_scalar(right_id, PineValue::Int(2))
        .expect("scalar matrix multiplication")
    else {
        panic!("expected scalar product matrix id");
    };
    assert_ne!(right_id, scalar_product_id);
    assert_eq!(runtime.matrix_shape(scalar_product_id), Some((3, 2)));
    assert_matrix_float_cell(&runtime, scalar_product_id, 0, 0, 14.0);
    assert_matrix_float_cell(&runtime, scalar_product_id, 2, 1, 24.0);

    let PineValue::Matrix(na_scalar_product_id) = runtime
        .matrix_mult_scalar(right_id, PineValue::Na)
        .expect("na scalar matrix multiplication")
    else {
        panic!("expected na scalar product matrix id");
    };
    assert_eq!(
        runtime
            .matrix_get_cloned(na_scalar_product_id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Array(vector_id) = runtime.new_array_from_values(
        ArrayElementKind::Float,
        vec![PineValue::Float(1.0), PineValue::Float(2.0)],
    ) else {
        panic!("expected vector array id");
    };
    let PineValue::Array(vector_product_id) = runtime
        .matrix_mult_array(right_id, vector_id)
        .expect("matrix array multiplication")
    else {
        panic!("expected vector product array id");
    };
    assert_ne!(vector_id, vector_product_id);
    assert_eq!(
        runtime
            .array_values_clone(vector_product_id)
            .expect("array clone should succeed"),
        Some(vec![
            PineValue::Float(23.0),
            PineValue::Float(29.0),
            PineValue::Float(35.0),
        ])
    );

    let PineValue::Array(na_vector_id) = runtime.new_array_from_values(
        ArrayElementKind::Float,
        vec![PineValue::Float(1.0), PineValue::Na],
    ) else {
        panic!("expected na vector array id");
    };
    let PineValue::Array(na_vector_product_id) = runtime
        .matrix_mult_array(right_id, na_vector_id)
        .expect("na matrix array multiplication")
    else {
        panic!("expected na vector product array id");
    };
    assert_eq!(
        runtime
            .array_get_cloned(na_vector_product_id, 0)
            .expect("array get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Array(short_vector_id) =
        runtime.new_array_from_values(ArrayElementKind::Float, vec![PineValue::Float(1.0)])
    else {
        panic!("expected short vector array id");
    };
    let err = runtime
        .matrix_mult_array(right_id, short_vector_id)
        .expect_err("short vector should fail");
    assert_eq!(
        err.message,
        "matrix multiplication requires matrix column count to match array size"
    );

    let PineValue::Array(left_vector_id) = runtime.new_array_from_values(
        ArrayElementKind::Float,
        vec![
            PineValue::Float(1.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0),
        ],
    ) else {
        panic!("expected left vector array id");
    };
    let PineValue::Array(left_vector_product_id) = runtime
        .array_mult_matrix(left_vector_id, right_id)
        .expect("array matrix multiplication")
    else {
        panic!("expected left vector product array id");
    };
    assert_eq!(
        runtime
            .array_values_clone(left_vector_product_id)
            .expect("array clone should succeed"),
        Some(vec![PineValue::Float(58.0), PineValue::Float(64.0)])
    );

    let PineValue::Array(short_left_vector_id) =
        runtime.new_array_from_values(ArrayElementKind::Float, vec![PineValue::Float(1.0)])
    else {
        panic!("expected short left vector array id");
    };
    let err = runtime
        .array_mult_matrix(short_left_vector_id, right_id)
        .expect_err("short left vector should fail");
    assert_eq!(
        err.message,
        "matrix multiplication requires array size to match matrix row count"
    );

    let PineValue::Array(dot_left_id) = runtime.new_array_from_values(
        ArrayElementKind::Float,
        vec![
            PineValue::Float(1.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0),
        ],
    ) else {
        panic!("expected dot left array id");
    };
    let PineValue::Array(dot_right_id) = runtime.new_array_from_values(
        ArrayElementKind::Int,
        vec![PineValue::Int(4), PineValue::Int(5), PineValue::Int(6)],
    ) else {
        panic!("expected dot right array id");
    };
    let PineValue::Array(dot_product_id) = runtime
        .array_mult_array(dot_left_id, dot_right_id)
        .expect("array array multiplication")
    else {
        panic!("expected dot product array id");
    };
    assert_ne!(dot_left_id, dot_product_id);
    assert_ne!(dot_right_id, dot_product_id);
    assert_eq!(
        runtime
            .array_values_clone(dot_product_id)
            .expect("array clone should succeed"),
        Some(vec![PineValue::Float(32.0)])
    );

    let PineValue::Array(na_dot_left_id) = runtime.new_array_from_values(
        ArrayElementKind::Float,
        vec![PineValue::Float(1.0), PineValue::Na],
    ) else {
        panic!("expected na dot left array id");
    };
    let PineValue::Array(na_dot_right_id) = runtime.new_array_from_values(
        ArrayElementKind::Float,
        vec![PineValue::Float(2.0), PineValue::Float(3.0)],
    ) else {
        panic!("expected na dot right array id");
    };
    let PineValue::Array(na_dot_product_id) = runtime
        .array_mult_array(na_dot_left_id, na_dot_right_id)
        .expect("na array array multiplication")
    else {
        panic!("expected na dot product array id");
    };
    assert_eq!(
        runtime
            .array_get_cloned(na_dot_product_id, 0)
            .expect("array get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Array(short_dot_right_id) =
        runtime.new_array_from_values(ArrayElementKind::Float, vec![PineValue::Float(1.0)])
    else {
        panic!("expected short dot right array id");
    };
    let err = runtime
        .array_mult_array(dot_left_id, short_dot_right_id)
        .expect_err("short right array should fail");
    assert_eq!(
        err.message,
        "matrix multiplication requires left array size to match right array size"
    );
}

#[test]
fn matrix_multiplication_handles_na_zero_dimensions_shape_and_cell_budget() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(na_left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Float(2.0))
        .expect("left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(na_left_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    let PineValue::Matrix(right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 1, PineValue::Float(3.0))
        .expect("right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(na_product_id) = runtime
        .matrix_mult(na_left_id, right_id)
        .expect("matrix multiplication")
    else {
        panic!("expected product matrix id");
    };
    assert_eq!(
        runtime
            .matrix_get_cloned(na_product_id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Matrix(empty_left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_product_id) = runtime
        .matrix_mult(empty_left_id, right_id)
        .expect("empty multiplication")
    else {
        panic!("expected empty product matrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_product_id), Some((0, 1)));

    let PineValue::Matrix(bad_shape_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 1, PineValue::Float(1.0))
        .expect("bad shape matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_mult(na_left_id, bad_shape_id)
        .expect_err("incompatible shapes should fail");
    assert_eq!(
        err.message,
        "matrix multiplication requires left column count to match right row count"
    );

    let PineValue::Matrix(large_left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 334, 1, PineValue::Float(1.0))
        .expect("large left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(large_right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 300, PineValue::Float(1.0))
        .expect("large right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_mult(large_left_id, large_right_id)
        .expect_err("oversized multiplication should fail");
    assert_eq!(err.message, "matrix cell count cannot exceed 100000");
}

#[test]
fn computes_matrix_difference_independently() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 8.0), (0, 1, 6.0), (1, 0, 4.0), (1, 1, 2.0)] {
        runtime
            .matrix_set_value(left_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }

    let PineValue::Matrix(right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 1.0), (0, 1, 2.0), (1, 0, 3.0), (1, 1, 4.0)] {
        runtime
            .matrix_set_value(right_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }

    let PineValue::Matrix(diff_id) = runtime
        .matrix_diff(left_id, right_id)
        .expect("matrix difference")
    else {
        panic!("expected difference matrix id");
    };

    assert_ne!(left_id, diff_id);
    assert_ne!(right_id, diff_id);
    assert_eq!(runtime.matrix_shape(diff_id), Some((2, 2)));
    assert_matrix_float_cell(&runtime, diff_id, 0, 0, 7.0);
    assert_matrix_float_cell(&runtime, diff_id, 0, 1, 4.0);
    assert_matrix_float_cell(&runtime, diff_id, 1, 0, 1.0);
    assert_matrix_float_cell(&runtime, diff_id, 1, 1, -2.0);

    runtime
        .matrix_set_value(left_id, 0, 0, PineValue::Float(99.0))
        .expect("source mutation should succeed");
    assert_matrix_float_cell(&runtime, diff_id, 0, 0, 7.0);

    let PineValue::Matrix(scalar_diff_id) = runtime
        .matrix_diff_scalar(right_id, PineValue::Float(1.5))
        .expect("scalar matrix difference")
    else {
        panic!("expected scalar difference matrix id");
    };
    assert_ne!(right_id, scalar_diff_id);
    assert_eq!(runtime.matrix_shape(scalar_diff_id), Some((2, 2)));
    assert_matrix_float_cell(&runtime, scalar_diff_id, 0, 0, -0.5);
    assert_matrix_float_cell(&runtime, scalar_diff_id, 1, 1, 2.5);

    let PineValue::Matrix(na_scalar_diff_id) = runtime
        .matrix_diff_scalar(right_id, PineValue::Na)
        .expect("na scalar matrix difference")
    else {
        panic!("expected na scalar difference matrix id");
    };
    assert_eq!(
        runtime
            .matrix_get_cloned(na_scalar_diff_id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Na)
    );
}

#[test]
fn matrix_difference_handles_na_zero_dimensions_and_shape_mismatch() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(na_left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Float(5.0))
        .expect("left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(na_left_id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    let PineValue::Matrix(right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Float(3.0))
        .expect("right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(na_diff_id) = runtime
        .matrix_diff(na_left_id, right_id)
        .expect("matrix difference")
    else {
        panic!("expected difference matrix id");
    };
    assert_matrix_float_cell(&runtime, na_diff_id, 0, 0, 2.0);
    assert_eq!(
        runtime
            .matrix_get_cloned(na_diff_id, 0, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Matrix(empty_left_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty left matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_right_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 2, PineValue::Na)
        .expect("empty right matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_diff_id) = runtime
        .matrix_diff(empty_left_id, empty_right_id)
        .expect("empty difference")
    else {
        panic!("expected empty difference matrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_diff_id), Some((0, 2)));

    let PineValue::Matrix(bad_shape_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 1, PineValue::Float(1.0))
        .expect("bad shape matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_diff(na_left_id, bad_shape_id)
        .expect_err("incompatible shapes should fail");
    assert_eq!(
        err.message,
        "matrix difference requires matching row and column counts"
    );
}

#[test]
fn computes_matrix_power_independently() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(source_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 1.0), (0, 1, 2.0), (1, 0, 3.0), (1, 1, 4.0)] {
        runtime
            .matrix_set_value(source_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }

    let PineValue::Matrix(square_id) = runtime.matrix_pow(source_id, 2).expect("matrix power")
    else {
        panic!("expected power matrix id");
    };
    assert_ne!(source_id, square_id);
    assert_eq!(runtime.matrix_shape(square_id), Some((2, 2)));
    assert_matrix_float_cell(&runtime, square_id, 0, 0, 7.0);
    assert_matrix_float_cell(&runtime, square_id, 0, 1, 10.0);
    assert_matrix_float_cell(&runtime, square_id, 1, 0, 15.0);
    assert_matrix_float_cell(&runtime, square_id, 1, 1, 22.0);

    let PineValue::Matrix(cube_id) = runtime.matrix_pow(source_id, 3).expect("matrix power") else {
        panic!("expected power matrix id");
    };
    assert_matrix_float_cell(&runtime, cube_id, 0, 0, 37.0);
    assert_matrix_float_cell(&runtime, cube_id, 0, 1, 54.0);
    assert_matrix_float_cell(&runtime, cube_id, 1, 0, 81.0);
    assert_matrix_float_cell(&runtime, cube_id, 1, 1, 118.0);

    runtime
        .matrix_set_value(source_id, 0, 0, PineValue::Float(99.0))
        .expect("source mutation should succeed");
    assert_matrix_float_cell(&runtime, square_id, 0, 0, 7.0);
}

#[test]
fn matrix_power_handles_zero_one_na_empty_and_errors() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(source_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(source_id, 0, 0, PineValue::Float(5.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(source_id, 0, 1, PineValue::Float(0.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(source_id, 1, 0, PineValue::Float(0.0))
        .expect("matrix set should succeed");

    let PineValue::Matrix(identity_id) = runtime.matrix_pow(source_id, 0).expect("identity power")
    else {
        panic!("expected identity matrix id");
    };
    assert_matrix_float_cell(&runtime, identity_id, 0, 0, 1.0);
    assert_matrix_float_cell(&runtime, identity_id, 0, 1, 0.0);
    assert_matrix_float_cell(&runtime, identity_id, 1, 0, 0.0);
    assert_matrix_float_cell(&runtime, identity_id, 1, 1, 1.0);

    let PineValue::Matrix(copy_id) = runtime.matrix_pow(source_id, 1).expect("copy power") else {
        panic!("expected copy matrix id");
    };
    assert_ne!(source_id, copy_id);
    assert_matrix_float_cell(&runtime, copy_id, 0, 0, 5.0);
    assert_eq!(
        runtime
            .matrix_get_cloned(copy_id, 1, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Matrix(na_square_id) = runtime.matrix_pow(source_id, 2).expect("na power")
    else {
        panic!("expected na power matrix id");
    };
    assert_eq!(
        runtime
            .matrix_get_cloned(na_square_id, 1, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Na)
    );

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_power_id) = runtime.matrix_pow(empty_id, 3).expect("empty power")
    else {
        panic!("expected empty power matrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_power_id), Some((0, 0)));

    let PineValue::Matrix(rectangle_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 2, PineValue::Float(1.0))
        .expect("rectangle matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_pow(rectangle_id, 2)
        .expect_err("non-square matrix power should fail");
    assert_eq!(err.message, "matrix power requires a square matrix");
}

#[test]
fn inverts_square_matrix_storage_independently() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(source_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 4.0), (0, 1, 7.0), (1, 0, 2.0), (1, 1, 6.0)] {
        runtime
            .matrix_set_value(source_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }

    let PineValue::Matrix(inv_id) = runtime.matrix_inv(source_id).expect("matrix inverse") else {
        panic!("expected inverse matrix id");
    };

    assert_ne!(source_id, inv_id);
    assert_eq!(runtime.matrix_shape(source_id), Some((2, 2)));
    assert_eq!(runtime.matrix_shape(inv_id), Some((2, 2)));
    assert_matrix_float_cell(&runtime, inv_id, 0, 0, 0.6);
    assert_matrix_float_cell(&runtime, inv_id, 0, 1, -0.7);
    assert_matrix_float_cell(&runtime, inv_id, 1, 0, -0.2);
    assert_matrix_float_cell(&runtime, inv_id, 1, 1, 0.4);

    runtime
        .matrix_set_value(source_id, 0, 0, PineValue::Float(99.0))
        .expect("source mutation should succeed");
    assert_matrix_float_cell(&runtime, inv_id, 0, 0, 0.6);
}

#[test]
fn matrix_inverse_handles_empty_singular_na_and_non_square_inputs() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_inv_id) = runtime.matrix_inv(empty_id).expect("empty inverse")
    else {
        panic!("expected empty inverse matrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_inv_id), Some((0, 0)));

    let PineValue::Matrix(singular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_inv(singular_id).expect("singular inverse"),
        PineValue::Na
    );

    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_inv(na_id).expect("na inverse"),
        PineValue::Na
    );

    let PineValue::Matrix(rectangle_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_inv(rectangle_id)
        .expect_err("non-square inverse should fail");
    assert_eq!(err.message, "matrix inverse requires a square matrix");
}

#[test]
fn computes_matrix_eigenvalues_for_square_numeric_cells() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(diagonal_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(diagonal_id, 0, 0, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_id, 1, 1, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    let PineValue::Array(diagonal_values_id) = runtime
        .matrix_eigenvalues(diagonal_id)
        .expect("matrix eigenvalues")
    else {
        panic!("expected eigenvalue array id");
    };
    assert_eq!(
        runtime
            .array_values_clone(diagonal_values_id)
            .expect("array clone")
            .expect("array values")
            .len(),
        2
    );
    assert_array_float_cell(&runtime, diagonal_values_id, 0, 2.0);
    assert_array_float_cell(&runtime, diagonal_values_id, 1, 3.0);

    let PineValue::Matrix(upper_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(upper_id, 0, 0, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(upper_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(upper_id, 1, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    let PineValue::Array(upper_values_id) = runtime
        .matrix_eigenvalues(upper_id)
        .expect("matrix eigenvalues")
    else {
        panic!("expected eigenvalue array id");
    };
    assert_array_float_cell(&runtime, upper_values_id, 0, 3.0);
    assert_array_float_cell(&runtime, upper_values_id, 1, 2.0);

    let PineValue::Matrix(negative_symmetric_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(negative_symmetric_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(negative_symmetric_id, 1, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    let PineValue::Array(negative_values_id) = runtime
        .matrix_eigenvalues(negative_symmetric_id)
        .expect("matrix eigenvalues")
    else {
        panic!("expected eigenvalue array id");
    };
    assert_array_float_cell(&runtime, negative_values_id, 0, -1.0);
    assert_array_float_cell(&runtime, negative_values_id, 1, 1.0);
}

#[test]
fn matrix_eigenvalues_handles_empty_na_complex_and_non_square_inputs() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Array(empty_values_id) = runtime
        .matrix_eigenvalues(empty_id)
        .expect("empty eigenvalues")
    else {
        panic!("expected empty eigenvalue array id");
    };
    assert_eq!(
        runtime
            .array_values_clone(empty_values_id)
            .expect("array clone")
            .expect("array values")
            .len(),
        0
    );

    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_eigenvalues(na_id).expect("na eigenvalues"),
        PineValue::Na
    );

    let PineValue::Matrix(complex_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(complex_id, 0, 1, PineValue::Float(-1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(complex_id, 1, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    assert_eq!(
        runtime
            .matrix_eigenvalues(complex_id)
            .expect("complex eigenvalues"),
        PineValue::Na
    );

    let PineValue::Matrix(rectangle_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_eigenvalues(rectangle_id)
        .expect_err("non-square eigenvalues should fail");
    assert_eq!(err.message, "matrix eigenvalues require a square matrix");
}

#[test]
fn computes_matrix_eigenvectors_for_square_numeric_cells() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(diagonal_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(diagonal_id, 0, 0, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(diagonal_id, 1, 1, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    let PineValue::Matrix(diagonal_vectors_id) = runtime
        .matrix_eigenvectors(diagonal_id)
        .expect("matrix eigenvectors")
    else {
        panic!("expected eigenvector matrix id");
    };
    assert_ne!(diagonal_id, diagonal_vectors_id);
    assert_eq!(runtime.matrix_shape(diagonal_vectors_id), Some((2, 2)));
    assert_matrix_float_cell(&runtime, diagonal_vectors_id, 0, 0, 1.0);
    assert_matrix_float_cell(&runtime, diagonal_vectors_id, 0, 1, 0.0);
    assert_matrix_float_cell(&runtime, diagonal_vectors_id, 1, 0, 0.0);
    assert_matrix_float_cell(&runtime, diagonal_vectors_id, 1, 1, 1.0);

    runtime
        .matrix_set_value(diagonal_id, 0, 0, PineValue::Float(99.0))
        .expect("source mutation should succeed");
    assert_matrix_float_cell(&runtime, diagonal_vectors_id, 0, 0, 1.0);

    let PineValue::Matrix(upper_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(upper_id, 0, 0, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(upper_id, 0, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(upper_id, 1, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    let PineValue::Matrix(upper_vectors_id) = runtime
        .matrix_eigenvectors(upper_id)
        .expect("matrix eigenvectors")
    else {
        panic!("expected eigenvector matrix id");
    };
    assert_matrix_float_cell(&runtime, upper_vectors_id, 0, 0, 1.0);
    assert_matrix_float_cell(&runtime, upper_vectors_id, 1, 0, 0.0);
    assert_matrix_float_cell(
        &runtime,
        upper_vectors_id,
        0,
        1,
        -std::f64::consts::FRAC_1_SQRT_2,
    );
    assert_matrix_float_cell(
        &runtime,
        upper_vectors_id,
        1,
        1,
        std::f64::consts::FRAC_1_SQRT_2,
    );
}

#[test]
fn matrix_eigenvectors_handles_empty_na_complex_and_non_square_inputs() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 0, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_vectors_id) = runtime
        .matrix_eigenvectors(empty_id)
        .expect("empty eigenvectors")
    else {
        panic!("expected empty eigenvector matrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_vectors_id), Some((0, 0)));

    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(
        runtime.matrix_eigenvectors(na_id).expect("na eigenvectors"),
        PineValue::Na
    );

    let PineValue::Matrix(complex_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(complex_id, 0, 1, PineValue::Float(-1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(complex_id, 1, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    assert_eq!(
        runtime
            .matrix_eigenvectors(complex_id)
            .expect("complex eigenvectors"),
        PineValue::Na
    );

    let PineValue::Matrix(rectangle_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let err = runtime
        .matrix_eigenvectors(rectangle_id)
        .expect_err("non-square eigenvectors should fail");
    assert_eq!(err.message, "matrix eigenvectors require a square matrix");
}

#[test]
fn computes_matrix_pseudo_inverse_for_square_singular_and_rectangular_inputs() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(square_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 4.0), (0, 1, 7.0), (1, 0, 2.0), (1, 1, 6.0)] {
        runtime
            .matrix_set_value(square_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }
    let PineValue::Matrix(square_pinv_id) = runtime.matrix_pinv(square_id) else {
        panic!("expected pseudo-inverse matrix id");
    };
    assert_eq!(runtime.matrix_shape(square_pinv_id), Some((2, 2)));
    assert_matrix_float_cell(&runtime, square_pinv_id, 0, 0, 0.6);
    assert_matrix_float_cell(&runtime, square_pinv_id, 0, 1, -0.7);
    assert_matrix_float_cell(&runtime, square_pinv_id, 1, 0, -0.2);
    assert_matrix_float_cell(&runtime, square_pinv_id, 1, 1, 0.4);

    let PineValue::Matrix(singular_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [(0, 0, 1.0), (0, 1, 2.0), (1, 0, 2.0), (1, 1, 4.0)] {
        runtime
            .matrix_set_value(singular_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }
    let PineValue::Matrix(singular_pinv_id) = runtime.matrix_pinv(singular_id) else {
        panic!("expected singular pseudo-inverse matrix id");
    };
    assert_matrix_float_cell(&runtime, singular_pinv_id, 0, 0, 0.04);
    assert_matrix_float_cell(&runtime, singular_pinv_id, 0, 1, 0.08);
    assert_matrix_float_cell(&runtime, singular_pinv_id, 1, 0, 0.08);
    assert_matrix_float_cell(&runtime, singular_pinv_id, 1, 1, 0.16);

    let PineValue::Matrix(tall_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 2, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(tall_id, 0, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(tall_id, 1, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    let PineValue::Matrix(tall_pinv_id) = runtime.matrix_pinv(tall_id) else {
        panic!("expected tall pseudo-inverse matrix id");
    };
    assert_eq!(runtime.matrix_shape(tall_pinv_id), Some((2, 3)));
    assert_matrix_float_cell(&runtime, tall_pinv_id, 0, 0, 1.0);
    assert_matrix_float_cell(&runtime, tall_pinv_id, 0, 2, 0.0);
    assert_matrix_float_cell(&runtime, tall_pinv_id, 1, 1, 1.0);

    let PineValue::Matrix(wide_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(wide_id, 0, 0, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(wide_id, 1, 1, PineValue::Float(1.0))
        .expect("matrix set should succeed");
    let PineValue::Matrix(wide_pinv_id) = runtime.matrix_pinv(wide_id) else {
        panic!("expected wide pseudo-inverse matrix id");
    };
    assert_eq!(runtime.matrix_shape(wide_pinv_id), Some((3, 2)));
    assert_matrix_float_cell(&runtime, wide_pinv_id, 0, 0, 1.0);
    assert_matrix_float_cell(&runtime, wide_pinv_id, 1, 1, 1.0);
    assert_matrix_float_cell(&runtime, wide_pinv_id, 2, 0, 0.0);
}

#[test]
fn matrix_pseudo_inverse_handles_zero_dimensions_and_na_cells() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(empty_rows_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 3, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let PineValue::Matrix(empty_rows_pinv_id) = runtime.matrix_pinv(empty_rows_id) else {
        panic!("expected empty pseudo-inverse matrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_rows_pinv_id), Some((3, 0)));

    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(runtime.matrix_pinv(na_id), PineValue::Na);
}

#[test]
fn computes_matrix_rank_for_rectangular_numeric_cells() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let PineValue::Matrix(full_rank_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [
        (0, 0, 1.0),
        (0, 1, 2.0),
        (0, 2, 3.0),
        (1, 0, 0.0),
        (1, 1, 1.0),
        (1, 2, 4.0),
    ] {
        runtime
            .matrix_set_value(full_rank_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }
    assert_eq!(runtime.matrix_rank(full_rank_id), Some(PineValue::Int(2)));

    let PineValue::Matrix(dependent_id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for (row, column, value) in [
        (0, 0, 1.0),
        (0, 1, 2.0),
        (1, 0, 2.0),
        (1, 1, 4.0),
        (2, 0, 3.0),
        (2, 1, 6.0),
    ] {
        runtime
            .matrix_set_value(dependent_id, row, column, PineValue::Float(value))
            .expect("matrix set should succeed");
    }
    assert_eq!(runtime.matrix_rank(dependent_id), Some(PineValue::Int(1)));

    let PineValue::Matrix(empty_id) = runtime
        .new_matrix(MatrixElementKind::Float, 0, 3, PineValue::Na)
        .expect("empty matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(runtime.matrix_rank(empty_id), Some(PineValue::Int(0)));

    let PineValue::Matrix(na_id) = runtime
        .new_matrix(MatrixElementKind::Float, 1, 1, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    assert_eq!(runtime.matrix_rank(na_id), Some(PineValue::Na));
}

#[test]
fn copies_matrix_storage_independently() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(source_id) = runtime
        .new_matrix(
            MatrixElementKind::String,
            1,
            2,
            PineValue::String("a".to_owned()),
        )
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    let PineValue::Matrix(copy_id) = runtime.copy_matrix(source_id) else {
        panic!("expected copied matrix id");
    };
    runtime
        .matrix_set_value(copy_id, 0, 1, PineValue::String("b".to_owned()))
        .expect("copy mutation should succeed");

    assert_ne!(source_id, copy_id);
    assert_eq!(
        runtime
            .matrix_get_cloned(source_id, 0, 1)
            .expect("source get should succeed"),
        Some(PineValue::String("a".to_owned()))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(copy_id, 0, 1)
            .expect("copy get should succeed"),
        Some(PineValue::String("b".to_owned()))
    );
    assert_eq!(runtime.matrix_store_profile().slots, 2);
}

#[test]
fn transposes_matrix_storage_independently() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(source_id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    for row in 0..2 {
        for column in 0..3 {
            runtime
                .matrix_set_value(
                    source_id,
                    row,
                    column,
                    PineValue::Float((row * 3 + column + 1) as f64),
                )
                .expect("matrix set should succeed");
        }
    }

    let PineValue::Matrix(transposed_id) = runtime.matrix_transpose(source_id) else {
        panic!("expected transposed matrix id");
    };

    assert_ne!(source_id, transposed_id);
    assert_eq!(runtime.matrix_shape(source_id), Some((2, 3)));
    assert_eq!(runtime.matrix_shape(transposed_id), Some((3, 2)));
    assert_eq!(
        runtime
            .matrix_get_cloned(transposed_id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(1.0))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(transposed_id, 0, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(4.0))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(transposed_id, 1, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(2.0))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(transposed_id, 2, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(6.0))
    );

    runtime
        .matrix_set_value(source_id, 0, 0, PineValue::Float(99.0))
        .expect("source mutation should succeed");
    assert_eq!(
        runtime
            .matrix_get_cloned(transposed_id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(1.0))
    );
}

#[test]
fn reverses_matrix_storage_in_place() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    for row in 0..2 {
        for column in 0..3 {
            runtime
                .matrix_set_value(
                    id,
                    row,
                    column,
                    PineValue::Float((row * 3 + column + 1) as f64),
                )
                .expect("matrix set should succeed");
        }
    }

    runtime.matrix_reverse(id);

    assert_eq!(runtime.matrix_shape(id), Some((2, 3)));
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 0, 0)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(6.0))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 0, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(5.0))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 1, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(2.0))
    );
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 1, 2)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(1.0))
    );
}

#[test]
fn reshapes_matrix_without_reordering_cells() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Float(0.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };

    for row in 0..2 {
        for column in 0..3 {
            runtime
                .matrix_set_value(id, row, column, PineValue::Float((row * 3 + column) as f64))
                .expect("matrix set should succeed");
        }
    }

    runtime
        .matrix_reshape(id, 3, 2)
        .expect("reshape should preserve element count");

    assert_eq!(runtime.matrix_shape(id), Some((3, 2)));
    assert_eq!(
        runtime
            .matrix_get_cloned(id, 2, 1)
            .expect("matrix get should succeed"),
        Some(PineValue::Float(5.0))
    );
}

#[test]
fn inserts_matrix_rows_from_copied_array_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(id, 1, 0, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(id, 1, 1, PineValue::Float(4.0))
        .expect("matrix set should succeed");

    runtime
        .matrix_add_row(id, 1, vec![PineValue::Float(9.0), PineValue::Int(10)])
        .expect("matrix add_row should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((3, 2)));
    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(9.0), PineValue::Float(10.0)])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 2)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(3.0), PineValue::Float(4.0)])
    );

    let mismatch = runtime
        .matrix_add_row(id, 0, vec![PineValue::Float(1.0)])
        .expect_err("short row should fail");
    assert_eq!(
        mismatch.message,
        "matrix add_row array size 1 must match column count 2"
    );
}

#[test]
fn inserts_matrix_columns_from_copied_array_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Float(1.0))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(id, 0, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(id, 1, 0, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(id, 1, 1, PineValue::Float(4.0))
        .expect("matrix set should succeed");

    runtime
        .matrix_add_col(id, 1, vec![PineValue::Float(9.0), PineValue::Int(10)])
        .expect("matrix add_col should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((2, 3)));
    assert_eq!(
        runtime
            .matrix_col_values(id, 1)
            .expect("matrix col should succeed"),
        Some(vec![PineValue::Float(9.0), PineValue::Float(10.0)])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 0)
            .expect("matrix row should succeed"),
        Some(vec![
            PineValue::Float(1.0),
            PineValue::Float(9.0),
            PineValue::Float(2.0),
        ])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![
            PineValue::Float(3.0),
            PineValue::Float(10.0),
            PineValue::Float(4.0),
        ])
    );

    let mismatch = runtime
        .matrix_add_col(id, 0, vec![PineValue::Float(1.0)])
        .expect_err("short column should fail");
    assert_eq!(
        mismatch.message,
        "matrix add_col array size 1 must match row count 2"
    );
}

#[test]
fn removes_matrix_rows_and_preserves_row_major_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for row in 0..3 {
        for column in 0..2 {
            runtime
                .matrix_set_value(
                    id,
                    row,
                    column,
                    PineValue::Float((row * 10 + column) as f64),
                )
                .expect("matrix set should succeed");
        }
    }

    runtime
        .matrix_remove_row(id, 1)
        .expect("matrix remove_row should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((2, 2)));
    assert_eq!(
        runtime
            .matrix_row_values(id, 0)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(0.0), PineValue::Float(1.0)])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(20.0), PineValue::Float(21.0)])
    );

    let out_of_bounds = runtime
        .matrix_remove_row(id, 2)
        .expect_err("row beyond shrunken matrix should fail");
    assert_eq!(
        out_of_bounds.message,
        "matrix row index 2 is out of bounds for size 2"
    );
}

#[test]
fn removes_matrix_columns_and_preserves_row_major_values() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for row in 0..2 {
        for column in 0..3 {
            runtime
                .matrix_set_value(
                    id,
                    row,
                    column,
                    PineValue::Float((row * 10 + column) as f64),
                )
                .expect("matrix set should succeed");
        }
    }

    runtime
        .matrix_remove_col(id, 1)
        .expect("matrix remove_col should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((2, 2)));
    assert_eq!(
        runtime
            .matrix_row_values(id, 0)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(0.0), PineValue::Float(2.0)])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(10.0), PineValue::Float(12.0)])
    );

    let out_of_bounds = runtime
        .matrix_remove_col(id, 2)
        .expect_err("column beyond shrunken matrix should fail");
    assert_eq!(
        out_of_bounds.message,
        "matrix column index 2 is out of bounds for size 2"
    );
}

#[test]
fn swaps_matrix_rows_in_place() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for row in 0..3 {
        for column in 0..2 {
            runtime
                .matrix_set_value(
                    id,
                    row,
                    column,
                    PineValue::Float((row * 10 + column) as f64),
                )
                .expect("matrix set should succeed");
        }
    }

    runtime
        .matrix_swap_rows(id, 0, 2)
        .expect("matrix swap_rows should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((3, 2)));
    assert_eq!(
        runtime
            .matrix_row_values(id, 0)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(20.0), PineValue::Float(21.0)])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(10.0), PineValue::Float(11.0)])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 2)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(0.0), PineValue::Float(1.0)])
    );

    runtime
        .matrix_swap_rows(id, 1, 1)
        .expect("same-row swap should succeed");
    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(10.0), PineValue::Float(11.0)])
    );

    let out_of_bounds = runtime
        .matrix_swap_rows(id, 3, 0)
        .expect_err("row beyond matrix should fail");
    assert_eq!(
        out_of_bounds.message,
        "matrix row index 3 is out of bounds for size 3"
    );
}

#[test]
fn swaps_matrix_columns_in_place() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for row in 0..2 {
        for column in 0..3 {
            runtime
                .matrix_set_value(
                    id,
                    row,
                    column,
                    PineValue::Float((row * 10 + column) as f64),
                )
                .expect("matrix set should succeed");
        }
    }

    runtime
        .matrix_swap_columns(id, 0, 2)
        .expect("matrix swap_columns should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((2, 3)));
    assert_eq!(
        runtime
            .matrix_row_values(id, 0)
            .expect("matrix row should succeed"),
        Some(vec![
            PineValue::Float(2.0),
            PineValue::Float(1.0),
            PineValue::Float(0.0),
        ])
    );
    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![
            PineValue::Float(12.0),
            PineValue::Float(11.0),
            PineValue::Float(10.0),
        ])
    );

    runtime
        .matrix_swap_columns(id, 1, 1)
        .expect("same-column swap should succeed");
    assert_eq!(
        runtime
            .matrix_col_values(id, 1)
            .expect("matrix column should succeed"),
        Some(vec![PineValue::Float(1.0), PineValue::Float(11.0)])
    );

    let out_of_bounds = runtime
        .matrix_swap_columns(id, 3, 0)
        .expect_err("column beyond matrix should fail");
    assert_eq!(
        out_of_bounds.message,
        "matrix column index 3 is out of bounds for size 3"
    );
}

#[test]
fn sorts_matrix_rows_by_column_in_place() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 4, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let rows = [
        [2.0, 30.0, 200.0],
        [1.0, 10.0, 100.0],
        [4.0, 20.0, 400.0],
        [3.0, 20.0, 300.0],
    ];
    for (row, values) in rows.iter().enumerate() {
        for (column, value) in values.iter().copied().enumerate() {
            runtime
                .matrix_set_value(id, row as i64, column as i64, PineValue::Float(value))
                .expect("matrix set should succeed");
        }
    }

    runtime
        .matrix_sort(id, 1, false)
        .expect("ascending matrix sort should succeed");

    assert_eq!(runtime.matrix_shape(id), Some((4, 3)));
    assert_eq!(
        runtime
            .matrix_col_values(id, 0)
            .expect("matrix column should succeed"),
        Some(vec![
            PineValue::Float(1.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(2.0),
        ])
    );

    runtime
        .matrix_set_value(id, 0, 1, PineValue::Na)
        .expect("matrix set should succeed");
    runtime
        .matrix_sort(id, 1, true)
        .expect("descending matrix sort should succeed");
    assert_eq!(
        runtime
            .matrix_col_values(id, 0)
            .expect("matrix column should succeed"),
        Some(vec![
            PineValue::Float(1.0),
            PineValue::Float(2.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
        ])
    );

    let out_of_bounds = runtime
        .matrix_sort(id, 3, false)
        .expect_err("column beyond matrix should fail");
    assert_eq!(
        out_of_bounds.message,
        "matrix column index 3 is out of bounds for size 3"
    );
}

#[test]
fn copies_matrix_submatrix_ranges() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 3, 4, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    for row in 0..3 {
        for column in 0..4 {
            runtime
                .matrix_set_value(
                    id,
                    row,
                    column,
                    PineValue::Float((row * 10 + column) as f64),
                )
                .expect("matrix set should succeed");
        }
    }

    let PineValue::Matrix(slice_id) = runtime
        .matrix_submatrix(id, 1, 3, 1, 4)
        .expect("submatrix should succeed")
    else {
        panic!("expected submatrix id");
    };
    assert_eq!(runtime.matrix_shape(slice_id), Some((2, 3)));
    assert_eq!(
        runtime
            .matrix_row_values(slice_id, 0)
            .expect("submatrix row should succeed"),
        Some(vec![
            PineValue::Float(11.0),
            PineValue::Float(12.0),
            PineValue::Float(13.0),
        ])
    );

    runtime
        .matrix_set_value(id, 1, 1, PineValue::Float(999.0))
        .expect("source mutation should succeed");
    assert_eq!(
        runtime
            .matrix_get_cloned(slice_id, 0, 0)
            .expect("submatrix get should succeed"),
        Some(PineValue::Float(11.0))
    );

    let PineValue::Matrix(empty_rows_id) = runtime
        .matrix_submatrix(id, 3, 3, 0, 4)
        .expect("empty-row submatrix should succeed")
    else {
        panic!("expected empty-row submatrix id");
    };
    assert_eq!(runtime.matrix_shape(empty_rows_id), Some((0, 4)));

    let out_of_bounds = runtime
        .matrix_submatrix(id, 0, 4, 0, 4)
        .expect_err("row beyond matrix should fail");
    assert_eq!(
        out_of_bounds.message,
        "matrix row index 4 is out of bounds for size 4"
    );
}

#[test]
fn copies_matrix_row_values_into_float_array() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 2, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(id, 1, 0, PineValue::Float(3.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(id, 1, 1, PineValue::Float(4.0))
        .expect("matrix set should succeed");

    assert_eq!(
        runtime
            .matrix_row_values(id, 1)
            .expect("matrix row should succeed"),
        Some(vec![PineValue::Float(3.0), PineValue::Float(4.0)])
    );
}

#[test]
fn copies_matrix_column_values_into_float_array() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);
    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Float, 2, 3, PineValue::Na)
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    runtime
        .matrix_set_value(id, 0, 1, PineValue::Float(2.0))
        .expect("matrix set should succeed");
    runtime
        .matrix_set_value(id, 1, 1, PineValue::Float(5.0))
        .expect("matrix set should succeed");

    assert_eq!(
        runtime
            .matrix_col_values(id, 1)
            .expect("matrix column should succeed"),
        Some(vec![PineValue::Float(2.0), PineValue::Float(5.0)])
    );
}

#[test]
fn rejects_invalid_matrix_dimensions_and_indexes() {
    let program = runtime_program();
    let mut runtime = HistoricalRuntime::new(&program);

    let negative = runtime
        .new_matrix(MatrixElementKind::Bool, -1, 2, PineValue::Bool(false))
        .expect_err("negative rows should fail");
    assert_eq!(negative.message, "matrix row count cannot be negative");

    let too_large = runtime
        .new_matrix(
            MatrixElementKind::Color,
            100_001,
            1,
            PineValue::Color(0xff00ffff),
        )
        .expect_err("too many cells should fail");
    assert_eq!(too_large.message, "matrix cell count cannot exceed 100000");

    let PineValue::Matrix(id) = runtime
        .new_matrix(MatrixElementKind::Bool, 1, 1, PineValue::Bool(false))
        .expect("matrix allocation")
    else {
        panic!("expected matrix id");
    };
    let bad_row = runtime
        .matrix_get_cloned(id, 1, 0)
        .expect_err("row out of bounds should fail");
    assert_eq!(
        bad_row.message,
        "matrix row index 1 is out of bounds for size 1"
    );
    let bad_column = runtime
        .matrix_set_value(id, 0, -1, PineValue::Bool(true))
        .expect_err("negative column should fail");
    assert_eq!(
        bad_column.message,
        "matrix column index -1 is out of bounds for size 1"
    );
}
