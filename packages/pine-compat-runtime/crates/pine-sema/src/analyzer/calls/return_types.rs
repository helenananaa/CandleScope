use crate::prelude::*;

impl Analyzer {
    pub(crate) fn return_type_for_call(
        &self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> Option<PineType> {
        if signature.variadic {
            return self.return_type(signature, arg_types);
        }

        // Indexed return specs refer to signature parameter slots, while named
        // arguments remain in source order in the AST. Other return specs use
        // the complete source argument list and must keep its existing shape.
        let referenced_param = match signature.returns {
            ReturnSpec::SameAsArg(index)
            | ReturnSpec::BoolFromArg(index)
            | ReturnSpec::ColorFromArg(index)
            | ReturnSpec::FloatFromStringArg(index)
            | ReturnSpec::ArrayElement(index)
            | ReturnSpec::ArrayNumeric(index)
            | ReturnSpec::MatrixElement(index)
            | ReturnSpec::MatrixArray(index)
            | ReturnSpec::IntFromArg(index)
            | ReturnSpec::FloatFromArg(index)
            | ReturnSpec::SeriesFromArg(index)
            | ReturnSpec::ChangeFromArg(index)
            | ReturnSpec::InputFromArg(index) => index,
            _ => return self.return_type(signature, arg_types),
        };
        let referenced_type = args.iter().enumerate().find_map(|(arg_index, arg)| {
            (super::param_index_for_arg(signature, arg_index, arg)? == referenced_param)
                .then(|| arg_types.get(arg_index).copied().flatten())
                .flatten()
        });
        let mut param_types = vec![None; referenced_param + 1];
        param_types[referenced_param] = referenced_type;
        self.return_type(signature, &param_types)
    }

    pub(crate) fn return_type(
        &self,
        signature: &BuiltinSignature,
        arg_types: &[Option<PineType>],
    ) -> Option<PineType> {
        match signature.returns {
            ReturnSpec::Fixed(pine_type) => Some(pine_type),
            ReturnSpec::Tuple(_) => Some(pine_builtins::tuple_return_type()),
            ReturnSpec::SameAsArg(index) => arg_types.get(index).copied().flatten(),
            ReturnSpec::BoolFromArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .map(pine_builtins::fallback_bool_for_arg),
            ReturnSpec::ColorFromArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .map(pine_builtins::color_return_for_arg),
            ReturnSpec::PromotedColor => promoted_color_type(arg_types),
            ReturnSpec::PromotedBool => promoted_bool_type(arg_types),
            ReturnSpec::PromotedInt => promoted_int_type(arg_types),
            ReturnSpec::PromotedString => promoted_string_type(arg_types),
            ReturnSpec::FloatFromStringArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .map(float_return_for_arg),
            ReturnSpec::PromotedNumeric => promoted_numeric_type(arg_types),
            ReturnSpec::ArrayElement(index) => array_element_return_type(arg_types, index),
            ReturnSpec::ArrayNumeric(index) => array_numeric_return_type(arg_types, index),
            ReturnSpec::ArrayFromArgs => array_from_return_type(arg_types),
            ReturnSpec::MatrixElement(index) => matrix_element_return_type(arg_types, index),
            ReturnSpec::MatrixArray(index) => matrix_array_return_type(arg_types, index),
            ReturnSpec::MatrixMult => matrix_mult_return_type(arg_types),
            ReturnSpec::IntFromArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .map(int_return_for_arg),
            ReturnSpec::FloatFromArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .map(float_return_for_arg),
            ReturnSpec::SeriesFromArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .and_then(series_return_for_arg),
            ReturnSpec::ChangeFromArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .and_then(pine_builtins::change_return_for_arg),
            ReturnSpec::PromotedFloat => promoted_float_type(arg_types),
            ReturnSpec::Round => round_return_type(arg_types),
            ReturnSpec::InputFromArg(index) => arg_types
                .get(index)
                .copied()
                .flatten()
                .and_then(pine_builtins::input_return_for_arg),
        }
    }
}
