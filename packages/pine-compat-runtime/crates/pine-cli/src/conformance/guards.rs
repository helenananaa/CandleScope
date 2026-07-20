mod call_results;
mod strategy;
const MATRIX_UNSUPPORTED_BOUNDARY_FIXTURES: &[&str] = &[
    "tests/fixtures/sema/unsupported_matrix.pine",
    "tests/fixtures/sema/unsupported_matrix_add_row.pine",
    "tests/fixtures/sema/unsupported_matrix_add_col.pine",
    "tests/fixtures/sema/unsupported_matrix_remove_row.pine",
    "tests/fixtures/sema/unsupported_matrix_remove_col.pine",
    "tests/fixtures/sema/unsupported_matrix_rows.pine",
    "tests/fixtures/sema/unsupported_matrix_rows_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_columns.pine",
    "tests/fixtures/sema/unsupported_matrix_columns_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_row.pine",
    "tests/fixtures/sema/unsupported_matrix_row_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_row_index_type.pine",
    "tests/fixtures/sema/unsupported_matrix_row_method_index_type.pine",
    "tests/fixtures/sema/unsupported_matrix_col.pine",
    "tests/fixtures/sema/unsupported_matrix_col_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_col_index_type.pine",
    "tests/fixtures/sema/unsupported_matrix_col_method_index_type.pine",
    "tests/fixtures/sema/unsupported_matrix_get.pine",
    "tests/fixtures/sema/unsupported_matrix_get_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_get_row_type.pine",
    "tests/fixtures/sema/unsupported_matrix_get_column_type.pine",
    "tests/fixtures/sema/unsupported_matrix_get_method_row_type.pine",
    "tests/fixtures/sema/unsupported_matrix_get_method_column_type.pine",
    "tests/fixtures/sema/unsupported_matrix_copy.pine",
    "tests/fixtures/sema/unsupported_matrix_copy_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_set.pine",
    "tests/fixtures/sema/unsupported_matrix_set_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_set_row_type.pine",
    "tests/fixtures/sema/unsupported_matrix_set_column_type.pine",
    "tests/fixtures/sema/unsupported_matrix_set_value.pine",
    "tests/fixtures/sema/unsupported_matrix_set_method_value.pine",
    "tests/fixtures/sema/unsupported_matrix_set_method_row_type.pine",
    "tests/fixtures/sema/unsupported_matrix_set_method_column_type.pine",
    "tests/fixtures/sema/unsupported_matrix_fill.pine",
    "tests/fixtures/sema/unsupported_matrix_fill_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_fill_value.pine",
    "tests/fixtures/sema/unsupported_matrix_fill_method_value.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape_method_receiver.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape_row_type.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape_column_type.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape_method_row_type.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape_method_column_type.pine",
    "tests/fixtures/sema/unsupported_matrix_new_template.pine",
    "tests/fixtures/sema/unsupported_matrix_new_deferred_template.pine",
    "tests/fixtures/sema/unsupported_matrix_new_initial_value.pine",
    "tests/fixtures/sema/unsupported_matrix_new_bool_initial_value.pine",
    "tests/fixtures/sema/unsupported_matrix_bool_sum.pine",
    "tests/fixtures/sema/unsupported_matrix_bool_set_float.pine",
    "tests/fixtures/sema/unsupported_matrix_bool_fill_float.pine",
    "tests/fixtures/sema/unsupported_matrix_new_string_initial_value.pine",
    "tests/fixtures/sema/unsupported_matrix_string_sum.pine",
    "tests/fixtures/sema/unsupported_matrix_string_set_float.pine",
    "tests/fixtures/sema/unsupported_matrix_string_fill_float.pine",
    "tests/fixtures/sema/unsupported_matrix_new_color_initial_value.pine",
    "tests/fixtures/sema/unsupported_matrix_color_sum.pine",
    "tests/fixtures/sema/unsupported_matrix_color_set_float.pine",
    "tests/fixtures/sema/unsupported_matrix_color_fill_float.pine",
    "tests/fixtures/sema/unsupported_matrix_set_udf.pine",
    "tests/fixtures/sema/unsupported_matrix_set_method_udf.pine",
    "tests/fixtures/sema/unsupported_matrix_fill_udf.pine",
    "tests/fixtures/sema/unsupported_matrix_fill_method_udf.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape_udf.pine",
    "tests/fixtures/sema/unsupported_matrix_reshape_method_udf.pine",
    "tests/fixtures/sema/unsupported_matrix_add_row_method.pine",
    "tests/fixtures/sema/unsupported_matrix_add_col_method.pine",
    "tests/fixtures/sema/unsupported_matrix_remove_row_method.pine",
    "tests/fixtures/sema/unsupported_matrix_remove_col_method.pine",
    "tests/fixtures/sema/unsupported_matrix_typed_decl.pine",
    "tests/fixtures/sema/unsupported_matrix_int_typed_decl.pine",
    "tests/fixtures/sema/unsupported_matrix_label_typed_decl.pine",
];

const FOR_IN_BOUNDARY_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/for_in.pine",
    "tests/fixtures/runtime/for_in_float.pine",
    "tests/fixtures/runtime/for_in_bool.pine",
    "tests/fixtures/runtime/for_in_string.pine",
    "tests/fixtures/runtime/for_in_color.pine",
    "tests/fixtures/runtime/for_in_label.pine",
    "tests/fixtures/runtime/for_in_line.pine",
    "tests/fixtures/runtime/for_in_linefill.pine",
    "tests/fixtures/runtime/for_in_polyline.pine",
    "tests/fixtures/runtime/for_in_box.pine",
    "tests/fixtures/runtime/for_in_table.pine",
    "tests/fixtures/runtime/for_in_chart_point.pine",
    "tests/fixtures/runtime/for_in_udt.pine",
    "tests/fixtures/runtime/for_in_index_value.pine",
    "tests/fixtures/runtime/for_in_index_value_float.pine",
    "tests/fixtures/runtime/for_in_index_value_bool.pine",
    "tests/fixtures/runtime/for_in_index_value_string.pine",
    "tests/fixtures/runtime/for_in_index_value_color.pine",
    "tests/fixtures/runtime/for_in_index_value_label.pine",
    "tests/fixtures/runtime/for_in_index_value_line.pine",
    "tests/fixtures/runtime/for_in_index_value_linefill.pine",
    "tests/fixtures/runtime/for_in_index_value_polyline.pine",
    "tests/fixtures/runtime/for_in_index_value_box.pine",
    "tests/fixtures/runtime/for_in_index_value_table.pine",
    "tests/fixtures/runtime/for_in_index_value_chart_point.pine",
    "tests/fixtures/runtime/for_in_index_value_udt.pine",
    "tests/fixtures/runtime/for_in_control_flow.pine",
    "tests/fixtures/runtime/for_in_mutation.pine",
    "tests/fixtures/runtime/for_in_stateful.pine",
    "tests/fixtures/runtime/for_in_zero_iteration.pine",
    "tests/fixtures/runtime/for_in_expression.pine",
    "tests/fixtures/runtime/map_for_in.pine",
    "tests/fixtures/runtime/matrix_for_in.pine",
    "tests/fixtures/realtime/for_in_rollback.pine",
    "tests/fixtures/realtime/for_in_varip.pine",
    "tests/fixtures/regressions/for_in_pop_shrink_bounds.pine",
    "tests/fixtures/regressions/for_in_clear_shrink_bounds.pine",
    "tests/fixtures/syntax/for_in_index_value.pine",
    "tests/fixtures/syntax/unsupported_for_in_index_value.pine",
    "tests/fixtures/syntax/for_in_expression_index_value.pine",
    "tests/fixtures/sema/unsupported_for_in.pine",
    "tests/fixtures/sema/unsupported_for_in_non_array.pine",
    "tests/fixtures/sema/unsupported_for_in_index_value_non_int.pine",
    "tests/fixtures/sema/supported_for_in_expression_float.pine",
    "tests/fixtures/sema/supported_for_in_expression_bool.pine",
    "tests/fixtures/sema/supported_for_in_expression_string.pine",
    "tests/fixtures/sema/supported_for_in_expression_color.pine",
    "tests/fixtures/sema/supported_for_in_expression_label.pine",
    "tests/fixtures/sema/supported_for_in_expression_line.pine",
    "tests/fixtures/sema/supported_for_in_expression_linefill.pine",
    "tests/fixtures/sema/supported_for_in_expression_polyline.pine",
    "tests/fixtures/sema/supported_for_in_expression_box.pine",
    "tests/fixtures/sema/supported_for_in_expression_table.pine",
    "tests/fixtures/sema/supported_for_in_expression_chart_point.pine",
    "tests/fixtures/sema/supported_for_in_expression_udt.pine",
    "tests/fixtures/sema/supported_for_in_expression_matrix.pine",
    "tests/fixtures/sema/supported_for_in_expression_index_value.pine",
    "tests/fixtures/sema/supported_map_for_in.pine",
    "tests/fixtures/sema/unsupported_for_in_expression_non_array.pine",
];

const SWITCH_STATEMENT_BLOCK_BOUNDARY_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/switch_statement_block.pine",
    "tests/fixtures/runtime/switch_statement_block_selector.pine",
    "tests/fixtures/runtime/switch_statement_block_default.pine",
    "tests/fixtures/runtime/switch_statement_block_scope.pine",
    "tests/fixtures/runtime/switch_statement_block_loop_control.pine",
    "tests/fixtures/runtime/switch_statement_block_tuple.pine",
    "tests/fixtures/runtime/switch_statement_block_udt.pine",
    "tests/fixtures/runtime/import_udt_switch_statement_block.pine",
    "tests/fixtures/sema/unsupported_switch_statement_block.pine",
    "tests/fixtures/sema/unsupported_switch_statement_block_selector.pine",
    "tests/fixtures/sema/unsupported_switch_statement_block_default.pine",
    "tests/fixtures/sema/unsupported_switch_statement_block_alert_result.pine",
    "tests/fixtures/sema/unsupported_switch_statement_block_reassignment_result.pine",
    "tests/fixtures/sema/unsupported_switch_statement_block_scope_leak.pine",
    "tests/fixtures/sema/unsupported_switch_statement_block_udt_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_switch_identity.pine",
];

const WHILE_EXPRESSION_BOUNDARY_FIXTURES: &[&str] = &[
    "tests/fixtures/syntax/while_expression.pine",
    "tests/fixtures/runtime/while_expression.pine",
    "tests/fixtures/runtime/while_expression_tuple.pine",
    "tests/fixtures/runtime/while_expression_udt.pine",
    "tests/fixtures/runtime/import_udt_while_expression.pine",
    "tests/fixtures/runtime/while_expression_stateful_scope.pine",
    "tests/fixtures/runtime/while_expression_nested_control.pine",
    "tests/fixtures/runtime/while_expression_array.pine",
    "tests/fixtures/runtime/while_expression_array_mutation.pine",
    "tests/fixtures/runtime/while_expression_array_alias.pine",
    "tests/fixtures/runtime/while_expression_array_control.pine",
    "tests/fixtures/runtime/while_expression_array_history.pine",
    "tests/fixtures/runtime/while_expression_array_zero.pine",
    "tests/fixtures/runtime/while_expression_matrix.pine",
    "tests/fixtures/runtime/while_expression_matrix_kinds.pine",
    "tests/fixtures/runtime/while_expression_matrix_control.pine",
    "tests/fixtures/runtime/while_expression_matrix_history.pine",
    "tests/fixtures/runtime/while_expression_matrix_zero.pine",
    "tests/fixtures/sema/supported_while_expression_matrix_kinds.pine",
    "tests/fixtures/sema/unsupported_while_expression_scope_leak.pine",
    "tests/fixtures/sema/unsupported_while_expression_no_final_result.pine",
    "tests/fixtures/sema/unsupported_while_expression_reassignment_result.pine",
    "tests/fixtures/sema/unsupported_while_expression_break_result.pine",
    "tests/fixtures/sema/unsupported_while_expression_continue_result.pine",
    "tests/fixtures/sema/unsupported_while_expression_alert_result.pine",
    "tests/fixtures/sema/unsupported_while_expression_nested_array_result.pine",
    "tests/fixtures/sema/unsupported_imported_udt_while_identity.pine",
];

const IMPORTED_UDT_BOUNDARY_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/import_udt_constructor.pine",
    "tests/fixtures/runtime/import_udt_reassignment.pine",
    "tests/fixtures/runtime/import_udt_typed_declaration.pine",
    "tests/fixtures/runtime/import_udt_var.pine",
    "tests/fixtures/runtime/import_udt_varip.pine",
    "tests/fixtures/runtime/import_udt_history.pine",
    "tests/fixtures/runtime/import_udt_private_dependency_history.pine",
    "tests/fixtures/runtime/import_udt_array_from.pine",
    "tests/fixtures/runtime/import_udt_array_new.pine",
    "tests/fixtures/runtime/import_udt_array_scalar_tree.pine",
    "tests/fixtures/runtime/import_udt_array_sort_field.pine",
    "tests/fixtures/runtime/import_udt_field_mutation.pine",
    "tests/fixtures/runtime/import_udt_field_mutation_control_flow.pine",
    "tests/fixtures/runtime/import_udt_ternary.pine",
    "tests/fixtures/runtime/import_udt_if_expression.pine",
    "tests/fixtures/runtime/import_udt_switch_statement_block.pine",
    "tests/fixtures/runtime/import_udt_while_expression.pine",
    "tests/fixtures/runtime/import_udt_for_expression.pine",
    "tests/fixtures/runtime/import_udt_udf_passthrough.pine",
    "tests/fixtures/runtime/import_udt_array_typed_udf_params.pine",
    "tests/fixtures/runtime/import_udt_array_typed_method_params.pine",
    "tests/fixtures/runtime/import_udt_udf_nested_passthrough.pine",
    "tests/fixtures/runtime/import_udt_udf_constructor_return.pine",
    "tests/fixtures/runtime/import_udt_udf_local_field_mutation.pine",
    "tests/fixtures/runtime/import_udt_udf_nested_constructor_return.pine",
    "tests/fixtures/libraries/import_udt_lib.pine",
    "tests/fixtures/libraries/import_private_udt_lib.pine",
    "tests/fixtures/libraries/import_duplicate_udt_lib.pine",
    "tests/fixtures/libraries/import_duplicate_udt_const_lib.pine",
    "tests/fixtures/libraries/import_duplicate_udt_function_lib.pine",
    "tests/fixtures/sema/unsupported_imported_udt_constructor.pine",
    "tests/fixtures/sema/unsupported_imported_private_udt_constructor.pine",
    "tests/fixtures/sema/unsupported_import_duplicate_exported_udt.pine",
    "tests/fixtures/sema/unsupported_import_duplicate_exported_udt_const.pine",
    "tests/fixtures/sema/unsupported_import_duplicate_exported_udt_function.pine",
    "tests/fixtures/sema/unsupported_imported_udt_varip.pine",
    "tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_field_mutation_type.pine",
    "tests/fixtures/sema/unsupported_imported_udt_parameter_field_mutation.pine",
    "tests/fixtures/sema/unsupported_imported_udt_global_field_mutation.pine",
    "tests/fixtures/sema/unsupported_imported_udt_nested_field_mutation.pine",
    "tests/fixtures/sema/supported_imported_udt_array_decl.pine",
    "tests/fixtures/sema/supported_imported_udt_array_alias_decl.pine",
    "tests/fixtures/sema/supported_imported_udt_array_new.pine",
    "tests/fixtures/sema/unsupported_imported_udt_assignment_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_typed_decl_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_var_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_ternary_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_if_expression_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_switch_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_while_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_for_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_udf_passthrough_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_udf_nested_passthrough_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_udf_constructor_return_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_udf_nested_constructor_return_identity.pine",
    "tests/fixtures/runtime/import_udt_method.pine",
    "tests/fixtures/runtime/import_udt_method_qualified.pine",
    "tests/fixtures/runtime/import_udt_method_return.pine",
    "tests/fixtures/runtime/import_udt_method_param_return.pine",
    "tests/fixtures/runtime/import_udt_method_block_return.pine",
    "tests/fixtures/runtime/import_udt_method_if_return.pine",
    "tests/fixtures/runtime/import_udt_method_for_return.pine",
    "tests/fixtures/runtime/import_udt_method_while_switch_return.pine",
    "tests/fixtures/runtime/import_udt_method_nested_return.pine",
    "tests/fixtures/runtime/import_udt_method_local_field_mutation.pine",
    "tests/fixtures/runtime/import_udt_method_constructor_return.pine",
    "tests/fixtures/sema/unsupported_imported_method_qualified_receiver.pine",
];

const UDT_VARIP_BOUNDARY_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/user_type_varip.pine",
    "tests/fixtures/realtime/user_type_varip.pine",
    "tests/fixtures/runtime/user_type_array_varip.pine",
    "tests/fixtures/realtime/user_type_array_varip.pine",
    "tests/fixtures/sema/supported_user_type_varip_decl.pine",
    "tests/fixtures/sema/supported_user_type_array_varip_decl.pine",
    "tests/fixtures/runtime/import_udt_varip.pine",
    "tests/fixtures/realtime/import_udt_varip.pine",
    "tests/fixtures/runtime/import_udt_array_varip.pine",
    "tests/fixtures/realtime/import_udt_array_varip.pine",
    "tests/fixtures/sema/supported_imported_udt_varip_decl.pine",
    "tests/fixtures/sema/unsupported_user_type_varip.pine",
    "tests/fixtures/sema/supported_user_type_array_varip_nested_decl.pine",
    "tests/fixtures/sema/supported_imported_udt_array_decl.pine",
    "tests/fixtures/sema/supported_imported_udt_array_alias_decl.pine",
    "tests/fixtures/sema/supported_imported_udt_array_varip_nested_decl.pine",
    "tests/fixtures/sema/unsupported_user_type_varip_assign_identity.pine",
    "tests/fixtures/sema/unsupported_imported_udt_varip.pine",
    "tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine",
];

const UDT_ARRAY_CONTROL_FLOW_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/user_type_array_scalar_tree.pine",
    "tests/fixtures/runtime/import_udt_array_scalar_tree.pine",
    "tests/fixtures/sema/supported_user_type_array_control_flow.pine",
    "tests/fixtures/sema/unsupported_user_type_array_control_flow_identity.pine",
    "tests/fixtures/sema/supported_imported_user_type_array_control_flow.pine",
    "tests/fixtures/sema/unsupported_imported_user_type_array_control_flow_identity.pine",
];

const LOCAL_UDT_ARRAY_PARAM_FOR_IN_FIXTURES: &[&str] = &[
    "tests/fixtures/runtime/user_type_array_scalar_tree.pine",
    "tests/fixtures/sema/supported_user_type_array_param_for_in.pine",
];

pub(super) fn validate_entry(
    line_number: usize,
    feature: &str,
    status: &str,
    notes: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    validate_status_fixture_paths(line_number, feature, status, fixtures)?;
    validate_request_fixture_paths(line_number, feature, status, fixtures)?;
    validate_partial_unsupported_notes_fixture_paths(
        line_number,
        feature,
        status,
        notes,
        fixtures,
    )?;
    validate_scalar_tree_udt_contract_notes(line_number, feature, notes)?;
    validate_label_getter_feature(line_number, feature)?;
    validate_array_unsupported_type_fixture_paths(line_number, feature, notes, fixtures)?;
    validate_switch_statement_block_fixture_paths(line_number, feature, fixtures)?;
    validate_while_expression_fixture_paths(line_number, feature, fixtures)?;
    validate_for_in_boundary_fixture_paths(line_number, feature, fixtures)?;
    validate_imported_udt_boundary_fixture_paths(line_number, feature, fixtures)?;
    validate_udt_varip_boundary_fixture_paths(line_number, feature, fixtures)?;
    validate_udt_array_control_flow_fixture_paths(line_number, feature, fixtures)?;
    validate_array_binary_search_fixture_pairs(line_number, feature, fixtures)?;
    call_results::validate_fixture_paths(line_number, feature, fixtures)?;
    validate_local_udt_array_param_for_in_fixture_paths(line_number, feature, fixtures)?;
    validate_map_boundary_fixture_paths(line_number, feature, fixtures)?;
    validate_matrix_unsupported_boundary_fixture_paths(line_number, feature, fixtures)?;
    validate_typed_declaration_collection_fixture_paths(line_number, feature, fixtures)?;
    call_results::validate_map_fixture_paths(line_number, feature, fixtures)?;
    strategy::validate_entry(line_number, feature, fixtures)?;

    Ok(())
}

fn validate_udt_array_control_flow_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !matches!(
        feature,
        "if" | "switch"
            | "for"
            | "while"
            | "array.new<UDT>"
            | "array.from"
            | "array.*"
            | "typed declarations"
            | "import"
            | "user-defined types"
    ) {
        return Ok(());
    }

    for fixture in UDT_ARRAY_CONTROL_FLOW_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `{feature}` must reference `{fixture}` for fixture-backed local/imported UDT array control-flow identity"
            ));
        }
    }

    Ok(())
}

fn validate_local_udt_array_param_for_in_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !matches!(
        feature,
        "for"
            | "array.from"
            | "array.*"
            | "expression-body functions"
            | "multi-statement functions"
            | "typed declarations"
            | "user-defined types"
            | "user-defined methods"
    ) {
        return Ok(());
    }

    for fixture in LOCAL_UDT_ARRAY_PARAM_FOR_IN_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `{feature}` must reference `{fixture}` for fixture-backed local UDF/typed-method for-in over UDT-array parameters"
            ));
        }
    }

    Ok(())
}

fn validate_scalar_tree_udt_contract_notes(
    line_number: usize,
    feature: &str,
    notes: &str,
) -> Result<(), String> {
    for stale_phrase in [
        "same-local scalar-field UDT array",
        "same-local scalar-field UDT-array",
        "same-imported scalar-field UDT",
        "non-scalar-field UDT",
    ] {
        if notes.contains(stale_phrase) {
            return Err(format!(
                "line {line_number}: `{feature}` uses stale UDT boundary phrase `{stale_phrase}`; use scalar-tree terminology for the fixture-backed UDT subset"
            ));
        }
    }

    Ok(())
}

fn validate_label_getter_feature(line_number: usize, feature: &str) -> Result<(), String> {
    if feature.starts_with("label.get_")
        && !matches!(feature, "label.get_x" | "label.get_y" | "label.get_text")
    {
        return Err(format!(
            "line {line_number}: label getter feature `{feature}` is outside the official label.get_x/label.get_y/label.get_text subset"
        ));
    }
    Ok(())
}

fn validate_partial_unsupported_notes_fixture_paths(
    line_number: usize,
    feature: &str,
    status: &str,
    notes: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if status == "partial"
        && contains_ascii_word(notes, "unsupported")
        && !fixtures
            .iter()
            .any(|fixture| fixture.starts_with("tests/fixtures/sema/unsupported_"))
    {
        return Err(format!(
            "line {line_number}: partial feature `{feature}` with unsupported notes must reference unsupported sema diagnostic fixture coverage"
        ));
    }
    Ok(())
}

fn validate_array_unsupported_type_fixture_paths(
    line_number: usize,
    feature: &str,
    notes: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !feature.starts_with("array.") {
        return Ok(());
    }

    for unsupported_type in ["linefill", "polyline", "UDT"] {
        if contains_ascii_word(notes, unsupported_type) {
            let fixture_term = unsupported_type.to_ascii_lowercase();
            if !fixtures
                .iter()
                .any(|fixture| fixture.to_ascii_lowercase().contains(&fixture_term))
            {
                return Err(format!(
                    "line {line_number}: array feature `{feature}` with {unsupported_type} notes must reference {unsupported_type} fixture coverage"
                ));
            }
        }
    }

    Ok(())
}

fn validate_for_in_boundary_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "for" {
        return Ok(());
    }

    for fixture in FOR_IN_BOUNDARY_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `for` must reference `{fixture}` while for...in remains limited to the fixture-backed statement-form array subset"
            ));
        }
    }

    Ok(())
}

fn validate_switch_statement_block_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "switch" {
        return Ok(());
    }

    for fixture in SWITCH_STATEMENT_BLOCK_BOUNDARY_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `switch` must reference `{fixture}` while statement-block switch arms remain limited to the fixture-backed final-expression subset"
            ));
        }
    }

    Ok(())
}

fn validate_while_expression_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "while" {
        return Ok(());
    }

    for fixture in WHILE_EXPRESSION_BOUNDARY_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `while` must reference `{fixture}` while while-expression support remains limited to the fixture-backed scalar, UDT, scalar-array, and matrix result subsets"
            ));
        }
    }

    Ok(())
}

fn validate_imported_udt_boundary_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "import" {
        return Ok(());
    }

    for fixture in IMPORTED_UDT_BOUNDARY_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `import` must reference `{fixture}` while imported UDT support remains limited to the fixture-backed scalar-tree identity subset"
            ));
        }
    }

    Ok(())
}

fn validate_udt_varip_boundary_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "user-defined types" {
        return Ok(());
    }

    for fixture in UDT_VARIP_BOUNDARY_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `user-defined types` must reference `{fixture}` while UDT varip support remains limited to the fixture-backed scalar-tree local/imported subset"
            ));
        }
    }

    Ok(())
}

fn validate_map_boundary_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "map.*" {
        return Ok(());
    }

    for fixture in [
        "tests/fixtures/runtime/map_new_size.pine",
        "tests/fixtures/runtime/map_put_get_contains.pine",
        "tests/fixtures/runtime/map_clear.pine",
        "tests/fixtures/runtime/map_remove.pine",
        "tests/fixtures/runtime/map_copy.pine",
        "tests/fixtures/runtime/map_methods.pine",
        "tests/fixtures/runtime/map_keys_values.pine",
        "tests/fixtures/runtime/map_for_in.pine",
        "tests/fixtures/runtime/map_put_all.pine",
        "tests/fixtures/runtime/map_history.pine",
        "tests/fixtures/runtime/map_varip.pine",
        "tests/fixtures/runtime/map_udf_read.pine",
        "tests/fixtures/runtime/map_typed_declarations.pine",
        "tests/fixtures/runtime/map_control_flow.pine",
        "tests/fixtures/realtime/map_rollback.pine",
        "tests/fixtures/realtime/map_varip.pine",
        "tests/fixtures/sema/supported_map_new_size.pine",
        "tests/fixtures/sema/supported_map_put_get_contains.pine",
        "tests/fixtures/sema/supported_map_clear.pine",
        "tests/fixtures/sema/supported_map_remove.pine",
        "tests/fixtures/sema/supported_map_copy.pine",
        "tests/fixtures/sema/supported_map_methods.pine",
        "tests/fixtures/sema/supported_map_keys_values.pine",
        "tests/fixtures/sema/supported_map_for_in.pine",
        "tests/fixtures/sema/supported_map_put_all.pine",
        "tests/fixtures/sema/supported_map_history.pine",
        "tests/fixtures/sema/supported_map_varip.pine",
        "tests/fixtures/sema/supported_map_udf_read.pine",
        "tests/fixtures/sema/supported_map_typed_decl.pine",
        "tests/fixtures/sema/supported_map_control_flow.pine",
        "tests/fixtures/sema/supported_map_udf_method_returns.pine",
        "tests/fixtures/sema/unsupported_map.pine",
        "tests/fixtures/sema/unsupported_map_new_template.pine",
        "tests/fixtures/sema/unsupported_map_new_dotted_template.pine",
        "tests/fixtures/sema/unsupported_map_get.pine",
        "tests/fixtures/sema/unsupported_map_contains.pine",
        "tests/fixtures/sema/unsupported_map_put_key_type.pine",
        "tests/fixtures/sema/unsupported_map_put_value_type.pine",
        "tests/fixtures/sema/unsupported_map_get_key_type.pine",
        "tests/fixtures/sema/unsupported_map_remove_key_type.pine",
        "tests/fixtures/sema/unsupported_map_assign_template.pine",
        "tests/fixtures/sema/unsupported_map_put_udf.pine",
        "tests/fixtures/sema/unsupported_map_put_method_udf.pine",
        "tests/fixtures/sema/unsupported_map_clear_udf.pine",
        "tests/fixtures/sema/unsupported_map_remove_udf.pine",
        "tests/fixtures/sema/unsupported_map_put_all_udf.pine",
        "tests/fixtures/sema/unsupported_map_put_all_method_udf.pine",
        "tests/fixtures/sema/unsupported_map_size.pine",
        "tests/fixtures/sema/unsupported_map_remove.pine",
        "tests/fixtures/sema/unsupported_map_clear.pine",
        "tests/fixtures/sema/unsupported_map_copy.pine",
        "tests/fixtures/sema/unsupported_map_keys.pine",
        "tests/fixtures/sema/unsupported_map_values.pine",
        "tests/fixtures/sema/unsupported_map_put_all.pine",
        "tests/fixtures/sema/unsupported_map_put_all_template.pine",
        "tests/fixtures/sema/unsupported_map_typed_decl.pine",
        "tests/fixtures/sema/unsupported_map_typed_decl_template.pine",
        "tests/fixtures/sema/unsupported_map_typed_decl_assign.pine",
        "tests/fixtures/sema/unsupported_map_control_flow_template.pine",
        "tests/fixtures/sema/unsupported_map_udf_method_return_templates.pine",
    ] {
        if !fixtures.contains(&fixture) {
            return Err(format!(
                "line {line_number}: `map.*` must reference `{fixture}` while map support is limited to the fixture-backed scalar map helper, control-flow result, direct key/value for-in, typed declaration, history, varip, read-only UDF, method-alias, and rollback subset"
            ));
        }
    }

    Ok(())
}

fn validate_matrix_unsupported_boundary_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "matrix.*" {
        return Ok(());
    }

    for fixture in [
        "tests/fixtures/runtime/matrix_varip.pine",
        "tests/fixtures/realtime/matrix_varip.pine",
        "tests/fixtures/sema/supported_matrix_varip.pine",
    ] {
        if !fixtures.contains(&fixture) {
            return Err(format!(
                "line {line_number}: `matrix.*` must reference `{fixture}` for fixture-backed matrix varip backing-store handoff"
            ));
        }
    }

    for fixture in MATRIX_UNSUPPORTED_BOUNDARY_FIXTURES {
        if !fixtures.contains(fixture) {
            return Err(format!(
                "line {line_number}: `matrix.*` must reference `{fixture}` while unsupported matrix templates, mutating side effects, receiver/type errors, and typed-declaration boundaries remain fixture-backed"
            ));
        }
    }

    Ok(())
}

fn validate_typed_declaration_collection_fixture_paths(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature != "typed declarations" {
        return Ok(());
    }

    for fixture in [
        "tests/fixtures/sema/unsupported_array_typed_decl.pine",
        "tests/fixtures/sema/unsupported_var_array_typed_decl.pine",
        "tests/fixtures/sema/unsupported_array_na_typed_decl.pine",
        "tests/fixtures/sema/unsupported_array_from_typed_decl.pine",
        "tests/fixtures/sema/unsupported_array_typed_decl_initial.pine",
        "tests/fixtures/sema/supported_user_type_array_decl.pine",
        "tests/fixtures/sema/supported_user_type_array_alias_decl.pine",
        "tests/fixtures/sema/unsupported_user_type_array_from_decl.pine",
        "tests/fixtures/runtime/user_type_array_varip.pine",
        "tests/fixtures/sema/supported_user_type_array_varip_decl.pine",
        "tests/fixtures/sema/supported_user_type_array_varip_nested_decl.pine",
        "tests/fixtures/sema/unsupported_array_map_typed_decl.pine",
        "tests/fixtures/sema/unsupported_array_matrix_typed_decl.pine",
        "tests/fixtures/sema/unsupported_array_nested_typed_decl.pine",
        "tests/fixtures/sema/unsupported_array_tuple_typed_decl.pine",
        "tests/fixtures/sema/unsupported_array_strategy_typed_decl.pine",
        "tests/fixtures/runtime/map_typed_declarations.pine",
        "tests/fixtures/sema/supported_map_typed_decl.pine",
        "tests/fixtures/sema/unsupported_map_typed_decl.pine",
        "tests/fixtures/sema/unsupported_map_typed_decl_template.pine",
        "tests/fixtures/sema/unsupported_map_typed_decl_assign.pine",
        "tests/fixtures/sema/unsupported_matrix_typed_decl.pine",
        "tests/fixtures/sema/unsupported_matrix_int_typed_decl.pine",
        "tests/fixtures/sema/unsupported_matrix_label_typed_decl.pine",
    ] {
        if !fixtures.contains(&fixture) {
            return Err(format!(
                "line {line_number}: `typed declarations` must reference `{fixture}` while collection typed declaration boundaries remain unsupported"
            ));
        }
    }

    Ok(())
}

fn validate_array_binary_search_fixture_pairs(
    line_number: usize,
    feature: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if !matches!(
        feature,
        "array.binary_search" | "array.binary_search_leftmost" | "array.binary_search_rightmost"
    ) {
        return Ok(());
    }

    let fixture_prefix = feature.replace('.', "_");
    for suffix in [
        "value",
        "bool",
        "string",
        "color",
        "label",
        "line",
        "box",
        "table",
        "linefill",
        "polyline",
        "chart_point",
        "udt",
    ] {
        let namespace_fixture =
            format!("tests/fixtures/sema/unsupported_{fixture_prefix}_{suffix}.pine");
        let method_fixture =
            format!("tests/fixtures/sema/unsupported_{fixture_prefix}_{suffix}_method.pine");
        if !fixtures.iter().any(|fixture| *fixture == namespace_fixture) {
            return Err(format!(
                "line {line_number}: `{feature}` must reference `{namespace_fixture}` for unsupported receiver coverage"
            ));
        }
        if !fixtures.iter().any(|fixture| *fixture == method_fixture) {
            return Err(format!(
                "line {line_number}: `{feature}` must reference `{method_fixture}` for unsupported method receiver coverage"
            ));
        }
    }

    Ok(())
}

fn contains_ascii_word(text: &str, needle: &str) -> bool {
    text.split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
        .any(|word| word.eq_ignore_ascii_case(needle))
}

fn validate_request_fixture_paths(
    line_number: usize,
    feature: &str,
    status: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    if feature.starts_with("request.")
        && matches!(status, "supported" | "partial")
        && !fixtures.iter().any(|fixture| fixture.contains("request"))
    {
        return Err(format!(
            "line {line_number}: {status} request feature `{feature}` must reference request fixture coverage"
        ));
    }
    Ok(())
}

fn validate_status_fixture_paths(
    line_number: usize,
    feature: &str,
    status: &str,
    fixtures: &[&str],
) -> Result<(), String> {
    match status {
        "supported" | "partial" => {
            if !fixtures.iter().any(|fixture| {
                fixture.starts_with("tests/fixtures/runtime/")
                    || fixture.starts_with("tests/fixtures/realtime/")
                    || fixture.starts_with("tests/fixtures/syntax/")
                    || fixture.starts_with("tests/fixtures/request/")
                    || fixture.starts_with("tests/fixtures/sema/supported_")
                    || fixture.starts_with("tests/fixtures/regressions/")
                    || (fixture.starts_with("tests/fixtures/legacy/")
                        && (fixture.contains("/runtime/") || fixture.contains("/sema/")))
            }) {
                return Err(format!(
                    "line {line_number}: {status} feature `{feature}` must reference runtime, realtime, syntax, supported sema, or regression fixture coverage"
                ));
            }
        }
        "unsupported" => {
            if !fixtures.iter().any(|fixture| {
                fixture.starts_with("tests/fixtures/sema/unsupported_")
                    || fixture.starts_with("tests/fixtures/syntax/")
            }) {
                return Err(format!(
                    "line {line_number}: unsupported feature `{feature}` must reference unsupported sema or syntax diagnostic fixture coverage"
                ));
            }
        }
        _ => unreachable!("status was validated before fixture rules"),
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::super::try_conformance_entries_from_tsv;
    use super::call_results::{
        BUILTIN_ARRAY_CALL_RESULT_FIXTURES, BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES,
        BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES, IMPORTED_UDT_ARRAY_CALL_RETURN_FIXTURES,
        LOCAL_UDT_ARRAY_CALL_RETURN_FIXTURES,
    };
    use super::{
        FOR_IN_BOUNDARY_FIXTURES, IMPORTED_UDT_BOUNDARY_FIXTURES,
        LOCAL_UDT_ARRAY_PARAM_FOR_IN_FIXTURES, MATRIX_UNSUPPORTED_BOUNDARY_FIXTURES,
        SWITCH_STATEMENT_BLOCK_BOUNDARY_FIXTURES, UDT_ARRAY_CONTROL_FLOW_FIXTURES,
        UDT_VARIP_BOUNDARY_FIXTURES, WHILE_EXPRESSION_BOUNDARY_FIXTURES,
        validate_local_udt_array_param_for_in_fixture_paths,
        validate_udt_array_control_flow_fixture_paths,
    };

    #[test]
    fn accepts_versioned_legacy_runtime_and_sema_fixture_ownership() {
        for fixture in [
            "tests/fixtures/legacy/v4/runtime/aliases_legacy.pine",
            "tests/fixtures/legacy/v4/sema/declaration_legacy.pine",
        ] {
            let tsv = format!(
                "feature\tstatus\tnotes\tfixtures\nlegacy.test\tsupported\tversioned legacy coverage\t{fixture}\n"
            );
            assert!(
                try_conformance_entries_from_tsv(&tsv).is_ok(),
                "{fixture} should count as legacy fixture ownership"
            );
        }
    }

    #[test]
    fn rejects_map_row_without_current_boundary_fixture_set() {
        let mut fixtures = vec![
            "tests/fixtures/runtime/map_new_size.pine",
            "tests/fixtures/runtime/map_put_get_contains.pine",
            "tests/fixtures/runtime/map_clear.pine",
            "tests/fixtures/runtime/map_remove.pine",
            "tests/fixtures/runtime/map_copy.pine",
            "tests/fixtures/runtime/map_methods.pine",
            "tests/fixtures/runtime/map_keys_values.pine",
            "tests/fixtures/runtime/map_for_in.pine",
            "tests/fixtures/runtime/map_put_all.pine",
            "tests/fixtures/runtime/map_history.pine",
            "tests/fixtures/runtime/map_varip.pine",
            "tests/fixtures/runtime/map_udf_read.pine",
            "tests/fixtures/runtime/map_typed_declarations.pine",
            "tests/fixtures/runtime/map_control_flow.pine",
            "tests/fixtures/realtime/map_rollback.pine",
            "tests/fixtures/realtime/map_varip.pine",
            "tests/fixtures/sema/supported_map_new_size.pine",
            "tests/fixtures/sema/supported_map_put_get_contains.pine",
            "tests/fixtures/sema/supported_map_clear.pine",
            "tests/fixtures/sema/supported_map_remove.pine",
            "tests/fixtures/sema/supported_map_copy.pine",
            "tests/fixtures/sema/supported_map_methods.pine",
            "tests/fixtures/sema/supported_map_keys_values.pine",
            "tests/fixtures/sema/supported_map_for_in.pine",
            "tests/fixtures/sema/supported_map_put_all.pine",
            "tests/fixtures/sema/supported_map_history.pine",
            "tests/fixtures/sema/supported_map_varip.pine",
            "tests/fixtures/sema/supported_map_udf_read.pine",
            "tests/fixtures/sema/supported_map_typed_decl.pine",
            "tests/fixtures/sema/supported_map_control_flow.pine",
            "tests/fixtures/sema/supported_map_udf_method_returns.pine",
            "tests/fixtures/sema/unsupported_map.pine",
            "tests/fixtures/sema/unsupported_map_new_template.pine",
            "tests/fixtures/sema/unsupported_map_new_dotted_template.pine",
            "tests/fixtures/sema/unsupported_map_get.pine",
            "tests/fixtures/sema/unsupported_map_contains.pine",
            "tests/fixtures/sema/unsupported_map_put_key_type.pine",
            "tests/fixtures/sema/unsupported_map_put_value_type.pine",
            "tests/fixtures/sema/unsupported_map_get_key_type.pine",
            "tests/fixtures/sema/unsupported_map_remove_key_type.pine",
            "tests/fixtures/sema/unsupported_map_assign_template.pine",
            "tests/fixtures/sema/unsupported_map_put_udf.pine",
            "tests/fixtures/sema/unsupported_map_put_method_udf.pine",
            "tests/fixtures/sema/unsupported_map_clear_udf.pine",
            "tests/fixtures/sema/unsupported_map_remove_udf.pine",
            "tests/fixtures/sema/unsupported_map_put_all_udf.pine",
            "tests/fixtures/sema/unsupported_map_put_all_method_udf.pine",
            "tests/fixtures/sema/unsupported_map_size.pine",
            "tests/fixtures/sema/unsupported_map_remove.pine",
            "tests/fixtures/sema/unsupported_map_clear.pine",
            "tests/fixtures/sema/unsupported_map_copy.pine",
            "tests/fixtures/sema/unsupported_map_keys.pine",
            "tests/fixtures/sema/unsupported_map_put_all.pine",
            "tests/fixtures/sema/unsupported_map_put_all_template.pine",
            "tests/fixtures/sema/unsupported_map_typed_decl.pine",
            "tests/fixtures/sema/unsupported_map_typed_decl_template.pine",
            "tests/fixtures/sema/unsupported_map_typed_decl_assign.pine",
            "tests/fixtures/sema/unsupported_map_control_flow_template.pine",
            "tests/fixtures/sema/unsupported_map_udf_method_return_templates.pine",
        ];
        fixtures.extend(BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.iter().copied());
        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\nmap.*\tpartial\tmap.new/map.size/map.put/map.get/map.contains/map.clear/map.remove subset; map collections beyond that remain unsupported\t{}\n",
            fixtures.join(";")
        );
        let error =
            try_conformance_entries_from_tsv(&tsv).expect_err("missing map fixture should fail");

        assert!(error.contains("tests/fixtures/sema/unsupported_map_values.pine"));
    }

    #[test]
    fn rejects_array_binary_search_rows_without_method_receiver_pairs() {
        let mut fixtures = vec!["tests/fixtures/runtime/array_search.pine".to_owned()];
        for suffix in [
            "value",
            "bool",
            "string",
            "color",
            "label",
            "line",
            "box",
            "table",
            "linefill",
            "polyline",
            "chart_point",
            "udt",
        ] {
            fixtures.push(format!(
                "tests/fixtures/sema/unsupported_array_binary_search_rightmost_{suffix}.pine"
            ));
            if suffix != "chart_point" {
                fixtures.push(format!(
                    "tests/fixtures/sema/unsupported_array_binary_search_rightmost_{suffix}_method.pine"
                ));
            }
        }

        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\narray.binary_search_rightmost\tpartial\tunsupported bool, linefill, polyline, chart.point, and UDT arrays remain unsupported\t{}\n",
            fixtures.join(";")
        );
        let error =
            try_conformance_entries_from_tsv(&tsv).expect_err("missing method pair should fail");

        assert!(error.contains(
            "tests/fixtures/sema/unsupported_array_binary_search_rightmost_chart_point_method.pine"
        ));
    }

    #[test]
    fn rejects_stale_scalar_field_udt_boundary_notes() {
        let tsv = "feature\tstatus\tnotes\tfixtures\narray.from\tpartial\tsame-imported scalar-field UDT element kinds remain fixture-backed\ttests/fixtures/runtime/array_from_udt_size.pine\n";
        let error = try_conformance_entries_from_tsv(tsv)
            .expect_err("stale scalar-field UDT boundary phrase should fail");

        assert!(error.contains("same-imported scalar-field UDT"));
        assert!(error.contains("scalar-tree terminology"));
    }

    #[test]
    fn rejects_udt_array_rows_without_control_flow_identity_fixtures() {
        let fixtures =
            &UDT_ARRAY_CONTROL_FLOW_FIXTURES[..UDT_ARRAY_CONTROL_FLOW_FIXTURES.len() - 1];
        let error = validate_udt_array_control_flow_fixture_paths(1, "import", fixtures)
            .expect_err("missing UDT array control-flow fixture should fail");

        assert!(error.contains(
            "tests/fixtures/sema/unsupported_imported_user_type_array_control_flow_identity.pine"
        ));
    }

    #[test]
    fn rejects_udt_array_param_for_in_rows_without_current_fixture_set() {
        let fixtures = &LOCAL_UDT_ARRAY_PARAM_FOR_IN_FIXTURES
            [..LOCAL_UDT_ARRAY_PARAM_FOR_IN_FIXTURES.len() - 1];
        let error = validate_local_udt_array_param_for_in_fixture_paths(1, "for", fixtures)
            .expect_err("missing UDT-array parameter for-in fixture should fail");

        assert!(error.contains("tests/fixtures/sema/supported_user_type_array_param_for_in.pine"));
    }

    #[test]
    fn rejects_typed_declarations_without_collection_boundary_fixtures() {
        let mut fixtures = vec![
            "tests/fixtures/runtime/scalar_typed_declarations.pine",
            "tests/fixtures/sema/unsupported_array_typed_decl.pine",
            "tests/fixtures/sema/unsupported_var_array_typed_decl.pine",
            "tests/fixtures/sema/unsupported_array_na_typed_decl.pine",
            "tests/fixtures/sema/unsupported_array_from_typed_decl.pine",
            "tests/fixtures/sema/unsupported_array_typed_decl_initial.pine",
            "tests/fixtures/sema/supported_user_type_array_decl.pine",
            "tests/fixtures/sema/supported_user_type_array_alias_decl.pine",
            "tests/fixtures/sema/unsupported_user_type_array_from_decl.pine",
            "tests/fixtures/runtime/user_type_array_varip.pine",
            "tests/fixtures/sema/supported_user_type_array_varip_decl.pine",
            "tests/fixtures/sema/supported_user_type_array_varip_nested_decl.pine",
            "tests/fixtures/sema/unsupported_array_map_typed_decl.pine",
            "tests/fixtures/sema/unsupported_array_nested_typed_decl.pine",
            "tests/fixtures/sema/unsupported_array_tuple_typed_decl.pine",
            "tests/fixtures/sema/unsupported_array_strategy_typed_decl.pine",
            "tests/fixtures/runtime/map_typed_declarations.pine",
            "tests/fixtures/sema/supported_map_typed_decl.pine",
            "tests/fixtures/sema/unsupported_map_typed_decl.pine",
            "tests/fixtures/sema/unsupported_map_typed_decl_template.pine",
            "tests/fixtures/sema/unsupported_map_typed_decl_assign.pine",
            "tests/fixtures/sema/unsupported_matrix_typed_decl.pine",
            "tests/fixtures/sema/unsupported_matrix_int_typed_decl.pine",
            "tests/fixtures/sema/unsupported_matrix_label_typed_decl.pine",
        ];
        fixtures.extend(UDT_ARRAY_CONTROL_FLOW_FIXTURES.iter().copied());
        fixtures.extend(LOCAL_UDT_ARRAY_CALL_RETURN_FIXTURES.iter().copied());
        fixtures.extend(IMPORTED_UDT_ARRAY_CALL_RETURN_FIXTURES.iter().copied());
        fixtures.extend(BUILTIN_ARRAY_CALL_RESULT_FIXTURES.iter().copied());
        fixtures.extend(BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.iter().copied());
        fixtures.extend(
            BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
                .iter()
                .copied(),
        );
        fixtures.extend(LOCAL_UDT_ARRAY_PARAM_FOR_IN_FIXTURES.iter().copied());
        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\ntyped declarations\tpartial\tbare array, bare map, non-scalar map templates, bare matrix, non-float matrix, and other typed declarations remain unsupported\t{}\n",
            fixtures.join(";")
        );
        let error = try_conformance_entries_from_tsv(&tsv)
            .expect_err("missing collection typed declaration fixture should fail");

        assert!(error.contains("tests/fixtures/sema/unsupported_array_matrix_typed_decl.pine"));
    }

    #[test]
    fn rejects_for_row_without_current_for_in_boundary_fixture_set() {
        let missing = "tests/fixtures/syntax/for_in_expression_index_value.pine";
        let mut fixtures = vec!["tests/fixtures/runtime/block_statements.pine"];
        fixtures.extend(
            FOR_IN_BOUNDARY_FIXTURES
                .iter()
                .copied()
                .filter(|fixture| *fixture != missing),
        );
        fixtures.extend(LOCAL_UDT_ARRAY_PARAM_FOR_IN_FIXTURES.iter().copied());

        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\nfor\tpartial\tstatement for...in over supported arrays and expression-form scalar-array, drawing-id-array, chart.point-array, UDT-array, and matrix-row for...in including optional index locals are fixture-backed\t{}\n",
            fixtures.join(";")
        );
        let error = try_conformance_entries_from_tsv(&tsv)
            .expect_err("missing for-in boundary fixture should fail");

        assert!(error.contains(missing));
    }

    #[test]
    fn rejects_switch_row_without_statement_block_boundary_fixture_set() {
        let missing = "tests/fixtures/sema/unsupported_imported_udt_switch_identity.pine";
        let mut fixtures = vec!["tests/fixtures/runtime/switch.pine"];
        fixtures.extend(
            SWITCH_STATEMENT_BLOCK_BOUNDARY_FIXTURES
                .iter()
                .copied()
                .filter(|fixture| *fixture != missing),
        );

        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\nswitch\tpartial\tstatement-block switch arms are supported only when their selected block ends in a final expression\t{}\n",
            fixtures.join(";")
        );
        let error = try_conformance_entries_from_tsv(&tsv)
            .expect_err("missing switch statement-block boundary fixture should fail");

        assert!(error.contains(missing));
    }

    #[test]
    fn rejects_while_row_without_while_expression_boundary_fixture_set() {
        let missing = "tests/fixtures/sema/unsupported_while_expression_nested_array_result.pine";
        let mut fixtures = vec!["tests/fixtures/runtime/while.pine"];
        fixtures.extend(
            WHILE_EXPRESSION_BOUNDARY_FIXTURES
                .iter()
                .copied()
                .filter(|fixture| *fixture != missing),
        );

        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\nwhile\tpartial\twhile expressions support scalar, UDT, scalar-array, and matrix result subsets while nested-array results remain unsupported\t{}\n",
            fixtures.join(";")
        );
        let error = try_conformance_entries_from_tsv(&tsv)
            .expect_err("missing while-expression boundary fixture should fail");

        assert!(error.contains(missing));
    }

    #[test]
    fn rejects_import_row_without_imported_udt_boundary_fixture_set() {
        let missing = "tests/fixtures/sema/unsupported_imported_method_qualified_receiver.pine";
        let mut fixtures = vec![
            "tests/fixtures/runtime/import.pine",
            "tests/fixtures/libraries/import_lib.pine",
        ];
        fixtures.extend(
            IMPORTED_UDT_BOUNDARY_FIXTURES
                .iter()
                .copied()
                .filter(|fixture| *fixture != missing),
        );
        fixtures.extend(IMPORTED_UDT_ARRAY_CALL_RETURN_FIXTURES.iter().copied());

        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\nimport\tpartial\timported UDT identity is supported for the scalar-tree subset plus receiver-style scalar imported UDT methods including direct same-identity, block-local alias, final-if alias, final-for alias, final-while alias, switch-expression alias, and nested-method passthrough plus constructor returns, and method-local field mutation while broader imported method flow remains unsupported\t{}\n",
            fixtures.join(";")
        );
        let error = try_conformance_entries_from_tsv(&tsv)
            .expect_err("missing imported UDT boundary fixture should fail");

        assert!(error.contains(missing));
    }

    #[test]
    fn rejects_user_defined_types_row_without_udt_varip_boundary_fixture_set() {
        let missing = "tests/fixtures/sema/unsupported_imported_udt_varip.pine";
        let mut fixtures = vec!["tests/fixtures/runtime/user_types.pine"];
        fixtures.extend(
            UDT_VARIP_BOUNDARY_FIXTURES
                .iter()
                .copied()
                .filter(|fixture| *fixture != missing),
        );

        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\nuser-defined types\tpartial\tUDT varip supports scalar-tree local and imported identities while unresolved imported UDT varip remains unsupported\t{}\n",
            fixtures.join(";")
        );
        let error = try_conformance_entries_from_tsv(&tsv)
            .expect_err("missing UDT varip boundary fixture should fail");

        assert!(error.contains(missing));
    }

    #[test]
    fn rejects_matrix_row_without_current_unsupported_boundary_fixture_set() {
        let missing = "tests/fixtures/sema/unsupported_matrix_add_col_method.pine";
        let mut fixtures = vec![
            "tests/fixtures/runtime/matrix_float.pine",
            "tests/fixtures/runtime/matrix_varip.pine",
            "tests/fixtures/realtime/matrix_varip.pine",
            "tests/fixtures/sema/supported_matrix_varip.pine",
        ];
        fixtures.extend(
            MATRIX_UNSUPPORTED_BOUNDARY_FIXTURES
                .iter()
                .copied()
                .filter(|fixture| *fixture != missing),
        );
        fixtures.extend(BUILTIN_NAMESPACE_ARRAY_CALL_RESULT_FIXTURES.iter().copied());
        fixtures.extend(
            BUILTIN_NAMESPACE_MATRIX_CALL_RESULT_FIXTURES
                .iter()
                .copied(),
        );

        let tsv = format!(
            "feature\tstatus\tnotes\tfixtures\nmatrix.*\tpartial\tfloat matrices and matrix varip are supported while selected boundaries remain unsupported\t{}\n",
            fixtures.join(";")
        );
        let error = try_conformance_entries_from_tsv(&tsv)
            .expect_err("missing matrix unsupported boundary fixture should fail");

        assert!(error.contains(missing));
    }
}
