from types import SimpleNamespace

import pytest

from app.replay.actor import ReplaySessionActor
from app.replay.broker import prepared_cache
from app.replay.broker.prepared_interval import PreparedBarInterval
from tests.fixtures.replay.broker_fakes import make_broker, bar, request


class Source:
    def __init__(self, bars, offset=0, revision="revision-1"):
        self.bars = bars
        self.i = offset
        self.revision = revision

    def cursor(self):
        return SimpleNamespace(source_sequence=self.i + 1)

    def next(self):
        if self.exhausted():
            return None
        result = self.bars[self.i]
        self.i += 1
        return result

    def exhausted(self):
        return self.i == len(self.bars)

    def snapshot_ref(self):
        return {"source_revision": self.revision}


def fixture():
    broker = make_broker()
    broker.place_order(request(client_order_id="open"), command_id="open")
    broker.apply_bar(bar(0, 100))
    return broker, [bar(i, str(100 + i % 7)) for i in range(1, 514)]


def prepare(path, broker, bars, offset=0, chain=None, revision="revision-1"):
    return prepared_cache.prepare(
        Source(bars, offset, revision), broker,
        chain or "sha256:" + "0" * 64,
        ReplaySessionActor._next_chain_hash, path,
    )


def test_restart_reuses_cache_at_advanced_cursor_without_rebuilding(tmp_path, monkeypatch):
    broker, bars = fixture()
    slow, _ = fixture()
    path = tmp_path / "index.zlib"
    index = prepare(path, broker, bars)
    index.apply(broker, 0, 131)
    before = broker.snapshot()

    def fail(*args, **kwargs):
        raise AssertionError("cache hit rebuilt the market index")

    monkeypatch.setattr(PreparedBarInterval, "__init__", fail)
    loaded = prepare(path, broker, bars, 131, index.chains[131])
    assert loaded.loaded_from_cache
    assert broker.snapshot() == before
    loaded.apply(broker, 131, 512)
    for event in bars[:512]:
        slow.apply_bar(event)
    assert broker.snapshot() == slow.snapshot()


@pytest.mark.parametrize("mismatch", ["bytes", "json", "version", "source", "builder", "chain"])
def test_invalid_or_mismatched_cache_rebuilds(tmp_path, mismatch):
    import json
    import zlib

    broker, bars = fixture()
    path = tmp_path / "index.zlib"
    prepare(path, broker, bars)
    kwargs = {}
    if mismatch == "bytes":
        path.write_bytes(path.read_bytes()[:-5])
    elif mismatch == "json":
        path.write_bytes(prepared_cache.MAGIC + zlib.compress(b"{}"))
    elif mismatch == "version":
        value = json.loads(zlib.decompress(path.read_bytes()[len(prepared_cache.MAGIC):]))
        value["version"] = "old"
        path.write_bytes(prepared_cache.MAGIC + zlib.compress(json.dumps(value).encode()))
    elif mismatch == "source":
        kwargs["revision"] = "revision-2"
    elif mismatch == "builder":
        broker._bar_builder._max_closed_bars += 1
    else:
        kwargs["chain"] = "sha256:" + "f" * 64
    assert not prepare(path, broker, bars, **kwargs).loaded_from_cache


def test_cache_io_failure_is_optional(tmp_path, monkeypatch):
    from pathlib import Path

    broker, bars = fixture()

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "write_bytes", fail)
    index = prepare(tmp_path / "index.zlib", broker, bars)
    assert len(index.bars) == len(bars)


def test_consumed_nonterminal_index_allows_new_preparation():
    broker, bars = fixture()
    index = PreparedBarInterval(Source(bars), broker._bar_builder,
                                "sha256:" + "0" * 64,
                                ReplaySessionActor._next_chain_hash, limit=256)
    index.apply(broker, 0, 256)
    assert not index.compatible(Source(bars, 256), broker._bar_builder, index.chains[256])


@pytest.mark.anyio
async def test_training_crosses_multiple_prepared_windows(tmp_path, monkeypatch):
    from tests.test_replay_interval_advance import (
        test_waiting_order_skips_safe_prefix_and_stops_at_first_fill as run_case,
    )

    original = PreparedBarInterval.__init__

    def smaller_window(self, *args, **kwargs):
        return original(self, *args, **{**kwargs, "limit": 128})

    monkeypatch.setattr(PreparedBarInterval, "__init__", smaller_window)
    await run_case(tmp_path, monkeypatch, False, 0, True, varying_mark=True, indexed=True)


def test_position_change_reuses_market_but_recomputes_valuation(tmp_path):
    broker, bars = fixture()
    path = tmp_path / "index.zlib"
    original = prepare(path, broker, bars)
    # A position/cash change must invalidate account summaries, while the
    # immutable market/builder cache remains usable.
    broker = make_broker()
    broker.apply_bar(bar(0, 100))
    loaded = prepare(path, broker, bars)
    assert loaded.loaded_from_cache
    assert loaded.valuation["key"] != original.valuation["key"]
    assert loaded.valuation["basis"] != original.valuation["basis"]
