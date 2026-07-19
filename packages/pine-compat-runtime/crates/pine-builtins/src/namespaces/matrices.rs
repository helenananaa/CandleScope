use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const MATRIX_NEW_FLOAT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "rows",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "columns",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
];

const MATRIX_NEW_INT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "rows",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "columns",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const MATRIX_NEW_BOOL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "rows",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "columns",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const MATRIX_NEW_STRING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "rows",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "columns",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const MATRIX_NEW_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "rows",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "columns",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
];

const MATRIX_ANY_ID_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::Matrix,
    optional: false,
}];

const MATRIX_NUMERIC_ID_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::NumericMatrix,
    optional: false,
}];

const MATRIX_TWO_NUMERIC_ID_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id1",
        accepts: Accepts::NumericMatrix,
        optional: false,
    },
    BuiltinParam {
        name: "id2",
        accepts: Accepts::NumericMatrix,
        optional: false,
    },
];

const MATRIX_MATRIX_OR_NUMERIC_PAIR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id1",
        accepts: Accepts::MatrixOrNumericCompatibleWithMatrixCounterpart(1),
        optional: false,
    },
    BuiltinParam {
        name: "id2",
        accepts: Accepts::MatrixOrNumericCompatibleWithMatrixCounterpart(0),
        optional: false,
    },
];

const MATRIX_MULT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id1",
        accepts: Accepts::MatrixOrNumericOrNumericArrayCompatibleWithMatrixCounterpart(1),
        optional: false,
    },
    BuiltinParam {
        name: "id2",
        accepts: Accepts::MatrixOrNumericOrNumericArrayCompatibleWithMatrixCounterpart(0),
        optional: false,
    },
];

const MATRIX_GET_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_SET_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "value",
        accepts: Accepts::MatrixElementCompatible(0),
        optional: false,
    },
];

const MATRIX_FILL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "value",
        accepts: Accepts::MatrixElementCompatible(0),
        optional: false,
    },
];

const MATRIX_CONCAT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id1",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "id2",
        accepts: Accepts::Matrix,
        optional: false,
    },
];

const MATRIX_RESHAPE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "rows",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "columns",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_POW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericMatrix,
        optional: false,
    },
    BuiltinParam {
        name: "power",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_ADD_ROW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "array_id",
        accepts: Accepts::MatrixElementArray(0),
        optional: false,
    },
];

const MATRIX_ADD_COL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "array_id",
        accepts: Accepts::MatrixElementArray(0),
        optional: false,
    },
];

const MATRIX_REMOVE_ROW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_REMOVE_COL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_SWAP_ROWS_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "row1",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "row2",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_SWAP_COLUMNS_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "column1",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
    BuiltinParam {
        name: "column2",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_SORT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericMatrix,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::SimpleInt,
        optional: true,
    },
    BuiltinParam {
        name: "order",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const MATRIX_SUBMATRIX_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "from_row",
        accepts: Accepts::SimpleInt,
        optional: true,
    },
    BuiltinParam {
        name: "to_row",
        accepts: Accepts::SimpleInt,
        optional: true,
    },
    BuiltinParam {
        name: "from_column",
        accepts: Accepts::SimpleInt,
        optional: true,
    },
    BuiltinParam {
        name: "to_column",
        accepts: Accepts::SimpleInt,
        optional: true,
    },
];

const MATRIX_ROW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

const MATRIX_COL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Matrix,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::SimpleInt,
        optional: false,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "matrix.new<float>",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NEW_FLOAT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.new<int>",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NEW_INT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.new<bool>",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NEW_BOOL_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.new<string>",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NEW_STRING_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.new<color>",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NEW_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_COLOR_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.get",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_GET_PARAMS,
        returns: ReturnSpec::MatrixElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.set",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_SET_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.fill",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_FILL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.concat",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_CONCAT_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.copy",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ANY_ID_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.transpose",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ANY_ID_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.reverse",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ANY_ID_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.reshape",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_RESHAPE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.kron",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_TWO_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.mult",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_MULT_PARAMS,
        returns: ReturnSpec::MatrixMult,
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.diff",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_MATRIX_OR_NUMERIC_PAIR_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.pow",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_POW_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.add_row",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ADD_ROW_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.add_col",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ADD_COL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.remove_row",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_REMOVE_ROW_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.remove_col",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_REMOVE_COL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.swap_rows",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_SWAP_ROWS_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.swap_columns",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_SWAP_COLUMNS_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.sort",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_SORT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.submatrix",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_SUBMATRIX_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.rows",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ANY_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.columns",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ANY_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.elements_count",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ANY_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_square",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ANY_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_binary",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_diagonal",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_antidiagonal",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_triangular",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_identity",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_symmetric",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_antisymmetric",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_stochastic",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.is_zero",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.sum",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.avg",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.min",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.max",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.median",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::MatrixElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.mode",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.trace",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.det",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.eigenvalues",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.eigenvectors",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.inv",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.pinv",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_MATRIX),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.rank",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_NUMERIC_ID_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.row",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_ROW_PARAMS,
        returns: ReturnSpec::MatrixArray(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "matrix.col",
        phase: BuiltinPhase::Phase1Core,
        params: MATRIX_COL_PARAMS,
        returns: ReturnSpec::MatrixArray(0),
        variadic: false,
    },
];
