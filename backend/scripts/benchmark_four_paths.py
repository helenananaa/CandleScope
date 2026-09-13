"""Serial paired ablation; each sample uses a fresh database and spawned worker."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

FLAGS = ("BACKTEST_NATIVE_ENTRY_ENABLED", "BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED",
         "BACKTEST_SPECIALIZED_BAR_ENABLED", "BACKTEST_INCREMENTAL_CHECKPOINT_ENABLED")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ablation", action="store_true")
    parser.add_argument("--dense", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workloads = [("PYTHON", "SMA")] if args.ablation or args.dense else [
        ("PYTHON", name) for name in ("EMPTY", "SMA", "STATE", "FEEDBACK", "ORDERS")
    ] + [("SMA", "SMA"), ("RSI", "SMA")]
    modes = {"off": dict.fromkeys(FLAGS, "0"), "on": dict.fromkeys(FLAGS, "1")}
    if args.ablation:
        for index, name in enumerate(("entry", "fields", "loop", "checkpoint")):
            modes[name + "_off"] = {flag: "0" if i == index else "1" for i, flag in enumerate(FLAGS)}
    samples = []
    for strategy, case in workloads:
        for repeat in range(args.repeats):
            order = list(modes) if repeat % 2 == 0 else list(reversed(modes))
            for mode in order:
                target = args.output / f"{strategy}-{case}-{repeat}-{mode}.json"
                command = [sys.executable, "-m", "scripts.benchmark_strategy_bar_audit", "--bars", "100000",
                    "--strategy", strategy, "--python-case", case, "--v2", "--output", str(target)]
                if args.dense:
                    command.append("--dense")
                completed = subprocess.run(command, env={**os.environ, **modes[mode]}, capture_output=True, text=True)
                if completed.returncode:
                    raise RuntimeError(completed.stdout + completed.stderr)
                sample = json.loads(target.read_text(encoding="utf-8"))
                assert sample["state"] == "COMPLETED" and sample["report_hash_valid"] and sample["processed_bars"] == 100000
                samples.append({"mode": mode, "repeat": repeat, **sample})
                print(f"{strategy}/{case} {repeat} {mode}: {sample['execution_seconds']:.3f}s", flush=True)
                (args.output / "samples.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
