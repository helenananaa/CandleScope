use crate::analyzer::user_types::UserTypeArrayElementInference;
use crate::prelude::*;

impl Analyzer {
    pub(crate) fn validate_array_value_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) {
        let value_index = match signature.name {
            "array.push"
            | "array.unshift"
            | "array.fill"
            | "array.includes"
            | "array.indexof"
            | "array.lastindexof"
            | "array.binary_search"
            | "array.binary_search_leftmost"
            | "array.binary_search_rightmost" => 1,
            "array.set" | "array.insert" => 2,
            _ => return,
        };
        let Some(array_type) = arg_types.first().copied().flatten() else {
            return;
        };
        let Some(value_type) = arg_types.get(value_index).copied().flatten() else {
            return;
        };
        let Some(element_kind) = array_type.kind.array_element_kind() else {
            return;
        };
        if value_type.kind == ValueKind::Na
            || value_type.kind == element_kind
            || (element_kind == ValueKind::Float && value_type.kind == ValueKind::Int)
        {
            return;
        }
        let Some(expected) = array_element_expected_label(element_kind) else {
            return;
        };

        self.diagnostics.push(call_arg_expected_type_diagnostic(
            signature.name,
            "value",
            expected,
            value_type,
            args.get(value_index)
                .map_or(Span::default(), |arg| arg.span),
        ));
    }

    pub(crate) fn validate_array_concat_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) {
        if signature.name != "array.concat" {
            return;
        }
        let Some(first_type) = arg_types.first().copied().flatten() else {
            return;
        };
        let Some(second_type) = arg_types.get(1).copied().flatten() else {
            return;
        };
        if !is_array_kind(first_type.kind)
            || !is_array_kind(second_type.kind)
            || first_type.kind == second_type.kind
        {
            return;
        }

        let expected = pine_type_name(first_type);
        self.diagnostics.push(call_arg_expected_type_diagnostic(
            "array.concat",
            "id2",
            &expected,
            second_type,
            args.get(1).map_or(Span::default(), |arg| arg.span),
        ));
    }

    pub(crate) fn validate_array_from_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) {
        if signature.name != "array.from" {
            return;
        }
        if array_from_return_type(arg_types).is_some() {
            return;
        }
        match self.array_from_user_type_element_inference(args, arg_types) {
            Some(
                UserTypeArrayElementInference::SameScalarLocal(_)
                | UserTypeArrayElementInference::SameScalarImported(_),
            ) => return,
            Some(inference) => {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_TYPE",
                    array_from_user_type_inference_message(&inference),
                    args.first().map_or(Span::default(), |arg| arg.span),
                ));
                return;
            }
            None => {}
        }

        let actual = array_from_actual_arg_labels(arg_types);
        let message = match actual {
            Some(actual) => {
                format!("`array.from` expects one supported array element kind, got {actual}")
            }
            None => "`array.from` arguments must infer one supported array element kind".to_owned(),
        };
        self.diagnostics.push(Diagnostic::error(
            "E_CALL_ARG_TYPE",
            message,
            args.first().map_or(Span::default(), |arg| arg.span),
        ));
    }
}

fn array_from_actual_arg_labels(arg_types: &[Option<PineType>]) -> Option<String> {
    let labels: Option<Vec<_>> = arg_types
        .iter()
        .map(|arg_type| arg_type.map(pine_type_name))
        .collect();
    let labels = labels?;
    match labels.as_slice() {
        [] => None,
        [only] => Some(only.clone()),
        [head @ .., tail] => Some(format!("{} and {tail}", head.join(", "))),
    }
}

fn array_from_user_type_inference_message(inference: &UserTypeArrayElementInference) -> String {
    match inference {
        UserTypeArrayElementInference::SameScalarLocal(_)
        | UserTypeArrayElementInference::SameScalarImported(_) => {
            unreachable!("supported UDT array inference returns before diagnostics")
        }
        UserTypeArrayElementInference::MixedLocal => {
            "`array.from` expects one scalar-tree UDT identity, got mixed UDT identities".to_owned()
        }
        UserTypeArrayElementInference::UnsupportedFieldType(type_name) => {
            format!("`array.from` does not support UDT array `{type_name}` with non-scalar fields")
        }
        UserTypeArrayElementInference::UnknownUserTypeName => {
            "`array.from` expects supported scalar-tree UDT values".to_owned()
        }
    }
}

fn array_element_expected_label(element_kind: ValueKind) -> Option<&'static str> {
    match element_kind {
        ValueKind::Float => Some("numeric-compatible"),
        ValueKind::Int => Some("integer-compatible"),
        ValueKind::Bool => Some("bool-compatible"),
        ValueKind::String => Some("string-compatible"),
        ValueKind::Color => Some("color-compatible"),
        ValueKind::Label => Some("label-compatible"),
        ValueKind::Line => Some("line-compatible"),
        ValueKind::LineFill => Some("linefill-compatible"),
        ValueKind::Polyline => Some("polyline-compatible"),
        ValueKind::Box => Some("box-compatible"),
        ValueKind::Table => Some("table-compatible"),
        ValueKind::ChartPoint => Some("chart.point-compatible"),
        _ => None,
    }
}
