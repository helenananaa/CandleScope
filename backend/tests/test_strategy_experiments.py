"""ADR-BACKTEST-015 P5b: an experiment runs one strategy over several inputs, held by the backend."""
from __future__ import annotations

import asyncio

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.strategy_experiments import parse_create
from app.data_engine.data_manager.strategy import StrategyDataManager
from tests.test_strategy_drafts import _settings, service  # noqa: F401 - fixture


class FakePort:
    """The preparation and run services, as an experiment's members see them."""

    def __init__(self) -> None:
        self.preparations: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.submitted: list[tuple[str, str]] = []
        self.refuse: str | None = None
        self.listeners: dict[tuple[str, str], object] = {}

    def _refused(self) -> None:
        if self.refuse:
            code, self.refuse = self.refuse, None
            raise BacktestError(code, "refused")

    async def submit_preparation(self, body, idempotency_key):
        self.submitted.append(("preparation", idempotency_key))
        self._refused()
        job = {"id": f"job{len(self.preparations)}", "state": "QUEUED", "stage": "QUEUED", "completed": 0, "total": 3,
               "result": None, "error": None, "waiting": None}
        self.preparations[job["id"]] = job
        return job

    async def submit_run(self, body, idempotency_key):
        self.submitted.append(("run", idempotency_key))
        self._refused()
        run = {"run_id": f"bt_{len(self.runs)}", "state": "QUEUED", "failure_code": None}
        self.runs[run["run_id"]] = run
        return run

    async def preparation(self, job_id):
        return self.preparations.get(job_id)

    async def run(self, run_id):
        return self.runs.get(run_id)

    async def cancel_preparation(self, job_id):
        self.preparations[job_id]["state"] = "CANCELLED"

    async def cancel_run(self, run_id):
        self.runs[run_id]["state"] = "CANCELLED"

    def listen_preparation(self, job_id, wake):
        self.listeners[("preparation", job_id)] = wake
        return lambda: self.listeners.pop(("preparation", job_id), None)

    def listen_run(self, run_id, wake):
        self.listeners[("run", run_id)] = wake
        return lambda: self.listeners.pop(("run", run_id), None)

    def launch(self, job_id: str) -> str:
        """The preparation finished and started its run."""
        run_id = f"bt_launched_{job_id}"
        self.runs[run_id] = {"run_id": run_id, "state": "RUNNING", "failure_code": None}
        self.preparations[job_id].update(state="READY", completed=3, result={"strategy_run": {"run_id": run_id}})
        return run_id


def body(key="experiment-key-1", members=None):
    return {"idempotency_key": key, "name": "SMA Cross · 2 inputs", "strategy": {"draft_id": "draft-1", "language": "python"},
            "members": members if members is not None else [
                {"input": {"kind": "EXCHANGE_SERIES", "symbol": "BTCUSDT"}, "preparation": {"context": {"symbol": "BTCUSDT"}}},
                {"input": {"kind": "IMPORTED_DATASET", "datasetId": "local-1"}, "run": {"dataset_id": "local-1"}},
            ]}


def test_an_experiment_submits_each_member_once_and_a_repeat_returns_it(service):
    port = FakePort()
    experiments = StrategyDataManager(service).experiments()
    created = asyncio.run(experiments.create(body(), port))
    assert created["experiment_id"].startswith("ex_")
    assert [member["state"] for member in created["members"]] == ["PREPARING", "QUEUED"]
    assert created["state"] == "RUNNING" and created["counts"]["active"] == 2
    assert [kind for kind, _key in port.submitted] == ["preparation", "run"]
    again = asyncio.run(experiments.create(body(), port))
    assert again["experiment_id"] == created["experiment_id"] and len(port.submitted) == 2, "same key, same experiment, no resubmission"
    with pytest.raises(BacktestError) as conflict:
        asyncio.run(experiments.create({**body(), "name": "Other"}, port))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"


def test_member_states_come_from_their_preparation_and_run(service):
    port = FakePort()
    experiments = StrategyDataManager(service).experiments()
    experiment_id = asyncio.run(experiments.create(body(), port))["experiment_id"]
    port.preparations["job0"].update(state="RUNNING", completed=2)
    view = asyncio.run(experiments.view(experiment_id, port))
    assert view["members"][0]["preparation"]["completed"] == 2 and view["members"][0]["state"] == "PREPARING"
    launched = port.launch("job0")
    port.runs["bt_0"]["state"] = "COMPLETED"
    view = asyncio.run(experiments.view(experiment_id, port))
    assert (view["members"][0]["state"], view["members"][0]["run_id"]) == ("RUNNING", launched)
    for finishing in ("COMPLETING", "PAUSED", "CANCELLING"):
        port.runs[launched]["state"] = finishing
        assert asyncio.run(experiments.view(experiment_id, port))["members"][0]["state"] == "RUNNING", finishing
    port.runs[launched]["state"] = "COMPLETED"
    done = asyncio.run(experiments.view(experiment_id, port))
    assert (done["state"], done["terminal"], done["counts"]["completed"]) == ("COMPLETED", True, 2)
    port.runs[launched].update(state="FAILED", failure_code="STRATEGY_RUNTIME_ERROR")
    failed = asyncio.run(experiments.view(experiment_id, port))
    assert failed["state"] == "FAILED" and failed["members"][0]["error"]["code"] == "STRATEGY_RUNTIME_ERROR"


def test_a_refused_member_fails_alone_and_is_retried_as_a_new_attempt(service):
    port = FakePort()
    port.refuse = "RANGE_REQUIRED"
    experiments = StrategyDataManager(service).experiments()
    view = asyncio.run(experiments.create(body(), port))
    assert view["members"][0]["state"] == "FAILED" and view["members"][0]["error"]["code"] == "RANGE_REQUIRED"
    assert view["members"][1]["state"] == "QUEUED", "the other member is submitted regardless"
    with pytest.raises(BacktestError) as active:
        asyncio.run(experiments.retry(view["experiment_id"], 1, port))
    assert active.value.code == "EXPERIMENT_MEMBER_ACTIVE"
    retried = asyncio.run(experiments.retry(view["experiment_id"], 0, port))
    assert retried["members"][0]["state"] == "PREPARING" and retried["members"][0]["attempt"] == 1
    assert port.submitted[-1] == ("preparation", f"{view['experiment_id']}:0:1"), "a retry is a new submission"


def test_cancelling_stops_active_members_and_keeps_finished_ones(service):
    port = FakePort()
    experiments = StrategyDataManager(service).experiments()
    created = asyncio.run(experiments.create(body(), port))
    port.runs["bt_0"]["state"] = "COMPLETED"
    cancelled = asyncio.run(experiments.cancel(created["experiment_id"], port))
    assert [member["state"] for member in cancelled["members"]] == ["CANCELLED", "COMPLETED"]
    assert cancelled["state"] == "CANCELLED" and cancelled["terminal"] is True
    with pytest.raises(BacktestError) as refused:
        asyncio.run(experiments.retry(created["experiment_id"], 0, port))
    assert refused.value.code == "EXPERIMENT_CANCELLED"


def test_the_stream_reports_each_member_change_and_ends_when_none_is_active(service):
    port = FakePort()
    experiments = StrategyDataManager(service).experiments()

    async def watched():
        created = await experiments.create(body(members=[body()["members"][0]]), port)
        watch = await experiments.watch(created["experiment_id"], port)
        frames = []

        async def consume():
            async for frame in watch.events():
                frames.append(frame)
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        assert ("preparation", "job0") in port.listeners, "the stream follows the member's preparation"
        port.preparations["job0"].update(state="RUNNING", completed=1)
        port.listeners[("preparation", "job0")]()
        await asyncio.sleep(0.01)
        run_id = port.launch("job0")
        port.listeners[("preparation", "job0")]()
        await asyncio.sleep(0.01)
        assert ("run", run_id) in port.listeners, "and then the run it launched"
        port.runs[run_id]["state"] = "COMPLETED"
        port.listeners[("run", run_id)]()
        await asyncio.wait_for(task, 2)
        assert not port.listeners, "a finished stream releases its bridges"
        return frames

    frames = asyncio.run(watched())
    states = [frame["experiment"]["members"][0]["state"] for frame in frames if frame["type"] == "status"]
    assert states == ["PREPARING", "PREPARING", "RUNNING", "COMPLETED"]
    assert frames[-1]["terminal"] is True


def test_an_experiment_survives_a_full_restart(tmp_path):
    """#332: references and results are recoverable after quitting."""
    port = FakePort()
    first = BacktestService.start(_settings(tmp_path), now_ms=1)
    try:
        experiment_id = asyncio.run(StrategyDataManager(first).experiments().create(body(), port))["experiment_id"]
    finally:
        first.shutdown()
    second = BacktestService.start(_settings(tmp_path), now_ms=2)
    try:
        view = asyncio.run(StrategyDataManager(second).experiments().view(experiment_id, port))
        assert [member["input"]["kind"] for member in view["members"]] == ["EXCHANGE_SERIES", "IMPORTED_DATASET"]
        listed = asyncio.run(StrategyDataManager(second).experiments().list(port))
        assert [item["experiment_id"] for item in listed["experiments"]] == [experiment_id]
    finally:
        second.shutdown()


@pytest.mark.parametrize("change", [
    {"members": []},
    {"members": [{"input": {}, "preparation": {}, "run": {}}]},
    {"members": [{"input": {}, "run": {"idempotency_key": "chosen-by-client"}}]},
    {"members": [{"input": {}, "preparation": {}}] * 9},
    {"kind": "STUDY"},
    {"name": ""},
    {"idempotency_key": "short"},
    {"extra": 1},
])
def test_invalid_experiments_are_refused(change):
    with pytest.raises(BacktestError) as invalid:
        parse_create({**body(), **change})
    assert invalid.value.code == "EXPERIMENT_INVALID"


def test_preparation_jobs_wake_listeners_on_every_committed_change(tmp_path):
    from app.data_preparation.models import PreparationRequest, Requirement
    from app.data_preparation.repository import PreparationRepository

    repository = PreparationRepository(tmp_path / "preparation.sqlite3")
    request = PreparationRequest(idempotency_key="prep-key-1", consumer="STRATEGY", requirements=[Requirement(
        exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m", role="BARS", start_ms=0, end_ms=60_000)])
    job = repository.create(request, 1)
    wakes: list[str] = []
    release = repository.updates.listen_commits(job["id"], lambda: wakes.append("wake"))
    repository.update(job["id"], state="RUNNING", completed=1)
    repository.defer(job["id"], {"code": "RATE_LIMITED", "message": "later"})
    repository.cancel(job["id"])
    release()
    repository.update(job["id"], state="FAILED")
    assert wakes == ["wake", "wake", "wake"]


def test_the_frontend_contract_fixture_is_what_the_backend_serves(service):
    from tests import strategy_run_oracles as oracles

    port = FakePort()
    experiments = StrategyDataManager(service).experiments()
    experiments.clock_ms = lambda: 1_763_600_000_000
    members = [
        {"input": {"kind": "EXCHANGE_SERIES", "exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT",
                   "interval": "1m", "startMs": 1_763_596_800_000, "endMs": 1_763_640_000_000},
         "preparation": {"context": {"symbol": "BTCUSDT"}}},
        {"input": {"kind": "IMPORTED_DATASET", "datasetId": "local-1", "dataEpoch": "sha256:" + "a" * 64, "name": "BTC sample"},
         "run": {"dataset_id": "local-1"}},
        {"input": {"kind": "EXCHANGE_SERIES", "exchange": "okx", "marketType": "spot", "symbol": "ETH-USDT",
                   "interval": "1h", "startMs": 1_761_955_200_000, "endMs": 1_762_560_000_000},
         "preparation": {"context": {"symbol": "ETH-USDT"}}},
    ]
    created = asyncio.run(experiments.create(body(members=members), port))
    port.preparations["job0"].update(state="RUNNING", stage="FETCHING", completed=2,
                                     waiting={"reason": "RATE_LIMIT", "retry_at_ms": 1_763_600_030_000})
    port.runs["bt_0"]["state"] = "COMPLETED"
    port.preparations["job1"].update(state="FAILED", stage="FAILED",
                                     error={"code": "SOURCE_UNAVAILABLE", "message": "The exchange did not answer"})
    view = asyncio.run(experiments.view(created["experiment_id"], port))
    oracles.assert_frontend_fixture("running", {**view, "experiment_id": "ex_fixture"}, kind="strategy-experiment")
