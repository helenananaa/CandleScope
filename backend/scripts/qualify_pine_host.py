"""Qualify the historical Pine Host profile against an explicitly installed worker.

Run from any directory with the backend test Python. Receipts are local evidence,
not a release or TradingView differential qualification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "test_pine_schedule_transport", "test_pine_bar_kernel", "test_pine_bar_workbench",
    "test_chart_pine_bar_callbacks", "test_pine_chart_kernel", "test_pine_v2_bar_kernel",
    "test_chart_pine_v2_bar", "test_pine_workbench_v2_bar", "test_pine_workbench_preparation",
    "test_pine_legacy_market_identity",
    "test_pine_default_sizing", "test_pine_sizing_contract",
    "test_pine_order_metadata", "test_pine_metadata_execution",
    "test_pine_workbench_contract", "test_pine_workbench_control", "test_chart_pine_risk_stops",
    "test_chart_pine_liquidation", "test_v2_margin_repricing", "test_pine_workbench_costs",
    "test_pine_cost_sensitivity", "test_workbench_default_upgrade", "test_external_replay",
    "test_chart_pine_entry_risk", "test_chart_pine_requested_data", "test_native_session_transport",
    "test_contract_quantity_rules", "test_pine_contract_metadata", "test_legacy_contract_rules",
    "test_chart_pine_contracts", "test_pine_contract_execution", "test_external_report",
    "test_account_liquidation_execution", "test_backtest_host_policy_m5",
    "test_catalog_contract_rules", "test_catalog_contract_adapters",
    "test_pine_catalog_contracts", "test_pine_catalog_native", "test_pine_host_inputs",
    "test_pine_request_updates", "test_pine_request_update_transport",
    "test_chart_pine_callbacks", "test_external_feedback", "test_external_requested_data",
    "test_pine_print_account", "test_pine_physical_admission", "test_pine_workbench_v2_print",
    "test_pine_workbench_v2_print_costs", "test_pine_v2_book_settlement", "test_pine_workbench_v2_print_preparation",
    "test_pine_tick_transport",
    "test_pine_indicator_observations",
    "test_pine_stream",
    "test_pine_history_tick_workbench", "test_pine_history_tick_clock", "test_pine_history_vertices",
)
SCHEMAS = {
    "EXTERNAL_STREAM_SCHEMA_VERSION": 1,
    "REALTIME_REQUEST_FEED_SCHEMA_VERSION": 1,
    "CONTRACT_METADATA_SCHEMA_VERSION": 1,
    "EXTERNAL_REQUEST_UPDATE_SCHEMA_VERSION": 1,
    "EXTERNAL_TICK_SCHEDULE_SCHEMA_VERSION": 1,
    "MAX_STRATEGY_OBSERVATIONS_PER_BAR": 100_000,
    "EXTERNAL_CLOCK_SCHEMA_VERSION": 1, "SYMBOL_METADATA_SCHEMA_VERSION": 1,
    "EXTERNAL_ORDER_SCHEMA_VERSION": 2, "EXTERNAL_CLOSING_TICK_SCHEMA_VERSION": 1,
    "STRATEGY_RISK_CONFIGURATION_SCHEMA_VERSION": 1, "EXTERNAL_SCHEDULE_SCHEMA_VERSION": 1,
    "EXTERNAL_SIZING_SCHEMA_VERSION": 1,
    "EXTERNAL_ORDER_METADATA_SCHEMA_VERSION": 1,
}
PROBE = """
import hashlib, json
from pathlib import Path
import pine_compat
import candlescope_plugin_pine_compat
import candlescope_plugin_sdk
files = {}
for module in (pine_compat, candlescope_plugin_pine_compat, candlescope_plugin_sdk):
    for path in sorted(Path(module.__file__).parent.rglob('*')):
        if path.is_file() and path.suffix in {'.py', '.pyd', '.so'}:
            files[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps({'schemas': {name: getattr(pine_compat, name, None)
    for name in %r}, 'files': files}))
""" % (tuple(SCHEMAS),)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(root=ROOT):
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "backend", "packages", "frontend/src", "frontend/scripts", "frontend/package.json",
         "frontend/package-lock.json", "docs/pine*"], cwd=root,
    ).decode("utf-8").split("\0")
    return {name: digest(root / name) for name in sorted(set(paths)) if name and (root / name).is_file()}


def validate_registry(registry, python):
    plugins = json.loads(registry.read_text(encoding="utf-8"))["plugins"]
    pine = [plugin for plugin in plugins if plugin["id"] == "candlescope.pine-compat"]
    if len(pine) != 1 or not pine[0].get("enabled"):
        raise ValueError("registry requires exactly one enabled Pine plugin")
    if os.path.normcase(os.path.abspath(pine[0]["launch"]["executable"])) != os.path.normcase(str(python)):
        raise ValueError("registry and test worker must use the same Python launcher")


def summarize_junit(path):
    cases = list(ET.parse(path).getroot().iter("testcase"))
    result = {"tests": len(cases), "failures": 0, "errors": 0, "skipped": 0}
    for kind in ("failure", "error", "skipped"):
        key = {"failure": "failures", "error": "errors", "skipped": "skipped"}[kind]
        result[key] = sum(case.find(kind) is not None for case in cases)
    result["passed"] = result["tests"] - sum(result[key] for key in ("failures", "errors", "skipped"))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--runtime-registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new receipt directory; never overwritten")
    args = parser.parse_args(argv)
    # Preserve venv launcher symlinks: resolving them selects system Python on POSIX.
    python = Path(os.path.abspath(args.runtime_python))
    registry, output = args.runtime_registry.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "candlescope.pine-host-qualification/1", "profile": "historical-bar-print-tick-transport-indicator-observations-stream-recovery",
               "status": "RUNNING", "host_head": subprocess.check_output(
                   ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "runtime_python": str(python), "runtime_registry": str(registry),
               "scope": "controlled installed-worker regression; no packaged-app or official oracle claim"}

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    started = time.monotonic()
    save()
    try:
        validate_registry(registry, python)
        runtime = json.loads(subprocess.check_output([str(python), "-I", "-c", PROBE], text=True))
        if runtime["schemas"] != SCHEMAS or not runtime["files"]:
            raise ValueError("installed runtime does not expose the required Pine Host contracts")
        sources = source_snapshot()
        registry_hash = digest(registry)
        (output / "sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
        receipt.update(runtime=runtime, runtime_registry_sha256=registry_hash,
                       source_files=len(sources), selection="not pyne")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"),
               "NATIVE_TEST_PYTHON": str(python), "NATIVE_TEST_PINE_PYTHON": str(python),
               "CANDLESCOPE_NATIVE_RUNTIME_REGISTRY": str(registry)}
        command = [sys.executable, "-u", "-m", "pytest",
                   *(f"backend/tests/{name}.py" for name in MODULES),
                   "-v", "-x", "--tb=short", "-k", "not pyne", f"--junitxml={output / 'tests.xml'}"]
        receipt["command"] = command
        save()
        print(f"Running {len(MODULES)} modules; evidence: {output}", flush=True)
        with (output / "tests.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            receipt["pytest_pid"] = process.pid
            save()
            receipt["exit_code"] = process.wait()
        receipt["tests"] = summarize_junit(output / "tests.xml")
        receipt["source_unchanged"] = source_snapshot() == sources
        receipt["runtime_unchanged"] = all(digest(Path(name)) == value for name, value in runtime["files"].items())
        receipt["registry_unchanged"] = digest(registry) == registry_hash
        passed = (receipt["exit_code"] == 0 and receipt["tests"]["passed"] > 0
                  and not any(receipt["tests"][key] for key in ("failures", "errors", "skipped"))
                  and all(receipt[key] for key in ("source_unchanged", "runtime_unchanged", "registry_unchanged")))
        receipt["status"] = "PASSED" if passed else "FAILED"
    except Exception as exc:
        receipt.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
    finally:
        receipt["seconds"] = time.monotonic() - started
        save()
    print(json.dumps({key: receipt[key] for key in ("status", "seconds")}), flush=True)
    return 0 if receipt["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
