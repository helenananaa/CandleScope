"""Benchmark-only entrypoint: profile the actual spawned BAR worker."""

import cProfile
import json
import os
import pstats
from collections import defaultdict
from pathlib import Path
from time import perf_counter


def profile_worker(*args):
    _measure_worker(args, profiling=True)


def timed_worker(*args):
    _measure_worker(args, profiling=False)


def _measure_worker(args, *, profiling):
    from app.backtest.colocated import _worker
    from app.backtest import service as module
    from app.backtest.strategy.local_python import LocalPythonRunner

    output = Path(os.environ["STRATEGY_AUDIT_PROFILE"]).resolve()
    timings, counts, originals = defaultdict(float), defaultdict(int), []

    def wrap(owner, attribute, label):
        original = getattr(owner, attribute)
        def timed(*values, **kwargs):
            started = perf_counter()
            try:
                return original(*values, **kwargs)
            finally:
                timings[label] += perf_counter() - started
                counts[label] += 1
                if label == "checkpoints" and os.environ.get("STRATEGY_AUDIT_FLUSH_CHECKPOINTS") == "1":
                    # Parent supervision may terminate a failed worker before
                    # this module's finalizer; preserve the completed stage.
                    output.with_suffix(".checkpoints.json").write_text(json.dumps({
                        "kind": "checkpoint-stage-only-not-completed-run",
                        "sequence": kwargs.get("sequence"),
                        "checkpoint_seconds": timings[label], "checkpoint_calls": counts[label],
                    }, indent=2), encoding="utf-8")
        setattr(owner, attribute, timed)
        originals.append((owner, attribute, original))

    for owner, attribute, label in (
        (module.SimulationKernel, "run", "kernels_including_callbacks"),
        (module, "build_cost_sensitivity_matrix", "cost_sensitivity"),
        (module.BacktestService, "_save_bar_checkpoint", "checkpoints"),
        (module.BacktestService, "_persist_completed_run", "report_and_persist"),
        (LocalPythonRunner, "call", "python_protocol_calls"),
        (LocalPythonRunner, "observe_frame", "python_object_calls"),
    ):
        if hasattr(owner, attribute):
            wrap(owner, attribute, label)
    from app.simulation import cost_sensitivity
    if hasattr(cost_sensitivity, "_BarSensitivityKernel"):
        wrap(cost_sensitivity._BarSensitivityKernel, "run_sensitivity", "cost_kernel_loops")
    if hasattr(cost_sensitivity, "_run_bar_scenarios"):
        wrap(cost_sensitivity, "_run_bar_scenarios", "cost_fused_loop")
    profiler = cProfile.Profile() if profiling else None
    started = perf_counter()
    try:
        if profiler:
            profiler.enable()
        _worker(*args)
    finally:
        elapsed = perf_counter() - started
        if profiler:
            profiler.disable()
        for owner, attribute, original in originals:
            setattr(owner, attribute, original)
        output.parent.mkdir(parents=True, exist_ok=True)
        if profiler:
            profiler.dump_stats(str(output.with_suffix(".pstats")))
            with output.with_suffix(".txt").open("w", encoding="utf-8") as stream:
                pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(55)
        output.with_suffix(".json").write_text(json.dumps({
            "kind": "actual-spawned-worker-profile-not-latency-benchmark" if profiling else "actual-spawned-worker-stage-timers",
            "child_elapsed_seconds": elapsed,
            "inclusive_seconds": timings, "calls": counts,
        }, indent=2), encoding="utf-8")
