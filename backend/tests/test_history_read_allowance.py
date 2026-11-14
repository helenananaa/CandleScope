"""The history-read allowance must admit the reads a four-cell window makes.

Reservations are worst-case ceilings taken before a read starts. When they do
not fit, the read is answered "pending" with no bars, however little memory is
actually in use.
"""
from __future__ import annotations

import inspect
from contextlib import ExitStack

import pytest

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.mixed_history import MixedHistoryReader, _SUMMARY_BYTES
from app.data_engine.data_manager.mixed_precedence import WORK_BYTES
from app.data_engine.memory_budget import MemoryBudget, MemoryBudgetExceeded

MIB = 1024 * 1024
CELLS_PER_WINDOW = 4
POSITIONS = inspect.signature(MixedHistoryReader.read).parameters["max_positions"].default
# What one custom-interval read reserves: planning in MixedHistoryReader.read, then
# working space in query_closed_mixed.
PLANNING_BYTES = POSITIONS * 512 + 64 * 1024 + 4 * _SUMMARY_BYTES
WORKING_BYTES = 64 * 1024 + WORK_BYTES


def budget_with(allowance):
    budget = MemoryBudget(DataManagerConfig().memory_budget_bytes)
    budget.register("history-query", limit_bytes=allowance, usage=lambda: {"estimated_bytes": 0})
    return budget


def reserve_reads(budget, stack, count):
    for _ in range(count):
        stack.enter_context(budget.reserve("history-query", PLANNING_BYTES))
        stack.enter_context(budget.reserve("history-query", WORKING_BYTES))


def test_one_custom_interval_read_per_chart_cell_is_admitted():
    allowance = DataManagerConfig().memory_owner_budgets["history-query"]
    with ExitStack() as stack:
        reserve_reads(budget_with(allowance), stack, CELLS_PER_WINDOW)


def test_the_former_allowance_refused_the_fourth_cell():
    budget = budget_with(64 * MIB)
    with ExitStack() as stack:
        reserve_reads(budget, stack, CELLS_PER_WINDOW - 1)
        with pytest.raises(MemoryBudgetExceeded):
            reserve_reads(budget, stack, 1)


def test_a_base_stream_ceiling_fits_beside_reads_of_the_other_cells():
    # Measured in the packaged app: building a 221-bar 89m range from 1m bars
    # reserves 125.3 MiB in one request, before its first source read.
    allowance = DataManagerConfig().memory_owner_budgets["history-query"]
    with ExitStack() as stack:
        budget = budget_with(allowance)
        stack.enter_context(budget.reserve("history-query", 126 * MIB))
        reserve_reads(budget, stack, CELLS_PER_WINDOW - 1)


def test_the_allowance_stays_inside_the_shared_total():
    config = DataManagerConfig()
    assert config.memory_owner_budgets["history-query"] < config.memory_budget_bytes


def test_the_data_manager_registers_the_configured_allowance():
    config = DataManagerConfig()
    owners = DataManager(config).memory_budget.snapshot()["owners"]
    assert owners["history-query"]["limit_bytes"] == config.memory_owner_budgets["history-query"]
