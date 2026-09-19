from decimal import Decimal, localcontext
import json

import pytest

from app.backtest.strategy.builtin import BuiltinSmaCrossProvider
from app.backtest.strategy.protocol import ObservationFrame, canonical_hash
from app.backtest.checkpoint_history import (
    trade_history_encoder,
    EXTENDED_TRADE_ENCODING,
    rollback_history,
)
from app.backtest.identity import canonical_json, sha256_hex
from app.backtest.errors import BacktestError
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from scripts.benchmark_trade_strategy import events
from tests.test_trade_strategy_performance import repository


def frame(i, value):
    return ObservationFrame(
        "r", i, i * 60000, i * 60000, "EVALUATION", {}, "sha256:x", bar={"close": value}
    )


def test_sma_full_outputs_state_hashes_and_restore_are_unchanged(monkeypatch):
    outputs = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_INCREMENTAL_SMA_HASH_ENABLED", str(enabled))
        provider = BuiltinSmaCrossProvider()
        provider.prepare({"parameters": {"fast": 3, "slow": 5}})
        seen = []
        for i in range(2000):
            if i == 777:
                snapshot = provider.snapshot()
                provider = BuiltinSmaCrossProvider()
                provider.restore(snapshot)
            result = provider.step(frame(i, str(100 + i % 9)))
            if result:
                assert result.state_hash == canonical_hash(
                    [str(v) for v in provider._closes]
                )
                seen.append(result.to_wire())
        outputs.append((seen, provider.snapshot(), provider.close()))
    assert outputs[0] == outputs[1]


def test_incremental_hash_decimal_representation_empty_and_reset(monkeypatch):
    monkeypatch.setenv("BACKTEST_INCREMENTAL_SMA_HASH_ENABLED", "1")
    provider = BuiltinSmaCrossProvider()
    provider.prepare({})
    assert provider._state_hash() == canonical_hash([])
    for capital in (1, 0, 1):
        with localcontext() as context:
            context.capitals = capital
            for text in ("1E+20", "0.0000001", "1.2300", "100.000"):
                provider.warmup(frame(1, text))
                assert provider._state_hash() == canonical_hash(
                    [str(v) for v in provider._closes]
                )
    provider.prepare({})
    assert provider._state_hash() == canonical_hash([])
    provider.restore({"fast": 3, "slow": 5, "closes": ["1E+20", "2.000"]})
    assert provider._state_hash() == canonical_hash(["1E+20", "2.000"])

    class Custom(BuiltinSmaCrossProvider):
        pass

    assert not Custom()._incremental_hash


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("v2", [False, True])
def test_extended_histories_round_trip_budget_and_new_tail(
    tmp_path, monkeypatch, dual, v2
):
    monkeypatch.setenv("BACKTEST_EXTENDED_TRADE_HISTORY_ENABLED", "1")
    options = {"checkpoint_event_interval": 0}
    if v2:
        options.update(
            execution_model_revision="EXECUTION_REALISM_V2",
            participation_rate=Decimal("0.1"),
        )

    def factory():
        return (
            DualClockSimulationKernel("1m", **options)
            if dual
            else TradeSimulationKernel(**options)
        )

    def strategy(_, e):
        return [
            {
                "side": "BUY" if e.sequence % 2 else "SELL",
                "type": "MARKET",
                "qty": "0.1",
            }
        ]

    tape = events(901, 1)
    kernel = factory()
    kernel.run(tape[:600], strategy)
    history = trade_history_encoder()
    history.begin()
    original = {
        "checkpointMode": "DUAL_CLOCK" if dual else "TRADE_TAPE",
        "engine": kernel.snapshot(),
    }
    encoded = {
        **original,
        "engine": kernel.snapshot(history_encoder=history),
        "historyEncoding": EXTENDED_TRADE_ENCODING,
    }
    raw = canonical_json(encoded)
    assert len(raw.encode()) + history.logical_extra - len(
        canonical_json("historyEncoding")
        + ":"
        + canonical_json(EXTENDED_TRADE_ENCODING)
        + ","
    ) == len(canonical_json(original).encode())
    owner = encoded["engine"]["execution"] if dual else encoded["engine"]
    assert isinstance(owner["decisions"], dict)
    if v2:
        assert owner["order_events"]["chunks"] and owner["fill_source_events"]["chunks"]
    repo = repository(tmp_path)
    try:
        assert repo.save_checkpoint(
            {
                "run_id": "r",
                "sequence": 600,
                "generation": 1,
                "payload_json": raw,
                "state_hash": "sha256:" + sha256_hex(raw),
                "created_at_ms": 1,
                "history_chunks": dict(history.pending),
            }
        )
        history.pending.clear()
        history.begin()
        assert kernel.snapshot(history_encoder=history) == encoded["engine"]
        assert history.pending == {}
        loaded = json.loads(repo.latest_checkpoint("r")["payload_json"])
        assert loaded == json.loads(canonical_json(original))
        resumed = factory()
        resumed.restore(loaded["engine"])
        assert resumed.run(tape[600:], strategy, finalize=True) == kernel.run(
            tape[600:], strategy, finalize=True
        )
    finally:
        repo.close()
    assert rollback_history(tmp_path / "state.db")["schemaVersion"] == 7


def test_corrupt_extended_decision_chunk_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_EXTENDED_TRADE_HISTORY_ENABLED", "1")
    kernel = DualClockSimulationKernel("1m")
    kernel.run(events(600, 1), lambda *_: [])
    history = trade_history_encoder()
    history.begin()
    payload = {
        "checkpointMode": "DUAL_CLOCK",
        "engine": kernel.snapshot(history_encoder=history),
        "historyEncoding": EXTENDED_TRADE_ENCODING,
    }
    raw = canonical_json(payload)
    repo = repository(tmp_path)
    try:
        assert repo.save_checkpoint(
            {
                "run_id": "r",
                "sequence": 600,
                "generation": 1,
                "payload_json": raw,
                "state_hash": "sha256:" + sha256_hex(raw),
                "created_at_ms": 1,
                "history_chunks": dict(history.pending),
            }
        )
        digest = payload["engine"]["decisions"]["chunks"][0]
        repo.connection.execute(
            "DELETE FROM backtest_checkpoint_chunks WHERE chunk_hash=?", (digest,)
        )
        repo.connection.commit()
        with pytest.raises(BacktestError, match="CHECKPOINT_CORRUPT"):
            repo.latest_checkpoint("r")
    finally:
        repo.close()
    with pytest.raises(BacktestError):
        rollback_history(tmp_path / "state.db")


def test_legacy_callable_snapshot_encoder_remains_supported():
    from dataclasses import asdict

    def encoder(name, rows):
        return [asdict(row) for row in rows]

    for kernel in (TradeSimulationKernel(), DualClockSimulationKernel("1m")):
        kernel.run(events(20, 1), lambda *_: [])
        assert kernel.snapshot(history_encoder=encoder) == kernel.snapshot()
