use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{BinaryOp, Expr, ExprKind, Literal, UnaryOp};

pub(crate) fn const_int_value(expr: &Expr) -> Option<i64> {
    match &expr.kind {
        ExprKind::Literal(Literal::Int(value)) => Some(*value),
        ExprKind::QualifiedName(parts) => pine_builtins::named_int_constant(&parts.join(".")),
        ExprKind::Unary {
            op: UnaryOp::Plus,
            expr,
        } => const_int_value(expr),
        ExprKind::Unary {
            op: UnaryOp::Minus,
            expr,
        } => const_int_value(expr).and_then(i64::checked_neg),
        ExprKind::Binary {
            op: BinaryOp::Add,
            left,
            right,
        } => const_int_value(left)?.checked_add(const_int_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Sub,
            left,
            right,
        } => const_int_value(left)?.checked_sub(const_int_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Mul,
            left,
            right,
        } => const_int_value(left)?.checked_mul(const_int_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Mod,
            left,
            right,
        } => const_int_value(left)?.checked_rem(const_int_value(right)?),
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            if const_bool_value(condition)? {
                const_int_value(then_expr)
            } else {
                const_int_value(else_expr)
            }
        }
        _ => None,
    }
}

pub(crate) fn const_numeric_value(expr: &Expr) -> Option<f64> {
    match &expr.kind {
        ExprKind::Literal(Literal::Int(value)) => Some(*value as f64),
        ExprKind::Literal(Literal::Float(value)) => Some(*value),
        ExprKind::QualifiedName(parts) => named_numeric_constant(&parts.join(".")),
        ExprKind::Unary {
            op: UnaryOp::Plus,
            expr,
        } => const_numeric_value(expr),
        ExprKind::Unary {
            op: UnaryOp::Minus,
            expr,
        } => const_numeric_value(expr).map(|value| -value),
        ExprKind::Binary {
            op: BinaryOp::Add,
            left,
            right,
        } => Some(const_numeric_value(left)? + const_numeric_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Sub,
            left,
            right,
        } => Some(const_numeric_value(left)? - const_numeric_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Mul,
            left,
            right,
        } => Some(const_numeric_value(left)? * const_numeric_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Div,
            left,
            right,
        } => finite_numeric(const_numeric_value(left)? / const_numeric_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Mod,
            left,
            right,
        } => finite_numeric(const_numeric_value(left)? % const_numeric_value(right)?),
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            if const_bool_value(condition)? {
                const_numeric_value(then_expr)
            } else {
                const_numeric_value(else_expr)
            }
        }
        _ => None,
    }
}

fn const_bool_value(expr: &Expr) -> Option<bool> {
    match &expr.kind {
        ExprKind::Literal(Literal::Bool(value)) => Some(*value),
        ExprKind::Unary {
            op: UnaryOp::Not,
            expr,
        } => const_bool_value(expr).map(|value| !value),
        ExprKind::Binary {
            op: BinaryOp::And,
            left,
            right,
        } => Some(const_bool_value(left)? && const_bool_value(right)?),
        ExprKind::Binary {
            op: BinaryOp::Or,
            left,
            right,
        } => Some(const_bool_value(left)? || const_bool_value(right)?),
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            if const_bool_value(condition)? {
                const_bool_value(then_expr)
            } else {
                const_bool_value(else_expr)
            }
        }
        ExprKind::Binary {
            op:
                op @ (BinaryOp::Eq
                | BinaryOp::NotEq
                | BinaryOp::Gt
                | BinaryOp::Gte
                | BinaryOp::Lt
                | BinaryOp::Lte),
            left,
            right,
        } => const_numeric_comparison(*op, left, right)
            .or_else(|| {
                let left = const_bool_value(left)?;
                let right = const_bool_value(right)?;
                match *op {
                    BinaryOp::Eq => Some(left == right),
                    BinaryOp::NotEq => Some(left != right),
                    _ => None,
                }
            })
            .or_else(|| {
                let left = const_string_value(left)?;
                let right = const_string_value(right)?;
                match *op {
                    BinaryOp::Eq => Some(left == right),
                    BinaryOp::NotEq => Some(left != right),
                    _ => None,
                }
            })
            .or_else(|| {
                let left = const_color_value(left)?;
                let right = const_color_value(right)?;
                match *op {
                    BinaryOp::Eq => Some(left == right),
                    BinaryOp::NotEq => Some(left != right),
                    _ => None,
                }
            }),
        _ => None,
    }
}

fn const_numeric_comparison(op: BinaryOp, left: &Expr, right: &Expr) -> Option<bool> {
    let left = const_numeric_value(left)?;
    let right = const_numeric_value(right)?;
    Some(match op {
        BinaryOp::Eq => left == right,
        BinaryOp::NotEq => left != right,
        BinaryOp::Gt => left > right,
        BinaryOp::Gte => left >= right,
        BinaryOp::Lt => left < right,
        BinaryOp::Lte => left <= right,
        _ => return None,
    })
}

fn named_numeric_constant(name: &str) -> Option<f64> {
    pine_builtins::named_float_constant(name)
        .or_else(|| pine_builtins::named_int_constant(name).map(|value| value as f64))
}

fn finite_numeric(value: f64) -> Option<f64> {
    value.is_finite().then_some(value)
}

pub(crate) fn const_string_value(expr: &Expr) -> Option<String> {
    match &expr.kind {
        ExprKind::Literal(Literal::String(value)) => Some(value.clone()),
        ExprKind::QualifiedName(parts) => {
            pine_builtins::named_string_constant(&parts.join(".")).map(str::to_owned)
        }
        ExprKind::Binary {
            op: BinaryOp::Add,
            left,
            right,
        } => {
            let mut value = const_string_value(left)?;
            value.push_str(&const_string_value(right)?);
            Some(value)
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            if const_bool_value(condition)? {
                const_string_value(then_expr)
            } else {
                const_string_value(else_expr)
            }
        }
        _ => None,
    }
}

pub(crate) fn const_color_value(expr: &Expr) -> Option<u32> {
    match &expr.kind {
        ExprKind::Literal(Literal::ColorHex(value)) => parse_color_hex(value),
        ExprKind::QualifiedName(parts) => pine_builtins::named_color(&parts.join(".")),
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            if const_bool_value(condition)? {
                const_color_value(then_expr)
            } else {
                const_color_value(else_expr)
            }
        }
        _ => None,
    }
}

fn parse_color_hex(value: &str) -> Option<u32> {
    u32::from_str_radix(value.trim_start_matches('#'), 16).ok()
}

pub(crate) fn literal_type(literal: &Literal) -> PineType {
    match literal {
        Literal::Int(_) => PineType::new(Qualifier::Const, ValueKind::Int),
        Literal::Float(_) => PineType::new(Qualifier::Const, ValueKind::Float),
        Literal::Bool(_) => PineType::new(Qualifier::Const, ValueKind::Bool),
        Literal::String(_) => PineType::new(Qualifier::Const, ValueKind::String),
        Literal::ColorHex(_) => PineType::new(Qualifier::Const, ValueKind::Color),
    }
}
