from __future__ import annotations

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.backtest.external_provider.repository import ExternalConnectionRepository
from app.backtest.strategy.protocol import StrategyProviderError

TOKEN = "local-test-external-connection-credential"
SCOPE = {"strategy_revision_id": "srv_model", "dataset_id": "local_one", "data_epoch": "epoch_one"}


@pytest.fixture
def store(tmp_path):
    repository = ExternalConnectionRepository(tmp_path / "external" / "connections.sqlite3")
    assert not repository.path.exists()
    repository.open()
    try:
        yield repository
    finally:
        repository.close()


def create(store):
    return store.create(dict(SCOPE), token=TOKEN, now_ms=100)


def test_plaintext_credential_is_not_persisted_or_returned(store) -> None:
    connection_id = create(store)
    lease = store.connect(connection_id, token=TOKEN, client_id="first", now_ms=101)
    assert "token" not in lease and "token_hash" not in lease
    for path in store.path.parent.iterdir():
        assert TOKEN.encode() not in path.read_bytes()
    with pytest.raises(StrategyProviderError) as failure:
        store.connect(connection_id, token="wrong-test-credential-value", client_id="other", now_ms=102)
    assert "wrong-test-credential-value" not in str(failure.value)


def test_connection_scope_remains_frozen_when_a_caller_mutates_its_copy(store) -> None:
    scope = dict(SCOPE)
    connection_id = store.create(scope, token=TOKEN, now_ms=100)
    scope["dataset_id"] = "another_dataset"
    detached = store.scope(connection_id)
    detached["data_epoch"] = "another_epoch"
    assert store.scope(connection_id) == SCOPE


def test_retry_is_idempotent_and_another_active_client_cannot_preempt(store) -> None:
    connection_id = create(store)
    first = store.connect(connection_id, token=TOKEN, client_id="first", now_ms=101)
    retry = store.connect(connection_id, token=TOKEN, client_id="first", now_ms=102)
    assert first["client_generation"] == retry["client_generation"]
    with pytest.raises(StrategyProviderError, match="another external client"):
        store.connect(connection_id, token=TOKEN, client_id="second", now_ms=103)
    assert store.ready(connection_id, now_ms=103)


def test_expired_or_reset_lease_requires_a_new_generation(store) -> None:
    connection_id = create(store)
    first = store.connect(connection_id, token=TOKEN, client_id="first", now_ms=101)
    deadline = int(first["lease_deadline_ms"])
    assert not store.ready(connection_id, now_ms=deadline)
    next_lease = store.connect(connection_id, token=TOKEN, client_id="second", now_ms=deadline)
    assert next_lease["client_generation"] > first["client_generation"]
    store.reset_client_leases()
    assert not store.ready(connection_id, now_ms=deadline + 1)
    restarted = store.connect(connection_id, token=TOKEN, client_id="second", now_ms=deadline + 2)
    assert restarted["client_generation"] > next_lease["client_generation"]
    with pytest.raises(StrategyProviderError, match="stale"):
        store.touch(connection_id, token=TOKEN, client_id="second",
                    client_generation=int(next_lease["client_generation"]), now_ms=deadline + 3)


def test_boolean_cannot_impersonate_generation_one(store) -> None:
    connection_id = create(store)
    store.connect(connection_id, token=TOKEN, client_id="first", now_ms=101)
    with pytest.raises(StrategyProviderError, match="stale"):
        store.touch(connection_id, token=TOKEN, client_id="first", client_generation=True, now_ms=102)


def test_revocation_is_final_and_connection_ceiling_is_enforced(tmp_path) -> None:
    store = ExternalConnectionRepository(tmp_path / "connections.sqlite3", max_connections=1)
    store.open()
    try:
        connection_id = create(store)
        with pytest.raises(StrategyProviderError, match="ceiling"):
            create(store)
        store.revoke(connection_id, now_ms=102)
        store.revoke(connection_id, now_ms=103)
        with pytest.raises(StrategyProviderError, match="credentials are invalid"):
            store.connect(connection_id, token=TOKEN, client_id="first", now_ms=104)
        assert not store.ready(connection_id, now_ms=104)
        assert create(store) != connection_id
    finally:
        store.close()


def test_two_sqlite_owners_racing_for_one_connection_have_one_winner(store) -> None:
    connection_id = create(store)
    second = ExternalConnectionRepository(store.path)
    second.open()
    barrier = threading.Barrier(2)

    def claim(repository, client_id):
        barrier.wait()
        try:
            repository.connect(connection_id, token=TOKEN, client_id=client_id, now_ms=101)
            return "owner"
        except StrategyProviderError:
            return "rejected"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, repository, client_id)
                       for repository, client_id in ((store, "first"), (second, "second"))]
            assert sorted(f.result() for f in futures) == ["owner", "rejected"]
    finally:
        second.close()


def test_status_reads_do_not_compete_for_sqlite_writer_ownership(store) -> None:
    connection_id = create(store)
    store.connect(connection_id, token=TOKEN, client_id="first", now_ms=101)
    writer = sqlite3.connect(store.path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        assert store.ready(connection_id, now_ms=102)
        assert store.scope(connection_id) == SCOPE
    finally:
        writer.rollback()
        writer.close()


def test_future_store_version_fails_without_modifying_its_database(tmp_path) -> None:
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE external_provider_meta(singleton INTEGER, schema_version INTEGER)")
    connection.execute("INSERT INTO external_provider_meta VALUES(1, 99)")
    connection.commit()
    connection.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    store = ExternalConnectionRepository(path)
    with pytest.raises(StrategyProviderError, match="unsupported external connection store"):
        store.open()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
