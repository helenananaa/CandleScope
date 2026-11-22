"""Qualify the exact combined calendar/Renko wheel and packaged offline runtime."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    output = args.output.resolve()
    subprocess.run([sys.executable, str(repo / "frontend/scripts/prepare-desktop-plugins.py"),
                    "--output", str(output), "--cache", str(args.cache.resolve()),
                    "--uv", args.uv, "--qualification"], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall",
                    *map(str, output.glob("*.whl"))], check=True)
    subprocess.run([sys.executable, "-c", "import pine_compat as p; assert p.BAR_BOUNDARY_SCHEMA == 'host-bar-boundaries/1'; assert p.EVENT_REQUEST_SERIES_CONTRACT == 'renko-event-rows/1'; assert p.ORDERED_CHART_INPUT_CONTRACT == 'ordered-chart-input/1'"], check=True)
    python_wheels = output / "python-indicator-wheels"
    python_wheels.mkdir(exist_ok=True)
    for name in ("candlescope_plugin_python_indicator", "candlescope_plugin_sdk"):
        (wheel,) = output.glob(f"{name}-*.whl")
        shutil.copy2(wheel, python_wheels / wheel.name)
    from importlib.metadata import version
    registry = output / "native-runtime-registry.json"
    registry.write_text(json.dumps({"schemaVersion": 1, "plugins": [{
        "id": "candlescope.pine-compat", "package": "candlescope-plugin-pine-compat",
        "version": version("candlescope-plugin-pine-compat"), "enabled": True,
        "required": False, "autoStart": False, "launch": {
            "executable": sys.executable, "args": ["-I", "-m", "candlescope_plugin_pine_compat"],
            "workingDirectory": str(output),
        },
    }]}), encoding="utf-8")
    env = {**os.environ, "NATIVE_CALENDAR_TEST": "1", "NATIVE_TEST_PYTHON": sys.executable,
           "NATIVE_TEST_PINE_PYTHON": sys.executable, "PINE_EVENT_TEST_PYTHON": sys.executable,
           "CANDLESCOPE_TEST_QUALIFIED_PINE_DESCRIPTOR": str(output / "unified-pine.json"),
           "CANDLESCOPE_TEST_UNIFIED_PYTHON_WHEELS": str(python_wheels),
           "CANDLESCOPE_NATIVE_RUNTIME_REGISTRY": str(registry),
           "CANDLESCOPE_RUNTIME_REGISTRY": str(registry),
           "DATA_DIR": str(output / "data"), "CANDLE_DATA_DIR": str(output / "data"),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    cases = [output / "engine-source/python/tests" / name for name in (
        "test_host_bar_boundaries.py", "test_renko_event_requests.py", "test_realtime_session.py",
        "test_bar_calendars.py", "test_external_ordered_chart_contract.py",
        "test_external_ordered_chart_events.py")]
    cases += [repo / "packages/candlescope-plugin-pine-compat/tests" / name for name in (
        "test_runtime.py", "test_native_sessions.py", "test_event_strategy.py", "test_chart_indicator_input.py",
        "test_host_completion.py", "test_host_boundary_inputs.py", "test_prefix_reply.py",
        "test_ordered_chart_strategy.py", "test_chart_event_stream.py")]
    cases += [repo / "backend/tests" / name for name in (
        "test_native_calendar_basis.py", "test_native_fixed_anchor.py",
        "test_pine_prefix_reply.py", "test_pyne_removal.py", "test_native_chart_indicator_input.py",
        "test_chart_signal_native_runs.py", "test_chart_event_series.py",
        "test_pine_chart_events.py", "test_native_chart_events.py", "test_chart_pine_bar_callbacks.py",
        "test_unified_script_runtime.py",
        "test_preview_update_requirements.py", "test_event_bus_routing_index.py",
        "test_deferred_component_preview.py", "test_deferred_component_preview_pipeline.py",
        "test_deferred_component_preview_prefix.py",
        "test_deferred_component_preview_source_window.py",
        "test_deferred_component_preview_continuation.py",
        "test_closed_component_retention.py",
        "test_forming_component_retention.py",
        "test_source_window_recovery.py",
        "test_history_prefix.py", "test_history_prefix_overlay.py",
        "test_history_prefix_runtime.py", "test_history_prefix_retention.py",
        "test_history_fetch_stream.py", "test_history_fetch_stream_engine.py",
        "test_chart_calculation_real_bus.py", "test_chart_calculation_ack_loss.py",
        "test_chart_calculation_source_fencing.py", "test_chart_calculation_transports.py",
        # ADR-BACKTEST-015 P0: financial oracles (host BAR, Python, aggTrade, FORWARD; Pine paths).
        "test_strategy_run_oracles.py", "test_strategy_run_oracles_pine.py", "test_run_result_pine.py",
        # ADR-BACKTEST-015 P2: Pine runs through the run facade.
        "test_strategy_runs_pine.py",
        # ADR-BACKTEST-015 P6: every bar-family fill clock x account model keeps its kernel digests,
        # and practice accounts keep their behaviour while their model becomes the shared one (P6e).
        "test_kernel_baselines.py", "test_practice_baselines.py", "test_practice_clock.py",
        "test_practice_runs.py")]
    # Confirm every required file exists: a renamed gate must never silently disappear.
    for case in cases:
        if not case.is_file():
            raise FileNotFoundError(case)
    command = [sys.executable, "-m", "pytest", "-q", "-o", "pythonpath=", "-p", "pytest_asyncio.plugin",
               "-p", "anyio.pytest_plugin", "-p", "pytest_timeout", "--timeout=120",
               f"--junitxml={output / 'host-contracts.xml'}", f"--basetemp={output / 'pytest-tmp'}", *map(str, cases)]
    env["PYTHONPATH"] = str(repo / "backend")
    subprocess.run(command, cwd=repo / "backend", env=env, check=True)
    (output / "qualification-receipt.json").write_text(json.dumps({
        "schema": "candlescope.host-contracts-qualification/1", "qualified": True,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "python": sys.version, "contracts": ["host-bar-boundaries/1", "renko-event-rows/1", "ordered-chart-input/1"],
        "checks": [str(p.relative_to(repo)) if p.is_relative_to(repo) else p.name for p in cases],
        "bundle_manifest": json.loads((output / "manifest.json").read_text()),
        "unified_pine": json.loads((output / "unified-pine.json").read_text(encoding="utf-8")),
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
