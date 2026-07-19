use pine_ir::{HirCallArg, HirExpr};

use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_polyline_new(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let points = self.eval_polyline_points_arg(args)?;
        let curved = self.eval_polyline_option_value(args, 1, "curved", PineValue::Bool(false))?;
        let closed = self.eval_polyline_option_value(args, 2, "closed", PineValue::Bool(false))?;
        let xloc = self.eval_polyline_option(args, 3, "xloc", "xloc.bar_index")?;
        let line_color =
            self.eval_polyline_option_value(args, 4, "line_color", PineValue::Color(0x2196F3))?;
        let fill_color = self.eval_polyline_option_value(args, 5, "fill_color", PineValue::Na)?;
        let line_style = self.eval_polyline_option(args, 6, "line_style", "line.style_solid")?;
        let line_width =
            self.eval_polyline_option_value(args, 7, "line_width", PineValue::Int(1))?;
        let force_overlay =
            self.eval_polyline_option_value(args, 8, "force_overlay", PineValue::Bool(false))?;
        let Some(points) = points else {
            return Ok(PineValue::Na);
        };
        self.evict_oldest_polylines_at_limit()?;
        let id = self.next_polyline_id;
        self.next_polyline_id =
            self.next_polyline_id
                .checked_add(1)
                .ok_or_else(|| RuntimeError {
                    message: "polyline id limit exceeded".to_owned(),
                })?;
        self.polylines.push(PolylineOutput {
            id,
            snapshots: vec![PolylineSnapshot {
                bar_index: self.bars,
                exists: true,
                points,
                curved,
                closed,
                xloc,
                line_color,
                fill_color,
                line_style,
                line_width,
                force_overlay,
            }],
        });
        Ok(PineValue::Polyline(id))
    }

    pub(super) fn eval_polyline_delete(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_polyline_id_arg(args)?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(polyline) = self.polylines.iter_mut().find(|polyline| polyline.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid polyline id `{id}`"),
            });
        };
        let Some(latest) = polyline.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("polyline `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest;
        next.bar_index = self.bars;
        next.exists = false;
        polyline.snapshots.push(next);
        Ok(PineValue::Void)
    }

    fn evict_oldest_polylines_at_limit(&mut self) -> Result<(), RuntimeError> {
        let limit = self.max_polyline_count();
        while self.active_polyline_count() >= limit {
            let Some(polyline) = self.polylines.iter_mut().find(|polyline| {
                polyline
                    .snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            }) else {
                break;
            };
            let Some(latest) = polyline.snapshots.last().cloned() else {
                return Err(RuntimeError {
                    message: format!("polyline `{}` has no snapshots", polyline.id),
                });
            };
            let mut next = latest;
            next.bar_index = self.bars;
            next.exists = false;
            polyline.snapshots.push(next);
        }
        Ok(())
    }

    fn active_polyline_count(&self) -> usize {
        self.polylines
            .iter()
            .filter(|polyline| {
                polyline
                    .snapshots
                    .last()
                    .is_some_and(|snapshot| snapshot.exists)
            })
            .count()
    }

    fn max_polyline_count(&self) -> usize {
        self.program
            .drawing_settings
            .max_polylines_count
            .map_or(DEFAULT_MAX_POLYLINES, |value| value as usize)
            .clamp(1, MAX_POLYLINES)
    }

    fn eval_polyline_id_arg(&mut self, args: &[HirCallArg]) -> Result<Option<u32>, RuntimeError> {
        let Some(arg) = polyline_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: "polyline id argument is required".to_owned(),
            });
        };
        match self.eval_expr(arg)? {
            PineValue::Polyline(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("expected polyline id, got {value:?}"),
            }),
        }
    }

    fn eval_polyline_points_arg(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<Option<Vec<PineValue>>, RuntimeError> {
        let Some(arg) = polyline_call_arg_expr(args, 0, "points") else {
            return Err(RuntimeError {
                message: "polyline.new missing points argument".to_owned(),
            });
        };
        match self.eval_expr(arg)? {
            PineValue::Array(array_id) => {
                if self.array_kinds.get(&array_id) != Some(&ArrayElementKind::ChartPoint) {
                    return Err(RuntimeError {
                        message: "polyline.new expected array<chart.point>".to_owned(),
                    });
                }
                Ok(Some(self.array_values_clone(array_id)?.unwrap_or_default()))
            }
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("polyline.new expected array<chart.point>, got {value:?}"),
            }),
        }
    }

    fn eval_polyline_option(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: &str,
    ) -> Result<PineValue, RuntimeError> {
        self.eval_polyline_option_value(args, index, name, PineValue::String(default.to_owned()))
    }

    fn eval_polyline_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        match polyline_call_arg_expr(args, index, name) {
            Some(expr) => self.eval_expr(expr),
            None => Ok(default),
        }
    }
}

fn polyline_call_arg_expr<'a>(
    args: &'a [HirCallArg],
    index: usize,
    name: &str,
) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}
