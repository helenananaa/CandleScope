use crate::prelude::*;

pub(crate) fn prepend_block_statements(mut prefix: Vec<HirStmt>, expr: HirExpr) -> HirExpr {
    match expr.kind {
        HirExprKind::Block { statements, result } => {
            prefix.extend(statements);
            HirExpr {
                kind: HirExprKind::Block {
                    statements: prefix,
                    result,
                },
                pine_type: expr.pine_type,
                series_id: expr.series_id,
            }
        }
        _ => HirExpr {
            pine_type: expr.pine_type,
            series_id: expr.series_id,
            kind: HirExprKind::Block {
                statements: prefix,
                result: Box::new(expr),
            },
        },
    }
}
