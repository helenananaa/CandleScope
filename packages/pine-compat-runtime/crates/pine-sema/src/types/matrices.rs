use pine_builtins::Accepts;
use pine_ir::{PineType, Qualifier, ValueKind};

use super::accepts_type;

pub(crate) fn matrix_element_return_type(
    arg_types: &[Option<PineType>],
    index: usize,
) -> Option<PineType> {
    let matrix_type = arg_types.get(index).copied().flatten()?;
    let kind = match matrix_type.kind {
        ValueKind::FloatMatrix => ValueKind::Float,
        ValueKind::IntMatrix => ValueKind::Int,
        ValueKind::BoolMatrix => ValueKind::Bool,
        ValueKind::StringMatrix => ValueKind::String,
        ValueKind::ColorMatrix => ValueKind::Color,
        _ => return None,
    };
    Some(PineType::new(Qualifier::Series, kind))
}

pub(crate) fn matrix_array_return_type(
    arg_types: &[Option<PineType>],
    index: usize,
) -> Option<PineType> {
    let matrix_type = arg_types.get(index).copied().flatten()?;
    let kind = match matrix_type.kind {
        ValueKind::FloatMatrix => ValueKind::FloatArray,
        ValueKind::IntMatrix => ValueKind::IntArray,
        ValueKind::BoolMatrix => ValueKind::BoolArray,
        ValueKind::StringMatrix => ValueKind::StringArray,
        ValueKind::ColorMatrix => ValueKind::ColorArray,
        _ => return None,
    };
    Some(PineType::new(Qualifier::Simple, kind))
}

pub(crate) fn matrix_mult_return_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    let left_type = arg_types.first().copied().flatten()?;
    let right_type = arg_types.get(1).copied().flatten()?;
    if matches!(
        (left_type.kind, right_type.kind),
        (ValueKind::FloatArray | ValueKind::IntArray, _)
            | (_, ValueKind::FloatArray | ValueKind::IntArray)
    ) {
        return Some(PineType::new(Qualifier::Simple, ValueKind::FloatArray));
    }
    Some(PineType::new(Qualifier::Simple, ValueKind::FloatMatrix))
}

pub(crate) fn accepts_matrix_element_arg(
    matrix_type: PineType,
    arg_type: PineType,
) -> Option<bool> {
    match matrix_type.kind {
        ValueKind::FloatMatrix => Some(accepts_type(Accepts::NumericCompatible, arg_type)),
        ValueKind::IntMatrix => Some(accepts_type(Accepts::IntCompatible, arg_type)),
        ValueKind::BoolMatrix => Some(accepts_type(Accepts::BoolCompatible, arg_type)),
        ValueKind::StringMatrix => Some(accepts_type(Accepts::StringCompatible, arg_type)),
        ValueKind::ColorMatrix => Some(accepts_type(Accepts::ColorCompatible, arg_type)),
        _ => None,
    }
}

pub(crate) fn accepts_matrix_element_array_arg(
    matrix_type: PineType,
    arg_type: PineType,
) -> Option<bool> {
    match matrix_type.kind {
        ValueKind::FloatMatrix => Some(accepts_type(
            Accepts::Exact(PineType::new(Qualifier::Simple, ValueKind::FloatArray)),
            arg_type,
        )),
        ValueKind::IntMatrix => Some(accepts_type(
            Accepts::Exact(PineType::new(Qualifier::Simple, ValueKind::IntArray)),
            arg_type,
        )),
        ValueKind::BoolMatrix => Some(accepts_type(
            Accepts::Exact(PineType::new(Qualifier::Simple, ValueKind::BoolArray)),
            arg_type,
        )),
        ValueKind::StringMatrix => Some(accepts_type(
            Accepts::Exact(PineType::new(Qualifier::Simple, ValueKind::StringArray)),
            arg_type,
        )),
        ValueKind::ColorMatrix => Some(accepts_type(
            Accepts::Exact(PineType::new(Qualifier::Simple, ValueKind::ColorArray)),
            arg_type,
        )),
        _ => None,
    }
}

pub(crate) fn is_matrix_kind(kind: ValueKind) -> bool {
    matches!(
        kind,
        ValueKind::FloatMatrix
            | ValueKind::IntMatrix
            | ValueKind::BoolMatrix
            | ValueKind::StringMatrix
            | ValueKind::ColorMatrix
    )
}

pub(crate) fn is_numeric_matrix_kind(kind: ValueKind) -> bool {
    matches!(kind, ValueKind::FloatMatrix | ValueKind::IntMatrix)
}

pub(crate) fn matrix_method_builtin_name(kind: ValueKind, method: &str) -> Option<&'static str> {
    if kind == ValueKind::IntMatrix {
        return match method {
            "add_col" => Some("matrix.add_col"),
            "add_row" => Some("matrix.add_row"),
            "avg" => Some("matrix.avg"),
            "copy" => Some("matrix.copy"),
            "columns" => Some("matrix.columns"),
            "concat" => Some("matrix.concat"),
            "elements_count" => Some("matrix.elements_count"),
            "fill" => Some("matrix.fill"),
            "get" => Some("matrix.get"),
            "is_antidiagonal" => Some("matrix.is_antidiagonal"),
            "is_antisymmetric" => Some("matrix.is_antisymmetric"),
            "is_binary" => Some("matrix.is_binary"),
            "is_diagonal" => Some("matrix.is_diagonal"),
            "is_identity" => Some("matrix.is_identity"),
            "is_square" => Some("matrix.is_square"),
            "is_stochastic" => Some("matrix.is_stochastic"),
            "is_symmetric" => Some("matrix.is_symmetric"),
            "is_triangular" => Some("matrix.is_triangular"),
            "is_zero" => Some("matrix.is_zero"),
            "col" => Some("matrix.col"),
            "diff" => Some("matrix.diff"),
            "det" => Some("matrix.det"),
            "eigenvalues" => Some("matrix.eigenvalues"),
            "eigenvectors" => Some("matrix.eigenvectors"),
            "inv" => Some("matrix.inv"),
            "kron" => Some("matrix.kron"),
            "max" => Some("matrix.max"),
            "median" => Some("matrix.median"),
            "min" => Some("matrix.min"),
            "mode" => Some("matrix.mode"),
            "mult" => Some("matrix.mult"),
            "pinv" => Some("matrix.pinv"),
            "pow" => Some("matrix.pow"),
            "rank" => Some("matrix.rank"),
            "reshape" => Some("matrix.reshape"),
            "remove_col" => Some("matrix.remove_col"),
            "remove_row" => Some("matrix.remove_row"),
            "reverse" => Some("matrix.reverse"),
            "row" => Some("matrix.row"),
            "rows" => Some("matrix.rows"),
            "set" => Some("matrix.set"),
            "sort" => Some("matrix.sort"),
            "submatrix" => Some("matrix.submatrix"),
            "sum" => Some("matrix.sum"),
            "swap_columns" => Some("matrix.swap_columns"),
            "swap_rows" => Some("matrix.swap_rows"),
            "trace" => Some("matrix.trace"),
            "transpose" => Some("matrix.transpose"),
            _ => None,
        };
    }
    if kind == ValueKind::BoolMatrix {
        return match method {
            "add_col" => Some("matrix.add_col"),
            "add_row" => Some("matrix.add_row"),
            "col" => Some("matrix.col"),
            "columns" => Some("matrix.columns"),
            "concat" => Some("matrix.concat"),
            "copy" => Some("matrix.copy"),
            "elements_count" => Some("matrix.elements_count"),
            "fill" => Some("matrix.fill"),
            "get" => Some("matrix.get"),
            "is_square" => Some("matrix.is_square"),
            "remove_col" => Some("matrix.remove_col"),
            "remove_row" => Some("matrix.remove_row"),
            "reshape" => Some("matrix.reshape"),
            "reverse" => Some("matrix.reverse"),
            "row" => Some("matrix.row"),
            "rows" => Some("matrix.rows"),
            "set" => Some("matrix.set"),
            "submatrix" => Some("matrix.submatrix"),
            "swap_columns" => Some("matrix.swap_columns"),
            "swap_rows" => Some("matrix.swap_rows"),
            "transpose" => Some("matrix.transpose"),
            _ => None,
        };
    }
    if kind == ValueKind::StringMatrix {
        return match method {
            "add_col" => Some("matrix.add_col"),
            "add_row" => Some("matrix.add_row"),
            "col" => Some("matrix.col"),
            "columns" => Some("matrix.columns"),
            "concat" => Some("matrix.concat"),
            "copy" => Some("matrix.copy"),
            "elements_count" => Some("matrix.elements_count"),
            "fill" => Some("matrix.fill"),
            "get" => Some("matrix.get"),
            "is_square" => Some("matrix.is_square"),
            "remove_col" => Some("matrix.remove_col"),
            "remove_row" => Some("matrix.remove_row"),
            "reshape" => Some("matrix.reshape"),
            "reverse" => Some("matrix.reverse"),
            "row" => Some("matrix.row"),
            "rows" => Some("matrix.rows"),
            "set" => Some("matrix.set"),
            "submatrix" => Some("matrix.submatrix"),
            "swap_columns" => Some("matrix.swap_columns"),
            "swap_rows" => Some("matrix.swap_rows"),
            "transpose" => Some("matrix.transpose"),
            _ => None,
        };
    }
    if kind == ValueKind::ColorMatrix {
        return match method {
            "add_col" => Some("matrix.add_col"),
            "add_row" => Some("matrix.add_row"),
            "col" => Some("matrix.col"),
            "columns" => Some("matrix.columns"),
            "concat" => Some("matrix.concat"),
            "copy" => Some("matrix.copy"),
            "elements_count" => Some("matrix.elements_count"),
            "fill" => Some("matrix.fill"),
            "get" => Some("matrix.get"),
            "is_square" => Some("matrix.is_square"),
            "remove_col" => Some("matrix.remove_col"),
            "remove_row" => Some("matrix.remove_row"),
            "reshape" => Some("matrix.reshape"),
            "reverse" => Some("matrix.reverse"),
            "row" => Some("matrix.row"),
            "rows" => Some("matrix.rows"),
            "set" => Some("matrix.set"),
            "submatrix" => Some("matrix.submatrix"),
            "swap_columns" => Some("matrix.swap_columns"),
            "swap_rows" => Some("matrix.swap_rows"),
            "transpose" => Some("matrix.transpose"),
            _ => None,
        };
    }
    if kind != ValueKind::FloatMatrix {
        return None;
    }
    match method {
        "add_col" => Some("matrix.add_col"),
        "add_row" => Some("matrix.add_row"),
        "avg" => Some("matrix.avg"),
        "copy" => Some("matrix.copy"),
        "concat" => Some("matrix.concat"),
        "col" => Some("matrix.col"),
        "det" => Some("matrix.det"),
        "diff" => Some("matrix.diff"),
        "eigenvalues" => Some("matrix.eigenvalues"),
        "eigenvectors" => Some("matrix.eigenvectors"),
        "elements_count" => Some("matrix.elements_count"),
        "fill" => Some("matrix.fill"),
        "get" => Some("matrix.get"),
        "is_antidiagonal" => Some("matrix.is_antidiagonal"),
        "is_square" => Some("matrix.is_square"),
        "is_binary" => Some("matrix.is_binary"),
        "is_diagonal" => Some("matrix.is_diagonal"),
        "is_identity" => Some("matrix.is_identity"),
        "is_symmetric" => Some("matrix.is_symmetric"),
        "is_antisymmetric" => Some("matrix.is_antisymmetric"),
        "is_stochastic" => Some("matrix.is_stochastic"),
        "is_triangular" => Some("matrix.is_triangular"),
        "is_zero" => Some("matrix.is_zero"),
        "inv" => Some("matrix.inv"),
        "kron" => Some("matrix.kron"),
        "max" => Some("matrix.max"),
        "median" => Some("matrix.median"),
        "min" => Some("matrix.min"),
        "mode" => Some("matrix.mode"),
        "mult" => Some("matrix.mult"),
        "pinv" => Some("matrix.pinv"),
        "pow" => Some("matrix.pow"),
        "rank" => Some("matrix.rank"),
        "reverse" => Some("matrix.reverse"),
        "remove_col" => Some("matrix.remove_col"),
        "remove_row" => Some("matrix.remove_row"),
        "reshape" => Some("matrix.reshape"),
        "row" => Some("matrix.row"),
        "set" => Some("matrix.set"),
        "sort" => Some("matrix.sort"),
        "submatrix" => Some("matrix.submatrix"),
        "sum" => Some("matrix.sum"),
        "swap_columns" => Some("matrix.swap_columns"),
        "swap_rows" => Some("matrix.swap_rows"),
        "trace" => Some("matrix.trace"),
        "transpose" => Some("matrix.transpose"),
        "rows" => Some("matrix.rows"),
        "columns" => Some("matrix.columns"),
        _ => None,
    }
}
