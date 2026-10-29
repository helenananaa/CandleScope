"""Qualify the exact combined calendar/Renko wheel and packaged offline runtime."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
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
    subprocess.run([sys.executable, "-c", "import pine_compat as p; assert p.BAR_BOUNDARY_SCHEMA == 'host-bar-boundaries/1'; assert p.EVENT_REQUEST_SERIES_CONTRACT == 'renko-event-rows/1'"], check=True)
    env = {**os.environ, "NATIVE_CALENDAR_TEST": "1", "NATIVE_TEST_PYTHON": sys.executable,
           "DATA_DIR": str(output / "data"), "CANDLE_DATA_DIR": str(output / "data"),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    cases = [output / "engine-source/python/tests" / name for name in (
        "test_host_bar_boundaries.py", "test_renko_event_requests.py", "test_realtime_session.py")]
    cases += [repo / "packages/candlescope-plugin-pine-compat/tests" / name for name in (
        "test_runtime.py", "test_native_sessions.py", "test_event_strategy.py")]
    cases += [repo / "backend/tests/test_native_calendar_basis.py"]
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
        "python": sys.version, "contracts": ["host-bar-boundaries/1", "renko-event-rows/1"],
        "checks": [str(p.relative_to(repo)) if p.is_relative_to(repo) else p.name for p in cases],
        "bundle_manifest": json.loads((output / "manifest.json").read_text()),
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
