use super::*;
use std::collections::HashMap;

pub(super) fn pure_if_expr_series_key(
    analyzer: &Analyzer,
    condition: &Expr,
    then_branch: &[Stmt],
    else_branch: &[Stmt],
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    Some(format!(
        "if:{}:{}:{}",
        pure_expr_series_key_with_params(
            analyzer,
            condition,
            param_keys,
            allow_udf_calls,
            udf_stack
        )?,
        pure_branch_series_key_with_params(
            analyzer,
            then_branch,
            param_keys,
            allow_udf_calls,
            udf_stack
        )?,
        pure_branch_series_key_with_params(
            analyzer,
            else_branch,
            param_keys,
            allow_udf_calls,
            udf_stack
        )?
    ))
}

pub(super) fn pure_switch_expr_series_key(
    analyzer: &Analyzer,
    selector: Option<&Expr>,
    arms: &[SwitchArm],
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let selector_key = match selector {
        Some(selector) => pure_expr_series_key_with_params(
            analyzer,
            selector,
            param_keys,
            allow_udf_calls,
            udf_stack,
        )?,
        None => "selector:none".to_owned(),
    };
    let arm_keys = arms
        .iter()
        .map(|arm| {
            pure_switch_arm_series_key_with_params(
                analyzer,
                arm,
                param_keys,
                allow_udf_calls,
                udf_stack,
            )
        })
        .collect::<Option<Vec<_>>>()?;
    Some(format!("switch:{selector_key}:{}", arm_keys.join(":")))
}

pub(super) struct PureForExprSeriesKeyInput<'a> {
    pub(super) analyzer: &'a Analyzer,
    pub(super) counter: &'a str,
    pub(super) from: &'a Expr,
    pub(super) to: &'a Expr,
    pub(super) step: Option<&'a Expr>,
    pub(super) body: &'a [Stmt],
    pub(super) param_keys: &'a HashMap<String, String>,
    pub(super) allow_udf_calls: bool,
}

pub(super) fn pure_for_expr_series_key(
    input: PureForExprSeriesKeyInput<'_>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let PureForExprSeriesKeyInput {
        analyzer,
        counter,
        from,
        to,
        step,
        body,
        param_keys,
        allow_udf_calls,
    } = input;
    let from_key =
        pure_expr_series_key_with_params(analyzer, from, param_keys, allow_udf_calls, udf_stack)?;
    let to_key =
        pure_expr_series_key_with_params(analyzer, to, param_keys, allow_udf_calls, udf_stack)?;
    let step_key = match step {
        Some(step) => pure_expr_series_key_with_params(
            analyzer,
            step,
            param_keys,
            allow_udf_calls,
            udf_stack,
        )?,
        None => "step:none".to_owned(),
    };
    let counter_key = format!("for_counter:{counter}:from:{from_key}:to:{to_key}:step:{step_key}");
    let mut local_keys = param_keys.clone();
    local_keys.insert(counter.to_owned(), counter_key);
    Some(format!(
        "for:{counter}:from:{from_key}:to:{to_key}:step:{step_key}:{}",
        pure_branch_series_key_with_locals(
            analyzer,
            body,
            &mut local_keys,
            allow_udf_calls,
            udf_stack,
        )?
    ))
}

pub(super) struct PureForInExprSeriesKeyInput<'a> {
    pub(super) analyzer: &'a Analyzer,
    pub(super) index: Option<&'a str>,
    pub(super) value: &'a str,
    pub(super) iterable: &'a Expr,
    pub(super) body: &'a [Stmt],
    pub(super) param_keys: &'a HashMap<String, String>,
    pub(super) allow_udf_calls: bool,
}

pub(super) fn pure_for_in_expr_series_key(
    input: PureForInExprSeriesKeyInput<'_>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let PureForInExprSeriesKeyInput {
        analyzer,
        index,
        value,
        iterable,
        body,
        param_keys,
        allow_udf_calls,
    } = input;
    let iterable_key = pure_inline_array_from_iterable_key(
        analyzer,
        iterable,
        param_keys,
        allow_udf_calls,
        udf_stack,
    )?;
    let mut local_keys = param_keys.clone();
    if let Some(index) = index {
        local_keys.insert(
            index.to_owned(),
            format!("for_in_index:{index}:{iterable_key}"),
        );
    }
    local_keys.insert(
        value.to_owned(),
        format!("for_in_value:{value}:{iterable_key}"),
    );
    Some(format!(
        "for_in:index:{}:value:{value}:iterable:{iterable_key}:{}",
        index.unwrap_or("none"),
        pure_branch_series_key_with_locals(
            analyzer,
            body,
            &mut local_keys,
            allow_udf_calls,
            udf_stack,
        )?
    ))
}

pub(super) fn pure_while_expr_series_key(
    analyzer: &Analyzer,
    condition: &Expr,
    body: &[Stmt],
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    Some(format!(
        "while:{}:{}",
        pure_expr_series_key_with_params(
            analyzer,
            condition,
            param_keys,
            allow_udf_calls,
            udf_stack
        )?,
        pure_branch_series_key_with_params(analyzer, body, param_keys, allow_udf_calls, udf_stack)?
    ))
}

fn pure_inline_array_from_iterable_key(
    analyzer: &Analyzer,
    iterable: &Expr,
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let ExprKind::Call { callee, args } = &iterable.kind else {
        return None;
    };
    if expr_name(callee)? != "array.from" || args.iter().any(|arg| arg.name.is_some()) {
        return None;
    }
    let item_keys = args
        .iter()
        .map(|arg| {
            pure_expr_series_key_with_params(
                analyzer,
                &arg.value,
                param_keys,
                allow_udf_calls,
                udf_stack,
            )
        })
        .collect::<Option<Vec<_>>>()?;
    Some(format!("array_from:{}", item_keys.join(":")))
}

fn pure_branch_series_key_with_params(
    analyzer: &Analyzer,
    statements: &[Stmt],
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let mut local_keys = param_keys.clone();
    pure_branch_series_key_with_locals(
        analyzer,
        statements,
        &mut local_keys,
        allow_udf_calls,
        udf_stack,
    )
}

fn pure_branch_series_key_with_locals(
    analyzer: &Analyzer,
    statements: &[Stmt],
    local_keys: &mut HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let (last, prefix) = statements.split_last()?;
    let mut prefix_keys = Vec::new();
    for statement in prefix {
        let key = pure_prefix_statement_series_key_with_params(
            analyzer,
            statement,
            local_keys,
            allow_udf_calls,
            udf_stack,
        )?;
        prefix_keys.push(key);
    }
    let StmtKind::Expr(result) = &last.kind else {
        return None;
    };
    let result_key =
        pure_expr_series_key_with_params(analyzer, result, local_keys, allow_udf_calls, udf_stack)?;
    Some(format!(
        "block:{}:result:{result_key}",
        prefix_keys.join(":")
    ))
}

fn pure_prefix_statement_series_key_with_params(
    analyzer: &Analyzer,
    statement: &Stmt,
    local_keys: &mut HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    match &statement.kind {
        StmtKind::Decl {
            mode,
            declared_type: _,
            name,
            value,
        } => {
            if *mode != pine_syntax::DeclMode::Normal {
                return None;
            }
            let field_aliases = alias_field_param_keys(name, value, local_keys);
            let value_key = pure_expr_series_key_with_params(
                analyzer,
                value,
                local_keys,
                allow_udf_calls,
                udf_stack,
            )?;
            if local_keys.insert(name.clone(), value_key.clone()).is_some() {
                return None;
            }
            local_keys.extend(field_aliases);
            Some(format!("decl:{name}:{value_key}"))
        }
        StmtKind::Expr(expr) => {
            let expr_key = pure_expr_series_key_with_params(
                analyzer,
                expr,
                local_keys,
                allow_udf_calls,
                udf_stack,
            )?;
            Some(format!("expr:{expr_key}"))
        }
        _ => None,
    }
}

fn pure_switch_arm_series_key_with_params(
    analyzer: &Analyzer,
    arm: &SwitchArm,
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let condition_key = match &arm.condition {
        Some(condition) => pure_expr_series_key_with_params(
            analyzer,
            condition,
            param_keys,
            allow_udf_calls,
            udf_stack,
        )?,
        None => "condition:none".to_owned(),
    };
    let result_key = match &arm.result {
        SwitchArmResult::Expr(expr) => pure_expr_series_key_with_params(
            analyzer,
            expr,
            param_keys,
            allow_udf_calls,
            udf_stack,
        )?,
        SwitchArmResult::Block(statements) => pure_branch_series_key_with_params(
            analyzer,
            statements,
            param_keys,
            allow_udf_calls,
            udf_stack,
        )?,
    };
    Some(format!("arm:{condition_key}:{result_key}"))
}
