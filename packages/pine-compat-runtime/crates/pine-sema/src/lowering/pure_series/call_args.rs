use super::*;
use std::collections::HashMap;

pub(super) fn pure_variadic_named_call_arg_keys(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<Vec<String>> {
    let signature = pine_builtins::get_phase_1_builtin(name)?;
    if !signature.variadic || args.len() > signature.params.len() {
        return None;
    }

    let mut arg_keys = vec![None; signature.params.len()];
    let mut saw_named = false;
    for (index, arg) in args.iter().enumerate() {
        let param_index = if let Some(arg_name) = &arg.name {
            saw_named = true;
            signature
                .params
                .iter()
                .position(|param| param.name == arg_name)?
        } else {
            if saw_named {
                return None;
            }
            index
        };
        if arg_keys.get(param_index)?.is_some() {
            return None;
        }
        arg_keys[param_index] = Some(pure_expr_series_key_with_params(
            analyzer,
            &arg.value,
            param_keys,
            allow_udf_calls,
            udf_stack,
        )?);
    }

    arg_keys.into_iter().collect()
}

pub(super) fn pure_fixed_call_arg_keys(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<Vec<String>> {
    let signature = pine_builtins::get_phase_1_builtin(name)?;
    if signature.variadic || args.len() > signature.params.len() {
        return None;
    }

    let mut arg_keys = vec![None; signature.params.len()];
    let mut saw_named = false;
    for (index, arg) in args.iter().enumerate() {
        let param_index = if let Some(arg_name) = &arg.name {
            saw_named = true;
            signature
                .params
                .iter()
                .position(|param| param.name == arg_name)?
        } else {
            if saw_named {
                return None;
            }
            index
        };
        if arg_keys.get(param_index)?.is_some() {
            return None;
        }
        arg_keys[param_index] = Some(pure_expr_series_key_with_params(
            analyzer,
            &arg.value,
            param_keys,
            allow_udf_calls,
            udf_stack,
        )?);
    }

    signature
        .params
        .iter()
        .zip(arg_keys)
        .map(|(param, arg_key)| {
            if param.optional {
                Some(arg_key.unwrap_or_else(|| "arg:none".to_owned()))
            } else {
                arg_key
            }
        })
        .collect()
}
