from decimal import Decimal
import time

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
        assert report["fills"]
        replay_params = {"snapshot_hash": snap, "report_hash": report["hashes"]["report"], "interval": "1m",
                         "comparison_interval": "5m"}
        replay_path = f"{RUNS}/{run_id}/result-replay"

        def frame(cursor):
            response = client.get(replay_path, params={**replay_params, "cursor": cursor})
            assert response.status_code == 200, response.text
            return response.json()

        for cursor in range(11):
            visible = frame(cursor)
            assert visible["schema"] == "candlescope.local-bar-result-replay/1"
            assert visible["total"] == 10 and visible["cursor"] == cursor
            assert len(visible["bars"]) == cursor
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
        before = frame(4)
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
    finally:
        cold.shutdown()
