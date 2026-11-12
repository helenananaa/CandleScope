"""Captured-source integration: real local revisions, saved runs and replay clocks."""
import asyncio
from dataclasses import asdict
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.synthetic import SyntheticRequest, router
from app.api.v1.synthetic_sources import pinned_seed_loader
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.synthetic_series.core import SyntheticConfig, SyntheticError, SyntheticKernel, TRANSFORMS
from app.data_engine.synthetic_series.service import SyntheticSeriesService
from app.local_data import LocalDatasetService, LocalImportOptions, LocalDatasetError
from tests.test_synthetic_series import Source, bar
from tests.asgi_peer import PeerASGIApp


def host():
    # Live prices intentionally disagree with every immutable source below.
    live = Source([bar(60, 9999), bar(120, 1)])
    service = SyntheticSeriesService(live)
    app = FastAPI()
    app.state.data_manager = SimpleNamespace(synthetic=service)
    app.include_router(router)
    return app, live, service


def payload(source, origin, anchor, through, transform="renko"):
    return {"source": asdict(source), "origin": origin,
        "config": {"transform": transform, "box_size": 2, "reversal_amount": 2},
        "anchor": anchor, "through": through, "complete_window": True}


def test_immutable_partial_buckets_keep_prices_finality_and_reject_live_updates():
    rows = [bar(60, 100, closed=False), bar(120, 106), bar(180, 102, closed=False)]
    kernel = SyntheticKernel(SyntheticConfig("heikin-ashi"))
    output = kernel.replace_snapshot(rows)
    assert [point["close"] for point in output] == [100, 106, 102]
    assert [point["open"] for point in output] == [100, 100, 103]
    assert [point["customValues"]["chartProjection"]["provisional"] for point in output] == [True, False, True]
    assert [row["is_closed"] for row in kernel.source] == [False, True, False]
    with pytest.raises(SyntheticError, match="immutable"):
        kernel.apply(bar(240, 999))
    assert kernel.output == output


def imported(local, path, *, changed=False, dataset_id=None):
    path.write_text("time,open,high,low,close,volume\n" + "\n".join(
        f"{i * 60000},{value},{value},{value},{value},1"
        for i, value in enumerate([100, 106, 102, 110, 114] if not changed else [800, 850, 900, 950, 999])))
    return local.import_csv(path, LocalImportOptions(name="pinned charts", symbol="BTCUSDT", interval="1m",
        timestamp_unit="ms", **({"dataset_id": dataset_id} if dataset_id else {})))


def test_pinned_local_revision_survives_current_revision_change_and_never_uses_live(tmp_path):
    app, live, service = host()
    local = LocalDatasetService(tmp_path / "local")
    manifest = imported(local, tmp_path / "input.csv")
    app.state.local_data_service = local
    origin = {"kind": "LOCAL_DATASET", "dataset_id": manifest["dataset_id"], "data_epoch": manifest["data_epoch"]}
    source = SeriesKey("BTCUSDT", "1m", exchange="local", market_type="local_dataset")
    with TestClient(PeerASGIApp(app, "127.0.0.1"), headers={"host": "127.0.0.1"}) as client:
        original = client.post("/synthetic/query", json=payload(source, origin, 0, 240)).json()
        assert original["status"] == "ready" and original["total"] == 9
        imported(local, tmp_path / "input.csv", changed=True, dataset_id=manifest["dataset_id"])
        for transform in TRANSFORMS:
            response = client.post("/synthetic/query", json=payload(source, origin, 0, 240, transform))
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "ready"
        again = client.post("/synthetic/query", json=payload(source, origin, 0, 240)).json()
        assert again == original
        assert not live.active and not live.callbacks and not service.instances
        wrong = {**origin, "data_epoch": "sha256:" + "f" * 64}
        assert client.post("/synthetic/query", json=payload(source, wrong, 0, 240)).status_code == 409
        with client.websocket_connect("/synthetic/stream") as ws:
            ws.send_json({**payload(source, origin, 0, 240), "limit": 3})
            chunks = [ws.receive_json() for _ in range(3)]
            assert [chunk["from_index"] for chunk in chunks] == [0, 3, 6]
            assert chunks[-1]["complete"] is True
            assert all(chunk["definition"]["origin"] == origin for chunk in chunks)
            assert not live.active and not live.callbacks
        denied = client.post("/synthetic/query", json=payload(source, origin, 0, 240),
            headers={"origin": "https://untrusted.example"})
        assert denied.status_code == 409 and "trusted local" in denied.text


def test_completed_result_and_frozen_snapshot_use_saved_receipts(tmp_path):
    from tests.test_backtest_research_source import _runtime
    runtime = _runtime(tmp_path)
    app, live, service = host()
    app.state.backtest_runtime = runtime
    try:
        manifest = imported(runtime.local_data, tmp_path / "input.csv")
        preview = runtime.preview_snapshot(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
            start_time_ms=0, end_time_ms=299999, interval="1m")
        created = runtime.service.create_run(dict(strategy_revision_id="builtin-sma-cross-v1",
            dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"], snapshot_hash=preview["snapshot_hash"],
            fidelity_mode="BAR_APPROX", start_time_ms=0, end_time_ms=299999, interval="1m",
            parameters={"fast": 2, "slow": 3}), idempotency_key="synthetic-saved")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            record = runtime.service.get_run(created["run_id"])
            if record["state"] in {"COMPLETED", "FAILED"}: break
            time.sleep(.02)
        assert record["state"] == "COMPLETED"
        report = runtime.service.get_report(record["run_id"])
        chart = runtime.chart_data(record["run_id"])
        source = SeriesKey("BTCUSDT", "1m", market_type="usdm")
        origins = [dict(kind="RUN_RESULT", run_id=record["run_id"], config_hash=record["config_hash"],
            report_hash=report["hashes"]["report"], chart_hash=chart["chart_hash"]),
            dict(kind="FROZEN_SNAPSHOT", run_id=record["run_id"], dataset_id=record["dataset_id"],
                data_epoch=record["data_epoch"], snapshot_hash=record["snapshot_hash"], chart_hash=chart["chart_hash"])]
        with TestClient(app) as client:
            ids = set()
            for origin in origins:
                for transform in TRANSFORMS:
                    response = client.post("/synthetic/query", json=payload(source, origin, 0, 240, transform))
                    assert response.status_code == 200, response.text
                    value = response.json(); ids.add(value["series_id"])
                    assert value["status"] == "ready" and value["strategy_qualified"] is False
                    if transform == "renko": assert value["total"] == 9
                wrong = {**origin, "chart_hash": "sha256:" + "0" * 64}
                assert client.post("/synthetic/query", json=payload(source, wrong, 0, 240)).status_code == 409
            assert len(ids) == 10
            assert not live.active and not live.callbacks and not service.instances
    finally:
        runtime.shutdown()


def test_client_captured_display_prefix_is_bounded_immutable_and_re_registerable():
    app, live, service = host()
    from app.data_engine.data_manager.core import DataManagerCore
    # Exercise the actual offline composition: no live DataManager exists.
    core = app.state.data_manager_core = DataManagerCore()
    service = core.synthetic
    app.state.data_manager = None
    source = SeriesKey("BTCUSDT", "1m")
    captured = dict(source=asdict(source), rows=[bar(60, 100), bar(120, 106)], scope="study:fixed", cutoff_ms=120000)
    with TestClient(PeerASGIApp(app, "127.0.0.1"), headers={"host": "127.0.0.1"}) as client:
        receipt = client.post("/synthetic/captures", json=captured)
        assert receipt.status_code == 200, receipt.text
        origin = receipt.json()
        assert client.post("/synthetic/captures", json=captured).json() == origin
        assert service.memory_usage()["estimated_bytes"] == 2 * 1536
        first = client.post("/synthetic/query", json=payload(source, origin, 60, 120)).json()
        assert first["total"] == 3 and first["strategy_qualified"] is False
        assert not live.active and not live.callbacks and not live.reads
        assert client.post("/synthetic/captures", json={**captured, "rows": [*captured["rows"], bar(180, 999)]}).status_code == 409
        assert client.post("/synthetic/captures", json=captured, headers={"origin": "https://untrusted.example"}).status_code == 403
        assert client.post("/synthetic/query", json=payload(source, origin, 60, 120), headers={"origin": "https://untrusted.example"}).status_code == 409
        for index in range(33):
            assert client.post("/synthetic/captures", json={**captured, "scope": f"study:{index}"}).status_code == 200
        assert len(service.captures) == 32
        assert client.post("/synthetic/query", json=payload(source, origin, 60, 120)).status_code == 409
        assert client.post("/synthetic/captures", json=captured).json() == origin
        assert client.post("/synthetic/query", json=payload(source, origin, 60, 120)).json() == first
        assert not service.instances
        client.portal.call(service.close)
        assert not service.captures and service.memory_usage()["estimated_bytes"] == 0


def test_host_frozen_library_revision_is_displayable_without_relaxing_comparison_contract(tmp_path):
    local = LocalDatasetService(tmp_path / "local")
    manifest = local.freeze_host_bars([bar(60, 100), bar(120, 106)],
        dataset_id="local-0123456789abcdef0123456789abcdef", name="frozen host",
        exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m", chart_context_hash="sha256:" + "1" * 64)
    with pytest.raises(LocalDatasetError, match="imported candles"):
        local.load_pinned_closed_bars(manifest["dataset_id"], data_epoch=manifest["data_epoch"], interval="1m", through_ms=179999, limit=10)
    app, live, _ = host(); app.state.local_data_service = local
    origin = dict(kind="LOCAL_DATASET", dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"])
    with TestClient(PeerASGIApp(app, "127.0.0.1"), headers={"host": "127.0.0.1"}) as client:
        response = client.post("/synthetic/query", json=payload(SeriesKey("BTCUSDT", "1m"), origin, 60, 120))
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 3
        assert not live.reads and not live.active


def test_imported_trade_derived_candles_use_the_pinned_local_display_owner(tmp_path):
    from tests.test_user_market_trades import fixture, START, END
    from app.local_data.user_market_trades import UserMarketTradeOptions
    local = LocalDatasetService(tmp_path / "local")
    path = tmp_path / "trades.csv"; path.write_text(fixture())
    manifest = local.import_user_market_trades(path, UserMarketTradeOptions(
        "pinned trades", "BTCUSDT", "BTC", "USDT", "ms", START, END, "MARKET_AGG_TRADE"))
    app, live, _ = host(); app.state.local_data_service = local
    origin = dict(kind="LOCAL_DATASET", dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"])
    with TestClient(PeerASGIApp(app, "127.0.0.1"), headers={"host": "127.0.0.1"}) as client:
        response = client.post("/synthetic/query", json=payload(SeriesKey("BTCUSDT", "1m"), origin,
            START // 1000, (END - 60000) // 1000, "heikin-ashi"))
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 10
        assert not live.reads and not live.active


@pytest.mark.anyio
async def test_captured_bar_replay_prefix_survives_forward_playback_without_account_mutation(tmp_path):
    from tests.test_replay_v2_training_history import _service, _create_run
    from tests.test_replay_v2_training_phase5 import _acquire
    from tests.test_replay_v2_training_phase6 import _send
    from app.replay.training.models import ReplayV2CommandType
    replay, _ = await _service(tmp_path / "replay.db")
    app, live, service = host(); app.state.replay_service = replay
    try:
        created, snapshot = await _create_run(replay)
        sid, run = snapshot["session_id"], created["run"]["run_id"]
        boundary = snapshot["cursor"]["virtual_time_ms"]
        page = await replay.training.history_page(sid, track_id="track-1", before_ms=boundary + 1,
            revealed_boundary_ms=boundary, data_epoch=snapshot["data_epoch"], display_interval="1m", history_epoch=None, limit=100)
        rows = page["bars"]
        origin = dict(kind="REPLAY", session_id=sid, track_id="track-1", data_epoch=snapshot["data_epoch"],
            history_epoch=page["history_epoch"], revealed_boundary_ms=boundary,
            source_sequence=snapshot["cursor"]["source_sequence"])
        body = SyntheticRequest.model_validate(payload(SeriesKey("BTCUSDT", "1m"), origin,
            rows[0]["open_time_ms"] // 1000, rows[-1]["open_time_ms"] // 1000, "heikin-ashi"))
        before = await replay.get_session_state(sid)
        lease = await service.attach(body.definition(), seed_loader=pinned_seed_loader(SimpleNamespace(app=app), body))
        first = await lease.snapshot(); await lease.close()
        assert first["status"] == "ready"
        assert await replay.get_session_state(sid) == before
        assert all(row["time"] * 1000 <= boundary for row in first["rows"])
        await _acquire(replay, run_id=run, selected_session_id=sid, command_id="acquire")
        await _send(replay, run_id=run, session_id=sid, command_id="forward", command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        lease = await service.attach(body.definition(), seed_loader=pinned_seed_loader(SimpleNamespace(app=app), body))
        assert await lease.snapshot() == first
        await lease.close()
        ahead = body.model_copy(update={"origin": body.origin.model_copy(update={"revealed_boundary_ms": boundary + 999999999})})
        with pytest.raises(SyntheticError, match="ahead"):
            await service.attach(ahead.definition(), seed_loader=pinned_seed_loader(SimpleNamespace(app=app), ahead))
        assert not live.active and not live.callbacks and not service.instances
    finally:
        await service.close(); await replay.shutdown()


@pytest.mark.anyio
async def test_snapshot_seed_is_shared_cancel_safe_and_never_claims_live_stream():
    app, live, service = host()
    body = SyntheticRequest.model_validate(payload(SeriesKey("BTCUSDT", "1m"),
        dict(kind="LOCAL_DATASET", dataset_id="fixed", data_epoch="revision"), 60, 120))
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def load():
        nonlocal calls
        calls += 1; entered.set(); await release.wait()
        return [bar(60, 100), bar(120, 106)], "revision"
    first = asyncio.create_task(service.attach(body.definition(), seed_loader=load))
    await entered.wait()
    second = asyncio.create_task(service.attach(body.definition(), seed_loader=load))
    await asyncio.sleep(0); first.cancel(); release.set()
    with pytest.raises(asyncio.CancelledError): await first
    lease = await second
    assert calls == 1 and (await lease.snapshot())["total"] == 3
    assert not live.active and not live.callbacks
    await lease.close(); assert not service.instances


@pytest.mark.anyio
@pytest.mark.parametrize("interval", ["1m", "2m"])
async def test_tape_replay_transform_uses_captured_sequence_and_forming_prefix(tmp_path, interval):
    from tests.test_replay_tape_phases import setup_tape
    from tests.test_replay_tape_projection import prepare
    replay, run, sid = await setup_tape(tmp_path, track_count=1)
    app, live, service = host(); app.state.replay_service = replay
    try:
        await prepare(replay, run, sid)
        snapshot = (await replay.get_session(sid))["snapshot"]
        origin = dict(kind="REPLAY", session_id=sid, track_id="track-1", data_epoch=snapshot["data_epoch"],
            revealed_boundary_ms=snapshot["cursor"]["virtual_time_ms"], source_sequence=snapshot["cursor"]["source_sequence"])
        async def selected(sequence):
            for _ in range(100):
                value = await replay.training.tape_projection(sid, track_id="track-1", data_epoch=origin["data_epoch"],
                    revealed_boundary_ms=origin["revealed_boundary_ms"], source_sequence=sequence,
                    display_interval=interval, limit=500)
                if value["status"] == "ready": return value
                await asyncio.sleep(0)
            pytest.fail("bounded tape fixture did not prepare")
        page = await selected(origin["source_sequence"])
        assert page["bars"]
        first_time, last_time = page["bars"][0]["open_time_ms"] // 1000, page["bars"][-1]["open_time_ms"] // 1000
        reference = [{"time": row["open_time_ms"] // 1000,
            **{key: row[key] for key in ("open", "high", "low", "close", "volume", "is_closed")}}
            for row in page["bars"]]
        before = await replay.get_session_state(sid)
        for transform in TRANSFORMS:
            body = SyntheticRequest.model_validate(payload(SeriesKey("BTCUSDT", interval, market_type="futures"),
                origin, first_time, last_time, transform))
            lease = await service.attach(body.definition(), seed_loader=pinned_seed_loader(SimpleNamespace(app=app), body))
            snapshot = await lease.snapshot(limit=5000)
            expected = SyntheticKernel(SyntheticConfig(**body.config.model_dump())).replace_snapshot(reference)
            assert [{key: value for key, value in row.items() if key not in {"id", "ordinal"}}
                for row in snapshot["rows"]] == expected
            await lease.close()
        assert await replay.get_session_state(sid) == before
        assert not live.active and not live.callbacks and not service.instances
        # The same public clock with a different selected trade prefix is a
        # different identity, including when both observations share a bucket.
        earlier = {**origin, "source_sequence": origin["source_sequence"] - 1}
        earlier_page = await selected(earlier["source_sequence"])
        assert earlier_page["source_sequence"] == earlier["source_sequence"]
        first_body = SyntheticRequest.model_validate(payload(SeriesKey("BTCUSDT", interval, market_type="futures"), origin, first_time, last_time))
        second_body = SyntheticRequest.model_validate(payload(SeriesKey("BTCUSDT", interval, market_type="futures"), earlier, first_time, last_time))
        assert first_body.definition().key != second_body.definition().key
    finally:
        await service.close(); await replay.shutdown()
