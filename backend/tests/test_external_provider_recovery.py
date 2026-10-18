from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal

from tests.test_external_provider_http_runtime import (
    SDK,
    LocalHost,
    completed,
    select,
    stop_client,
    wait_until,
)
from tests.test_external_provider_http_runtime import (
    fixture as fixture,  # noqa: PLC0414 - re-export shared pytest fixture
)


def test_inflight_model_call_survives_host_runtime_restart_without_duplicate_fills(fixture, tmp_path):
    settings, local_root, data, model_manifest = fixture
    script = tmp_path / "independent_slow_model.py"
    script.write_text('''from pathlib import Path
import hashlib
import signal
import sys
import threading
import time
from candlescope_external_provider.client import ExternalClient
from candlescope_external_provider.example import RollingMeanModel, manifest
class SlowModel(RollingMeanModel):
    def step(self, observation):
        time.sleep(0.15)
        return super().step(observation)
spec = manifest()
spec["artifact_sha256"] = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
spec["provider_revision"] = "recovery-1"
stopped = threading.Event()
for number in (signal.SIGINT, signal.SIGTERM):
    signal.signal(number, lambda *_args: stopped.set())
ExternalClient(Path(sys.argv[1]), spec, SlowModel).run(stopped)
''')
    model_manifest = {**model_manifest, "artifact_sha256": "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest(),
                      "provider_revision": "recovery-1"}
    setup = settings, local_root, data, model_manifest
    host = LocalHost(settings, local_root)
    client = None
    try:
        selected, binding = select(host, setup)
        client = subprocess.Popen([sys.executable, str(script), binding["connection_file"]], cwd=tmp_path,
                                  env=dict(os.environ, PYTHONPATH=str(SDK)), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        wait_until(lambda: host.runtime.service.external.waiting_reason(binding["connection_id"]) is None)
        host.request("POST", "/provider-connections/" + binding["connection_id"] + "/smoke", selected)
        config = {**selected, "external_connection_id": binding["connection_id"], "warmup_bars": 3}
        created = host.request("POST", "/runs", config, headers={"Idempotency-Key": "inflight-recovery"})
        run_id = created["run_id"]

        def at_inflight_call_after_checkpoint():
            checkpoint = host.runtime.service.repository.latest_checkpoint(run_id)
            if checkpoint is None or checkpoint["sequence"] < 4:
                return None
            with host.runtime.service.external.store._read() as connection:
                row = connection.execute(
                    "SELECT call_id, payload_json FROM external_provider_calls WHERE run_id = ? AND reply_json IS NULL AND operation = 'step'",
                    (run_id,),
                ).fetchone()
            return dict(row) if row is not None and json.loads(row["payload_json"])["observation"]["sequence"] >= 5 else None

        pending = wait_until(at_inflight_call_after_checkpoint)
        host.runtime.worker.shutdown()
        interrupted = host.runtime.service.repository.get_run_by_id(run_id)
        assert interrupted["state"] == "QUEUED" and interrupted["generation"] == 2
        assert host.runtime.service.repository.latest_checkpoint(run_id) is not None
        assert client.poll() is None
        host.close()
        host = LocalHost(settings, local_root)
        recovered, report = completed(host, run_id)
        assert recovered["generation"] == 2 and client.poll() is None
        assert [fill["sequence"] for fill in report["fills"]] == [5, 7]
        assert len(report["fills"]) == 2
        net = sum((Decimal(fill["price"]) * Decimal(fill["qty"]) * (1 if fill["side"] == "SELL" else -1)
                   - Decimal(fill["fee"]) for fill in report["fills"]), Decimal(0))
        assert net == Decimal("-0.0070019")
        with host.runtime.service.external.store._read() as connection:
            row = connection.execute("SELECT reply_json FROM external_provider_calls WHERE call_id = ?", (pending["call_id"],)).fetchone()
            assert row is not None and row[0] is not None
            assert connection.execute("SELECT status FROM external_provider_sessions WHERE run_id = ?", (run_id,)).fetchone()[0] == "CLOSED"
        assert report["strategy"]["external_provider"]["decision_count"] == 5
    finally:
        if client is not None:
            stop_client(client)
        host.close()
