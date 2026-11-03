"""Reject skipped Windows worker cases; keep evidence tied to actual sources."""
from pathlib import Path
import hashlib
import json
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    "test_cold_strategy_worker_does_not_modify_sdk_or_bundle_with_bytecode",
    "test_sandboxed_strategy_runs_sdk_but_cannot_read_host_file_or_connect_loopback",
    "test_disposable_strategy_profiles_do_not_accumulate_shared_acl_grants",
)


def main() -> int:
    report, output = map(Path, sys.argv[1:])
    errors = []
    cases = []
    if sys.platform != "win32" or os.name != "nt":
        errors.append("Qualification requires a real Windows interpreter")
    try:
        cases = list(ET.parse(report).getroot().iter("testcase"))
    except (OSError, ET.ParseError) as exc:
        errors.append(f"JUnit report unavailable: {exc}")
    if not cases:
        errors.append("No worker test cases executed")
    for name in REQUIRED:
        matches = [case for case in cases if case.get("name") == name]
        if len(matches) != 1:
            errors.append(f"Required case absent or duplicated: {name}")
        elif any(matches[0].find(tag) is not None for tag in ("skipped", "failure", "error")):
            errors.append(f"Required case did not pass: {name}")
    skipped = [case.get("name") for case in cases if case.find("skipped") is not None]
    failed = [case.get("name") for case in cases if any(case.find(tag) is not None for tag in ("failure", "error"))]
    if skipped or failed:
        errors.append("Worker suite contains skipped or failed cases")
    paths = [ROOT / "backend/app/backtest/strategy/python_runner.py"]
    paths += sorted((ROOT / "packages/candlescope-backtest-sdk/src").rglob("*.py"))
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    dirty = subprocess.run(
        ["git", "diff", "--quiet", "--", "backend/app/backtest/strategy/python_runner.py", "packages/candlescope-backtest-sdk/src"],
        cwd=ROOT, check=False,
    ).returncode
    if dirty:
        errors.append("Tracked worker or SDK bytes changed during qualification")
    receipt = {
        "schema": "candlescope.windows-python-worker/1",
        "passed": not errors,
        "scope": "Native worker/controlled strategy execution, host-file and loopback denial, disposable ACL cleanup and cold SDK byte preservation. No desktop installer, UI, public market or full Windows acceptance.",
        "platform": platform.platform(),
        "python": sys.version,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "cases": len(cases),
        "required": list(REQUIRED),
        "skipped": skipped,
        "failed": failed,
        "sourceSha256": source_hashes,
        "errors": errors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("passed", "cases", "skipped", "failed", "errors")}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
