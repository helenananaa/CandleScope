use crate::prelude::*;

impl Analyzer {
    pub(crate) fn validate_named_drawing_count_arg(
        &mut self,
        call_name: &str,
        name: &str,
        max: i64,
        arg: &CallArg,
    ) {
        if arg.name.is_none() {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_NAME",
                format!("`{call_name}` argument `{name}` must be named in the current subset"),
                arg.span,
            ));
            return;
        }

        let Some(value) = self.known_const_int_for_validation(&arg.value) else {
            return;
        };
        let Ok(value) = value else {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_VALUE",
                format!("`{call_name}` argument `{name}` must be between 1 and {max}"),
                arg.span,
            ));
            return;
        };
        if !(1..=max).contains(&value) {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_VALUE",
                format!("`{call_name}` argument `{name}` must be between 1 and {max}"),
                arg.span,
            ));
            return;
        }

        match name {
            "max_labels_count" => {
                self.drawing_settings.max_labels_count = Some(value as u32);
            }
            "max_boxes_count" => {
                self.drawing_settings.max_boxes_count = Some(value as u32);
            }
            "max_lines_count" => {
                self.drawing_settings.max_lines_count = Some(value as u32);
            }
            "max_polylines_count" => {
                self.drawing_settings.max_polylines_count = Some(value as u32);
            }
            _ => unreachable!("known drawing-count declaration"),
        }
    }

    pub(crate) fn validate_indicator_drawing_count_arg(
        &mut self,
        signature: &BuiltinSignature,
        arg: &CallArg,
        index: usize,
    ) -> bool {
        let drawing_count = [
            ("max_labels_count", 500),
            ("max_boxes_count", 500),
            ("max_lines_count", 500),
            ("max_polylines_count", 100),
        ]
        .into_iter()
        .find(|(name, _)| {
            arg.name.as_deref() == Some(*name)
                || (arg.name.is_none()
                    && signature
                        .params
                        .get(index)
                        .is_some_and(|param| param.name == *name))
        });
        let Some((name, max)) = drawing_count else {
            return false;
        };

        self.validate_named_drawing_count_arg("indicator", name, max, arg);
        true
    }
}
