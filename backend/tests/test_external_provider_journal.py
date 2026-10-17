from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.backtest.external_provider.contracts import parse_manifest
from app.backtest.external_provider.journal import ExternalCallJournal
from app.backtest.external_provider.repository import ExternalConnectionRepository
from app.backtest.strategy.protocol import StrategyProviderError
from tests.test_external_provider_contracts import manifest

TOKEN = "test-local-external-provider-private-token"


@pytest.fixture
def connected(tmp_path):
    store = ExternalConnectionRepository(tmp_path / "external.sqlite3")
    store.open()
    connection_id = store.create({"strategy_revision_id": "srv_model", "dataset_id": "local_one",
                                  "data_epoch": "epoch_one", "snapshot_hash": "sha256:dataset"},
                                 token=TOKEN, now_ms=100)
    lease = store.connect(connection_id, token=TOKEN, client_id="client_one", now_ms=101)
    journal = ExternalCallJournal(store, parse_manifest(manifest()))
    journal.start(connection_id, "run_one", host_generation=1, context={"dataset_id": "local_one"})
    try:
        yield store, journal, connection_id, lease
    finally:
        store.close()


def queue(journal, cursor=1, *, operation="prepare", payload=None, generation=1):
    return journal.enqueue("run_one", host_generation=generation, cursor=cursor, operation=operation,
                           payload={} if payload is None else payload, now_ms=102)


def poll(connected):
    _, journal, connection_id, lease = connected
    return journal.poll(connection_id, token=TOKEN, client_id="client_one",
                        client_generation=lease["client_generation"], now_ms=103)


def submit(connected, packet, *, state=None, decision=None, result=None, **overrides):
    _, journal, connection_id, lease = connected
    args = {"token": TOKEN, "client_id": "client_one", "client_generation": lease["client_generation"],
            **{key: packet[key] for key in ("run_id", "host_generation", "cursor", "call_id", "input_hash")},
            "result": {"decision": decision, "model_state": {} if state is None else state} if result is None else result,
            "now_ms": 104, **overrides}
    return journal.submit(connection_id, **args)


def test_durable_response_retry_replays_without_another_external_call(connected):
    store, journal, _, _ = connected
    queued = queue(journal)
    packet = poll(connected)
    assert packet["call_id"] == queued["call_id"]
    assert packet["bootstrap"]["model_state"] is None
    first = submit(connected, packet, state={"n": 1})
    assert submit(connected, packet, state={"n": 1}) == first
    assert queue(journal) == first
    assert poll(connected) is None
    # A new SQLite owner, as used after a complete Host restart, reads the same
    # immutable call and does not ask the model to execute it again.
    second = ExternalConnectionRepository(store.path)
    second.open()
    try:
        restarted = ExternalCallJournal(second, journal.manifest)
        assert restarted.recorded("run_one", 1, host_generation=1) == first
    finally:
        second.close()


def test_changed_response_or_replay_input_is_rejected_without_overwriting_record(connected):
    _, journal, _, _ = connected
    queue(journal)
    packet = poll(connected)
    original = submit(connected, packet, state={"n": 1})
    with pytest.raises(StrategyProviderError, match="IDENTITY_MUTATION"):
        submit(connected, packet, state={"n": 2})
    with pytest.raises(StrategyProviderError, match="IDENTITY_MUTATION"):
        queue(journal, payload={"different": True})
    assert journal.recorded("run_one", 1, host_generation=1) == original


@pytest.mark.parametrize("change", [{"cursor": True}, {"cursor": 2}, {"run_id": "another"},
                                    {"host_generation": True}, {"host_generation": 2},
                                    {"client_generation": True}, {"call_id": "another"},
                                    {"input_hash": "sha256:other"}])
def test_wrong_call_or_generation_never_commits_to_current_call(connected, change):
    _, journal, _, _ = connected
    queue(journal)
    packet = poll(connected)
    with pytest.raises(StrategyProviderError):
        submit(connected, packet, **change)
    assert journal.recorded("run_one", 1, host_generation=1)["reply"] is None


def test_host_restart_fences_old_response_and_redelivers_pending_same_call(connected):
    _, journal, connection_id, _ = connected
    queue(journal)
    old = poll(connected)
    journal.start(connection_id, "run_one", host_generation=2, context={"dataset_id": "local_one"})
    with pytest.raises(StrategyProviderError, match="stale"):
        submit(connected, old)
    current = poll(connected)
    assert current["host_generation"] == 2
    assert current["call_id"] == old["call_id"] and current["input_hash"] == old["input_hash"]
    submit(connected, current)
    with pytest.raises(StrategyProviderError, match="stale"):
        journal.start(connection_id, "run_one", host_generation=1, context={"dataset_id": "local_one"})


def test_checkpoint_state_is_pinned_but_unpinned_intermediate_states_are_collected(connected):
    store, journal, _, _ = connected
    queue(journal)
    submit(connected, poll(connected), state={"n": 1})
    checkpoint = journal.snapshot("run_one", 1, host_generation=1)
    for cursor in range(2, 12):
        queue(journal, cursor, operation="onExecutionReport", payload={"fill_sequence": cursor})
        packet = poll(connected)
        assert packet["bootstrap"]["model_state"] == {"n": cursor - 1}
        submit(connected, packet, state={"n": cursor})
    with store._read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM external_provider_states").fetchone()[0] == 2
    assert journal.snapshot("run_one", 1, host_generation=1) == checkpoint
    assert journal.recorded("run_one", 5, host_generation=1)["reply"]["model_state_hash"]
    replay_checkpoint = journal.snapshot("run_one", 5, host_generation=1)
    assert replay_checkpoint["model_state_hash"] == journal.recorded("run_one", 5, host_generation=1)["reply"]["model_state_hash"]
    with store._read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM external_provider_states").fetchone()[0] == 2


def test_storage_limit_rolls_back_state_response_and_cursor_together(connected):
    store, journal, _, _ = connected
    queue(journal)
    packet = poll(connected)
    with store._read() as connection:
        used = connection.execute("SELECT logical_bytes FROM external_provider_usage").fetchone()[0]
    journal.max_record_bytes = used + 10
    with pytest.raises(StrategyProviderError, match="BUDGET_EXCEEDED"):
        submit(connected, packet, state={"model": "x" * 100})
    with store._read() as connection:
        assert connection.execute("SELECT logical_bytes FROM external_provider_usage").fetchone()[0] == used
        assert connection.execute("SELECT last_completed FROM external_provider_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM external_provider_states").fetchone()[0] == 0
    assert journal.recorded("run_one", 1, host_generation=1)["reply"] is None
    journal.max_record_bytes = 1_000_000
    submit(connected, packet)


def test_pending_calls_are_serial_and_runtime_identity_cannot_change(connected):
    _, journal, connection_id, _ = connected
    queue(journal)
    with pytest.raises(StrategyProviderError, match="serialized"):
        queue(journal, 2)
    with pytest.raises(StrategyProviderError, match="IDENTITY_MUTATION"):
        journal.start(connection_id, "run_one", host_generation=2, context={"dataset_id": "another"})
    other_manifest = parse_manifest(manifest(artifact_sha256="sha256:" + "b" * 64))
    with pytest.raises(StrategyProviderError, match="IDENTITY_MUTATION"):
        ExternalCallJournal(journal.store, other_manifest).recorded("run_one", 1, host_generation=1)


def test_credential_never_enters_persistent_reply_or_state(connected):
    store, journal, _, _ = connected
    queue(journal)
    result = submit(connected, poll(connected), state={"accidental_secret": TOKEN})
    assert result["reply"]["error"]["code"] == "PROVIDER_UNAUTHORIZED_WRITE"
    for path in store.path.parent.iterdir():
        assert TOKEN.encode() not in path.read_bytes()
    assert journal.recorded("run_one", 1, host_generation=1) == result


def test_authorized_invalid_output_fails_promptly_and_different_invalid_retry_is_rejected(connected):
    _, journal, _, _ = connected
    queue(journal, operation="step", payload={"observation": {"phase": "EVALUATION", "sequence": 7}})
    packet = poll(connected)
    invalid = {"sequence": 8, "kind": "TARGET_POSITION", "payload": {"targetExposure": "1"}}
    result = submit(connected, packet, decision=invalid)
    assert result["reply"]["error"]["code"] == "PROVIDER_PROTOCOL_VIOLATION"
    assert "model_state" not in result["reply"]
    assert submit(connected, packet, decision=invalid) == result
    with pytest.raises(StrategyProviderError, match="IDENTITY_MUTATION"):
        submit(connected, packet, decision={**invalid, "sequence": 9})
    assert poll(connected) is None


@pytest.mark.parametrize("operation,result", [("close", {"decision": None, "model_state": {}}),
    ("prepare", {"error": {"code": "PROVIDER_TIMEOUT", "message": "bounded model timeout"}})])
def test_closed_or_failed_session_does_not_accept_new_calls(connected, operation, result):
    _, journal, _, _ = connected
    queue(journal, operation=operation)
    packet = poll(connected)
    completed = submit(connected, packet, result=result)
    assert submit(connected, packet, result=result) == completed
    with pytest.raises(StrategyProviderError, match="serialized"):
        queue(journal, 2)
    assert poll(connected) is None


def test_revocation_fences_in_flight_response_and_host_reads(connected):
    store, journal, connection_id, _ = connected
    queue(journal)
    packet = poll(connected)
    store.revoke(connection_id, now_ms=104)
    with pytest.raises(StrategyProviderError):
        submit(connected, packet)
    with pytest.raises(StrategyProviderError):
        journal.recorded("run_one", 1, host_generation=1)
    with pytest.raises(StrategyProviderError):
        poll(connected)


@pytest.mark.parametrize("field,value", [("payload_json", '{"tampered":true}'), ("reply_json", '{"tampered":true}')])
def test_recorded_input_and_response_corruption_are_detected(connected, field, value):
    store, journal, _, _ = connected
    queue(journal)
    submit(connected, poll(connected))
    writer = sqlite3.connect(store.path)
    try:
        writer.execute(f"UPDATE external_provider_calls SET {field} = ?", (value,))
        writer.commit()
    finally:
        writer.close()
    with pytest.raises(StrategyProviderError, match="integrity"):
        journal.recorded("run_one", 1, host_generation=1)


def test_two_owners_accept_identical_response_once_and_share_committed_record(connected):
    store, journal, _, _ = connected
    queue(journal)
    packet = poll(connected)
    second = ExternalConnectionRepository(store.path)
    second.open()
    other = ExternalCallJournal(second, journal.manifest)
    second_context = (second, other, connected[2], connected[3])
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, context, packet, state={"n": 1})
                       for context in (connected, second_context)]
            assert futures[0].result() == futures[1].result()
        with store._read() as connection:
            assert connection.execute("SELECT last_completed FROM external_provider_sessions").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM external_provider_states").fetchone()[0] == 1
    finally:
        second.close()
