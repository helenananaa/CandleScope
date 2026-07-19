use pine_ir::{HirCallArg, HirExpr};

use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_line_new(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        if line_has_named_point_args(args) {
            return self.eval_line_new_from_points(args, PineValue::Na);
        }
        let x1 = self.eval_required_line_arg(args, 0, "x1")?;
        if matches!(x1, PineValue::ChartPoint(_)) {
            return self.eval_line_new_from_points(args, x1);
        }
        let y1 = self.eval_required_line_arg(args, 1, "y1")?;
        let x2 = self.eval_required_line_arg(args, 2, "x2")?;
        let y2 = self.eval_required_line_arg(args, 3, "y2")?;
        let xloc = self.eval_line_option(args, 4, "xloc", "xloc.bar_index")?;
        let extend = self.eval_line_option(args, 5, "extend", "extend.none")?;
        let color = self.eval_line_option_value(args, 6, "color", PineValue::Color(0x2196F3))?;
        let style = self.eval_line_option(args, 7, "style", "line.style_solid")?;
        let width = self.eval_line_option_value(args, 8, "width", PineValue::Int(1))?;
        let _force_overlay =
            self.eval_line_option_value(args, 9, "force_overlay", PineValue::Bool(false))?;
        self.create_line(LineFields {
            x1,
            y1,
            x2,
            y2,
            xloc,
            extend,
            color,
            style,
            width,
        })
    }

    fn eval_line_new_from_points(
        &mut self,
        args: &[HirCallArg],
        first: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        let first = if line_has_named_point_args(args) {
            self.eval_required_line_arg(args, 0, "first_point")?
        } else {
            first
        };
        let second = self.eval_required_line_arg(args, 1, "second_point")?;
        let xloc = self.eval_line_option(args, 2, "xloc", "xloc.bar_index")?;
        let extend = self.eval_line_option(args, 3, "extend", "extend.none")?;
        let color = self.eval_line_option_value(args, 4, "color", PineValue::Color(0x2196F3))?;
        let style = self.eval_line_option(args, 5, "style", "line.style_solid")?;
        let width = self.eval_line_option_value(args, 6, "width", PineValue::Int(1))?;
        let _force_overlay =
            self.eval_line_option_value(args, 7, "force_overlay", PineValue::Bool(false))?;
        let Some((x1, y1)) = line_point_coordinates(first, &xloc) else {
            return Ok(PineValue::Na);
        };
        let Some((x2, y2)) = line_point_coordinates(second, &xloc) else {
            return Ok(PineValue::Na);
        };
        self.create_line(LineFields {
            x1,
            y1,
            x2,
            y2,
            xloc,
            extend,
            color,
            style,
            width,
        })
    }

    fn create_line(&mut self, fields: LineFields) -> Result<PineValue, RuntimeError> {
        self.evict_oldest_lines_at_limit()?;
        let id = self.next_line_id;
        self.next_line_id = self
            .next_line_id
            .checked_add(1)
            .ok_or_else(|| RuntimeError {
                message: "line id limit exceeded".to_owned(),
            })?;
        self.lines.push(LineOutput {
            id,
            snapshots: vec![LineSnapshot {
                bar_index: self.bars,
                exists: true,
                x1: fields.x1,
                y1: fields.y1,
                x2: fields.x2,
                y2: fields.y2,
                xloc: fields.xloc,
                color: fields.color,
                width: fields.width,
                style: fields.style,
                extend: fields.extend,
            }],
        });
        Ok(PineValue::Line(id))
    }

    pub(super) fn eval_line_set_x1(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let x = self.eval_required_line_arg(args, 1, "x")?;
        self.mutate_line(id, |snapshot| {
            snapshot.x1 = x;
        })
    }

    pub(super) fn eval_line_set_first_point(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let point = self.eval_required_line_arg(args, 1, "point")?;
        self.mutate_line(id, |snapshot| {
            if let Some((x, y)) = line_point_coordinates(point, &snapshot.xloc) {
                snapshot.x1 = x;
                snapshot.y1 = y;
            }
        })
    }

    pub(super) fn eval_line_set_y1(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let y = self.eval_required_line_arg(args, 1, "y")?;
        self.mutate_line(id, |snapshot| {
            snapshot.y1 = y;
        })
    }

    pub(super) fn eval_line_set_xy1(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let x = self.eval_required_line_arg(args, 1, "x")?;
        let y = self.eval_required_line_arg(args, 2, "y")?;
        self.mutate_line(id, |snapshot| {
            snapshot.x1 = x;
            snapshot.y1 = y;
        })
    }

    pub(super) fn eval_line_set_x2(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let x = self.eval_required_line_arg(args, 1, "x")?;
        self.mutate_line(id, |snapshot| {
            snapshot.x2 = x;
        })
    }

    pub(super) fn eval_line_set_second_point(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let point = self.eval_required_line_arg(args, 1, "point")?;
        self.mutate_line(id, |snapshot| {
            if let Some((x, y)) = line_point_coordinates(point, &snapshot.xloc) {
                snapshot.x2 = x;
                snapshot.y2 = y;
            }
        })
    }

    pub(super) fn eval_line_set_y2(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let y = self.eval_required_line_arg(args, 1, "y")?;
        self.mutate_line(id, |snapshot| {
            snapshot.y2 = y;
        })
    }

    pub(super) fn eval_line_set_xy2(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let x = self.eval_required_line_arg(args, 1, "x")?;
        let y = self.eval_required_line_arg(args, 2, "y")?;
        self.mutate_line(id, |snapshot| {
            snapshot.x2 = x;
            snapshot.y2 = y;
        })
    }

    pub(super) fn eval_line_set_xloc(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let x1 = self.eval_required_line_arg(args, 1, "x1")?;
        let x2 = self.eval_required_line_arg(args, 2, "x2")?;
        let xloc = self.eval_required_line_arg(args, 3, "xloc")?;
        self.mutate_line(id, |snapshot| {
            snapshot.x1 = x1;
            snapshot.x2 = x2;
            snapshot.xloc = xloc;
        })
    }

    pub(super) fn eval_line_set_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let color = self.eval_required_line_arg(args, 1, "color")?;
        self.mutate_line(id, |snapshot| {
            snapshot.color = color;
        })
    }

    pub(super) fn eval_line_set_width(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let width = self.eval_required_line_arg(args, 1, "width")?;
        self.mutate_line(id, |snapshot| {
            snapshot.width = width;
        })
    }

    pub(super) fn eval_line_set_style(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let style = self.eval_required_line_arg(args, 1, "style")?;
        self.mutate_line(id, |snapshot| {
            snapshot.style = style;
        })
    }

    pub(super) fn eval_line_set_extend(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let extend = self.eval_required_line_arg(args, 1, "extend")?;
        self.mutate_line(id, |snapshot| {
            snapshot.extend = extend;
        })
    }

    pub(super) fn eval_line_delete(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(line) = self.lines.iter_mut().find(|line| line.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid line id `{id}`"),
            });
        };
        let Some(latest) = line.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("line `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest;
        next.bar_index = self.bars;
        next.exists = false;
        line.snapshots.push(next);
        Ok(PineValue::Void)
    }

    pub(super) fn eval_line_copy(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_id_arg(args)?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(line) = self.lines.iter().find(|line| line.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid line id `{id}`"),
            });
        };
        let Some(latest) = line.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("line `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        self.evict_oldest_lines_at_limit()?;
        let copied_id = self.next_line_id;
        self.next_line_id = self
            .next_line_id
            .checked_add(1)
            .ok_or_else(|| RuntimeError {
                message: "line id limit exceeded".to_owned(),
            })?;
        let mut copied = latest;
        copied.bar_index = self.bars;
        self.lines.push(LineOutput {
            id: copied_id,
            snapshots: vec![copied],
        });
        Ok(PineValue::Line(copied_id))
    }

    fn evict_oldest_lines_at_limit(&mut self) -> Result<(), RuntimeError> {
        let limit = self.max_line_count();
        while self.active_line_count() >= limit {
            let Some(line) = self.lines.iter_mut().find(|line| {
                line.snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            }) else {
                break;
            };
            let Some(latest) = line.snapshots.last().cloned() else {
                return Err(RuntimeError {
                    message: format!("line `{}` has no snapshots", line.id),
                });
            };
            let mut next = latest;
            next.bar_index = self.bars;
            next.exists = false;
            line.snapshots.push(next);
        }
        Ok(())
    }

    fn active_line_count(&self) -> usize {
        self.lines
            .iter()
            .filter(|line| {
                line.snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            })
            .count()
    }

    fn max_line_count(&self) -> usize {
        self.program
            .drawing_settings
            .max_lines_count
            .map_or(DEFAULT_MAX_LINES, |value| value as usize)
            .clamp(1, MAX_LINES)
    }

    pub(super) fn eval_line_get_x1(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_line_get(args, "line.get_x1", |snapshot| snapshot.x1.clone())
    }

    pub(super) fn eval_line_get_y1(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_line_get(args, "line.get_y1", |snapshot| snapshot.y1.clone())
    }

    pub(super) fn eval_line_get_x2(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_line_get(args, "line.get_x2", |snapshot| snapshot.x2.clone())
    }

    pub(super) fn eval_line_get_y2(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_line_get(args, "line.get_y2", |snapshot| snapshot.y2.clone())
    }

    pub(super) fn eval_line_get_price(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_get_id_arg(args, "line.get_price")?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let x_arg = match line_call_arg_expr(args, 1, "x") {
            Some(arg) => self.eval_expr(arg)?,
            None => {
                return Err(RuntimeError {
                    message: "line.get_price missing x argument".to_owned(),
                });
            }
        };
        let Some(x) = x_arg.as_f64() else {
            return Ok(PineValue::Na);
        };
        if !x.is_finite() {
            return Ok(PineValue::Na);
        }

        let Some(line) = self.lines.iter().find(|line| line.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid line id `{id}`"),
            });
        };
        let Some(latest) = line.snapshots.last() else {
            return Err(RuntimeError {
                message: format!("line `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        if latest.xloc == PineValue::String("xloc.bar_time".to_owned()) {
            return Ok(PineValue::Na);
        }
        let Some(x1) = latest.x1.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(y1) = latest.y1.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(x2) = latest.x2.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(y2) = latest.y2.as_f64() else {
            return Ok(PineValue::Na);
        };
        if !x1.is_finite() || !y1.is_finite() || !x2.is_finite() || !y2.is_finite() {
            return Ok(PineValue::Na);
        }
        let dx = x2 - x1;
        if dx == 0.0 {
            return Ok(PineValue::Na);
        }
        let value = y1 + (x - x1) * ((y2 - y1) / dx);
        if value.is_finite() {
            Ok(PineValue::Float(value))
        } else {
            Ok(PineValue::Na)
        }
    }

    fn eval_line_id_arg(&mut self, args: &[HirCallArg]) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = line_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: "line mutation missing id argument".to_owned(),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::Line(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("line mutation expected line id, got {value:?}"),
            }),
        }
    }

    fn eval_required_line_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = line_call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("line.new missing {name} argument"),
            });
        };
        self.eval_expr(arg)
    }

    fn eval_line_option(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: &str,
    ) -> Result<PineValue, RuntimeError> {
        self.eval_line_option_value(args, index, name, PineValue::String(default.to_owned()))
    }

    fn eval_line_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        match line_call_arg_expr(args, index, name) {
            Some(expr) => self.eval_expr(expr),
            None => Ok(default),
        }
    }

    fn eval_line_get(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
        get_value: impl FnOnce(&LineSnapshot) -> PineValue,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_line_get_id_arg(args, function_name)?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(line) = self.lines.iter().find(|line| line.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid line id `{id}`"),
            });
        };
        let Some(latest) = line.snapshots.last() else {
            return Err(RuntimeError {
                message: format!("line `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        Ok(get_value(latest))
    }

    fn eval_line_get_id_arg(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
    ) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = line_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: format!("{function_name} missing id argument"),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::Line(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("{function_name} expected line id, got {value:?}"),
            }),
        }
    }

    fn mutate_line(
        &mut self,
        id: Option<u32>,
        mutate: impl FnOnce(&mut LineSnapshot),
    ) -> Result<PineValue, RuntimeError> {
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(line) = self.lines.iter_mut().find(|line| line.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid line id `{id}`"),
            });
        };
        let Some(latest) = line.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("line `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest.clone();
        mutate(&mut next);
        if next != latest {
            next.bar_index = self.bars;
            line.snapshots.push(next);
        }
        Ok(PineValue::Void)
    }
}

struct LineFields {
    x1: PineValue,
    y1: PineValue,
    x2: PineValue,
    y2: PineValue,
    xloc: PineValue,
    extend: PineValue,
    color: PineValue,
    style: PineValue,
    width: PineValue,
}

fn line_has_named_point_args(args: &[HirCallArg]) -> bool {
    args.iter()
        .any(|arg| matches!(arg.name.as_deref(), Some("first_point" | "second_point")))
}

fn line_point_coordinates(point: PineValue, xloc: &PineValue) -> Option<(PineValue, PineValue)> {
    let PineValue::ChartPoint(point) = point else {
        return None;
    };
    let x = match xloc {
        PineValue::String(value) if value == "xloc.bar_time" => point.field(0),
        _ => point.field(1),
    };
    Some((x, point.field(2)))
}

fn line_call_arg_expr<'a>(args: &'a [HirCallArg], index: usize, name: &str) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}
