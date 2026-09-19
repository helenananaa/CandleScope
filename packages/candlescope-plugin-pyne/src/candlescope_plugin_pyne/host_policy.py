"""CandleScope policy, independent of Pyne's standalone defaults.

Execution is inline within the managed plugin process. The host owns process
termination; Pyne's inline timeout is cooperative, not a hard timeout.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pyne_runtime

# Preserve the former host budgets and explicitly bound the new 0.4 resources.
# PYNE_* environment settings remain an explicit operator override, including
# the runtime's supported unlimited values. Never mutate the process environment.
HOST_DEFAULTS = {
    "security_mode": "safe",
    "timeout_seconds": 5.0,
    "max_bars": 50_000,
    "max_output_series": 20,
    "max_output_points": 1_000_000,
    "max_drawing_objects": 500,
    "max_array_size": 100_000,
    "max_map_size": 100_000,
    "max_matrix_cells": 100_000,
    "max_collection_depth": 8,
    "max_strategy_pending_operations": 1_000_000,
    "max_window_size": 100_000,
    "max_total_window_items": 1_000_000,
    "max_state_keys": 10_000,
    "max_object_events": 100_000,
    "max_strategy_log_entries": 100_000,
    "max_state_payload_items": 1_000_000,
    "max_preview_payload_items": 1_000_000,
    "max_table_cells": 10_000,
    "incremental_retention_bars": 10_000,
    "replay_history_bars": 50_000,
}


def host_settings(*, security_mode: str | None = None) -> pyne_runtime.PyneSettings:
    """Apply host defaults only where the operator has not selected a value."""
    settings = pyne_runtime.PyneSettings.from_env()
    overrides = {
        field: value
        for field, value in HOST_DEFAULTS.items()
        if ("PYNE_EXEC_TIMEOUT_SECONDS" if field == "timeout_seconds" else "PYNE_" + field.upper())
        not in os.environ
    }
    if security_mode is not None:
        overrides["security_mode"] = security_mode
    return replace(settings, **overrides, executor_mode="inline")
