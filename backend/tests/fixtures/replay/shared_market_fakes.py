"""Shared persisted ranges over the standard immutable service fixture."""

from hashlib import sha256
from pathlib import Path

from app.replay.catalog import ReplaySeriesIdentity
from app.replay.shared_market_index import build, open_object, MarketRange, index_path
from tests.fixtures.replay.service_fakes import ImmutableReplayHistoryFake


def install_shared_market(monkeypatch, root):
    root = Path(root)
    root.mkdir(exist_ok=True)

    def query(
        self,
        revision,
        symbol,
        interval,
        *,
        start_ms,
        end_ms,
        exchange=None,
        market_type=None,
        offset_ms=0,
    ):
        identity = ReplaySeriesIdentity(exchange, market_type, symbol)
        content = (revision + exchange + market_type + symbol + interval).encode()
        digest = "sha256:" + sha256(content).hexdigest()
        source = root / (digest[7:] + ".parquet")
        if not source.exists():
            source.write_bytes(content)
        if not index_path(source).exists():
            rows = self.query_bars_at_revision(
                revision, symbol, interval, exchange=exchange, market_type=market_type
            )
            build(source, digest, interval, identity, rows)
        obj = open_object(source, digest)
        a, b = obj.bound(start_ms), obj.bound(end_ms)
        return MarketRange([(obj, a, b)], offset_ms)

    monkeypatch.setattr(
        ImmutableReplayHistoryFake, "shared_market_at_revision", query, raising=False
    )
