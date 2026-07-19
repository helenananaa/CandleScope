use crate::prelude::*;

impl Analyzer {
    pub(crate) fn validate_matrix_concat_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) {
        if signature.name != "matrix.concat" {
            return;
        }
        let Some(first_type) = arg_types.first().copied().flatten() else {
            return;
        };
        let Some(second_type) = arg_types.get(1).copied().flatten() else {
            return;
        };
        if !is_matrix_kind(first_type.kind)
            || !is_matrix_kind(second_type.kind)
            || first_type.kind == second_type.kind
        {
            return;
        }

        self.diagnostics.push(call_arg_expected_type_diagnostic(
            "matrix.concat",
            "id2",
            &pine_type_name(first_type),
            second_type,
            args.get(1).map_or(Span::default(), |arg| arg.span),
        ));
    }
}
