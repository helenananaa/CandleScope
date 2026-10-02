import asyncio
from types import SimpleNamespace as NS

import pytest

from app.api.v1.data_preparation import ReplayPreparationPayload
from app.data_preparation.market_random import eligible_start_bounds, resolve_market_random, MINUTE
from app.data_preparation.models import PreparationError
from app.data_engine.ingestion.models import StreamType
from tests.test_replay_v2_run_centric import _setup_payload

START = 1_710_028_800_000


def payload(**changes):
    setup = {**_setup_payload(), "start_mode": "RANDOM", "requested_start_ms": None,
             "random_range_start_ms": None, "random_range_end_ms": None,
             "indicator_warmup_bars": 3, "forward_cache_ms": 5 * MINUTE}
    return ReplayPreparationPayload(idempotency_key="market-random-1", setup=setup,
        exchange="binance", market_type="spot", symbol="BTCUSDT", random_by_market=True, **changes)


class Factory:
    def __init__(self, first=START, last=START + 19 * MINUTE, symbol="BTCUSDT"):
        self.first, self.last, self.symbol = first, last, symbol
        self.calls = []
    async def fetch_market(self, descriptor, **kwargs):
        self.calls.append(kwargs)
        times = ([self.first] if kwargs.get("start_ms") == 0 or kwargs.get("start_ms") == self.first and kwargs["limit"] == 1
                 else [self.last] if kwargs.get("start_ms") is None
                 else range(kwargs["start_ms"], kwargs["end_ms"] + 1, MINUTE))
        return [NS(exchange=descriptor.exchange, market_type=descriptor.market_type, symbol=self.symbol,
            event_type=StreamType.KLINE, data={"open_time": t}) for t in times]


@pytest.mark.parametrize("last_draw", [False, True])
def test_random_bounds_reserve_warmup_and_future_and_freeze_one_minute(monkeypatch, last_draw):
    monkeypatch.setattr("app.data_preparation.market_random.get_cached_symbol_metadata", lambda *a: None)
    factory = Factory()
    setup = asyncio.run(resolve_market_random(payload(), factory, now_ms=START + 20 * MINUTE,
                                              randbelow=lambda n: n - 1 if last_draw else 0))
    chosen = START + (15 if last_draw else 3) * MINUTE
    assert setup["random_range_start_ms"] == setup["random_range_end_ms"] == chosen
    assert setup["start_mode"] == "RANDOM" and setup["requested_start_ms"] is None
    assert factory.calls[0]["start_ms"] == 0
    assert sum(c["limit"] for c in factory.calls) == 11  # boundaries plus the eight-minute training window


def test_short_or_mismatched_history_does_not_fall_back(monkeypatch):
    monkeypatch.setattr("app.data_preparation.market_random.get_cached_symbol_metadata", lambda *a: None)
    with pytest.raises(PreparationError, match="历史不足"):
        asyncio.run(resolve_market_random(payload(), Factory(last=START + MINUTE), now_ms=START + 20 * MINUTE))
    with pytest.raises(PreparationError, match="可验证"):
        asyncio.run(resolve_market_random(payload(), Factory(symbol="ETHUSDT"), now_ms=START + 20 * MINUTE))


def test_unknown_listing_on_other_provider_is_explicit(monkeypatch):
    monkeypatch.setattr("app.data_preparation.market_random.get_cached_symbol_metadata", lambda *a: None)
    with pytest.raises(PreparationError, match="上市边界"):
        asyncio.run(resolve_market_random(payload().model_copy(update={"exchange": "unknown"}), Factory()))


def test_listing_expiry_and_lookback_bound_the_window(monkeypatch):
    monkeypatch.setattr("app.data_preparation.market_random.get_cached_symbol_metadata",
        lambda *a: {"listedAtMs": START, "expiryAtMs": START + 20 * MINUTE})
    factory = Factory()
    asyncio.run(resolve_market_random(payload(), factory, now_ms=START + 100 * MINUTE))
    assert factory.calls[0]["start_ms"] == START
    assert factory.calls[1]["end_ms"] == START + 20 * MINUTE - 1
    setup = payload().setup.model_dump(mode="json")
    setup["visible_history_lookback"] = {"mode": "DURATION", "duration_ms": 10 * MINUTE}
    assert eligible_start_bounds(START, START + 20 * MINUTE, setup) == (START + 10 * MINUTE, START + 15 * MINUTE)


def test_hole_excludes_overlapping_windows_before_freezing_the_draw(monkeypatch):
    monkeypatch.setattr("app.data_preparation.market_random.get_cached_symbol_metadata", lambda *a: None)
    class Gapped(Factory):
        async def fetch_market(self, descriptor, **kwargs):
            events = await super().fetch_market(descriptor, **kwargs)
            return [event for event in events if event.data["open_time"] != START + 4 * MINUTE]
    setup = asyncio.run(resolve_market_random(payload(), Gapped(), now_ms=START + 20 * MINUTE, randbelow=lambda n: 0))
    # Starts 3..7 all need minute 4. The next valid start is minute 8.
    assert setup["random_range_start_ms"] == START + 8 * MINUTE
