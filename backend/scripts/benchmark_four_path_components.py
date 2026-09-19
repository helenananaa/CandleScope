"""Development-only component timings; never a substitute for full-run latency."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/candlescope-backtest-sdk/src"))
import pytest
from tests.test_generic_native_rows import pipeline, row
from app.simulation.kernel import SimulationKernel, _flat_record
from app.backtest.strategy import _native_rows

if __name__ == "__main__":
    target = Path(sys.argv[1])
    events = tuple(row(i) for i in range(1, 100001))
    results, transcript = [], None
    for repeat in range(3):
        modes = [(0, 0), (1, 0), (0, 1), (1, 1)]
        if repeat % 2:
            modes.reverse()
        for entry, fields in modes:
            with pytest.MonkeyPatch.context() as patch:
                patch.setenv("BACKTEST_NATIVE_ENTRY_ENABLED", str(entry))
                patch.setenv("BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED", str(fields))
                runner, session, adapter, direct, observe = pipeline(patch, True, True)
                start = time.perf_counter()
                for event in events:
                    observe(event, "EVALUATION")
                elapsed = time.perf_counter() - start
                receipt = runner.close()
                assert runner._strategy.seen == 100000
                assert transcript is None or receipt == transcript
                transcript = receipt
                adapter.close()
            sample = dict(component="callback_and_receipt", repeat=repeat, entry=entry, fields=fields, seconds=elapsed)
            results.append(sample)
            print(json.dumps(sample), flush=True)
    expected = None
    for repeat in range(3):
        for enabled in ((False, True) if repeat % 2 == 0 else (True, False)):
            kernel = SimulationKernel(scale_stream_decisions=True, equity_curve_event_interval=10000)
            kernel._specialized_bar = enabled
            kernel._record_encoder = _flat_record
            kernel._native_empty_hash = _native_rows.empty_decision_hash
            start = time.perf_counter()
            result = kernel.run(events, lambda visible, event: [], finalize=True)
            elapsed = time.perf_counter() - start
            state = (result, kernel.snapshot())
            assert expected is None or state == expected
            expected = state
            sample = dict(component="empty_bar_kernel", repeat=repeat, specialized=enabled, seconds=elapsed)
            results.append(sample)
            print(json.dumps(sample), flush=True)
    target.write_text(json.dumps(results, indent=2), encoding="utf-8")
