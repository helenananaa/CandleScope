use pine_ir::HirCallArg;

use crate::builtins::args::call_arg_expr;
use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_table_new(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let position = self.eval_required_table_arg(args, 0, "position")?;
        let columns = self.eval_required_table_int_arg(args, 1, "columns")?;
        let rows = self.eval_required_table_int_arg(args, 2, "rows")?;
        let bg_color = self.eval_table_option_value(args, 3, "bgcolor", PineValue::Na)?;
        let frame_color = self.eval_table_option_value(args, 4, "frame_color", PineValue::Na)?;
        let frame_width = self.eval_table_option_value(args, 5, "frame_width", PineValue::Na)?;
        let border_color = self.eval_table_option_value(args, 6, "border_color", PineValue::Na)?;
        let border_width = self.eval_table_option_value(args, 7, "border_width", PineValue::Na)?;
        if columns <= 0 || rows <= 0 {
            return Err(RuntimeError {
                message: "table dimensions must be positive".to_owned(),
            });
        }
        let Some(cells) = columns.checked_mul(rows) else {
            return Err(RuntimeError {
                message: "table cell count overflow".to_owned(),
            });
        };
        if cells > MAX_TABLE_CELLS {
            return Err(RuntimeError {
                message: format!("table cell count cannot exceed {MAX_TABLE_CELLS}"),
            });
        }
        if self.tables.len() >= MAX_TABLES {
            return Err(RuntimeError {
                message: format!("table count cannot exceed {MAX_TABLES}"),
            });
        }
        let id = self.next_table_id;
        self.next_table_id = self
            .next_table_id
            .checked_add(1)
            .ok_or_else(|| RuntimeError {
                message: "table id limit exceeded".to_owned(),
            })?;
        self.tables.push(TableOutput {
            id,
            position,
            bg_color,
            frame_color,
            frame_width,
            border_color,
            border_width,
            columns,
            rows,
            snapshots: vec![TableSnapshot {
                bar_index: self.bars,
                exists: true,
                cells: Vec::new(),
                merged_cells: Vec::new(),
            }],
        });
        Ok(PineValue::Table(id))
    }

    pub(super) fn eval_table_delete(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        let Some(latest) = table.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("table `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(PineValue::Void);
        }
        table.snapshots.push(TableSnapshot {
            bar_index: self.bars,
            exists: false,
            cells: Vec::new(),
            merged_cells: Vec::new(),
        });
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_clear(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let start_column = self.eval_required_table_int_arg(args, 1, "start_column")?;
        let start_row = self.eval_required_table_int_arg(args, 2, "start_row")?;
        let end_column = self.eval_required_table_int_arg(args, 3, "end_column")?;
        let end_row = self.eval_required_table_int_arg(args, 4, "end_row")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.clear_table_cells(id, start_column, start_row, end_column, end_row)?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_merge_cells(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let start_column = self.eval_required_table_int_arg(args, 1, "start_column")?;
        let start_row = self.eval_required_table_int_arg(args, 2, "start_row")?;
        let end_column = self.eval_required_table_int_arg(args, 3, "end_column")?;
        let end_row = self.eval_required_table_int_arg(args, 4, "end_row")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.merge_table_cells(id, start_column, start_row, end_column, end_row)?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text = self.eval_required_table_arg(args, 3, "text")?;
        let width = self.eval_table_option_value(args, 4, "width", PineValue::Na)?;
        let height = self.eval_table_option_value(args, 5, "height", PineValue::Na)?;
        let text_color = self.eval_table_option_value(args, 6, "text_color", PineValue::Na)?;
        let text_halign = self.eval_table_option_value(args, 7, "text_halign", PineValue::Na)?;
        let text_valign = self.eval_table_option_value(args, 8, "text_valign", PineValue::Na)?;
        let text_size = self.eval_table_option_value(args, 9, "text_size", PineValue::Na)?;
        let bg_color = self.eval_table_option_value(args, 10, "bgcolor", PineValue::Na)?;
        let tooltip =
            self.eval_table_option_value(args, 11, "tooltip", PineValue::String(String::new()))?;
        let text_font_family = self.eval_table_option_value(
            args,
            12,
            "text_font_family",
            PineValue::String("font.family_default".to_owned()),
        )?;
        let text_formatting =
            self.eval_table_text_formatting_option_value(args, 13, "text_formatting")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let next_cell = TableCellSnapshot {
            column,
            row,
            text,
            bg_color,
            text_color,
            width,
            height,
            text_size,
            text_halign,
            text_valign,
            text_wrap: PineValue::String("text.wrap_none".to_owned()),
            tooltip,
            text_font_family,
            text_formatting,
        };
        self.mutate_table_cell(id, column, row, true, |cell| *cell = next_cell)?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_set_position(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let position = self.eval_required_table_arg(args, 1, "position")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        if table
            .snapshots
            .last()
            .is_some_and(|snapshot| !snapshot.exists)
        {
            return Ok(PineValue::Void);
        }
        table.position = position;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_set_bgcolor(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let bg_color = self.eval_required_table_arg(args, 1, "bgcolor")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        if table
            .snapshots
            .last()
            .is_some_and(|snapshot| !snapshot.exists)
        {
            return Ok(PineValue::Void);
        }
        table.bg_color = bg_color;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_set_frame_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let frame_color = self.eval_required_table_arg(args, 1, "frame_color")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        if table
            .snapshots
            .last()
            .is_some_and(|snapshot| !snapshot.exists)
        {
            return Ok(PineValue::Void);
        }
        table.frame_color = frame_color;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_set_frame_width(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let frame_width = self.eval_required_table_arg(args, 1, "frame_width")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        if table
            .snapshots
            .last()
            .is_some_and(|snapshot| !snapshot.exists)
        {
            return Ok(PineValue::Void);
        }
        table.frame_width = frame_width;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_set_border_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let border_color = self.eval_required_table_arg(args, 1, "border_color")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        if table
            .snapshots
            .last()
            .is_some_and(|snapshot| !snapshot.exists)
        {
            return Ok(PineValue::Void);
        }
        table.border_color = border_color;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_set_border_width(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let border_width = self.eval_required_table_arg(args, 1, "border_width")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        if table
            .snapshots
            .last()
            .is_some_and(|snapshot| !snapshot.exists)
        {
            return Ok(PineValue::Void);
        }
        table.border_width = border_width;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text = self.eval_required_table_arg(args, 3, "text")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text = text;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_bgcolor(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let bg_color = self.eval_required_table_arg(args, 3, "bgcolor")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.bg_color = bg_color;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text_color(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text_color = self.eval_required_table_arg(args, 3, "text_color")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text_color = text_color;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_width(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let width = self.eval_required_table_arg(args, 3, "width")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.width = width;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_height(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let height = self.eval_required_table_arg(args, 3, "height")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.height = height;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text_size(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text_size = self.eval_required_table_arg(args, 3, "text_size")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text_size = text_size;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text_halign(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text_halign = self.eval_required_table_arg(args, 3, "text_halign")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text_halign = text_halign;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text_valign(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text_valign = self.eval_required_table_arg(args, 3, "text_valign")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text_valign = text_valign;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text_wrap(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text_wrap = self.eval_required_table_arg(args, 3, "text_wrap")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text_wrap = text_wrap;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_tooltip(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let tooltip = self.eval_required_table_arg(args, 3, "tooltip")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.tooltip = tooltip;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text_font_family(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text_font_family = self.eval_required_table_arg(args, 3, "text_font_family")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text_font_family = text_font_family;
        })?;
        Ok(PineValue::Void)
    }

    pub(super) fn eval_table_cell_set_text_formatting(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_table_id_arg(args)?;
        let column = self.eval_required_table_int_arg(args, 1, "column")?;
        let row = self.eval_required_table_int_arg(args, 2, "row")?;
        let text_formatting = self.eval_table_text_formatting_arg(args, 3, "text_formatting")?;
        let Some(id) = id else {
            return Ok(PineValue::Void);
        };
        self.mutate_table_cell(id, column, row, false, |cell| {
            cell.text_formatting = text_formatting;
        })?;
        Ok(PineValue::Void)
    }

    fn eval_table_id_arg(&mut self, args: &[HirCallArg]) -> Result<Option<u32>, RuntimeError> {
        let Some(id_arg) = call_arg_expr(args, 0, "id") else {
            return Err(RuntimeError {
                message: "table mutation missing id argument".to_owned(),
            });
        };
        match self.eval_expr(id_arg)? {
            PineValue::Table(id) => Ok(Some(id)),
            PineValue::Na => Ok(None),
            value => Err(RuntimeError {
                message: format!("table mutation expected table id, got {value:?}"),
            }),
        }
    }

    fn eval_required_table_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("table call missing {name} argument"),
            });
        };
        self.eval_expr(arg)
    }

    fn eval_required_table_int_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<i64, RuntimeError> {
        match self.eval_required_table_arg(args, index, name)? {
            PineValue::Int(value) => Ok(value),
            PineValue::Na => Err(RuntimeError {
                message: format!("table call expected integer {name}, got na"),
            }),
            value => Err(RuntimeError {
                message: format!("table call expected integer {name}, got {value:?}"),
            }),
        }
    }

    fn eval_table_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        match optional_table_arg_expr(args, index, name) {
            Some(expr) => self.eval_expr(expr),
            None => Ok(default),
        }
    }

    fn eval_table_text_formatting_option_value(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = optional_table_arg_expr(args, index, name) else {
            return Ok(PineValue::Int(0));
        };
        self.eval_table_text_formatting_expr(arg, name)
    }

    fn eval_table_text_formatting_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("table mutation missing `{name}` argument"),
            });
        };
        self.eval_table_text_formatting_expr(arg, name)
    }

    fn eval_table_text_formatting_expr(
        &mut self,
        arg: &HirExpr,
        name: &str,
    ) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(arg)?;
        match value {
            PineValue::Int(mask) if (0..=3).contains(&mask) => Ok(PineValue::Int(mask)),
            PineValue::Na => Ok(PineValue::Na),
            value => Err(RuntimeError {
                message: format!(
                    "table mutation `{name}` expected text format mask, got {value:?}"
                ),
            }),
        }
    }

    fn clear_table_cells(
        &mut self,
        id: u32,
        start_column: i64,
        start_row: i64,
        end_column: i64,
        end_row: i64,
    ) -> Result<(), RuntimeError> {
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        let Some(latest) = table.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("table `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(());
        }
        if start_column > end_column || start_row > end_row {
            return Err(RuntimeError {
                message: "table clear start coordinate cannot exceed end coordinate".to_owned(),
            });
        }
        if start_column < 0
            || start_column >= table.columns
            || end_column < 0
            || end_column >= table.columns
            || start_row < 0
            || start_row >= table.rows
            || end_row < 0
            || end_row >= table.rows
        {
            return Err(RuntimeError {
                message: format!(
                    "table clear coordinate out of bounds `{start_column},{start_row}` to `{end_column},{end_row}`"
                ),
            });
        }
        let mut next = latest.clone();
        next.cells.retain(|cell| {
            cell.column < start_column
                || cell.column > end_column
                || cell.row < start_row
                || cell.row > end_row
        });
        next.merged_cells.retain(|merged_cell| {
            !rectangles_intersect(
                (start_column, start_row, end_column, end_row),
                (
                    merged_cell.start_column,
                    merged_cell.start_row,
                    merged_cell.end_column,
                    merged_cell.end_row,
                ),
            )
        });
        if next != latest {
            next.bar_index = self.bars;
            table.snapshots.push(next);
        }
        Ok(())
    }

    fn merge_table_cells(
        &mut self,
        id: u32,
        start_column: i64,
        start_row: i64,
        end_column: i64,
        end_row: i64,
    ) -> Result<(), RuntimeError> {
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        let Some(latest) = table.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("table `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(());
        }
        if start_column > end_column || start_row > end_row {
            return Err(RuntimeError {
                message: "table merge start coordinate cannot exceed end coordinate".to_owned(),
            });
        }
        if start_column < 0
            || start_column >= table.columns
            || end_column < 0
            || end_column >= table.columns
            || start_row < 0
            || start_row >= table.rows
            || end_row < 0
            || end_row >= table.rows
        {
            return Err(RuntimeError {
                message: format!(
                    "table merge coordinate out of bounds `{start_column},{start_row}` to `{end_column},{end_row}`"
                ),
            });
        }
        if latest.merged_cells.iter().any(|merged_cell| {
            rectangles_intersect(
                (start_column, start_row, end_column, end_row),
                (
                    merged_cell.start_column,
                    merged_cell.start_row,
                    merged_cell.end_column,
                    merged_cell.end_row,
                ),
            )
        }) {
            return Err(RuntimeError {
                message: "table merge range intersects existing merged cells".to_owned(),
            });
        }
        let mut next = latest.clone();
        next.merged_cells.push(TableMergedCellSnapshot {
            start_column,
            start_row,
            end_column,
            end_row,
        });
        next.merged_cells
            .sort_by_key(|cell| (cell.start_row, cell.start_column));
        if next != latest {
            next.bar_index = self.bars;
            table.snapshots.push(next);
        }
        Ok(())
    }

    fn mutate_table_cell<F>(
        &mut self,
        id: u32,
        column: i64,
        row: i64,
        create_missing: bool,
        mutate: F,
    ) -> Result<(), RuntimeError>
    where
        F: FnOnce(&mut TableCellSnapshot),
    {
        let Some(table) = self.tables.iter_mut().find(|table| table.id == id) else {
            return Err(RuntimeError {
                message: format!("invalid table id `{id}`"),
            });
        };
        let Some(latest) = table.snapshots.last().cloned() else {
            return Err(RuntimeError {
                message: format!("table `{id}` has no snapshots"),
            });
        };
        if !latest.exists {
            return Ok(());
        }
        if column < 0 || column >= table.columns || row < 0 || row >= table.rows {
            return Err(RuntimeError {
                message: format!("table cell coordinate out of bounds `{column},{row}`"),
            });
        }
        let mut next = latest.clone();
        match next
            .cells
            .iter_mut()
            .find(|cell| cell.column == column && cell.row == row)
        {
            Some(cell) => mutate(cell),
            None if create_missing => {
                let mut cell = TableCellSnapshot {
                    column,
                    row,
                    text: PineValue::String(String::new()),
                    bg_color: PineValue::Na,
                    text_color: PineValue::Na,
                    width: PineValue::Na,
                    height: PineValue::Na,
                    text_size: PineValue::Na,
                    text_halign: PineValue::Na,
                    text_valign: PineValue::Na,
                    text_wrap: PineValue::String("text.wrap_none".to_owned()),
                    tooltip: PineValue::String(String::new()),
                    text_font_family: PineValue::String("font.family_default".to_owned()),
                    text_formatting: PineValue::Int(0),
                };
                mutate(&mut cell);
                next.cells.push(cell);
            }
            None => {
                return Err(RuntimeError {
                    message: format!("table cell `{column},{row}` has not been populated"),
                });
            }
        }
        next.cells.sort_by_key(|cell| (cell.row, cell.column));
        if next != latest {
            next.bar_index = self.bars;
            table.snapshots.push(next);
        }
        Ok(())
    }
}

fn optional_table_arg_expr<'a>(
    args: &'a [HirCallArg],
    index: usize,
    name: &str,
) -> Option<&'a pine_ir::HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

fn rectangles_intersect(left: (i64, i64, i64, i64), right: (i64, i64, i64, i64)) -> bool {
    let (start_column, start_row, end_column, end_row) = left;
    let (other_start_column, other_start_row, other_end_column, other_end_row) = right;
    start_column <= other_end_column
        && end_column >= other_start_column
        && start_row <= other_end_row
        && end_row >= other_start_row
}
