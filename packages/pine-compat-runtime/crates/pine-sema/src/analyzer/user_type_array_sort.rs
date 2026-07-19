use pine_builtins::Accepts;
use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{CallArg, Diagnostic, Span};

use crate::analyzer::calls::{
    call_arg_accepts_type_expected_diagnostic, call_requirement_diagnostic,
};
use crate::analyzer::context::Analyzer;

const SORT_PARAM_NAMES: [&str; 3] = ["id", "order", "sort_field"];

pub(crate) fn array_new_user_type_name(name: &str) -> Option<&str> {
    let type_name = name.strip_prefix("array.new<")?.strip_suffix('>')?;
    (type_name != "chart.point").then_some(type_name)
}

pub(crate) fn is_user_type_array_ordering_call(
    name: &str,
    args: &[CallArg],
    arg_types: &[Option<PineType>],
) -> bool {
    matches!(name, "array.sort" | "array.sort_indices")
        && user_type_array_sort_arg(args, 0).is_some_and(|(index, _)| {
            matches!(
                arg_types.get(index).copied().flatten().map(|ty| ty.kind),
                Some(ValueKind::UserTypeArray)
            )
        })
}

pub(crate) fn user_type_array_sort_arg(
    args: &[CallArg],
    param_index: usize,
) -> Option<(usize, &CallArg)> {
    let param_name = SORT_PARAM_NAMES.get(param_index)?;
    args.iter().enumerate().find(|(arg_index, arg)| {
        arg.name.as_deref() == Some(*param_name)
            || (arg.name.is_none() && *arg_index == param_index)
    })
}

impl Analyzer {
    pub(crate) fn analyze_user_type_array_sort_call(
        &mut self,
        name: &str,
        span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> Option<PineType> {
        self.validate_user_type_array_sort_bindings(name, span, args);

        if let Some((index, arg)) = user_type_array_sort_arg(args, 1)
            && let Some(order_type) = arg_types.get(index).copied().flatten()
            && let Some(diagnostic) = call_arg_accepts_type_expected_diagnostic(
                name,
                "order",
                Accepts::ConstString,
                order_type,
                arg.span,
            )
        {
            self.diagnostics.push(diagnostic);
        }
        if let Some((index, arg)) = user_type_array_sort_arg(args, 2)
            && let Some(field_type) = arg_types.get(index).copied().flatten()
            && (field_type.qualifier != Qualifier::Const
                || !matches!(field_type.kind, ValueKind::Int | ValueKind::String))
        {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_TYPE",
                format!(
                    "`{name}` argument `sort_field` expects const int or string, got {}",
                    crate::types::pine_type_name(field_type)
                ),
                arg.span,
            ));
        }
        if self.user_type_array_sort_field_index(args).is_none() {
            self.diagnostics.push(call_requirement_diagnostic(
                name,
                "a scalar-tree UDT array and a root int, float, or string `sort_field`",
                user_type_array_sort_arg(args, 2).map_or(span, |(_, arg)| arg.span),
            ));
        }
        let pine_type = if name == "array.sort_indices" {
            PineType::new(Qualifier::Simple, ValueKind::IntArray)
        } else {
            PineType::new(Qualifier::Const, ValueKind::Void)
        };
        Some(pine_type)
    }

    fn validate_user_type_array_sort_bindings(&mut self, name: &str, span: Span, args: &[CallArg]) {
        if args.len() > SORT_PARAM_NAMES.len() {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`{name}` expects at most {} argument(s), got {}",
                    SORT_PARAM_NAMES.len(),
                    args.len()
                ),
                args[SORT_PARAM_NAMES.len()].span,
            ));
        }

        let mut bound = [false; SORT_PARAM_NAMES.len()];
        let mut saw_named = false;
        for (arg_index, arg) in args.iter().enumerate().take(SORT_PARAM_NAMES.len()) {
            let param_index = if let Some(arg_name) = arg.name.as_deref() {
                saw_named = true;
                let Some(param_index) = SORT_PARAM_NAMES
                    .iter()
                    .position(|param_name| *param_name == arg_name)
                else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_CALL_ARG_NAME",
                        format!("`{name}` has no argument named `{arg_name}`"),
                        arg.span,
                    ));
                    continue;
                };
                param_index
            } else {
                if saw_named {
                    self.diagnostics.push(Diagnostic::error(
                        "E_CALL_ARG_ORDER",
                        "positional arguments cannot follow named arguments in built-in calls",
                        arg.span,
                    ));
                    continue;
                }
                arg_index
            };

            if bound[param_index] {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_DUPLICATE",
                    format!(
                        "`{name}` argument `{}` is provided more than once",
                        SORT_PARAM_NAMES[param_index]
                    ),
                    arg.span,
                ));
                continue;
            }
            bound[param_index] = true;
        }

        if !bound[0] {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!("`{name}` is missing argument `id`"),
                args.first().map_or(span, |arg| arg.span),
            ));
        }
    }

    pub(crate) fn user_type_array_sort_field_index(&self, args: &[CallArg]) -> Option<usize> {
        let (_, id) = user_type_array_sort_arg(args, 0)?;
        let type_name = self.user_type_array_name_of_expr(&id.value)?;
        let (index, kind) = match user_type_array_sort_arg(args, 2) {
            None => (0, self.user_type_array_sort_field_kind_at(&type_name, 0)?),
            Some((_, field)) => {
                if let Some(index) = self.known_const_int_value(&field.value) {
                    let index = usize::try_from(index).ok()?;
                    (
                        index,
                        self.user_type_array_sort_field_kind_at(&type_name, index)?,
                    )
                } else {
                    let field_name = self.known_const_string_value(&field.value)?;
                    self.user_type_array_sort_field_named(&type_name, &field_name)?
                }
            }
        };
        matches!(kind, ValueKind::Int | ValueKind::Float | ValueKind::String).then_some(index)
    }

    fn user_type_array_sort_field_kind_at(
        &self,
        type_name: &str,
        index: usize,
    ) -> Option<ValueKind> {
        if let Some(user_type) = self.user_types.get(type_name) {
            return user_type
                .fields
                .get(index)
                .map(|field| field.pine_type.kind);
        }
        self.imported_user_types
            .get(type_name)?
            .fields
            .get(index)?
            .pine_type
            .map(|pine_type| pine_type.kind)
    }

    fn user_type_array_sort_field_named(
        &self,
        type_name: &str,
        field_name: &str,
    ) -> Option<(usize, ValueKind)> {
        if let Some((index, field)) = self.user_type_field(type_name, field_name) {
            return Some((index, field.pine_type.kind));
        }
        let user_type = self.imported_user_types.get(type_name)?;
        let (index, field) = user_type
            .fields
            .iter()
            .enumerate()
            .find(|(_, field)| field.name == field_name)?;
        Some((index, field.pine_type?.kind))
    }
}
