use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_array_new_float(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_float", ArrayElementKind::Float)
    }

    pub(crate) fn eval_array_new_int(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_int", ArrayElementKind::Int)
    }

    pub(crate) fn eval_array_new_bool(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_bool", ArrayElementKind::Bool)
    }

    pub(crate) fn eval_array_new_string(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_string", ArrayElementKind::String)
    }

    pub(crate) fn eval_array_new_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_color", ArrayElementKind::Color)
    }

    pub(crate) fn eval_array_new_line(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_line", ArrayElementKind::Line)
    }

    pub(crate) fn eval_array_new_linefill(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_linefill", ArrayElementKind::LineFill)
    }

    pub(crate) fn eval_array_new_polyline(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_polyline", ArrayElementKind::Polyline)
    }

    pub(crate) fn eval_array_new_label(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_label", ArrayElementKind::Label)
    }

    pub(crate) fn eval_array_new_box(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_box", ArrayElementKind::Box)
    }

    pub(crate) fn eval_array_new_table(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new_table", ArrayElementKind::Table)
    }

    pub(crate) fn eval_array_new_chart_point(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_array_new_with_kind(args, "array.new<chart.point>", ArrayElementKind::ChartPoint)
    }

    pub(crate) fn eval_array_new_user_type(
        &mut self,
        args: &[HirCallArg],
        type_name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let function_name = format!("array.new<{type_name}>");
        let Some(size) = self.eval_array_new_size(args, &function_name)? else {
            return Ok(PineValue::Na);
        };

        let initial_value = if let Some(value_arg) = args.get(1) {
            self.eval_array_value(&value_arg.value, ArrayElementKind::UserType)?
        } else {
            PineValue::Na
        };

        let value = self.new_array(ArrayElementKind::UserType, size, initial_value);
        if let PineValue::Array(id) = value {
            self.array_user_types.insert(id, type_name.to_owned());
        }
        Ok(value)
    }

    pub(crate) fn eval_array_from(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        if args.len() > MAX_ARRAY_ELEMENTS {
            return Err(RuntimeError {
                message: format!("array.from cannot exceed {MAX_ARRAY_ELEMENTS} elements"),
            });
        }

        let mut values = Vec::with_capacity(args.len());
        for arg in args {
            values.push(self.eval_expr(&arg.value)?);
        }

        let Some(kind) = infer_array_from_kind(&values) else {
            return Ok(PineValue::Na);
        };
        for value in &mut values {
            if matches!(kind, ArrayElementKind::Float) {
                let int_value = match value {
                    PineValue::Int(int_value) => Some(*int_value),
                    _ => None,
                };
                if let Some(int_value) = int_value {
                    *value = PineValue::Float(int_value as f64);
                }
            }
        }
        Ok(self.new_array_from_values(kind, values))
    }

    pub(crate) fn eval_array_new_size(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
    ) -> Result<Option<usize>, RuntimeError> {
        if let Some(size_arg) = args.first() {
            let Some(size) = self.eval_expr(&size_arg.value)?.as_i64() else {
                return Ok(None);
            };
            if size < 0 {
                return Err(RuntimeError {
                    message: format!("{function_name} size cannot be negative"),
                });
            }
            let size = size as usize;
            if size > MAX_ARRAY_ELEMENTS {
                return Err(RuntimeError {
                    message: format!(
                        "{function_name} size cannot exceed {MAX_ARRAY_ELEMENTS} elements"
                    ),
                });
            }
            Ok(Some(size))
        } else {
            Ok(Some(0))
        }
    }

    pub(crate) fn new_array_from_values(
        &mut self,
        kind: ArrayElementKind,
        values: Vec<PineValue>,
    ) -> PineValue {
        let id = self.next_array_id;
        self.next_array_id += 1;
        self.array_store.insert(id, values);
        self.array_kinds.insert(id, kind);
        PineValue::Array(id)
    }

    #[allow(dead_code)]
    pub(crate) fn new_user_type_array_from_values(
        &mut self,
        type_name: impl Into<String>,
        values: Vec<PineValue>,
    ) -> PineValue {
        let value = self.new_array_from_values(ArrayElementKind::UserType, values);
        if let PineValue::Array(id) = value {
            self.array_user_types.insert(id, type_name.into());
        }
        value
    }

    fn eval_array_new_with_kind(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
        kind: ArrayElementKind,
    ) -> Result<PineValue, RuntimeError> {
        let Some(size) = self.eval_array_new_size(args, function_name)? else {
            return Ok(PineValue::Na);
        };

        let initial_value = if let Some(value_arg) = args.get(1) {
            self.eval_array_value(&value_arg.value, kind)?
        } else {
            PineValue::Na
        };

        Ok(self.new_array(kind, size, initial_value))
    }

    fn new_array(
        &mut self,
        kind: ArrayElementKind,
        size: usize,
        initial_value: PineValue,
    ) -> PineValue {
        let id = self.next_array_id;
        self.next_array_id += 1;
        self.array_store.insert(id, vec![initial_value; size]);
        self.array_kinds.insert(id, kind);
        PineValue::Array(id)
    }
}
