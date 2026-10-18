from __future__ import annotations

import asyncio
import hashlib
import http.client
import importlib
import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest
import uvicorn
from app.api.v1.backtests import router
from app.backtest.external_provider.endpoint import publish
from app.backtest.external_provider.wire import digest, encode
from app.backtest.runtime import BacktestRuntime, BacktestWorker
from app.core.config import load_backtest_settings
from app.local_data.service import LocalDatasetService, LocalImportOptions
from fastapi import FastAPI

SDK = Path(__file__).resolve().parents[2] / "packages" / "candlescope-external-provider" / "src"


class LocalHost:
    def __init__(self, settings, local_root, archive_dir=None):
        self.runtime = BacktestRuntime.start(settings, local_data_dir=local_root, trade_archive_dir=archive_dir)
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.state.backtest_service = self.runtime.service
        app.state.backtest_runtime = self.runtime
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_level="error"))
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve(sockets=[self.socket])))
        self.thread.start()
        wait_until(lambda: self.server.started)
        publish(self.runtime.service.external.endpoint_file, host="127.0.0.1", port=self.port)

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        self.runtime.shutdown()
        self.socket.close()

    def request(self, method, path, payload=None, *, headers=None, expected=200):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload) if payload is not None else None
        try:
            connection.request(method, "/api/v1/backtests" + path, body=body,
                               headers={"Content-Type": "application/json", **(headers or {})})
            response = connection.getresponse()
            data = json.loads(response.read())
            assert response.status == expected, data
            return data
        finally:
            connection.close()


def wait_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("bounded external Host condition did not become ready")


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SDK))
    model_manifest = importlib.import_module("candlescope_external_provider.example").manifest()
    local_root = tmp_path / "local-data"
    csv = tmp_path / "bars.csv"
    closes = ["10", "9", "8", "12", "13", "7", "6", "14"]
    csv.write_text("time,open,high,low,close,volume\n" + "\n".join(
        f"{index * 60000},{price},{price},{price},{price},1" for index, price in enumerate(closes)
    ))
    local_manifest = LocalDatasetService(local_root).import_csv(
        csv, LocalImportOptions(name="external HTTP model", symbol="LTCUSDT", interval="1m", timestamp_unit="ms")
    )
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1",
                                       "BACKTEST_EXTERNAL_PROVIDER_ENABLED": "1", "BACKTEST_CHECKPOINT_EVENT_INTERVAL": "2"},
                                      data_dir=tmp_path, klines_db_path=tmp_path / "candlescope.db", replay_db_path=tmp_path / "replay.db")
    return settings, local_root, local_manifest, model_manifest


def select(host, fixture, **overrides):
    _, _, dataset, model_manifest = fixture
    revision = host.request("POST", "/strategy-revisions", {"name": "external rolling mean", "language": "EXTERNAL_PROVIDER",
                                                             "source_text": json.dumps(model_manifest), "parameter_schema": []})
    selected = {"strategy_revision_id": revision["revision_id"], "dataset_id": dataset["dataset_id"],
                "data_epoch": dataset["data_epoch"], "start_time_ms": 0, "end_time_ms": 480000,
                "interval": "1m", "fidelity_mode": "BAR_APPROX", "exchange": "binance", "market_type": "usdm",
                "contract_data_mode": "LEGACY_FIXED_V1", "account_model": "LINEAR_PERP_ONE_WAY_V1", "funding_mode": "OFF", **overrides}
    preview = host.runtime.preview_snapshot(**{key: value for key, value in selected.items() if key != "strategy_revision_id"})
    selected["snapshot_hash"] = preview["snapshot_hash"]
    selected["data_epoch"] = preview["data_epoch"]
    binding = host.request("POST", "/provider-connections", selected)
    assert "token" not in binding
    return selected, binding


def launch_client(binding, tmp_path):
    environment = dict(os.environ, PYTHONPATH=str(SDK))
    command = shlex.split(binding["example_command"]) if os.name != "nt" and binding.get("example_command") else [
        sys.executable, "-m", "candlescope_external_provider", "--connection", binding["connection_file"]]
    return subprocess.Popen(command,
                            cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def stop_client(client):
    client.terminate()
    try:
        stdout, stderr = client.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        client.kill()
        stdout, stderr = client.communicate(timeout=3)
        raise AssertionError("external SDK did not stop after signal")
    assert not stdout and not stderr


def completed(host, run_id):
    def terminal():
        row = host.request("GET", "/runs/" + run_id)
        return row if row["state"] in {"COMPLETED", "FAILED", "CANCELLED"} else None
    row = wait_until(terminal)
    assert row["state"] == "COMPLETED", row.get("failure_code")
    return row, host.request("GET", "/runs/" + run_id + "/report")


def test_independent_process_http_smoke_run_and_full_host_restart(fixture, tmp_path):
    settings, local_root, _, _ = fixture
    host = LocalHost(settings, local_root)
    client = None
    try:
        selected, binding = select(host, fixture)
        config = {**selected, "external_connection_id": binding["connection_id"], "warmup_bars": 3,
                  "parameters": {}, "output_mode": "TARGET_POSITION", "symbol": "WRONGUSDT"}
        before = host.request("POST", "/runs", config, headers={"Idempotency-Key": "before-smoke"}, expected=400)
        assert before["error"]["code"] == "SMOKE_REQUIRED"
        client = launch_client(binding, tmp_path)
        wait_until(lambda: host.runtime.service.external.store.ready(binding["connection_id"], now_ms=int(time.time() * 1000)))
        assert client.poll() is None
        smoke = host.request("POST", "/provider-connections/" + binding["connection_id"] + "/smoke", selected)
        assert smoke["qualification"] == "EXTERNAL_LIFECYCLE_ONLY"
        assert smoke["warmupBars"] == 3 and smoke["evaluationBars"] == 3
        changed = host.request("POST", "/runs", {**config, "parameters": {"quantity": "0.002"}},
                               headers={"Idempotency-Key": "changed-external-parameters"}, expected=400)
        assert changed["error"]["code"] == "SMOKE_REQUIRED"
        validated = host.request("POST", "/runs/validate", config)
        created = host.request("POST", "/runs", config, headers={"Idempotency-Key": "external-first"})
        queued_config = json.loads(created["config_json"])
        assert queued_config["symbol"] == "LTCUSDT"
        assert queued_config["source_event_kind"] == "BAR"
        assert created["config_hash"] == validated["config_hash"]
        first, report = completed(host, created["run_id"])
        result = report
        fills = result["fills"]
        assert [fill["sequence"] for fill in fills] == [5, 7]
        assert [fill["side"] for fill in fills] == ["BUY", "SELL"]
        cashflow = sum((Decimal(fill["price"]) * Decimal(fill["qty"]) * (1 if fill["side"] == "SELL" else -1)
                        - Decimal(fill["fee"]) for fill in fills), Decimal(0))
        assert cashflow == Decimal("-0.0070019")
        assert result["strategy"]["external_provider"]["decision_count"] == 5
        assert report["hashes"]["report"].startswith("sha256:")
        frozen = host.runtime.service.repository.get_run_by_id(first["run_id"])
        private_file = Path(binding["connection_file"]).read_bytes()
        assert Path(binding["connection_file"]).stat().st_mode & 0o077 == 0
        token = json.loads(private_file)["token"].encode()
        for path in host.runtime.service.external.directory.iterdir():
            if path.suffix != ".json":
                assert token not in path.read_bytes()
        old_port = host.port
        host.close()
        host = LocalHost(settings, local_root)
        assert host.port != old_port
        wait_until(lambda: host.runtime.service.external.store.ready(binding["connection_id"], now_ms=int(time.time() * 1000)))
        assert client.poll() is None
        assert host.runtime.service.repository.get_run_by_id(first["run_id"]) == frozen
        assert Path(binding["connection_file"]).read_bytes() == private_file
        again = host.request("POST", "/runs", config, headers={"Idempotency-Key": "external-after-restart"})
        _, second_report = completed(host, again["run_id"])
        second_result = second_report
        for name in ("fills", "orders", "ledger", "equity_curve"):
            assert second_result[name] == result[name]
        assert second_report["hashes"]["fill"] == report["hashes"]["fill"]
        stop_client(client)
        client = None
        host.request("POST", "/provider-connections/" + binding["connection_id"] + "/revoke")
        host.request("POST", "/strategy-revisions/" + selected["strategy_revision_id"] + "/archive")
        cursor = 0
        trace = []
        while True:
            page = host.request("GET", "/provider-connections/runs/" + first["run_id"] + f"/trace?after={cursor}&limit=3")
            trace.extend(page["items"])
            if not page["has_more"]:
                break
            assert page["next_after"] > cursor
            cursor = page["next_after"]
        assert sum(item["operation"] == "step" for item in trace) == 5
        observations = [item["payload"]["observation"] for item in trace if item["operation"] in {"warmup", "step"}]
        assert all(item["market"] == {"venue": "binance", "market_type": "usdm", "symbol": "LTCUSDT"}
                   for item in observations)
        audit = hashlib.sha256()
        for item in trace:
            assert "model_state" not in item["reply"]
            assert digest({key: item[key] for key in ("run_id", "cursor", "operation", "payload", "model_state_before_hash")}) == item["input_hash"]
            assert digest(item["reply"]) == item["reply_hash"]
            if item["operation"] != "close":
                audit.update(encode({key: item[key] for key in ("cursor", "operation", "input_hash", "reply_hash")}).encode())
                audit.update(b"\n")
        assert "sha256:" + audit.hexdigest() == report["strategy"]["external_provider"]["trace_hash"]
        assert token.decode() not in json.dumps(trace)
        assert host.runtime.service.repository.get_run_by_id(first["run_id"]) == frozen
    finally:
        if client is not None:
            stop_client(client)
        host.close()


def test_disconnected_queued_model_does_not_starve_other_runs_and_revoke_is_final(fixture, tmp_path):
    settings, local_root, _, _ = fixture
    host = LocalHost(settings, local_root)
    client = None
    try:
        selected, binding = select(host, fixture)
        client = launch_client(binding, tmp_path)
        wait_until(lambda: host.runtime.service.external.store.ready(binding["connection_id"], now_ms=int(time.time() * 1000)))
        host.request("POST", "/provider-connections/" + binding["connection_id"] + "/smoke", selected)
        host.runtime.worker.shutdown()
        external = host.request("POST", "/runs", {**selected, "external_connection_id": binding["connection_id"], "warmup_bars": 3},
                                headers={"Idempotency-Key": "wait-external"})
        stop_client(client)
        client = None
        host.runtime.service.external.store.reset_client_leases()
        builtin = host.request("POST", "/runs", {**selected, "strategy_revision_id": "builtin-sma-cross-v1",
                                                "parameters": {"fast": 3, "slow": 5}},
                               headers={"Idempotency-Key": "independent-builtin"})
        host.runtime.worker = BacktestWorker(settings=settings, local_data=host.runtime.local_data)
        host.runtime.worker.start()
        completed(host, builtin["run_id"])
        waiting = host.request("GET", "/runs/" + external["run_id"])
        assert waiting["state"] == "QUEUED" and waiting["waiting_for"] == "EXTERNAL_CONNECTION"
        for _ in range(2):
            revoked = host.request("POST", "/provider-connections/" + binding["connection_id"] + "/revoke")
            assert revoked["revoked"] is True
        assert host.request("GET", "/runs/" + external["run_id"])["state"] == "CANCELLED"
        assert not Path(binding["connection_file"]).exists()
    finally:
        if client is not None:
            stop_client(client)
        host.close()
