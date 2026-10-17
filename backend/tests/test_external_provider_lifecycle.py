from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.backtest.external_provider.contracts import parse_manifest
from app.backtest.external_provider.journal import ExternalCallJournal
from app.backtest.external_provider.provider import ExternalDecisionProvider
from app.backtest.external_provider.repository import ExternalConnectionRepository
from app.backtest.strategy.host_adapter import StrategyHostAdapter
from app.backtest.strategy.protocol import (
    StrategyProviderError,
    StrategyProviderSession,
)
from tests.test_external_provider_contracts import manifest
from tests.test_external_provider_journal import TOKEN
from tests.test_external_provider_messages import frame

CONTEXT = {"runId": "run_one", "inputPlan": {"roles": ["BARS"]}}


@pytest.fixture
def connected(tmp_path):
    store = ExternalConnectionRepository(tmp_path / "external.sqlite3")
    store.open()
    now = int(time.time() * 1000)
    connection_id = store.create({"strategy_revision_id": "srv_model", "dataset_id": "local_one",
                                  "data_epoch": "epoch_one", "snapshot_hash": "sha256:dataset"},
                                 token=TOKEN, now_ms=now)
    lease = store.connect(connection_id, token=TOKEN, client_id="client_one", now_ms=now)
    try:
        yield store, ExternalCallJournal(store, parse_manifest(manifest())), connection_id, lease
    finally:
        store.close()


class IndependentClient:
    """Independent SQLite owner exercises delivery, not a direct model callback."""

    def __init__(self, setup):
        store, journal, connection_id, lease = setup
        self.store = ExternalConnectionRepository(store.path)
        self.store.open()
        self.journal = ExternalCallJournal(self.store, journal.manifest)
        self.connection_id = connection_id
        self.generation = lease["client_generation"]
        self.calls = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.serve)
        self.failure = None

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=2)
        self.store.close()
        assert not self.thread.is_alive()
        if self.failure is not None:
            raise self.failure

    def serve(self):
        try:
            while not self.stopped.is_set():
                now = int(time.time() * 1000)
                packet = self.journal.poll(self.connection_id, token=TOKEN, client_id="client_one",
                                           client_generation=self.generation, now_ms=now)
                if packet is None:
                    self.stopped.wait(0.001)
                    continue
                self.calls.append(packet)
                state = dict(packet["bootstrap"]["model_state"] or {"bars": 0, "reports": 0})
                decision = None
                if packet["operation"] in ("step", "warmup"):
                    state["bars"] += 1
                    if packet["operation"] == "step":
                        decision = {"sequence": packet["payload"]["observation"]["sequence"],
                                    "kind": "TARGET_POSITION", "payload": {"targetExposure": str(state["bars"])}}
                if packet["operation"] == "onExecutionReport":
                    state["reports"] += 1
                self.journal.submit(self.connection_id, token=TOKEN, client_id="client_one",
                                    client_generation=self.generation, now_ms=now,
                                    **{key: packet[key] for key in ("run_id", "host_generation", "cursor", "call_id", "input_hash")},
                                    result={"decision": decision, "model_state": state})
        except BaseException as exc:  # noqa: BLE001 - propagate every client-thread failure to the test owner
            self.failure = exc


def provider(setup, *, generation=1, timeout=1, check_control=None):
    _, journal, connection_id, _ = setup
    return ExternalDecisionProvider(journal, connection_id=connection_id, host_generation=generation,
                                    step_timeout_s=timeout, check_control=check_control)


def live_lease(setup):
    store, _, connection_id, _ = setup
    now = int(time.time() * 1000)
    setup[3].update(store.connect(connection_id, token=TOKEN, client_id="client_one", now_ms=now))


def test_real_host_session_lifecycle_uses_recorded_decisions_and_private_state(connected):
    live_lease(connected)
    external = provider(connected)
    session = StrategyProviderSession(external, run_id="run_one")
    adapter = StrategyHostAdapter(session, step_timeout_s=1)
    try:
        with IndependentClient(connected) as client:
            adapter.start({"roles": ["BARS"]})
            assert adapter.observe(sequence=1, event_time_ms=100, watermark_ms=100, phase="WARMUP",
                                   market={}, bar={"close_time_ms": 100, "close": "12"},
                                   features={"close": "12", "volume": "1"}) is None
            output = adapter.observe(sequence=2, event_time_ms=200, watermark_ms=200, phase="EVALUATION",
                                     market={}, bar={"close_time_ms": 200, "close": "13"},
                                     features={"close": "13", "volume": "1"})
            assert output["payload"] == {"targetExposure": "2"}
            session.on_execution_report({"generation": 1, "accepted": True, "fill": {"qty": "2"}})
            snapshot = session.snapshot()
            assert "model_state" not in snapshot["provider"]
            metadata = external.report_metadata()["external_provider"]
            assert metadata["decision_count"] == 1 and metadata["call_count"] == 4
            assert session.close() == metadata["trace_hash"]
            assert external.report_metadata()["external_provider"] == metadata
            assert [packet["operation"] for packet in client.calls] == ["prepare", "warmup", "step", "onExecutionReport", "close"]
            assert "generation" not in client.calls[-2]["payload"]["report"]
    finally:
        adapter.close()


def test_recovery_replays_committed_steps_without_model_calls_then_bootstraps_current_state(connected):
    live_lease(connected)
    external = provider(connected)
    with IndependentClient(connected) as client:
        external.prepare(CONTEXT)
        external.warmup(replace(frame(), sequence=1, phase="WARMUP"))
        checkpoint = external.snapshot()
        first = external.step(replace(frame(), sequence=2))
        second = external.step(replace(frame(), sequence=3))
        count = len(client.calls)
        recovered = ExternalDecisionProvider(external.journal, connection_id=external.connection_id,
                                              host_generation=2, step_timeout_s=1)
        recovered.prepare(CONTEXT)
        recovered.restore(checkpoint)
        assert recovered.step(replace(frame(), sequence=2)) == first
        # The Host can persist a new checkpoint before it has replayed all
        # committed calls; the model is not invoked to reconstruct old state.
        replay_checkpoint = recovered.snapshot()
        assert recovered.step(replace(frame(), sequence=3)) == second
        assert len(client.calls) == count
        assert recovered.step(replace(frame(), sequence=4)).payload == {"targetExposure": "4"}
        assert client.calls[-1]["bootstrap"]["model_state"] == {"bars": 3, "reports": 0}
        recovered.restore(replay_checkpoint)
        assert recovered.step(replace(frame(), sequence=3)) == second
        assert recovered.step(replace(frame(), sequence=4)).payload == {"targetExposure": "4"}
        recovered.close()


def test_timeout_fences_pending_delivery_and_new_host_owner_can_retry(connected):
    live_lease(connected)
    external = provider(connected, timeout=0.03)
    started = time.monotonic()
    with pytest.raises(StrategyProviderError, match="PROVIDER_TIMEOUT"):
        external.prepare(CONTEXT)
    assert time.monotonic() - started < 0.5
    assert external.close() == ""
    journal = connected[1]
    assert journal.poll(connected[2], token=TOKEN, client_id="client_one",
                        client_generation=connected[3]["client_generation"], now_ms=int(time.time() * 1000)) is None
    with IndependentClient(connected) as client:
        recovered = ExternalDecisionProvider(journal, connection_id=connected[2], host_generation=2, step_timeout_s=1)
        recovered.prepare(CONTEXT)
        assert client.calls[0]["host_generation"] == 2
        recovered.close()


def test_cancellation_interrupts_wait_without_waiting_for_the_step_budget(connected):
    live_lease(connected)
    cancelled = threading.Event()

    def check():
        if cancelled.is_set():
            raise StrategyProviderError("RUN_CANCELLED", "cancelled by Host")

    external = provider(connected, timeout=2, check_control=check)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(external.prepare, CONTEXT)
        deadline = time.monotonic() + 1
        while external.run_id is None and time.monotonic() < deadline:
            cancelled.wait(0.001)
        cancelled.set()
        with pytest.raises(StrategyProviderError, match="RUN_CANCELLED"):
            future.result(timeout=0.5)
    assert external.close() == ""


def test_restore_cannot_substitute_another_state_or_context(connected):
    live_lease(connected)
    external = provider(connected)
    with IndependentClient(connected):
        external.prepare(CONTEXT)
        checkpoint = external.snapshot()
        with pytest.raises(StrategyProviderError, match="IDENTITY_MUTATION"):
            external.restore({**checkpoint, "model_state_hash": "sha256:other"})
        external.close()
