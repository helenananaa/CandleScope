"""New optional defaults must not invalidate old durable Workbench retries."""

import asyncio
from copy import deepcopy
import json
import sqlite3
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import NativePreparationPayload, router
from app.backtest.native_contracts import ExternalRunRequest
from app.backtest.native import NativeBacktests, digest
from app.backtest.errors import BacktestError
from app.data_preparation.models import PreparationRequest, Requirement
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService

ADDITIVE_FIELDS = {
    "account_model",
    "leverage",
    "funding_mode",
    "account_data",
    "execution_model_revision",
    "participation_rate",
    "bar_path_scenario",
}


def run_payload():
    return ExternalRunRequest.model_validate(
        {
            "execution_mode": "CANDLESCOPE",
            "language": "pine",
            "source": '//@version=6\nstrategy("Legacy")\nplot(close)',
            "dataset_id": "frozen-bars",
            "data_epoch": "epoch-old",
            "snapshot_hash": "sha256:frozen",
            "start_time_ms": 0,
            "end_time_ms": 179999,
            "interval": "1m",
            "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"},
        }
    ).model_dump(mode="json")


def legacy_run():
    return {
        key: value for key, value in run_payload().items() if key not in ADDITIVE_FIELDS
    }


def preparation(kind):
    if kind == "external":
        body = {"idempotency_key": "legacy-frozen-prepare", "run": run_payload()}
        legacy = {**body, "run": legacy_run()}
        return "/data-preparations/external-strategy", body, legacy
    body = {
        "idempotency_key": "legacy-automatic-prepare",
        "language": "pine",
        "source": run_payload()["source"],
        "execution": {"execution_fidelity": "TRADE_TAPE"},
        "context": {
            "exchange": "binance",
            "market_type": "futures",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "range_mode": "CUSTOM",
            "fidelity_preference": "FAST",
            "start_time_ms": 1700000040000,
            "end_time_ms": 1700000219999,
        },
    }
    legacy = NativePreparationPayload.model_validate(body).model_dump(mode="json")
    legacy.pop("chart_metadata")
    legacy.pop("currency_rates")
    legacy["execution"] = {
        key: value
        for key, value in legacy["execution"].items()
        if key in {"execution_fidelity", "host_settings", "fill_recalculation"}
    }
    return "/data-preparations/native-strategy", body, legacy


def retry_preparation(path, body, stored):
    prior = {
        "id": "durable-existing-job",
        "state": "READY",
        "request": {"intent": {"submission": stored}},
        "result": {"native_run": {"run_id": "existing-native-run"}},
    }
    original = deepcopy(prior)

    async def storage(operation, *args):
        return operation(*args)

    service = SimpleNamespace(
        repository=SimpleNamespace(by_idempotency=lambda key: prior), storage=storage
    )
    app = FastAPI()
    app.include_router(router)
    app.state.data_preparation_service = service

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(path, json=body)

    result = asyncio.run(call())
    assert prior == original
    return result, original


@pytest.mark.parametrize("kind", ["automatic", "external"])
def test_legacy_preparation_retry_returns_the_same_durable_job_after_new_defaults(kind):
    path, body, stored = preparation(kind)
    response, prior = retry_preparation(path, body, stored)
    assert response.status_code == 202, response.text
    assert response.json() == prior


@pytest.mark.parametrize("kind", ["automatic", "external"])
def test_real_source_change_still_conflicts_after_default_upgrade(kind):
    path, body, stored = preparation(kind)
    target = body["run"] if kind == "external" else body
    target["source"] += "\nplot(1)"
    response, _ = retry_preparation(path, body, stored)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("kind", ["automatic", "external"])
def test_reopened_preparation_database_keeps_original_job_and_fingerprint(
    tmp_path, kind
):
    path, body, stored = preparation(kind)
    database = tmp_path / "jobs.db"
    repository = PreparationRepository(database)
    request = PreparationRequest(
        idempotency_key=body["idempotency_key"],
        consumer="STRATEGY",
        requirements=[
            Requirement(
                exchange="binance",
                market_type="futures",
                symbol="BTCUSDT",
                start_ms=0,
                end_ms=60000,
            )
        ],
        intent={"submission": stored},
    )
    created = repository.create(request, 1)
    repository.update(
        created["id"],
        state="READY",
        stage="READY",
        result={"native_run": {"run_id": "original-run"}},
    )
    prior = repository.by_idempotency(body["idempotency_key"])
    reopened = PreparationRepository(database)

    def forbidden(*_):
        raise AssertionError("a retry must not acquire inputs or launch a second run")

    service = PreparationService(reopened, SimpleNamespace(validate=forbidden))
    app = FastAPI()
    app.include_router(router)
    app.state.data_preparation_service = service

    async def call():
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.post(path, json=body)
        finally:
            await service.shutdown()

    response = asyncio.run(call())
    assert response.status_code == 202, response.text
    assert response.json() == prior
    assert reopened.by_idempotency(body["idempotency_key"]) == prior
    with reopened.connect() as database:
        assert (
            database.execute(
                "SELECT fingerprint FROM preparation_jobs WHERE id=?", (prior["id"],)
            ).fetchone()[0]
            == request.identity()
        )


def native_existing(stored, *, stored_hash=None):
    native = NativeBacktests.__new__(NativeBacktests)
    native.runtime = SimpleNamespace(settings=SimpleNamespace(bar_effective=True))
    native.lock = threading.RLock()
    native.db = sqlite3.connect(":memory:")
    native.db.execute("CREATE TABLE runs (id TEXT, key TEXT, hash TEXT, record TEXT)")
    record = {
        "run_id": "existing-native-run",
        "state": "COMPLETED",
        "config": stored,
        "input_hash": "sha256:original-wire",
        "result": {"report_hash": "sha256:original-report"},
    }
    native.db.execute(
        "INSERT INTO runs VALUES (?,?,?,?)",
        (
            record["run_id"],
            "same-key",
            stored_hash or digest(stored),
            json.dumps(record),
        ),
    )
    return native, record


def test_legacy_native_retry_returns_original_record_without_resubmitting_or_rewriting_hash():
    native, record = native_existing(legacy_run())
    before = native.db.execute("SELECT * FROM runs").fetchall()
    try:
        assert native.create(run_payload(), "same-key") == record
        assert native.db.execute("SELECT * FROM runs").fetchall() == before
    finally:
        native.db.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_model", "LINEAR_PERP_ONE_WAY_V2"),
        ("leverage", 2),
        ("funding_mode", "HISTORICAL_REQUIRED"),
        (
            "account_data",
            {
                "symbol": "BTCUSDT",
                "events": [
                    {
                        "time_ms": 0,
                        "role": "MARK_INDEX",
                        "payload": {"mark_price": "10"},
                    }
                ],
            },
        ),
        ("execution_model_revision", "EXECUTION_REALISM_V2"),
        ("participation_rate", 0.5),
        ("bar_path_scenario", "OHLC_NEAREST_EXTREME_PATH_V2"),
    ],
)
def test_new_nondefault_host_settings_are_not_erased_by_legacy_retry_matching(
    field, value
):
    native, _ = native_existing(legacy_run())
    incoming = run_payload()
    incoming[field] = value
    try:
        with pytest.raises(BacktestError, match="IDEMPOTENCY_CONFLICT"):
            native.create(incoming, "same-key")
    finally:
        native.db.close()


def test_legacy_retry_cannot_alias_a_corrupt_stored_configuration_hash():
    native, _ = native_existing(legacy_run(), stored_hash="sha256:wrong")
    try:
        with pytest.raises(BacktestError, match="IDEMPOTENCY_CONFLICT"):
            native.create(run_payload(), "same-key")
    finally:
        native.db.close()


def test_existing_exact_payload_retry_keeps_its_record_and_native_mode_is_not_normalized():
    payload = run_payload()
    native, record = native_existing(payload)
    try:
        assert native.create(payload, "same-key") == record
        changed = {**payload, "execution_mode": "NATIVE"}
        with pytest.raises(BacktestError, match="IDEMPOTENCY_CONFLICT"):
            native.create(changed, "same-key")
    finally:
        native.db.close()


@pytest.mark.parametrize("before,after", [(1, 1.0), (True, 1)])
def test_default_aliases_do_not_coerce_strategy_parameter_types(before, after):
    stored = legacy_run()
    stored["parameters"] = {"argument": before}
    incoming = run_payload()
    incoming["parameters"] = {"argument": after}
    native, _ = native_existing(stored)
    try:
        with pytest.raises(BacktestError, match="IDEMPOTENCY_CONFLICT"):
            native.create(incoming, "same-key")
    finally:
        native.db.close()


def test_unknown_future_defaults_are_not_implicitly_aliased():
    native, _ = native_existing(legacy_run())
    incoming = run_payload()
    incoming["unreviewed_future_field"] = None
    try:
        with pytest.raises(BacktestError, match="IDEMPOTENCY_CONFLICT"):
            native.create(incoming, "same-key")
    finally:
        native.db.close()


def test_native_account_requests_keep_exact_identity_even_for_host_default_names():
    stored = {**legacy_run(), "execution_mode": "NATIVE"}
    native, _ = native_existing(stored)
    try:
        with pytest.raises(BacktestError, match="IDEMPOTENCY_CONFLICT"):
            native.create({**stored, "leverage": 1}, "same-key")
    finally:
        native.db.close()
