use pine_ir::{HirCallArg, HirExpr};

use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_box_new(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        if box_has_named_point_args(args) {
            return self.eval_box_new_from_points(args, PineValue::Na);
        }
        let left = self.eval_required_box_arg(args, 0, "left")?;
        if matches!(left, PineValue::ChartPoint(_)) {
            return self.eval_box_new_from_points(args, left);
        }
        let top = self.eval_required_box_arg(args, 1, "top")?;
        let right = self.eval_required_box_arg(args, 2, "right")?;
        let bottom = self.eval_required_box_arg(args, 3, "bottom")?;
        let border_color =
            self.eval_box_option_value(args, 4, "border_color", PineValue::Color(0x2196F3))?;
        let border_width =
            self.eval_box_option_value(args, 5, "border_width", PineValue::Int(1))?;
        let border_style = self.eval_box_option(args, 6, "border_style", "line.style_solid")?;
        let extend = self.eval_box_option(args, 7, "extend", "extend.none")?;
        let xloc = self.eval_box_option(args, 8, "xloc", "xloc.bar_index")?;
        let bg_color =
            self.eval_box_option_value(args, 9, "bgcolor", PineValue::Color(0x2196F3))?;
        let text =
            self.eval_box_option_value(args, 10, "text", PineValue::String(String::new()))?;
        let text_size = self.eval_box_option(args, 11, "text_size", "size.auto")?;
        let text_color =
            self.eval_box_option_value(args, 12, "text_color", PineValue::Color(0x363A45))?;
        let text_halign = self.eval_box_option(args, 13, "text_halign", "text.align_center")?;
        let text_valign = self.eval_box_option(args, 14, "text_valign", "text.align_center")?;
        let text_wrap = self.eval_box_option(args, 15, "text_wrap", "text.wrap_none")?;
        let text_font_family =
            self.eval_box_option(args, 16, "text_font_family", "font.family_default")?;
        let _force_overlay =
            self.eval_box_option_value(args, 17, "force_overlay", PineValue::Bool(false))?;
        let text_formatting =
            self.eval_box_text_formatting_option_value(args, 18, "text_formatting")?;
        self.create_box(BoxFields {
            left,
            top,
            right,
            bottom,
            xloc,
            bg_color,
            border_color,
            border_width,
            border_style,
            extend,
            text,
            text_color,
            text_size,
            text_halign,
            text_valign,
            text_wrap,
            text_font_family,
            text_formatting,
        })
    }

    fn eval_box_new_from_points(
        &mut self,
        args: &[HirCallArg],
        top_left: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        let top_left = if box_has_named_point_args(args) {
            self.eval_required_box_arg(args, 0, "top_left")?
        } else {
            top_left
        };
        let bottom_right = self.eval_required_box_arg(args, 1, "bottom_right")?;
        let border_color =
            self.eval_box_option_value(args, 2, "border_color", PineValue::Color(0x2196F3))?;
        let border_width =
            self.eval_box_option_value(args, 3, "border_width", PineValue::Int(1))?;
        let border_style = self.eval_box_option(args, 4, "border_style", "line.style_solid")?;
        let extend = self.eval_box_option(args, 5, "extend", "extend.none")?;
        let xloc = self.eval_box_option(args, 6, "xloc", "xloc.bar_index")?;
        let bg_color =
            self.eval_box_option_value(args, 7, "bgcolor", PineValue::Color(0x2196F3))?;
        let text = self.eval_box_option_value(args, 8, "text", PineValue::String(String::new()))?;
        let text_size = self.eval_box_option(args, 9, "text_size", "size.auto")?;
        let text_color =
            self.eval_box_option_value(args, 10, "text_color", PineValue::Color(0x363A45))?;
        let text_halign = self.eval_box_option(args, 11, "text_halign", "text.align_center")?;
        let text_valign = self.eval_box_option(args, 12, "text_valign", "text.align_center")?;
        let text_wrap = self.eval_box_option(args, 13, "text_wrap", "text.wrap_none")?;
        let text_font_family =
            self.eval_box_option(args, 14, "text_font_family", "font.family_default")?;
        let _force_overlay =
            self.eval_box_option_value(args, 15, "force_overlay", PineValue::Bool(false))?;
        let text_formatting =
            self.eval_box_text_formatting_option_value(args, 16, "text_formatting")?;
        let Some((left, top)) = box_point_coordinates(top_left, &xloc) else {
            return Ok(PineValue::Na);
        };
        let Some((right, bottom)) = box_point_coordinates(bottom_right, &xloc) else {
            return Ok(PineValue::Na);
        };
        self.create_box(BoxFields {
            left,
            top,
            right,
            bottom,
            xloc,
            bg_color,
            border_color,
            border_width,
            border_style,
            extend,
            text,
            text_color,
            text_size,
            text_halign,
            text_valign,
            text_wrap,
            text_font_family,
            text_formatting,
        })
    }

    fn create_box(&mut self, fields: BoxFields) -> Result<PineValue, RuntimeError> {
        self.evict_oldest_boxes_at_limit()?;
        let id = self.next_box_id;
        self.next_box_id = self
            .next_box_id
            .checked_add(1)
            .ok_or_else(|| RuntimeError {
                message: "box id limit exceeded".to_owned(),
            })?;
        self.boxes.push(BoxOutput {
            id,
            snapshots: vec![BoxSnapshot {
                bar_index: self.bars,
                exists: true,
                left: fields.left,
                top: fields.top,
                right: fields.right,
                bottom: fields.bottom,
                xloc: fields.xloc,
                bg_color: fields.bg_color,
                border_color: fields.border_color,
                border_width: fields.border_width,
                border_style: fields.border_style,
                extend: fields.extend,
                text: fields.text,
                text_color: fields.text_color,
                text_size: fields.text_size,
                text_halign: fields.text_halign,
                text_valign: fields.text_valign,
                text_wrap: fields.text_wrap,
                text_font_family: fields.text_font_family,
                text_formatting: fields.text_formatting,
            }],
        });
        Ok(PineValue::Box(id))
    }

    pub(super) fn eval_box_set_left(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let left = self.eval_required_box_arg(args, 1, "x")?;
        self.mutate_box(id, |snapshot| {
            snapshot.left = left;
        })
    }

    pub(super) fn eval_box_set_top(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let top = self.eval_required_box_arg(args, 1, "y")?;
        self.mutate_box(id, |snapshot| {
            snapshot.top = top;
        })
    }

    pub(super) fn eval_box_set_right(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let right = self.eval_required_box_arg(args, 1, "x")?;
        self.mutate_box(id, |snapshot| {
            snapshot.right = right;
        })
    }

    pub(super) fn eval_box_set_bottom(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let bottom = self.eval_required_box_arg(args, 1, "y")?;
        self.mutate_box(id, |snapshot| {
            snapshot.bottom = bottom;
        })
    }

    pub(super) fn eval_box_set_lefttop(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let left = self.eval_required_box_arg(args, 1, "x")?;
        let top = self.eval_required_box_arg(args, 2, "y")?;
        self.mutate_box(id, |snapshot| {
            snapshot.left = left;
            snapshot.top = top;
        })
    }

    pub(super) fn eval_box_set_top_left_point(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let point = self.eval_required_box_arg(args, 1, "point")?;
        self.mutate_box(id, |snapshot| {
            if let Some((x, y)) = box_point_coordinates(point, &snapshot.xloc) {
                snapshot.left = x;
                snapshot.top = y;
            }
        })
    }

    pub(super) fn eval_box_set_rightbottom(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let right = self.eval_required_box_arg(args, 1, "x")?;
        let bottom = self.eval_required_box_arg(args, 2, "y")?;
        self.mutate_box(id, |snapshot| {
            snapshot.right = right;
            snapshot.bottom = bottom;
        })
    }

    pub(super) fn eval_box_set_bottom_right_point(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let point = self.eval_required_box_arg(args, 1, "point")?;
        self.mutate_box(id, |snapshot| {
            if let Some((x, y)) = box_point_coordinates(point, &snapshot.xloc) {
                snapshot.right = x;
                snapshot.bottom = y;
            }
        })
    }

    pub(super) fn eval_box_set_bgcolor(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let bg_color = self.eval_required_box_arg(args, 1, "color")?;
        self.mutate_box(id, |snapshot| {
            snapshot.bg_color = bg_color;
        })
    }

    pub(super) fn eval_box_set_border_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let border_color = self.eval_required_box_arg(args, 1, "color")?;
        self.mutate_box(id, |snapshot| {
            snapshot.border_color = border_color;
        })
    }

    pub(super) fn eval_box_set_border_width(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let border_width = self.eval_required_box_arg(args, 1, "width")?;
        self.mutate_box(id, |snapshot| {
            snapshot.border_width = border_width;
        })
    }

    pub(super) fn eval_box_set_border_style(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let border_style = self.eval_required_box_arg(args, 1, "style")?;
        self.mutate_box(id, |snapshot| {
            snapshot.border_style = border_style;
        })
    }

    pub(super) fn eval_box_set_extend(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let extend = self.eval_required_box_arg(args, 1, "extend")?;
        self.mutate_box(id, |snapshot| {
            snapshot.extend = extend;
        })
    }

    pub(super) fn eval_box_set_xloc(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let left = self.eval_required_box_arg(args, 1, "left")?;
        let right = self.eval_required_box_arg(args, 2, "right")?;
        let xloc = self.eval_required_box_arg(args, 3, "xloc")?;
        self.mutate_box(id, |snapshot| {
            snapshot.left = left;
            snapshot.right = right;
            snapshot.xloc = xloc;
        })
    }

    pub(super) fn eval_box_set_text(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text = self.eval_required_box_arg(args, 1, "text")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text = text;
        })
    }

    pub(super) fn eval_box_set_text_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text_color = self.eval_required_box_arg(args, 1, "text_color")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text_color = text_color;
        })
    }

    pub(super) fn eval_box_set_text_size(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text_size = self.eval_required_box_arg(args, 1, "text_size")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text_size = text_size;
        })
    }

    pub(super) fn eval_box_set_text_halign(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text_halign = self.eval_required_box_arg(args, 1, "text_halign")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text_halign = text_halign;
        })
    }

    pub(super) fn eval_box_set_text_valign(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text_valign = self.eval_required_box_arg(args, 1, "text_valign")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text_valign = text_valign;
        })
    }

    pub(super) fn eval_box_set_text_wrap(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text_wrap = self.eval_required_box_arg(args, 1, "text_wrap")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text_wrap = text_wrap;
        })
    }

    pub(super) fn eval_box_set_text_font_family(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text_font_family = self.eval_required_box_arg(args, 1, "text_font_family")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text_font_family = text_font_family;
        })
    }

    pub(super) fn eval_box_set_text_formatting(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let text_formatting = self.eval_box_text_formatting_arg(args, 1, "text_formatting")?;
        self.mutate_box(id, |snapshot| {
            snapshot.text_formatting = text_formatting;
        })
    }

    pub(super) fn eval_box_delete(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(box_output) = self.boxes.iter_mut().find(|box_output| box_output.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid box id `{id}`"),
            });
        };
        let Some(latest) = box_output.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("box `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest;
        next.bar_index = self.bars;
        next.exists = false;
        box_output.snapshots.push(next);
        Ok(PineValue::Void)
    }

    pub(super) fn eval_box_copy(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_id_arg(args)?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(box_output) = self.boxes.iter().find(|box_output| box_output.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid box id `{id}`"),
            });
        };
        let Some(latest) = box_output.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("box `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        self.evict_oldest_boxes_at_limit()?;
        let copied_id = self.next_box_id;
        self.next_box_id = self
            .next_box_id
            .checked_add(1)
            .ok_or_else(|| RuntimeError {
                message: "box id limit exceeded".to_owned(),
            })?;
        let mut copied = latest;
        copied.bar_index = self.bars;
        self.boxes.push(BoxOutput {
            id: copied_id,
            snapshots: vec![copied],
        });
        Ok(PineValue::Box(copied_id))
    }

    fn evict_oldest_boxes_at_limit(&mut self) -> Result<(), RuntimeError> {
        let limit = self.max_box_count();
        while self.active_box_count() >= limit {
            let Some(box_output) = self.boxes.iter_mut().find(|box_output| {
                box_output
                    .snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            }) else {
                break;
            };
            let Some(latest) = box_output.snapshots.last().cloned() else {
                return Err(RuntimeError {
                    message: format!("box `{}` has no snapshots", box_output.id),
                });
            };
            let mut next = latest;
            next.bar_index = self.bars;
            next.exists = false;
            box_output.snapshots.push(next);
        }
        Ok(())
    }

    fn active_box_count(&self) -> usize {
        self.boxes
            .iter()
            .filter(|box_output| {
                box_output
                    .snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            })
            .count()
    }

    fn max_box_count(&self) -> usize {
        self.program
            .drawing_settings
            .max_boxes_count
            .map_or(DEFAULT_MAX_BOXES, |value| value as usize)
            .clamp(1, MAX_BOXES)
    }

    pub(super) fn eval_box_get_top(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_box_get(args, "box.get_top", |snapshot| snapshot.top.clone())
    }

    pub(super) fn eval_box_get_bottom(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_box_get(args, "box.get_bottom", |snapshot| snapshot.bottom.clone())
    }

    pub(super) fn eval_box_get_left(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_box_get(args, "box.get_left", |snapshot| snapshot.left.clone())
    }

    pub(super) fn eval_box_get_right(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_box_get(args, "box.get_right", |snapshot| snapshot.right.clone())
    }

    fn eval_box_id_arg(&mut self, args: &[HirCallArg]) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = box_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: "box mutation missing id argument".to_owned(),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::Box(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("box mutation expected box id, got {value:?}"),
            }),
        }
    }

    fn eval_required_box_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = box_call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("box call missing {name} argument"),
            });
        };
        self.eval_expr(arg)
    }

    fn eval_box_text_formatting_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = box_call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("box call missing {name} argument"),
            });
        };
        self.eval_box_text_formatting_expr(arg, name)
    }

    fn eval_box_text_formatting_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = box_call_arg_expr(args, index, name) else {
            return Ok(PineValue::Int(0));
        };
        self.eval_box_text_formatting_expr(arg, name)
    }

    fn eval_box_text_formatting_expr(
        &mut self,
        arg: &HirExpr,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        match self.eval_expr(arg)? {
            PineValue::Int(mask) if (0..=3).contains(&mask) => Ok(PineValue::Int(mask)),
            PineValue::Na => Ok(PineValue::Na),
            value => Err(RuntimeError {
                message: format!("box call `{name}` expected text format mask, got {value:?}"),
            }),
        }
    }

    fn eval_box_option(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: &str,
    ) -> Result<PineValue, RuntimeError> {
        self.eval_box_option_value(args, index, name, PineValue::String(default.to_owned()))
    }

    fn eval_box_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        match box_call_arg_expr(args, index, name) {
            Some(expr) => self.eval_expr(expr),
            None => Ok(default),
        }
    }

    fn mutate_box(
        &mut self,
        id: Option<u32>,
        mutate: impl FnOnce(&mut BoxSnapshot),
    ) -> Result<PineValue, RuntimeError> {
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(box_output) = self.boxes.iter_mut().find(|box_output| box_output.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid box id `{id}`"),
            });
        };
        let Some(latest) = box_output.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("box `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest.clone();
        mutate(&mut next);
        if next != latest {
            next.bar_index = self.bars;
            box_output.snapshots.push(next);
        }
        Ok(PineValue::Void)
    }

    fn eval_box_get(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
        get_value: impl FnOnce(&BoxSnapshot) -> PineValue,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_box_get_id_arg(args, function_name)?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(box_output) = self.boxes.iter().find(|box_output| box_output.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid box id `{id}`"),
            });
        };
        let Some(latest) = box_output.snapshots.last() else {
            return Err(RuntimeError {
                message: format!("box `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        Ok(get_value(latest))
    }

    fn eval_box_get_id_arg(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
    ) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = box_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: format!("{function_name} missing id argument"),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::Box(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("{function_name} expected box id, got {value:?}"),
            }),
        }
    }
}

struct BoxFields {
    left: PineValue,
    top: PineValue,
    right: PineValue,
    bottom: PineValue,
    xloc: PineValue,
    bg_color: PineValue,
    border_color: PineValue,
    border_width: PineValue,
    border_style: PineValue,
    extend: PineValue,
    text: PineValue,
    text_color: PineValue,
    text_size: PineValue,
    text_halign: PineValue,
    text_valign: PineValue,
    text_wrap: PineValue,
    text_font_family: PineValue,
    text_formatting: PineValue,
}

fn box_has_named_point_args(args: &[HirCallArg]) -> bool {
    args.iter()
        .any(|arg| matches!(arg.name.as_deref(), Some("top_left" | "bottom_right")))
}

fn box_call_arg_expr<'a>(args: &'a [HirCallArg], index: usize, name: &str) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

fn box_point_coordinates(point: PineValue, xloc: &PineValue) -> Option<(PineValue, PineValue)> {
    let PineValue::ChartPoint(point) = point else {
        return None;
    };
    let x = match xloc {
        PineValue::String(value) if value == "xloc.bar_time" => point.field(0),
        _ => point.field(1),
    };
    Some((x, point.field(2)))
}
