use crate::outputs::value_to_py;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};

pub(crate) fn tables_to_py(
    py: Python<'_>,
    tables: &[pine_runtime::TableOutput],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for table in tables {
        let item = PyDict::new(py);
        item.set_item("id", table.id)?;
        item.set_item("position", value_to_py(py, &table.position)?)?;
        item.set_item("bgColor", value_to_py(py, &table.bg_color)?)?;
        item.set_item("frameColor", value_to_py(py, &table.frame_color)?)?;
        item.set_item("frameWidth", value_to_py(py, &table.frame_width)?)?;
        item.set_item("borderColor", value_to_py(py, &table.border_color)?)?;
        item.set_item("borderWidth", value_to_py(py, &table.border_width)?)?;
        item.set_item("columns", table.columns)?;
        item.set_item("rows", table.rows)?;
        item.set_item("snapshots", table_snapshots_to_py(py, &table.snapshots)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn table_snapshots_to_py(
    py: Python<'_>,
    snapshots: &[pine_runtime::TableSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in snapshots {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        item.set_item("exists", snapshot.exists)?;
        if snapshot.exists {
            item.set_item("cells", table_cells_to_py(py, &snapshot.cells)?)?;
            item.set_item(
                "mergedCells",
                table_merged_cells_to_py(py, &snapshot.merged_cells)?,
            )?;
        }
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn table_cells_to_py(
    py: Python<'_>,
    cells: &[pine_runtime::TableCellSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for cell in cells {
        let item = PyDict::new(py);
        item.set_item("column", cell.column)?;
        item.set_item("row", cell.row)?;
        item.set_item("text", value_to_py(py, &cell.text)?)?;
        item.set_item("bgColor", value_to_py(py, &cell.bg_color)?)?;
        item.set_item("textColor", value_to_py(py, &cell.text_color)?)?;
        item.set_item("width", value_to_py(py, &cell.width)?)?;
        item.set_item("height", value_to_py(py, &cell.height)?)?;
        item.set_item("textSize", value_to_py(py, &cell.text_size)?)?;
        item.set_item("textHalign", value_to_py(py, &cell.text_halign)?)?;
        item.set_item("textValign", value_to_py(py, &cell.text_valign)?)?;
        item.set_item("textWrap", value_to_py(py, &cell.text_wrap)?)?;
        item.set_item("tooltip", value_to_py(py, &cell.tooltip)?)?;
        item.set_item("textFontFamily", value_to_py(py, &cell.text_font_family)?)?;
        item.set_item("textFormatting", value_to_py(py, &cell.text_formatting)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn table_merged_cells_to_py(
    py: Python<'_>,
    merged_cells: &[pine_runtime::TableMergedCellSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for cell in merged_cells {
        let item = PyDict::new(py);
        item.set_item("startColumn", cell.start_column)?;
        item.set_item("startRow", cell.start_row)?;
        item.set_item("endColumn", cell.end_column)?;
        item.set_item("endRow", cell.end_row)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}
