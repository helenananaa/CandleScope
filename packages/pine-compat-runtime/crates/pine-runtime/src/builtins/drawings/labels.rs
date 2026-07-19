use crate::*;
use pine_ir::{HirCallArg, HirExpr};

struct LabelFields {
    x: PineValue,
    y: PineValue,
    text: PineValue,
    xloc: PineValue,
    yloc: PineValue,
    color: PineValue,
    style: PineValue,
    text_color: PineValue,
    size: PineValue,
    tooltip: PineValue,
    text_align: PineValue,
    text_font_family: PineValue,
    text_formatting: PineValue,
}

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_label_new(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        if label_has_named_point_args(args) {
            return self.eval_label_new_from_point(args, PineValue::Na);
        }
        let Some(x_arg) = label_call_arg_expr(args, 0, "x") else {
            return Err(RuntimeError {
                message: "label.new missing x argument".to_owned(),
            });
        };
        let x = self.eval_expr(x_arg)?;
        if matches!(x, PineValue::ChartPoint(_)) {
            return self.eval_label_new_from_point(args, x);
        }
        let Some(y_arg) = label_call_arg_expr(args, 1, "y") else {
            return Err(RuntimeError {
                message: "label.new missing y argument".to_owned(),
            });
        };
        let y = self.eval_expr(y_arg)?;
        let text =
            self.eval_label_option_value(args, 2, "text", PineValue::String(String::new()))?;
        let xloc = self.eval_label_option(args, 3, "xloc", "xloc.bar_index")?;
        let yloc = self.eval_label_option(args, 4, "yloc", "yloc.price")?;
        let color = self.eval_label_option_value(args, 5, "color", PineValue::Color(0x2196F3))?;
        let style = self.eval_label_option(args, 6, "style", "label.style_label_down")?;
        let text_color =
            self.eval_label_option_value(args, 7, "textcolor", PineValue::Color(0xFFFFFF))?;
        let size = self.eval_label_option(args, 8, "size", "size.normal")?;
        let text_align = self.eval_label_option(args, 9, "textalign", "text.align_center")?;
        let tooltip =
            self.eval_label_option_value(args, 10, "tooltip", PineValue::String(String::new()))?;
        let text_font_family =
            self.eval_label_option(args, 11, "text_font_family", "font.family_default")?;
        let text_formatting =
            self.eval_label_text_formatting_option_value(args, 13, "text_formatting")?;
        self.create_label(LabelFields {
            x,
            y,
            text,
            xloc,
            yloc,
            color,
            style,
            text_color,
            size,
            tooltip,
            text_align,
            text_font_family,
            text_formatting,
        })
    }

    fn eval_label_new_from_point(
        &mut self,
        args: &[HirCallArg],
        point: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        let point = if label_has_named_point_args(args) {
            self.eval_required_label_arg(args, 0, "point")?
        } else {
            point
        };
        let text =
            self.eval_label_option_value(args, 1, "text", PineValue::String(String::new()))?;
        let xloc = self.eval_label_option(args, 2, "xloc", "xloc.bar_index")?;
        let yloc = self.eval_label_option(args, 3, "yloc", "yloc.price")?;
        let color = self.eval_label_option_value(args, 4, "color", PineValue::Color(0x2196F3))?;
        let style = self.eval_label_option(args, 5, "style", "label.style_label_down")?;
        let text_color =
            self.eval_label_option_value(args, 6, "textcolor", PineValue::Color(0xFFFFFF))?;
        let size = self.eval_label_option(args, 7, "size", "size.normal")?;
        let text_align = self.eval_label_option(args, 8, "textalign", "text.align_center")?;
        let tooltip =
            self.eval_label_option_value(args, 9, "tooltip", PineValue::String(String::new()))?;
        let text_font_family =
            self.eval_label_option(args, 10, "text_font_family", "font.family_default")?;
        let _force_overlay =
            self.eval_label_option_value(args, 11, "force_overlay", PineValue::Bool(false))?;
        let text_formatting =
            self.eval_label_text_formatting_option_value(args, 12, "text_formatting")?;
        let Some((x, y)) = label_point_coordinates(point, &xloc) else {
            return Ok(PineValue::Na);
        };
        self.create_label(LabelFields {
            x,
            y,
            text,
            xloc,
            yloc,
            color,
            style,
            text_color,
            size,
            tooltip,
            text_align,
            text_font_family,
            text_formatting,
        })
    }

    fn create_label(&mut self, fields: LabelFields) -> Result<PineValue, RuntimeError> {
        self.evict_oldest_labels_at_limit()?;
        let id = self.next_label_id;
        self.next_label_id = self
            .next_label_id
            .checked_add(1)
            .ok_or_else(|| RuntimeError {
                message: "label id limit exceeded".to_owned(),
            })?;
        self.labels.push(LabelOutput {
            id,
            snapshots: vec![LabelSnapshot {
                bar_index: self.bars,
                exists: true,
                x: fields.x,
                y: fields.y,
                text: fields.text,
                xloc: fields.xloc,
                yloc: fields.yloc,
                color: fields.color,
                style: fields.style,
                text_color: fields.text_color,
                size: fields.size,
                tooltip: fields.tooltip,
                text_align: fields.text_align,
                text_font_family: fields.text_font_family,
                text_formatting: fields.text_formatting,
            }],
        });
        Ok(PineValue::Label(id))
    }

    pub(super) fn eval_label_set_x(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let x = self.eval_required_label_arg(args, 1, "x")?;
        self.mutate_label(id, |snapshot| {
            snapshot.x = x;
        })
    }

    pub(super) fn eval_label_set_xloc(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let x = self.eval_required_label_arg(args, 1, "x")?;
        let xloc = self.eval_required_label_arg(args, 2, "xloc")?;
        self.mutate_label(id, |snapshot| {
            snapshot.x = x;
            snapshot.xloc = xloc;
        })
    }

    pub(super) fn eval_label_set_y(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let y = self.eval_required_label_arg(args, 1, "y")?;
        self.mutate_label(id, |snapshot| {
            snapshot.y = y;
        })
    }

    pub(super) fn eval_label_set_xy(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let x = self.eval_required_label_arg(args, 1, "x")?;
        let y = self.eval_required_label_arg(args, 2, "y")?;
        self.mutate_label(id, |snapshot| {
            snapshot.x = x;
            snapshot.y = y;
        })
    }

    pub(super) fn eval_label_set_point(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let point = self.eval_required_label_arg(args, 1, "point")?;
        self.mutate_label(id, |snapshot| {
            if let Some((x, y)) = label_point_coordinates(point, &snapshot.xloc) {
                snapshot.x = x;
                snapshot.y = y;
            }
        })
    }

    pub(super) fn eval_label_set_yloc(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let yloc = self.eval_required_label_arg(args, 1, "yloc")?;
        self.mutate_label(id, |snapshot| {
            snapshot.yloc = yloc;
        })
    }

    pub(super) fn eval_label_set_text(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let text = self.eval_required_label_arg(args, 1, "text")?;
        self.mutate_label(id, |snapshot| {
            snapshot.text = text;
        })
    }

    pub(super) fn eval_label_set_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let color = self.eval_required_label_arg(args, 1, "color")?;
        self.mutate_label(id, |snapshot| {
            snapshot.color = color;
        })
    }

    pub(super) fn eval_label_set_textcolor(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let text_color = self.eval_required_label_arg(args, 1, "textcolor")?;
        self.mutate_label(id, |snapshot| {
            snapshot.text_color = text_color;
        })
    }

    pub(super) fn eval_label_set_style(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let style = self.eval_required_label_arg(args, 1, "style")?;
        self.mutate_label(id, |snapshot| {
            snapshot.style = style;
        })
    }

    pub(super) fn eval_label_set_size(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let size = self.eval_required_label_arg(args, 1, "size")?;
        self.mutate_label(id, |snapshot| {
            snapshot.size = size;
        })
    }

    pub(super) fn eval_label_set_tooltip(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let tooltip = self.eval_required_label_arg(args, 1, "tooltip")?;
        self.mutate_label(id, |snapshot| {
            snapshot.tooltip = tooltip;
        })
    }

    pub(super) fn eval_label_set_textalign(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let text_align = self.eval_required_label_arg(args, 1, "textalign")?;
        self.mutate_label(id, |snapshot| {
            snapshot.text_align = text_align;
        })
    }

    pub(super) fn eval_label_set_text_font_family(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let text_font_family = self.eval_required_label_arg(args, 1, "text_font_family")?;
        self.mutate_label(id, |snapshot| {
            snapshot.text_font_family = text_font_family;
        })
    }

    pub(super) fn eval_label_set_text_formatting(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let text_formatting = self.eval_label_text_formatting_arg(args, 1, "text_formatting")?;
        self.mutate_label(id, |snapshot| {
            snapshot.text_formatting = text_formatting;
        })
    }

    pub(super) fn eval_label_delete(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_id_arg(args)?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(label) = self.labels.iter_mut().find(|label| label.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid label id `{id}`"),
            });
        };
        let Some(latest) = label.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("label `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest;
        next.bar_index = self.bars;
        next.exists = false;
        label.snapshots.push(next);
        Ok(PineValue::Void)
    }

    pub(super) fn eval_label_copy(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_get_id_arg(args, "label.copy")?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(label) = self.labels.iter().find(|label| label.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid label id `{id}`"),
            });
        };
        let Some(latest) = label.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("label `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        self.evict_oldest_labels_at_limit()?;
        let copied_id = self.next_label_id;
        self.next_label_id = self
            .next_label_id
            .checked_add(1)
            .ok_or_else(|| RuntimeError {
                message: "label id limit exceeded".to_owned(),
            })?;
        let mut copied = latest;
        copied.bar_index = self.bars;
        self.labels.push(LabelOutput {
            id: copied_id,
            snapshots: vec![copied],
        });
        Ok(PineValue::Label(copied_id))
    }

    fn evict_oldest_labels_at_limit(&mut self) -> Result<(), RuntimeError> {
        let limit = self.max_label_count();
        while self.active_label_count() >= limit {
            let Some(label) = self.labels.iter_mut().find(|label| {
                label
                    .snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            }) else {
                break;
            };
            let Some(latest) = label.snapshots.last().cloned() else {
                return Err(RuntimeError {
                    message: format!("label `{}` has no snapshots", label.id),
                });
            };
            let mut next = latest;
            next.bar_index = self.bars;
            next.exists = false;
            label.snapshots.push(next);
        }
        Ok(())
    }

    fn active_label_count(&self) -> usize {
        self.labels
            .iter()
            .filter(|label| {
                label
                    .snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            })
            .count()
    }

    fn max_label_count(&self) -> usize {
        self.program
            .drawing_settings
            .max_labels_count
            .map_or(DEFAULT_MAX_LABELS, |value| value as usize)
            .clamp(1, MAX_LABELS)
    }

    pub(super) fn eval_label_get_x(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_label_get(args, "label.get_x", |snapshot| snapshot.x.clone())
    }

    pub(super) fn eval_label_get_y(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_label_get(args, "label.get_y", |snapshot| snapshot.y.clone())
    }

    pub(super) fn eval_label_get_text(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_label_get(args, "label.get_text", |snapshot| snapshot.text.clone())
    }

    fn eval_label_id_arg(&mut self, args: &[HirCallArg]) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = label_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: "label mutation missing id argument".to_owned(),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::Label(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("label mutation expected label id, got {value:?}"),
            }),
        }
    }

    fn eval_required_label_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = label_call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("label mutation missing {name} argument"),
            });
        };
        self.eval_expr(arg)
    }

    fn eval_label_text_formatting_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = label_call_arg_expr(args, index, name) else {
            return Ok(PineValue::Int(0));
        };
        self.eval_label_text_formatting_expr(arg, name)
    }

    fn eval_label_text_formatting_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = label_call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("label mutation missing {name} argument"),
            });
        };
        self.eval_label_text_formatting_expr(arg, name)
    }

    fn eval_label_text_formatting_expr(
        &mut self,
        arg: &pine_ir::HirExpr,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        match self.eval_expr(arg)? {
            PineValue::Int(mask) if (0..=3).contains(&mask) => Ok(PineValue::Int(mask)),
            PineValue::Na => Ok(PineValue::Na),
            value => Err(RuntimeError {
                message: format!(
                    "label mutation `{name}` expected text format mask, got {value:?}"
                ),
            }),
        }
    }

    fn mutate_label(
        &mut self,
        id: Option<u32>,
        mutate: impl FnOnce(&mut LabelSnapshot),
    ) -> Result<PineValue, RuntimeError> {
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(label) = self.labels.iter_mut().find(|label| label.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid label id `{id}`"),
            });
        };
        let Some(latest) = label.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("label `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest.clone();
        mutate(&mut next);
        if next != latest {
            next.bar_index = self.bars;
            label.snapshots.push(next);
        }
        Ok(PineValue::Void)
    }

    fn eval_label_get(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
        get_value: impl FnOnce(&LabelSnapshot) -> PineValue,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_label_get_id_arg(args, function_name)?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(label) = self.labels.iter().find(|label| label.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid label id `{id}`"),
            });
        };
        let Some(latest) = label.snapshots.last() else {
            return Err(RuntimeError {
                message: format!("label `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        Ok(get_value(latest))
    }

    fn eval_label_get_id_arg(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
    ) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = label_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: format!("{function_name} missing id argument"),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::Label(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("{function_name} expected label id, got {value:?}"),
            }),
        }
    }

    fn eval_label_option(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: &str,
    ) -> Result<PineValue, RuntimeError> {
        self.eval_label_option_value(args, index, name, PineValue::String(default.to_owned()))
    }

    fn eval_label_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        match label_call_arg_expr(args, index, name) {
            Some(expr) => self.eval_expr(expr),
            None => Ok(default),
        }
    }
}

fn label_call_arg_expr<'a>(
    args: &'a [HirCallArg],
    index: usize,
    name: &str,
) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

fn label_has_named_point_args(args: &[HirCallArg]) -> bool {
    args.iter().any(|arg| arg.name.as_deref() == Some("point"))
}

fn label_point_coordinates(point: PineValue, xloc: &PineValue) -> Option<(PineValue, PineValue)> {
    let PineValue::ChartPoint(point) = point else {
        return None;
    };
    let x = match xloc {
        PineValue::String(value) if value == "xloc.bar_time" => point.field(0),
        _ => point.field(1),
    };
    Some((x, point.field(2)))
}
