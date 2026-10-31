from copy import deepcopy
from dataclasses import replace

import pytest

from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.pine_bar_kernel import PineBarKernel
from app.simulation.pine_chart_kernel import PineChartBarKernel
from tests.test_pine_bar_kernel import bar


def execute(kernel, values):
    return kernel.run(values, lambda *_: [], fill_callback=lambda *_: [])


def test_chart_source_cursor_and_path_cursor_restore_independently():
    kernel = PineChartBarKernel()
    execute(kernel, [bar()])
    assert kernel.source_sequence == kernel.chart_bar_count == 1
    assert kernel.path_sequence == 4
    saved = deepcopy(kernel.snapshot())
    restored = PineChartBarKernel()
    restored.restore(saved)
    for item in (kernel, restored):
        execute(item, [replace(bar(begin=60000), sequence=2)])
    assert restored.snapshot() == kernel.snapshot()
    assert restored.result() == kernel.result()
    with pytest.raises(MarketDatasetError, match="own clock"):
        PineBarKernel().restore(saved)


@pytest.mark.parametrize("policy", ["REJECT", "PAUSE", "SKIP_WITH_WARNING"])
def test_chart_source_gap_keeps_frozen_policy(policy):
    kernel = PineChartBarKernel(gap_policy=policy)
    execute(kernel, [bar()])
    next_bar = replace(bar(begin=60000), sequence=3)
    if policy == "REJECT":
        with pytest.raises(MarketDatasetError, match="sequence gap"):
            execute(kernel, [next_bar])
    else:
        execute(kernel, [next_bar])
        assert kernel.paused is (policy == "PAUSE")
        assert kernel.chart_bar_count == (1 if policy == "PAUSE" else 2)
        assert kernel.ambiguity_count == (0 if policy == "PAUSE" else 1)


def test_source_cursor_rewind_is_rejected_even_when_gaps_are_allowed():
    kernel = PineChartBarKernel(gap_policy="SKIP_WITH_WARNING")
    execute(kernel, [bar()])
    with pytest.raises(MarketDatasetError, match="sequence went backwards"):
        execute(kernel, [bar(begin=60000)])


def test_explicit_chart_clock_and_consistent_close_timestamp_are_required():
    with pytest.raises(MarketDatasetError, match="explicit callback clock"):
        PineChartBarKernel().run([bar()], lambda *_: [])
    with pytest.raises(MarketDatasetError, match="close timestamp differs"):
        execute(PineChartBarKernel(), [replace(bar(), event_time_ms=50000)])
