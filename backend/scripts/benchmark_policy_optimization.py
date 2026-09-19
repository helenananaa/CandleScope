"""Serial actual-worker pairs. Storage remains enabled in both dense arms."""
import json
import os
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=True)
    samples = []
    for case, dense in (("SMA", False), ("FEEDBACK", False), ("ORDERS", False), ("SMA", True)):
        for repeat in range(3):
            for enabled in ((False, True) if repeat % 2 == 0 else (True, False)):
                path = root / f'{case}-{dense}-{repeat}-{int(enabled)}.json'
                command = [sys.executable, "-m", "scripts.benchmark_strategy_bar_audit", "--bars", "100000",
                    "--strategy", "PYTHON", "--python-case", case, "--v2", "--output", str(path)]
                if dense: command.append("--dense")
                env = {**os.environ, "BACKTEST_DIRECT_FEEDBACK_ENABLED": str(int(enabled)),
                       "BACKTEST_OWNED_REPORT_ENABLED": str(int(enabled)), "BACKTEST_CHUNKED_REPORT_ENABLED": "1"}
                completed = subprocess.run(command, env=env, capture_output=True, text=True)
                if completed.returncode:
                    raise RuntimeError(completed.stdout + completed.stderr)
                sample = json.loads(path.read_text())
                assert sample["state"] == "COMPLETED" and sample["report_hash_valid"] and sample["processed_bars"] == 100000, sample
                samples.append({"enabled": enabled, "dense": dense, "repeat": repeat, **sample})
                (root / "samples.json").write_text(json.dumps(samples, indent=2))
                print(f'{case} dense={dense} repeat={repeat} on={enabled}: {sample["execution_seconds"]:.3f}s', flush=True)
