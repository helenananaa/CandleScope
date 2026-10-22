"""Independent Workbench Pine executions for cost and capacity scenarios."""

from copy import deepcopy
from decimal import Decimal
import time
from types import SimpleNamespace

from app.market_dataset.snapshot import sha256_hex
from app.simulation.cost_sensitivity import _scenario_wire
from .errors import BacktestError

CONTRACT = "candlescope.workbench-cost/1"


def check_control(cancelled, deadline):
    if cancelled.is_set():
        raise BacktestError("NATIVE_CANCELLED", "Workbench execution cancelled")
    if time.monotonic() >= deadline:
        raise BacktestError(
            "NATIVE_TIMEOUT",
            "Workbench execution and cost scenarios exceeded their shared deadline",
        )


def validate_contract(wire):
    if wire.get("pine_cost_contract") not in {None, CONTRACT}:
        raise BacktestError(
            "NATIVE_IDENTITY_MISMATCH", "Workbench cost contract changed"
        )
    if wire.get("pine_cost_contract") and wire.get("cost_sensitivity_mode") not in {
        "AUTO",
        "SKIP",
    }:
        raise BacktestError(
            "NATIVE_IDENTITY_MISMATCH", "Workbench cost selection changed"
        )


def _sealed(payload):
    return {**payload, "matrix_hash": "sha256:" + sha256_hex(payload)}


def skipped_matrix():
    return _sealed(
        {
            "schemaVersion": "candlescope.cost-sensitivity/1",
            "contract": CONTRACT,
            "status": "SKIPPED_BY_REQUEST",
            "purpose": "ROBUSTNESS_CHECK_NOT_PARAMETER_TUNING",
            "decision_source": "INDEPENDENT_PINE_HOST_REEXECUTION",
            "baseline_reexecution_verified": False,
            "included_in_primary_config_hash": False,
            "scenarios": [],
        }
    )


def _execute(plugin, wire, runner, cancelled, deadline):
    from .external import run_external_host

    check_control(cancelled, deadline)
    return run_external_host(
        plugin, wire, runner, cancelled, deadline=deadline, _cost_scenario=True
    )


def _summary(name, assumptions, result, *, status="COMPLETED"):
    from .native import digest

    data = result["raw_output"]["kernel"]
    row = _scenario_wire(
        name,
        assumptions,
        SimpleNamespace(
            fills=data["fills"],
            ledger=data["ledger"],
            fill_hash=data["fill_hash"],
            ledger_hash=data["ledger_hash"],
        ),
    )
    row.pop("scenario_hash")
    row.update(status=status, executed=status == "COMPLETED")
    row["hashes"].update(
        decision=data["decision_hash"],
        execution=digest(result),
        policy="sha256:"
        + sha256_hex(
            {
                "allocation": result["raw_output"]["entry_allocation"],
                "risk": result.get("pine_risk_stops"),
            }
        ),
    )
    row["metrics"].update(
        ending_position=str(data["ledger"]["account"]["position_qty"]),
        rejection_count=len(data["rejected"]),
    )
    return {**row, "scenario_hash": "sha256:" + sha256_hex(row)}


def build_matrix(plugin, wire, runner, cancelled, primary, *, deadline):
    from .native import digest

    baseline = _execute(plugin, deepcopy(wire), runner, cancelled, deadline)
    if digest(baseline) != digest(primary):
        raise BacktestError(
            "PINE_SENSITIVITY_BASELINE_MISMATCH",
            "Independent Workbench baseline differs from primary execution",
        )
    rate = (wire.get("pine_v2_settings") or {}).get("participation_rate")

    def assumptions(multiplier="1", participation=rate):
        return {
            "fee_multiplier": multiplier,
            "slippage_multiplier": multiplier,
            "latency_ms_delta": 0,
            "latency_events_delta": 0,
            "participation_rate": None if participation is None else str(participation),
        }

    rows = [_summary("BASELINE", assumptions(), baseline)]
    for name, multiplier in (
        ("COSTS_PLUS_25_PERCENT", Decimal("1.25")),
        ("COSTS_PLUS_50_PERCENT", Decimal("1.5")),
    ):
        scenario = deepcopy(wire)
        for field in ("slippage_bps", "taker_fee_bps"):
            scenario["host_settings"][field] = str(
                Decimal(str(wire["host_settings"][field])) * multiplier
            )
        result = _execute(plugin, scenario, runner, cancelled, deadline)
        rows.append(_summary(name, assumptions(str(multiplier)), result))
    bar_clock = wire["execution_fidelity"] == "BAR_APPROX"
    rows.append(
        _summary(
            "LATENCY_PLUS_ONE_TIER",
            assumptions(),
            baseline,
            status="NOT_APPLICABLE_BAR_CLOCK"
            if bar_clock
            else "NOT_APPLICABLE_WORKBENCH_LATENCY_CONTRACT"
            if wire.get("pine_v2_print_contract")
            else "NOT_APPLICABLE_LEGACY_EXECUTION_MODEL",
        )
    )
    if rate is None:
        rows.append(
            _summary(
                "PARTICIPATION_DOWN_ONE_TIER",
                assumptions(),
                baseline,
                status="NOT_APPLICABLE_OHLC_PATH_NO_TAPE_CAPACITY"
                if bar_clock
                else "NOT_APPLICABLE_VISIBLE_BOOK_OR_LEGACY_CAPACITY",
            )
        )
    else:
        scenario = deepcopy(wire)
        reduced = Decimal(str(rate)) / 2
        scenario["pine_v2_settings"]["participation_rate"] = str(reduced)
        result = _execute(plugin, scenario, runner, cancelled, deadline)
        rows.append(
            _summary(
                "PARTICIPATION_DOWN_ONE_TIER",
                assumptions(participation=reduced),
                result,
            )
        )
    check_control(cancelled, deadline)
    return _sealed(
        {
            "schemaVersion": "candlescope.cost-sensitivity/1",
            "contract": CONTRACT,
            "status": "COMPLETED",
            "purpose": "ROBUSTNESS_CHECK_NOT_PARAMETER_TUNING",
            "decision_source": "INDEPENDENT_PINE_HOST_REEXECUTION",
            "included_in_primary_config_hash": False,
            "baseline_reexecution_verified": True,
            "baseline_execution_hash": digest(baseline),
            "scenarios": rows,
        }
    )
