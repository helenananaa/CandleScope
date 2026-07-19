pub(crate) const RUNTIME_ERROR_FIXTURES: &[(&str, &str)] = &[
    (
        "tests/fixtures/regressions/runtime_error_custom_message.pine",
        "invalid bar 2",
    ),
    (
        "tests/fixtures/regressions/runtime_error_na_message.pine",
        "NaN",
    ),
    (
        "tests/fixtures/regressions/array_concat_limit.pine",
        "array.concat cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_join_result_limit.pine",
        "array.join result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/array_push_limit.pine",
        "array.push cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_insert_limit.pine",
        "array.insert cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_get_positive_bounds.pine",
        "array index 3 is out of bounds for array of size 3",
    ),
    (
        "tests/fixtures/regressions/array_get_negative_bounds.pine",
        "array index -4 is out of bounds for array of size 3",
    ),
    (
        "tests/fixtures/regressions/array_set_bounds.pine",
        "array index 3 is out of bounds for array of size 3",
    ),
    (
        "tests/fixtures/regressions/array_insert_bounds.pine",
        "array index 4 is out of bounds for array of size 3",
    ),
    (
        "tests/fixtures/regressions/array_remove_empty_bounds.pine",
        "array index 0 is out of bounds for array of size 0",
    ),
    (
        "tests/fixtures/regressions/array_slice_parent_out_of_bounds.pine",
        "array slice is out of bounds of the parent array",
    ),
    (
        "tests/fixtures/regressions/for_in_pop_shrink_bounds.pine",
        "array index 1 is out of bounds for array of size 1",
    ),
    (
        "tests/fixtures/regressions/for_in_clear_shrink_bounds.pine",
        "array index 1 is out of bounds for array of size 0",
    ),
    (
        "tests/fixtures/regressions/map_for_in_put_size_change.pine",
        "map size cannot change during direct for...in iteration",
    ),
    (
        "tests/fixtures/regressions/map_for_in_key_put_size_change.pine",
        "map size cannot change during direct for...in iteration",
    ),
    (
        "tests/fixtures/regressions/array_unshift_limit.pine",
        "array.unshift cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_sort_unsupported_order.pine",
        "unsupported array.sort order `sideways`",
    ),
    (
        "tests/fixtures/regressions/array_sort_indices_unsupported_order.pine",
        "unsupported array.sort_indices order `sideways`",
    ),
    (
        "tests/fixtures/regressions/array_sort_udt_na_element.pine",
        "array.sort cannot sort UDT arrays containing na elements",
    ),
    (
        "tests/fixtures/regressions/array_sort_indices_udt_na_element.pine",
        "array.sort_indices cannot sort UDT arrays containing na elements",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udf_return.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_builtin_result.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_ternary_result.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_if_result.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_switch_result.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_for_result.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_while_result.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_udf_passthrough.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_udf_nested_passthrough.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_udf_return.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_udf_nested_return.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_method_passthrough.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_method_nested_passthrough.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_method_return.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_udt_field_method_nested_return.pine",
        "history offset must be non-negative",
    ),
    (
        "tests/fixtures/regressions/array_new_float_negative_size.pine",
        "array.new_float size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_float_size_limit.pine",
        "array.new_float size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_int_negative_size.pine",
        "array.new_int size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_int_size_limit.pine",
        "array.new_int size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_bool_negative_size.pine",
        "array.new_bool size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_bool_size_limit.pine",
        "array.new_bool size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_string_negative_size.pine",
        "array.new_string size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_string_size_limit.pine",
        "array.new_string size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_color_negative_size.pine",
        "array.new_color size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_color_size_limit.pine",
        "array.new_color size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_line_negative_size.pine",
        "array.new_line size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_line_size_limit.pine",
        "array.new_line size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_linefill_negative_size.pine",
        "array.new_linefill size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_linefill_size_limit.pine",
        "array.new_linefill size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_label_negative_size.pine",
        "array.new_label size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_label_size_limit.pine",
        "array.new_label size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_box_negative_size.pine",
        "array.new_box size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_box_size_limit.pine",
        "array.new_box size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_table_negative_size.pine",
        "array.new_table size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_table_size_limit.pine",
        "array.new_table size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/array_new_chart_point_negative_size.pine",
        "array.new<chart.point> size cannot be negative",
    ),
    (
        "tests/fixtures/regressions/array_new_chart_point_size_limit.pine",
        "array.new<chart.point> size cannot exceed 100000 elements",
    ),
    (
        "tests/fixtures/regressions/matrix_get_row_bounds.pine",
        "matrix row index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_column_bounds.pine",
        "matrix column index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_method_row_bounds.pine",
        "matrix row index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_method_column_bounds.pine",
        "matrix column index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_negative_row_bounds.pine",
        "matrix row index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_negative_column_bounds.pine",
        "matrix column index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_method_negative_row_bounds.pine",
        "matrix row index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_method_negative_column_bounds.pine",
        "matrix column index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_get_na_row_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_get_na_column_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_get_method_na_row_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_get_method_na_column_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_row_bounds.pine",
        "matrix row index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_col_bounds.pine",
        "matrix column index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_row_negative_bounds.pine",
        "matrix row index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_col_negative_bounds.pine",
        "matrix column index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_row_na_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_col_na_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_row_method_bounds.pine",
        "matrix row index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_col_method_bounds.pine",
        "matrix column index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_row_method_negative_bounds.pine",
        "matrix row index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_col_method_negative_bounds.pine",
        "matrix column index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_row_method_na_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_col_method_na_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_set_row_bounds.pine",
        "matrix row index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_column_bounds.pine",
        "matrix column index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_method_row_bounds.pine",
        "matrix row index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_method_column_bounds.pine",
        "matrix column index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_negative_row_bounds.pine",
        "matrix row index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_negative_column_bounds.pine",
        "matrix column index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_method_negative_row_bounds.pine",
        "matrix row index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_method_negative_column_bounds.pine",
        "matrix column index -1 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_set_na_row_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_set_method_na_row_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_set_na_column_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_set_method_na_column_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_new_negative_row_count.pine",
        "matrix row count cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_new_negative_column_count.pine",
        "matrix column count cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_new_na_row_count.pine",
        "matrix row count cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_new_na_column_count.pine",
        "matrix column count cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_cell_limit.pine",
        "matrix cell count cannot exceed 100000",
    ),
    (
        "tests/fixtures/regressions/matrix_concat_cell_limit.pine",
        "matrix cell count cannot exceed 100000",
    ),
    (
        "tests/fixtures/regressions/matrix_concat_column_mismatch.pine",
        "matrix.concat column count 2 must match source column count 3",
    ),
    (
        "tests/fixtures/regressions/matrix_kron_cell_limit.pine",
        "matrix cell count cannot exceed 100000",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_kron_cell_limit.pine",
        "matrix cell count cannot exceed 100000",
    ),
    (
        "tests/fixtures/regressions/matrix_mult_cell_limit.pine",
        "matrix cell count cannot exceed 100000",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_mult_cell_limit.pine",
        "matrix cell count cannot exceed 100000",
    ),
    (
        "tests/fixtures/regressions/matrix_mult_shape_mismatch.pine",
        "matrix multiplication requires left column count to match right row count",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_mult_shape_mismatch.pine",
        "matrix multiplication requires left column count to match right row count",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_mult_array_size_mismatch.pine",
        "matrix multiplication requires matrix column count to match array size",
    ),
    (
        "tests/fixtures/regressions/matrix_diff_shape_mismatch.pine",
        "matrix difference requires matching row and column counts",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_diff_shape_mismatch.pine",
        "matrix difference requires matching row and column counts",
    ),
    (
        "tests/fixtures/regressions/matrix_pow_non_square.pine",
        "matrix power requires a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_pow_non_square.pine",
        "matrix power requires a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_pow_negative_power.pine",
        "matrix power cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_pow_negative_power.pine",
        "matrix power cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_pow_na_power.pine",
        "matrix power cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_add_row_bounds.pine",
        "matrix row index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_add_row_size_mismatch.pine",
        "matrix add_row array size 1 must match column count 2",
    ),
    (
        "tests/fixtures/regressions/matrix_add_col_bounds.pine",
        "matrix column index 2 is out of bounds for size 2",
    ),
    (
        "tests/fixtures/regressions/matrix_add_col_size_mismatch.pine",
        "matrix add_col array size 1 must match row count 2",
    ),
    (
        "tests/fixtures/regressions/matrix_remove_row_bounds.pine",
        "matrix row index 1 is out of bounds for size 1",
    ),
    (
        "tests/fixtures/regressions/matrix_remove_row_na_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_remove_col_bounds.pine",
        "matrix column index 1 is out of bounds for size 1",
    ),
    (
        "tests/fixtures/regressions/matrix_remove_col_na_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_swap_rows_bounds.pine",
        "matrix row index 1 is out of bounds for size 1",
    ),
    (
        "tests/fixtures/regressions/matrix_swap_rows_na_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_swap_columns_bounds.pine",
        "matrix column index 1 is out of bounds for size 1",
    ),
    (
        "tests/fixtures/regressions/matrix_swap_columns_na_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_sort_bounds.pine",
        "matrix column index 1 is out of bounds for size 1",
    ),
    (
        "tests/fixtures/regressions/matrix_sort_na_index.pine",
        "matrix column index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_sort_unsupported_order.pine",
        "unsupported matrix.sort order `sideways`",
    ),
    (
        "tests/fixtures/regressions/matrix_submatrix_bounds.pine",
        "matrix row index 4 is out of bounds for size 4",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_submatrix_bounds.pine",
        "matrix row index 4 is out of bounds for size 4",
    ),
    (
        "tests/fixtures/regressions/matrix_submatrix_na_index.pine",
        "matrix row index cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_submatrix_reversed_row_range.pine",
        "matrix row range start cannot be greater than end",
    ),
    (
        "tests/fixtures/regressions/matrix_submatrix_reversed_column_range.pine",
        "matrix column range start cannot be greater than end",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_mismatch.pine",
        "matrix reshape dimensions must preserve element count",
    ),
    (
        "tests/fixtures/regressions/matrix_det_non_square.pine",
        "matrix determinant requires a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_eigenvalues_non_square.pine",
        "matrix eigenvalues require a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_eigenvectors_non_square.pine",
        "matrix eigenvectors require a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_eigenvectors_non_square.pine",
        "matrix eigenvectors require a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_inv_non_square.pine",
        "matrix inverse requires a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_call_result_inv_non_square.pine",
        "matrix inverse requires a square matrix",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_method_mismatch.pine",
        "matrix reshape dimensions must preserve element count",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_negative_row_count.pine",
        "matrix row count cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_method_negative_row_count.pine",
        "matrix row count cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_negative_column_count.pine",
        "matrix column count cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_method_negative_column_count.pine",
        "matrix column count cannot be negative",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_na_row_count.pine",
        "matrix row count cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_method_na_row_count.pine",
        "matrix row count cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_method_na_column_count.pine",
        "matrix column count cannot be na",
    ),
    (
        "tests/fixtures/regressions/matrix_reshape_na_column_count.pine",
        "matrix column count cannot be na",
    ),
    (
        "tests/fixtures/regressions/table_new_count_limit.pine",
        "table count cannot exceed 50",
    ),
    (
        "tests/fixtures/regressions/table_new_cell_limit.pine",
        "table cell count cannot exceed 1000",
    ),
    (
        "tests/fixtures/regressions/table_new_positive_dimensions.pine",
        "table dimensions must be positive",
    ),
    (
        "tests/fixtures/regressions/table_new_positive_row_dimension.pine",
        "table dimensions must be positive",
    ),
    (
        "tests/fixtures/regressions/table_new_negative_column_dimension.pine",
        "table dimensions must be positive",
    ),
    (
        "tests/fixtures/regressions/table_new_negative_row_dimension.pine",
        "table dimensions must be positive",
    ),
    (
        "tests/fixtures/regressions/table_clear_coordinate_order.pine",
        "table clear start coordinate cannot exceed end coordinate",
    ),
    (
        "tests/fixtures/regressions/table_clear_coordinate_row_order.pine",
        "table clear start coordinate cannot exceed end coordinate",
    ),
    (
        "tests/fixtures/regressions/table_clear_coordinate_bounds.pine",
        "table clear coordinate out of bounds `0,0` to `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_clear_coordinate_row_bounds.pine",
        "table clear coordinate out of bounds `0,0` to `1,1`",
    ),
    (
        "tests/fixtures/regressions/table_clear_coordinate_negative.pine",
        "table clear coordinate out of bounds `-1,0` to `1,0`",
    ),
    (
        "tests/fixtures/regressions/table_clear_coordinate_row_negative.pine",
        "table clear coordinate out of bounds `0,-1` to `1,0`",
    ),
    (
        "tests/fixtures/regressions/table_merge_coordinate_order.pine",
        "table merge start coordinate cannot exceed end coordinate",
    ),
    (
        "tests/fixtures/regressions/table_merge_coordinate_row_order.pine",
        "table merge start coordinate cannot exceed end coordinate",
    ),
    (
        "tests/fixtures/regressions/table_merge_coordinate_bounds.pine",
        "table merge coordinate out of bounds `0,0` to `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_merge_coordinate_row_bounds.pine",
        "table merge coordinate out of bounds `0,0` to `1,1`",
    ),
    (
        "tests/fixtures/regressions/table_merge_coordinate_negative.pine",
        "table merge coordinate out of bounds `-1,0` to `1,0`",
    ),
    (
        "tests/fixtures/regressions/table_merge_coordinate_row_negative.pine",
        "table merge coordinate out of bounds `0,-1` to `1,0`",
    ),
    (
        "tests/fixtures/regressions/table_merge_overlap.pine",
        "table merge range intersects existing merged cells",
    ),
    (
        "tests/fixtures/regressions/table_cell_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_bgcolor_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_bgcolor_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_bgcolor_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_bgcolor_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_bgcolor_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_color_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_color_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_color_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_color_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_color_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_width_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_width_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_width_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_width_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_width_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_height_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_height_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_height_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_height_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_height_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_size_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_size_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_size_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_size_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_size_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_halign_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_halign_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_halign_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_halign_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_halign_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_valign_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_valign_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_valign_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_valign_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_valign_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_wrap_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_wrap_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_wrap_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_wrap_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_wrap_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_tooltip_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_tooltip_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_tooltip_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_tooltip_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_tooltip_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_font_family_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_font_family_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_font_family_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_font_family_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_font_family_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_formatting_missing_cell.pine",
        "table cell `0,0` has not been populated",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_formatting_coordinate_bounds.pine",
        "table cell coordinate out of bounds `2,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_formatting_coordinate_row_bounds.pine",
        "table cell coordinate out of bounds `0,1`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_formatting_coordinate_negative.pine",
        "table cell coordinate out of bounds `-1,0`",
    ),
    (
        "tests/fixtures/regressions/table_cell_set_text_formatting_coordinate_row_negative.pine",
        "table cell coordinate out of bounds `0,-1`",
    ),
    (
        "tests/fixtures/regressions/str_match_invalid_regex.pine",
        "str.match invalid regex",
    ),
    (
        "tests/fixtures/regressions/str_match_invalid_unicode_block.pine",
        "str.match invalid regex",
    ),
    (
        "tests/fixtures/regressions/str_match_invalid_class_range.pine",
        "str.match invalid regex",
    ),
    (
        "tests/fixtures/regressions/str_match_invalid_class_intersection.pine",
        "str.match invalid regex",
    ),
    (
        "tests/fixtures/regressions/str_match_invalid_named_character.pine",
        "str.match invalid regex",
    ),
    (
        "tests/fixtures/regressions/str_repeat_negative_count.pine",
        "str.repeat count cannot be negative: -1",
    ),
    (
        "tests/fixtures/regressions/str_repeat_result_limit.pine",
        "str.repeat result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/string_concatenation_result_limit.pine",
        "string concatenation result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/str_replace_result_limit.pine",
        "str.replace result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/str_replace_all_result_limit.pine",
        "str.replace_all result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/str_tostring_result_limit.pine",
        "str.tostring result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/str_substring_invalid_range.pine",
        "str.substring end_pos 1 is less than begin_pos 2",
    ),
    (
        "tests/fixtures/regressions/str_substring_begin_out_of_range.pine",
        "str.substring begin_pos 4 is outside string length 3",
    ),
    (
        "tests/fixtures/regressions/str_substring_negative_begin.pine",
        "str.substring begin_pos -1 is outside string length 3",
    ),
    (
        "tests/fixtures/regressions/str_substring_negative_end.pine",
        "str.substring end_pos -1 is less than begin_pos 0",
    ),
    (
        "tests/fixtures/regressions/str_format_unmatched_left_brace.pine",
        "str.format has unmatched `{`",
    ),
    (
        "tests/fixtures/regressions/str_format_unmatched_right_brace.pine",
        "str.format has unmatched `}`",
    ),
    (
        "tests/fixtures/regressions/str_format_timestamp_out_of_range.pine",
        "str.format timestamp is out of range: 9223372036854775807",
    ),
    (
        "tests/fixtures/regressions/str_format_time_placeholder_timestamp_out_of_range.pine",
        "str.format timestamp is out of range: 9223372036854775807",
    ),
    (
        "tests/fixtures/regressions/str_format_result_limit.pine",
        "str.format result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/str_format_time_unsupported_timezone.pine",
        "str.format_time unsupported timezone `Mars/Olympus`",
    ),
    (
        "tests/fixtures/regressions/str_format_time_timestamp_out_of_range.pine",
        "str.format_time timestamp is out of range: 9223372036854775807",
    ),
    (
        "tests/fixtures/regressions/str_format_time_result_limit.pine",
        "str.format_time result cannot exceed 40960 characters",
    ),
    (
        "tests/fixtures/regressions/time_component_unsupported_timezone.pine",
        "hour unsupported timezone `Mars/Olympus`",
    ),
    (
        "tests/fixtures/regressions/time_function_unsupported_timezone.pine",
        "time unsupported timezone `Mars/Olympus`",
    ),
    (
        "tests/fixtures/regressions/timestamp_unsupported_timezone.pine",
        "timestamp unsupported timezone `Mars/Olympus`",
    ),
    (
        "tests/fixtures/regressions/timestamp_date_string_unsupported_timezone.pine",
        "timestamp unsupported dateString `20 Aug 2024 00:00 Mars/Olympus`",
    ),
];

pub(crate) type RuntimeLibraryErrorFixture = (
    &'static str,
    &'static str,
    &'static [(&'static str, &'static str)],
);

pub(crate) const RUNTIME_LIBRARY_ERROR_FIXTURES: &[RuntimeLibraryErrorFixture] = &[
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_nested_field.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_udf_passthrough.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_udf_return.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_udf_nested_return.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_method_passthrough.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_method_nested_passthrough.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_alias_qualified_method_passthrough.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_alias_qualified_method_nested_passthrough.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_method_return.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_alias_qualified_method_return.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_alias_qualified_method_nested_return.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
    (
        "tests/fixtures/regressions/history_dynamic_negative_offset_import_udt_field_method_nested_return.pine",
        "history offset must be non-negative",
        &[("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine")],
    ),
];
