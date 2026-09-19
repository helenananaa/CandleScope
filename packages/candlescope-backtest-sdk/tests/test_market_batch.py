import importlib.util
from pathlib import Path
import random

import pytest

from candlescope_backtest_sdk import MarketBatch, StrategyContext, Observation, Bar


def strategy():
    path = Path(__file__).resolve().parents[1] / "templates/sma_cross_batch/strategy.py"
    spec = importlib.util.spec_from_file_location("batch_template", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Strategy()


def columns(prices):
    return {"sequence": list(range(1, len(prices)+1)), "event_time_ms": [i*60 for i in range(len(prices))],
            **{key: list(prices) for key in ("open", "high", "low", "close", "volume")}}


@pytest.mark.parametrize("fast,slow", [(2,3), (3,5), (17,7), (50,512)])
@pytest.mark.parametrize("chunk", [1, 31, 256])
def test_scalar_equivalence_for_arbitrary_chunk_boundaries(fast, slow, chunk):
    rng = random.Random(938)
    prices = [str(rng.randrange(90, 120)/7) for _ in range(650)]
    scalar = strategy()
    scalar.prepare(StrategyContext("r", "r", {"fast": fast, "slow": slow}))
    expected = []
    for i, price in enumerate(prices):
        frame = Observation("r", "r", 1, i+1, i*60, i*60, "STEP", {}, Bar(0, 0, price, price, price, price, price))
        if i < 13:
            scalar.warmup(frame)
            expected.append(None)
        else:
            expected.append(scalar.step(frame).quantity)
    outputs = []
    for start in range(0, len(prices), chunk):
        prefix = max(0, start-max(fast, slow)+1)
        end = min(len(prices), start+chunk)
        batch = MarketBatch.from_columns(columns(prices[prefix:end]), context_rows=start-prefix,
                                         warmup_rows=min(end-start, max(0, 13-start)))
        outputs.extend(scalar.calculate_batch(batch, {"fast": fast, "slow": slow}))
    assert outputs == expected


def test_columns_are_detached_and_normalize_like_scalar_sdk():
    source = columns(["+1.00", "1e-3"])
    batch = MarketBatch.from_columns(source)
    source["close"][0] = "999"
    assert batch.close == ("1.00", "0.001")
    assert batch.to_wire()["protocol"] == "candlescope.python-market-batch/1"


@pytest.mark.parametrize("edit", [
    lambda value: value["close"].pop(),
    lambda value: value.update(extra=[]),
    lambda value: value["sequence"].__setitem__(1, 2**54),
    lambda value: value["sequence"].__setitem__(1, 1),
    lambda value: value["event_time_ms"].__setitem__(1, -1),
    lambda value: value["close"].__setitem__(1, "NaN"),
])
def test_invalid_batch_input_is_rejected(edit):
    value = columns(["1", "2"])
    edit(value)
    with pytest.raises(ValueError):
        MarketBatch.from_columns(value)
