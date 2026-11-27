"""External models in forward runs (B-333c).

A forward run restarted mid-way equals ``service.execute_bar_run`` of the same model's
decisions. Forward connections are scoped to a revision and market series; revocation
cancels the forward runs a connection served; the decision trace serves ``cs_`` run ids.
"""
import asyncio
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.external_providers import router
from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_controller import ContinuousStrategyController
from app.backtest.continuous_definition import prepare_definition
from app.backtest.continuous_provider import ContinuousProviderFactory, prepare_provider
from app.backtest.continuous_repair_plan import preview
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.backtest.external_provider.access import ExternalProviderAccess
from app.backtest.external_provider.journal import ExternalCallJournal
from app.backtest.external_provider.provider import ExternalDecisionProvider
from app.backtest.external_provider.repository import ExternalConnectionRepository
from app.backtest.identity import canonical_json
from app.backtest.models import ENGINE_VERSION
from app.backtest.service import BacktestService
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy_versions import continuous_material
from app.data_engine.data_manager.continuous_strategy import ForwardExternalRuns
from app.data_engine.data_manager.core import DataManagerCore
from tests.test_backtest_control_plane import _payload, _settings
from tests.test_continuous_bar_host import apply
from tests.test_continuous_definition import KEY
from tests.test_external_provider_contracts import manifest
from tests.test_strategy_bar_continuation import events

MARKET = {"exchange": "binance", "market_type": "usdm", "symbol": "BTCUSDT", "interval": "1m"}
OBSERVED = {"venue": "binance", "symbol": "BTCUSDT"}


def now():
    return int(time.time() * 1000)


class Model:
    """An outside client answering every active session on its connection, as the SDK client does."""

    def __init__(self, control, connection):
        self.store = ExternalConnectionRepository(control.store.path)
        self.store.open()
        self.connection_id = connection["connection_id"]
        self.journal = ExternalCallJournal(self.store, control.journal(self.connection_id).manifest)
        self.token = json.loads(Path(connection["connection_file"]).read_text())["token"]
        self.generation = control.store.connect(self.connection_id, token=self.token, client_id="model",
                                                now_ms=now())["client_generation"]
        self.calls = []
        self.stopped = threading.Event()
        self.failure = None
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=5)
        self.store.close()
        if self.failure is not None:
            raise self.failure

    def serve(self):
        try:
            while not self.stopped.is_set():
                packet = self.journal.poll(self.connection_id, token=self.token, client_id="model",
                                           client_generation=self.generation, now_ms=now())
                if packet is None:
                    self.stopped.wait(0.002)
                    continue
                self.calls.append((packet["run_id"], packet["operation"]))
                state = dict(packet["bootstrap"]["model_state"] or {"bars": 0})
                decision = None
                if packet["operation"] in ("warmup", "step"):
                    state["bars"] += 1
                if packet["operation"] == "step":
                    observation = packet["payload"]["observation"]
                    # Long above 104, flat otherwise: a function of the bars alone.
                    target = "1" if Decimal(observation["bar"]["close"]) > 104 else "0"
                    decision = {"sequence": observation["sequence"], "kind": "TARGET_POSITION",
                                "payload": {"targetExposure": target}}
                self.journal.submit(self.connection_id, token=self.token, client_id="model",
                                    client_generation=self.generation, now_ms=now(),
                                    **{key: packet[key] for key in ("run_id", "host_generation", "cursor", "call_id", "input_hash")},
                                    result={"decision": decision, "model_state": state})
        except BaseException as exc:  # noqa: BLE001 - surfaced by __exit__
            self.failure = exc


@pytest.fixture
def host_service(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED", "0")
    service = BacktestService.start(_settings(tmp_path, BACKTEST_EXTERNAL_PROVIDER_ENABLED="1"), now_ms=1)
    revision = service.create_strategy_revision({"name": "model", "language": "EXTERNAL_PROVIDER", "source_text": manifest()})
    try:
        yield service, str(revision["revision_id"])
    finally:
        service.shutdown()


def editor(revision_id, connection_id, **changes):
    return {"language": "external", "strategy_revision_id": revision_id, "external_connection_id": connection_id,
            "output_mode": "TARGET_POSITION", **changes}


def reference_run(service):
    row = service.create_run(_payload(parameters={"fast": 3, "slow": 5}, warmup_bars=3, taker_fee_bps="3", maker_fee_bps="1",
                                      account_model="LINEAR_PERP_ONE_WAY_V1", initial_balance="10000", **MARKET),
                             idempotency_key="reference", now_ms=2)
    config = json.loads(row["config_json"])
    configuration = {key: value for key, value in config.items() if key not in {"strategy_source", "output_mode", "parameters"}}
    return row, {**configuration, **MARKET}


def forward_definition(factory, revision_id, connection_id, configuration):
    provider = prepare_provider(editor(revision_id, connection_id))
    provider["external"] = factory.bind_external(provider, configuration, warmup_bars=3)
    return {"engine_version": ENGINE_VERSION, "language": "external", "provider": provider, "market": OBSERVED,
            "input_plan": {"roles": ["BARS"]}, "configuration": configuration}


def session(control, run_id):
    with control.store._read() as connection:
        return dict(connection.execute("SELECT host_generation, status FROM external_provider_sessions WHERE run_id = ?",
                                       (run_id,)).fetchone())


def test_forward_external_run_restarts_and_equals_the_fixed_host_run(host_service, tmp_path):
    service, revision_id = host_service
    control = service.external
    connection = control.create_forward(revision_id=revision_id, market=MARKET)
    row, configuration = reference_run(service)
    factory = ContinuousProviderFactory(external=control)
    store = ContinuousStrategyStore(tmp_path / "continuous.db")
    host = None
    with Model(control, connection) as model:
        try:
            definition = forward_definition(factory, revision_id, connection["connection_id"], configuration)
            ContinuousBarHost.create_run(store, "cs_external", definition=definition, mode="HISTORY_LIVE",
                                         data_revision="r1", event_time_ms=0, provider_factory=factory)
            # Creation interrupts the session; it never sends the model's terminal close.
            assert session(control, "cs_external") == {"host_generation": 1, "status": "INTERRUPTED"}
            host = ContinuousBarHost.resume(store, "cs_external", factory)
            assert session(control, "cs_external") == {"host_generation": 2, "status": "ACTIVE"}
            apply(host, events()[:11])
            host.close()
            store.close()
            store = ContinuousStrategyStore(tmp_path / "continuous.db")
            host = ContinuousBarHost.resume(store, "cs_external", factory)
            assert host.row["sequence"] == 11 and session(control, "cs_external")["host_generation"] == 3
            apply(host, events()[11:20])
            apply(host, events()[20:], caught_up=True)
            actual = asdict(host.kernel.run((), host._observe, finalize=True))
            reference_provider = ExternalDecisionProvider(control.journal(connection["connection_id"]),
                                                          connection_id=connection["connection_id"], host_generation=1,
                                                          step_timeout_s=2)
            reference = service.execute_bar_run(row["run_id"], events=events(), provider=reference_provider, now_ms=4,
                                                observation_market=OBSERVED)["result"]
            for key in ["decision_hash", "fill_hash", "ledger_hash", "fills", "ledger", "orders", "equity_curve"]:
                assert canonical_json(actual[key]) == canonical_json(reference[key]), key
            assert actual["fills"] and store.summary("cs_external")["sequence"] == 25
            # Restarts replay the recorded prepare reply; the model prepared this run once.
            forward_calls = [operation for run_id, operation in model.calls if run_id == "cs_external"]
            assert forward_calls.count("prepare") == 1 and "close" not in forward_calls
            assert forward_calls.count("step") == 22 and forward_calls.count("warmup") == 3
            # Forward checkpoints pin no model state: only the latest is retained.
            with control.store._read() as db:
                assert db.execute("SELECT count(*) FROM external_provider_states WHERE run_id = ? AND pinned = 1",
                                  ("cs_external",)).fetchone()[0] == 0
            trace = control.trace("cs_external", after=0, limit=500)
            assert trace["last_completed_cursor"] == len(forward_calls)
            assert sum(item["reply"].get("decision") is not None for item in trace["items"]) == 22
            assert continuous_material(definition)["language"] == "external"
        finally:
            if host is not None:
                host.close()
            store.close()


def test_forward_connections_bind_one_revision_and_market(host_service):
    service, revision_id = host_service
    control = service.external
    factory = ContinuousProviderFactory(external=control)
    forward = control.create_forward(revision_id=revision_id, market=MARKET)
    dataset = control.create(revision_id=revision_id, dataset_id="local_one", data_epoch="epoch", snapshot_hash="sha256:snapshot")
    assert forward["scope"]["forward_market"] == MARKET and "dataset_id" not in forward["scope"]
    configuration = {**MARKET, "account_model": "LINEAR_PERP_ONE_WAY_V1"}
    provider = prepare_provider(editor(revision_id, forward["connection_id"]))
    # The client connects before a forward run starts: its first call is the model's prepare.
    with pytest.raises(BacktestError, match="connect the external client"):
        factory.bind_external(provider, configuration, warmup_bars=3)
    control.store.connect(forward["connection_id"], token=json.loads(Path(forward["connection_file"]).read_text())["token"],
                          client_id="model", now_ms=now())
    assert set(factory.bind_external(provider, configuration, warmup_bars=3)) == {"external_scope_hash", "external_provider_identity"}
    for configured, match in [({**configuration, "symbol": "ETHUSDT"}, "different revision, dataset or market"),
                              ({**configuration, "interval": "5m"}, "different revision, dataset or market")]:
        with pytest.raises(BacktestError, match=match):
            factory.bind_external(provider, configured, warmup_bars=3)
    with pytest.raises(BacktestError, match="different revision, dataset or market"):
        factory.bind_external(prepare_provider(editor(revision_id, dataset["connection_id"])), configuration, warmup_bars=3)
    with pytest.raises(StrategyProviderError, match="different revision or dataset snapshot"):
        control.validate_binding({"strategy_revision_id": revision_id, "external_connection_id": forward["connection_id"],
                                  "dataset_id": "local_one", "data_epoch": "epoch", "snapshot_hash": "sha256:snapshot"})
    with pytest.raises(BacktestError, match="does not decide in this output mode"):
        factory.bind_external(prepare_provider(editor(revision_id, forward["connection_id"], output_mode="SIGNAL")),
                              configuration, warmup_bars=3)
    with pytest.raises(BacktestError, match="at least 3 warmup bars"):
        factory.bind_external(provider, configuration, warmup_bars=2)
    with pytest.raises(BacktestError, match="this Host's external connections"):
        ContinuousProviderFactory().bind_external(provider, configuration, warmup_bars=3)
    # A stored binding cannot change, and a revoked connection serves no new Host.
    definition = {"engine_version": ENGINE_VERSION, "language": "external", "market": OBSERVED, "input_plan": {"roles": ["BARS"]},
                  "configuration": configuration,
                  "provider": {**provider, "external": factory.bind_external(provider, configuration, warmup_bars=3)}}
    tampered = {**definition, "provider": {**definition["provider"],
                "external": {**definition["provider"]["external"], "external_scope_hash": "sha256:" + "0" * 64}}}
    with pytest.raises(BacktestError, match="IDENTITY_MUTATION"):
        factory(tampered)
    factory(definition).close()
    control.revoke(forward["connection_id"])
    with pytest.raises(BacktestError, match="external connection is unavailable"):
        factory(definition)


@pytest.mark.parametrize("payload,match", [
    ({"language": "external", "strategy_revision_id": "srv", "external_connection_id": "epc",
      "external": {"external_scope_hash": "x", "external_provider_identity": {}}}, "Unknown continuous provider fields"),
    ({"language": "external", "strategy_revision_id": "srv", "external_connection_id": "epc", "source_text": "x = 1"},
     "names no source"),
    ({"language": "external", "strategy_revision_id": "srv"}, "names its revision and forward connection"),
    ({"language": "python", "source_text": "", "runtime_mode": "SANDBOXED_LOCAL", "external_connection_id": "epc"},
     "require an external model"),
])
def test_editor_input_names_an_external_model_but_never_its_binding(payload, match):
    with pytest.raises(BacktestError, match=match):
        prepare_provider(payload)


@pytest.mark.parametrize("execution,follow,match", [
    ({}, True, "The chart follows builtin and Python strategies"),
    ({"signal_chart": {"transform": "heikin_ashi"}}, False, "without a signal chart"),
    ({"account_rules": "candlescope.practice-account/1"}, False, "without practice account rules"),
    ({"execution_model_revision": "candlescope.execution-realism/2"}, False, "without execution realism"),
])
def test_external_forward_runs_refuse_what_they_do_not_run(execution, follow, match):
    provider = editor("srv_model", "epc_" + "0" * 32)
    with pytest.raises(BacktestError, match=match):
        prepare_definition(provider, {"account_model": "LINEAR_PERP_ONE_WAY_V1", **execution}, KEY, warmup_bars=3,
                           follow=follow, bind_external=lambda *_args, **_kwargs: pytest.fail("bound before refusing"))
    with pytest.raises(BacktestError, match="this Host's external connections"):
        prepare_definition(provider, {"account_model": "LINEAR_PERP_ONE_WAY_V1"}, KEY, warmup_bars=3)


def test_definition_binds_the_connection_for_its_own_market(host_service):
    service, revision_id = host_service
    control = service.external
    market = {"exchange": KEY.exchange, "market_type": KEY.market_type, "symbol": KEY.symbol, "interval": KEY.interval}
    connection = control.create_forward(revision_id=revision_id, market=market)
    control.store.connect(connection["connection_id"], token=json.loads(Path(connection["connection_file"]).read_text())["token"],
                          client_id="model", now_ms=now())
    factory = ContinuousProviderFactory(external=control)
    definition = prepare_definition(editor(revision_id, connection["connection_id"]), {"account_model": "LINEAR_PERP_ONE_WAY_V1"},
                                    KEY, warmup_bars=3, bind_external=factory.bind_external)
    assert definition["language"] == "external" and definition["provider"]["source_text"] == ""
    assert definition["provider"]["external"]["external_provider_identity"] == control.manifest(revision_id).identity()


def test_repair_revocation_and_trace_for_forward_runs(host_service, tmp_path):
    service, revision_id = host_service
    control = service.external
    connection = control.create_forward(revision_id=revision_id, market=MARKET)
    _row, configuration = reference_run(service)
    factory = ContinuousProviderFactory(external=control)
    store = ContinuousStrategyStore(tmp_path / "continuous.db")
    try:
        with Model(control, connection):
            definition = forward_definition(factory, revision_id, connection["connection_id"], configuration)
            ContinuousBarHost.create_run(store, "cs_external", definition=definition, mode="LIVE_ONLY",
                                         data_revision="r1", event_time_ms=0, provider_factory=factory)
        summary = store.summary("cs_external")
        # Corrected bars cannot replay recorded decisions: repair is refused, by name.
        repair = store.stop("cs_external", generation=summary["generation"], revision=summary["revision"],
                            phase="REPAIR_REQUIRED", error={"code": "BAR_AMENDED", "message": "amended"})
        with pytest.raises(BacktestError, match="corrected history needs a new forward run"):
            preview(store, None, "cs_external", expected=store.results.identity(repair), resume_after=True, now_ms=now())

        # The trace serves forward run ids this profile holds.
        held = SimpleNamespace(require=store.summary, cancel_connection=lambda _id: ["cs_external"])
        access = ExternalProviderAccess(lambda: service, None, forward_runs=held)
        assert access.trace("cs_external", after=0, limit=10)["run_id"] == "cs_external"
        with pytest.raises(BacktestError, match="CONTINUOUS_RUN_NOT_FOUND"):
            access.trace("cs_unknown", after=0, limit=10)
        with pytest.raises(BacktestError, match="CONTINUOUS_NOT_READY"):
            ExternalProviderAccess(lambda: service, None).trace("cs_external", after=0, limit=10)

        # Revocation cancels the forward runs the connection served, after revoking it.
        assert store.external_connection_runs(connection["connection_id"]) == ["cs_external"]
        order = []

        def cancel_connection(connection_id):
            assert control.waiting_reason(connection_id) == "EXTERNAL_CONNECTION_REVOKED"
            order.append(connection_id)
            return asyncio.run(ContinuousStrategyController.cancel_external(controller, connection_id))

        async def cancel(run_id):
            current = store.summary(run_id)
            return store.stop(run_id, generation=current["generation"], revision=current["revision"], phase="CANCELLED")

        controller = SimpleNamespace(_ready=lambda: None, store=store, runtime=SimpleNamespace(cancel=cancel))
        revoked = ExternalProviderAccess(lambda: service, None, forward_runs=SimpleNamespace(
            require=store.summary, cancel_connection=cancel_connection)).revoke(connection["connection_id"])
        assert revoked == {"connection_id": connection["connection_id"], "revoked": True,
                           "cancelled_forward_runs": ["cs_external"]}
        assert order == [connection["connection_id"]] and store.summary("cs_external")["phase"] == "CANCELLED"
        assert store.external_connection_runs(connection["connection_id"]) == []
    finally:
        store.close()


def test_profile_forward_runs_cancel_on_the_controller_loop(tmp_path):
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    seen = []

    async def cancel_external(connection_id):
        seen.append((connection_id, asyncio.get_running_loop() is loop))
        return ["cs_one"]

    store = ContinuousStrategyStore(tmp_path / "continuous.db")
    try:
        owner = SimpleNamespace(continuous=None)
        runs = ForwardExternalRuns(owner)
        assert runs.cancel_connection("epc_x") == []
        with pytest.raises(BacktestError, match="CONTINUOUS_NOT_READY"):
            runs.require("cs_one")
        owner.continuous = SimpleNamespace(closed=False, loop=loop, store=store, cancel_external=cancel_external)
        assert runs.cancel_connection("epc_x") == ["cs_one"] and seen == [("epc_x", True)]
        with pytest.raises(BacktestError, match="CONTINUOUS_RUN_NOT_FOUND"):
            runs.require("cs_one")
    finally:
        store.close()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


def test_forward_connection_route_and_capabilities(host_service, tmp_path):
    service, revision_id = host_service
    app = FastAPI()
    app.include_router(router)
    app.state.backtest_service = service
    app.state.data_manager_core = DataManagerCore()
    app.state.data_manager_core.bind_strategy(service)

    async def request():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post("/provider-connections/forward", json={"strategy_revision_id": revision_id, **MARKET})
            # No forward owner is started in this profile, so its run ids have no trace yet.
            trace = await client.get("/provider-connections/runs/cs_unknown/trace")
            return created, trace

    created, trace = asyncio.run(request())
    assert created.status_code == 200 and created.json()["scope"]["forward_market"] == MARKET
    assert trace.json()["error"]["code"] == "CONTINUOUS_NOT_READY"
