from decimal import Decimal

import pytest

from app.backtest.checkpoint_codec import checkpoint_json
from app.backtest.checkpoint_history import (
    HistoryEncoder, ENCODING, TRADE_ENCODING, EXTENDED_TRADE_ENCODING, history_locations,
)
from app.backtest.identity import canonical_json


@pytest.mark.parametrize("mode,encoding", [
    ("BAR", ENCODING), ("TRADE_TAPE", TRADE_ENCODING), ("DUAL_CLOCK", TRADE_ENCODING),
    ("TRADE_TAPE", EXTENDED_TRADE_ENCODING), ("DUAL_CLOCK", EXTENDED_TRADE_ENCODING),
])
@pytest.mark.parametrize("count", [0, 1, 255, 256, 257, 513])
def test_fragment_bytes_budget_and_chunks_are_exact(monkeypatch, mode, encoding, count):
    results = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_REUSE_HISTORY_JSON_ENABLED", str(enabled))
        history = HistoryEncoder(dict, extended=encoding == EXTENDED_TRADE_ENCODING)
        history.begin()
        execution = {"execution_model_revision": "EXECUTION_REALISM_V2"}
        engine = {"execution": execution, "execution_model_revision": "EXECUTION_REALISM_V2"} if mode == "DUAL_CLOCK" else execution
        payload = {"checkpointMode": mode, "historyEncoding": encoding, "engine": engine,
                   "provider": {"provider": {"note": "中文\n\\\"🙂"}}, "planner": {"x": Decimal("1.2300")}}
        full_arrays = {}
        for ordinal, (owner, name) in enumerate(history_locations(payload)):
            rows = [] if name == "orders" else [
                {"n": i, "text": "中文\n\\\"🙂", "decimal": Decimal("1.2300"), "empty": []}
                for i in range(count)
            ]
            owner[name] = history(str(ordinal), rows)
            full_arrays[(id(owner), name)] = rows
        expected = canonical_json(payload)
        actual = checkpoint_json(payload, canonical_json(payload["provider"]), history=history)
        assert actual == expected
        assert not history.fragments
        results.append((actual, history.logical_extra, dict(history.pending)))
        for owner, name in history_locations(payload):
            owner[name] = full_arrays[(id(owner), name)]
        # Full size with the same header must equal manifest size plus correction.
        assert len(actual.encode("utf-8")) + history.logical_extra == len(canonical_json(payload).encode("utf-8"))
    assert results[0] == results[1]


def test_fragments_only_apply_to_owned_manifest_and_are_consumed(monkeypatch):
    monkeypatch.setenv("BACKTEST_REUSE_HISTORY_JSON_ENABLED", "1")
    history = HistoryEncoder(dict)
    payload = {"checkpointMode": "BAR", "historyEncoding": ENCODING, "provider": {},
               "engine": {"orders": history("orders", []), "fills": history("fills", [{"a": 1}])}}
    # A substituted object is not allowed to inherit an old fragment.
    payload["engine"]["fills"] = {"chunks": [], "tail": [{"a": 2}]}
    assert checkpoint_json(payload, "{}", history=history) == canonical_json(payload)
    payload["engine"]["fills"]["tail"][0]["a"] = 3
    assert checkpoint_json(payload, "{}", history=history) == canonical_json(payload)
    history("new", [{"a": 4}])
    assert history.fragments
    history.begin()
    assert not history.fragments


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("switch", ["BACKTEST_REUSE_HISTORY_JSON_ENABLED", "BACKTEST_FLAT_TRADE_RECORDS_ENABLED"])
def test_service_stores_identical_checkpoints_and_results(tmp_path, monkeypatch, dual, switch):
    from dataclasses import replace
    import shutil
    from app.backtest.service import BacktestService
    from scripts.benchmark_trade_strategy import settings, events
    from tests.test_trade_research_options import request, Orders

    config = settings(tmp_path, 100)
    service = BacktestService.start(config, now_ms=1)
    run = service.create_run(request(dual), idempotency_key="same", now_ms=2)
    service.shutdown()
    outcomes = []
    for enabled in (0, 1):
        monkeypatch.setenv(switch, str(enabled))
        db = tmp_path / f"reuse-{enabled}.db"
        shutil.copy2(config.db_path, db)
        service = BacktestService.start(replace(config, db_path=db), now_ms=1)
        records = []
        save = service.repository.save_checkpoint

        def record(value):
            records.append({key: value[key] for key in ("sequence", "payload_json", "state_hash", "history_chunks")})
            return save(value)

        service.repository.save_checkpoint = record
        try:
            execute = service.execute_dual_clock_run if dual else service.execute_trade_run
            completed = execute(run["run_id"], events=events(850, 1), provider=Orders(), now_ms=3)
            outcomes.append((records, completed["result"], completed["report"]))
        finally:
            service.shutdown()
    assert outcomes[0] == outcomes[1]
