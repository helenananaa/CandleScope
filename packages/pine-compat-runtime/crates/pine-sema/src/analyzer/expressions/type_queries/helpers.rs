use crate::prelude::*;

pub(super) fn map_new_template_types(name: &str) -> Option<(&str, &str)> {
    let inner = name.strip_prefix("map.new<")?.strip_suffix('>')?;
    inner.split_once(',')
}

pub(super) fn selected_branch_type(
    condition_qualifier: Qualifier,
    then_type: PineType,
    else_type: PineType,
    condition_value: bool,
) -> Option<PineType> {
    let selected_type = if condition_value {
        then_type
    } else {
        else_type
    };
    Some(PineType::new(
        strongest_qualifier(condition_qualifier, selected_type.qualifier),
        common_kind(then_type.kind, else_type.kind)?,
    ))
}

pub(super) fn merge_tuple_element_types(
    current: Option<Vec<PineType>>,
    next: Vec<PineType>,
) -> Option<Vec<PineType>> {
    let Some(current) = current else {
        return Some(next);
    };
    if current.len() != next.len() {
        return None;
    }
    current
        .into_iter()
        .zip(next)
        .map(|(current, next)| merge_result_types(Some(current), next))
        .collect()
}

pub(super) fn selected_tuple_branch_types(
    condition_qualifier: Qualifier,
    then_types: Vec<PineType>,
    else_types: Vec<PineType>,
    condition_value: bool,
) -> Option<Vec<PineType>> {
    if then_types.len() != else_types.len() {
        return None;
    }

    let selected_types = if condition_value {
        then_types.iter()
    } else {
        else_types.iter()
    };

    selected_types
        .zip(then_types.iter().zip(else_types.iter()))
        .map(|(selected_type, (then_type, else_type))| {
            Some(PineType::new(
                strongest_qualifier(condition_qualifier, selected_type.qualifier),
                common_kind(then_type.kind, else_type.kind)?,
            ))
        })
        .collect()
}

pub(super) fn promote_tuple_element_qualifiers(
    types: Vec<PineType>,
    qualifier: Qualifier,
) -> Vec<PineType> {
    types
        .into_iter()
        .map(|pine_type| {
            PineType::new(
                strongest_qualifier(qualifier, pine_type.qualifier),
                pine_type.kind,
            )
        })
        .collect()
}
