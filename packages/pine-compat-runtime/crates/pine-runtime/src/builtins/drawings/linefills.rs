use pine_ir::{HirCallArg, HirExpr};

use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_linefill_new(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let line1 = self.eval_linefill_line_arg(args, 0, "line1")?;
        let line2 = self.eval_linefill_line_arg(args, 1, "line2")?;
        let color = self.eval_required_linefill_arg(args, 2, "color")?;
        let (Some(line1), Some(line2)) = (line1, line2) else {
            return Ok(PineValue::Na);
        };
        if !self.line_exists(line1)? || !self.line_exists(line2)? {
            return Ok(PineValue::Na);
        }
        if let Some(existing_index) = self
            .line_fills
            .iter()
            .position(|line_fill| linefill_active_same_pair(line_fill, line1, line2))
        {
            let latest = self.line_fills[existing_index]
                .snapshots
                .last()
                .cloned()
                .ok_or_else(|| RuntimeError {
                    message: format!(
                        "linefill `{}` has no snapshots",
                        self.line_fills[existing_index].id
                    ),
                })?;
            if latest.exists {
                let mut replacement = latest;
                replacement.bar_index = self.bars;
                replacement.exists = false;
                self.line_fills[existing_index].snapshots.push(replacement);
            }
        }
        if self.line_fills.len() >= MAX_LINEFILLS {
            return Err(RuntimeError {
                message: format!("linefill count cannot exceed {MAX_LINEFILLS}"),
            });
        }
        let id = self.next_line_fill_id;
        self.next_line_fill_id =
            self.next_line_fill_id
                .checked_add(1)
                .ok_or_else(|| RuntimeError {
                    message: "linefill id limit exceeded".to_owned(),
                })?;
        self.line_fills.push(LineFillOutput {
            id,
            snapshots: vec![LineFillSnapshot {
                bar_index: self.bars,
                exists: true,
                line1,
                line2,
                color,
            }],
        });
        Ok(PineValue::LineFill(id))
    }

    pub(super) fn eval_linefill_set_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_linefill_id_arg(args)?;
        let color = self.eval_required_linefill_arg(args, 1, "color")?;
        self.mutate_linefill(id, |snapshot| {
            snapshot.color = color;
        })
    }

    pub(super) fn eval_linefill_get_line1(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_linefill_get(args, "linefill.get_line1", |snapshot| {
            PineValue::Line(snapshot.line1)
        })
    }

    pub(super) fn eval_linefill_get_line2(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_linefill_get(args, "linefill.get_line2", |snapshot| {
            PineValue::Line(snapshot.line2)
        })
    }

    pub(super) fn eval_linefill_delete(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_linefill_id_arg(args)?;
        self.mutate_linefill(id, |snapshot| {
            snapshot.exists = false;
        })
    }

    fn eval_linefill_id_arg(&mut self, args: &[HirCallArg]) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = linefill_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: "linefill mutation missing id argument".to_owned(),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::LineFill(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("linefill mutation expected linefill id, got {value:?}"),
            }),
        }
    }

    fn eval_linefill_line_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<Option<u32>, RuntimeError> {
        let Some(arg) = linefill_call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("linefill.new missing {name} argument"),
            });
        };
        match self.eval_expr(arg)? {
            PineValue::Line(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("linefill.new expected line id for {name}, got {value:?}"),
            }),
        }
    }

    fn eval_required_linefill_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = linefill_call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("linefill.new missing {name} argument"),
            });
        };
        self.eval_expr(arg)
    }

    fn eval_linefill_get(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
        get_value: impl FnOnce(&LineFillSnapshot) -> PineValue,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_linefill_get_id_arg(args, function_name)?;
        let Some(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(line_fill) = self.line_fills.iter().find(|line_fill| line_fill.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid linefill id `{id}`"),
            });
        };
        let Some(latest) = line_fill.snapshots.last() else {
            return Err(RuntimeError {
                message: format!("linefill `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Na);
        }
        Ok(get_value(latest))
    }

    fn eval_linefill_get_id_arg(
        &mut self,
        args: &[HirCallArg],
        function_name: &str,
    ) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = linefill_call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: format!("{function_name} missing id argument"),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::LineFill(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("{function_name} expected linefill id, got {value:?}"),
            }),
        }
    }

    fn line_exists(&self, id: u32) -> Result<bool, RuntimeError> {
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
        Ok(latest.exists)
    }

    fn mutate_linefill(
        &mut self,
        id: Option<u32>,
        mutate: impl FnOnce(&mut LineFillSnapshot),
    ) -> Result<PineValue, RuntimeError> {
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(line_fill) = self
            .line_fills
            .iter_mut()
            .find(|line_fill| line_fill.id == id)
        else {
            return Err(RuntimeError {
                message: format!("invalid linefill id `{id}`"),
            });
        };
        let Some(latest) = line_fill.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("linefill `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        let mut next = latest.clone();
        mutate(&mut next);
        if next != latest {
            next.bar_index = self.bars;
            line_fill.snapshots.push(next);
        }
        Ok(PineValue::Void)
    }
}

fn linefill_active_same_pair(line_fill: &LineFillOutput, line1: u32, line2: u32) -> bool {
    let Some(latest) = line_fill.snapshots.last() else {
        return false;
    };
    latest.exists
        && ((latest.line1 == line1 && latest.line2 == line2)
            || (latest.line1 == line2 && latest.line2 == line1))
}

fn linefill_call_arg_expr<'a>(
    args: &'a [HirCallArg],
    index: usize,
    name: &str,
) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}
