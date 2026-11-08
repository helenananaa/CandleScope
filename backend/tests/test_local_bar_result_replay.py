from decimal import Decimal
import time

from app.backtest.result_replay import MAX_REVEALED_BARS, _display_chart
from app.data_engine.interval_policy import parse_interval_spec
from app.market_dataset.snapshot import MarketEvent
from tests.test_backtest_chart_context import _runtime
from tests.test_python_editor import compile_editor
from tests.test_user_market_trades import RUNS, START, app_client


def bars_csv(last=1000):
    rows = ["time,open,high,low,close,volume"]
    for index in range(10):
        price = 100 + index
        close = price + 1 if index < 9 else last
        rows.append(f"{START + index * 60_000},{price},{close},{price},{close},20")
    return "\n".join(rows) + "\n"


def test_pinned_bar_result_replay_links_two_periods_and_survives_reimport(tmp_path):
    runtime = _runtime(tmp_path)
    client = app_client(runtime)
    import_path = "/api/v1/local/imports/csv"
    params = {"name": "Offline BAR", "symbol": "ETHUSDC", "interval": "1m",
              "timestamp_unit": "ms", "base_asset": "ETH", "quote_asset": "USDC"}
    try:
        uploaded = client.post(import_path, params=params, content=bars_csv())
        assert uploaded.status_code == 201, uploaded.text
        manifest = uploaded.json()
        snapshot_request = {
            "dataset_id": manifest["dataset_id"], "data_epoch": manifest["data_epoch"],
            "start_time_ms": START, "end_time_ms": START + 9 * 60_000 + 1, "interval": "1m",
            "fidelity_mode": "BAR_APPROX", "exchange": "local", "market_type": "spot",
            "account_model": "SPOT_CASH_V1",
        }
        preview = client.post("/api/v1/backtests/datasets/snapshot", json=snapshot_request)
        assert preview.status_code == 200, preview.text
        snap = preview.json()["snapshot_hash"]
        revision = compile_editor(runtime.service)["revision_id"]
        confirmation = {"python_runtime_mode": "TRUSTED_LOCAL", "python_trusted_confirmed": True}
        smoke = client.post("/api/v1/backtests/strategy-revisions/" + revision + "/smoke", json={
            **confirmation, "dataset_id": manifest["dataset_id"], "snapshot_hash": snap,
            "start_time_ms": START, "end_time_ms": snapshot_request["end_time_ms"],
        })
        assert smoke.status_code == 200, smoke.text
        creation = client.post(RUNS, headers={"Idempotency-Key": "bar-result-replay"}, json={
            **snapshot_request, **confirmation, "strategy_revision_id": revision, "snapshot_hash": snap,
            "source_event_kind": "BAR", "output_mode": "SIGNAL", "symbol": "ETHUSDC",
            "sizing_policy": "EQUITY_PERCENT_V1", "equity_percent": "10",
            "execution_model_revision": "EXECUTION_REALISM_V2", "participation_rate": "0.1",
        })
        assert creation.status_code == 200, creation.text
        run_id = creation.json()["run_id"]
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            run = client.get(f"{RUNS}/{run_id}").json()
            if run["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.05)
        assert run["state"] == "COMPLETED", run
        report = client.get(f"{RUNS}/{run_id}/report").json()
        chart = client.get(f"{RUNS}/{run_id}/chart").json()
        assert report["data_quality"]["quote_asset"] == "USDC"
        assert report["fills"]
        replay_params = {"snapshot_hash": snap, "report_hash": report["hashes"]["report"], "interval": "1m",
                         "comparison_interval": "5m", "ma_period": 2, "comparison_ma_period": 2}
        replay_path = f"{RUNS}/{run_id}/result-replay"

        def frame(cursor):
            response = client.get(replay_path, params={**replay_params, "cursor": cursor})
            assert response.status_code == 200, response.text
            return response.json()

        reference_params = {**params, "name": "Second symbol", "symbol": "SOLUSDC",
                            "base_asset": "SOL", "interval": "5m"}

        def reference_csv(final):
            return "time,open,high,low,close,volume\n" + "".join(
                f"{START + index * 300_000},{value},{value},{value},{value},1\n"
                for index, value in enumerate((30, final, 9000))
            )

        imported = client.post(import_path, params=reference_params, content=reference_csv(4000))
        assert imported.status_code == 201, imported.text
        reference = imported.json()
        reference_replay_params = {**replay_params,
                                   "comparison_dataset_id": reference["dataset_id"],
                                   "comparison_data_epoch": reference["data_epoch"]}

        def reference_frame(cursor):
            response = client.get(replay_path, params={**reference_replay_params, "cursor": cursor})
            assert response.status_code == 200, response.text
            return response.json()

        assert reference_frame(0)["comparison"]["bars"] == []
        assert reference_frame(4)["comparison"]["bars"] == []
        at_five = reference_frame(5)
        assert at_five["comparison"]["symbol"] == "SOLUSDC"
        assert at_five["comparison"]["display_intervals"] == ["5m", "15m", "1h"]
        assert [bar["high"] for bar in at_five["comparison"]["bars"]] == ["30"]
        assert at_five["comparison"]["ma"]["points"] == []
        full_reference = reference_frame(10)
        assert [bar["high"] for bar in full_reference["comparison"]["bars"]] == ["30", "4000"]
        assert full_reference["comparison"]["ma"]["points"] == [{"open_time_ms": START + 300_000, "value": 2015}]
        assert reference_frame(4)["comparison"]["bars"] == []
        assert {k: v for k, v in full_reference.items() if k != "comparison"} == {
            k: v for k, v in frame(10).items() if k != "comparison"
        }
        pending_coarse = client.get(replay_path, params={**reference_replay_params, "cursor": 10,
                                                       "comparison_interval": "15m"})
        assert pending_coarse.status_code == 200, pending_coarse.text
        assert pending_coarse.json()["comparison"]["bars"] == []
        bad_pin = client.get(replay_path, params={**reference_replay_params, "cursor": 4,
                                                "comparison_data_epoch": manifest["data_epoch"]})
        assert bad_pin.status_code == 400
        changed_reference = client.post(import_path, params={**reference_params, "dataset_id": reference["dataset_id"]},
                                        content=reference_csv(8000))
        assert changed_reference.status_code == 201 and changed_reference.json()["data_epoch"] != reference["data_epoch"]
        assert reference_frame(10) == full_reference

        for cursor in range(11):
            visible = frame(cursor)
            assert visible["schema"] == "candlescope.local-bar-result-replay/1"
            assert visible["total"] == 10 and visible["cursor"] == cursor
            assert len(visible["bars"]) == cursor
            assert visible["display_intervals"] == ["1m", "5m", "15m", "1h"]
            assert visible["signal_trace_available"]
            assert [signal["reveal_sequence"] for signal in visible["closed_bar_signals"]] == list(range(1, cursor + 1))
            assert visible["time_ms"] == (START + cursor * 60_000 - 1 if cursor else None)
            if cursor:
                assert all(bar["closed"] and bar["close_time_ms"] <= visible["time_ms"] for bar in visible["bars"])
                secondary = visible["comparison"]["bars"]
                assert len(secondary) == (cursor + 4) // 5
                assert secondary[-1]["closed"] == (cursor % 5 == 0)
                assert secondary[-1]["high"] == ("1000" if cursor == 10 else str(100 + cursor))
            else:
                assert visible["comparison"]["bars"] == []
            closes = [*range(101, 110), 1000]
            expected = [
                {"open_time_ms": START + index * 60_000, "value": (closes[index - 1] + closes[index]) / 2}
                for index in range(1, cursor)
            ]
            assert visible["ma"] == {"period": 2, "points": expected}
            assert visible["comparison"]["ma"] == {"period": 2, "points": (
                [{"open_time_ms": START + 5 * 60_000, "value": 552.5}] if cursor == 10 else []
            )}
            fills = [fill for fill in report["fills"] if fill["source_sequence"] <= cursor]
            assert visible["fill_count"] == len(fills)
            cash, qty = Decimal("10000"), Decimal(0)
            for fill in fills:
                quantity = Decimal(fill["qty"])
                signed = quantity if fill["side"] == "BUY" else -quantity
                qty += signed
                cash -= signed * Decimal(fill["price"]) + Decimal(fill["fee"])
            close = Decimal("1000" if cursor == 10 else str(100 + cursor))
            assert Decimal(visible["cash"]) == cash
            assert Decimal(visible["position"]) == qty
            assert Decimal(visible["equity"]) == cash + qty * close
        assert frame(10)["bars"][-1]["high"] == "1000"
        assert frame(1)["bars"][0]["high"] == "101"
        note_id = "ebee5398-f389-4171-9d75-6206578fd88d"
        later_id = "1b9a9721-4eca-4e1e-9adc-dc6414097dc0"

        def save_note(cursor, body, *, revision=0, id=note_id, **overrides):
            return client.post(f"{replay_path}/notes", json={
                "snapshot_hash": snap, "report_hash": report["hashes"]["report"], "interval": "1m",
                "cursor": cursor, "note_id": id, "expected_revision": revision, "body": body, **overrides,
            })

        first = save_note(1, "  First close  ")
        assert first.status_code == 200 and first.json() == {"revision": 1}
        assert save_note(5, "Fifth close", revision=1).json() == {"revision": 2}
        assert save_note(9, "Ninth close", id=later_id).json() == {"revision": 1}
        assert save_note(1, "First close").json() == first.json()
        assert save_note(4, "Conflicting edit", revision=1).json()["error"]["code"] == "RESULT_REPLAY_NOTE_CONFLICT"
        assert save_note(4, "Backdated edit", revision=2).json()["error"]["code"] == "RESULT_REPLAY_NOTE_CONFLICT"
        assert save_note(6, "   ", revision=2).status_code == 422
        assert save_note(11, "Outside snapshot", revision=2).status_code == 400
        wrong = save_note(7, "Wrong report", revision=2, report_hash="sha256:" + "0" * 64)
        assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "DATA_SNAPSHOT_MISMATCH"
        assert frame(0)["notes"] == []
        before = frame(4)
        assert [(note["id"], note["revision"], note["cursor"], note["time_ms"], note["body"]) for note in before["notes"]] == [
            (note_id, 1, 1, START + 59_999, "First close"),
        ]
        after = frame(10)
        assert [(note["id"], note["revision"], note["cursor"], note["body"]) for note in after["notes"]] == [
            (note_id, 2, 5, "Fifth close"), (later_id, 1, 9, "Ninth close"),
        ]
        assert client.get(f"{RUNS}/{run_id}/report").json()["hashes"]["report"] == report["hashes"]["report"]
        replacement = client.post(import_path, params={**params, "dataset_id": manifest["dataset_id"]},
                                  content=bars_csv(1200))
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["data_epoch"] != manifest["data_epoch"]
        assert frame(4) == before
        assert frame(10)["comparison"]["bars"][-1]["high"] == "1000"
        assert client.get(f"{RUNS}/{run_id}/chart").json()["chart_hash"] == chart["chart_hash"]
        assert len(client.get(RUNS).json()["runs"]) == 1
    finally:
        runtime.shutdown()

    cold = _runtime(tmp_path)
    try:
        restored = app_client(cold).get(replay_path, params={**replay_params, "cursor": 4})
        assert restored.status_code == 200 and restored.json() == before
        pinned = app_client(cold).get(replay_path, params={**reference_replay_params, "cursor": 10})
        assert pinned.status_code == 200 and pinned.json()["comparison"] == full_reference["comparison"]
        latest = app_client(cold).get(replay_path, params={**replay_params, "cursor": 10})
        assert latest.status_code == 200 and latest.json() == after
    finally:
        cold.shutdown()


def test_replay_ma_warms_first_visible_bar_from_bounded_revealed_history():
    events = []
    for index in range(171):
        start = START + index * 60_000
        close = 1000 if index == 170 else index + 1
        events.append(MarketEvent(index + 1, start + 59_999, "BARS", {
            "open_time_ms": start, "close_time_ms": start + 59_999,
            "open": close, "high": close, "low": close, "close": close, "volume": 1,
        }))
    times = [event.event_time_ms for event in events]
    spec = parse_interval_spec("1m")
    chart = _display_chart(events, times, 170, spec, trade=False, source_interval="1m", ma_period=5)
    assert len(chart["bars"]) == len(chart["ma"]["points"]) == MAX_REVEALED_BARS
    assert chart["ma"]["points"][0] == {"open_time_ms": START + 10 * 60_000, "value": 9}
    assert chart["ma"]["points"][-1]["value"] == 168
    assert _display_chart(events, times, 171, spec, trade=False, source_interval="1m",
                          ma_period=5)["ma"]["points"][-1]["value"] == 334.8
