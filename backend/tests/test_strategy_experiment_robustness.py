"""ADR-BACKTEST-015 P5c3: robustness as an experiment rule, over a Study V2 that runs Python strategies."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.backtest.errors import BacktestError
from app.backtest.strategy_experiments import STUDY_PROTOCOL, parse_create, robustness_view, study_members
from app.data_engine.data_manager.strategy import StrategyDataManager
from tests.test_python_editor import SOURCE, service_at
from tests.test_strategy_drafts import _settings, service  # noqa: F401 - fixture

DAY = 86_400_000
TRUSTED = {"Origin": "http://127.0.0.1:15173"}
# The chart's Python SMA template, with its fast length as a parameter the study varies.
PARAMETERISED = SOURCE.replace("self.fast = 3", 'self.fast = int(context.parameters.get("fast", 3))')


def _fold(ordinal, trials, *, test_run_id=None, selected=None, state="TRAINING"):
    start = (ordinal - 1) * 40 * DAY
    return {"ordinal": ordinal, "state": state, "train_start_ms": start, "train_end_ms": start + 110 * DAY,
            "test_start_ms": start + 110 * DAY, "test_end_ms": start + 150 * DAY, "test_run_id": test_run_id,
            "selection_receipt": None if selected is None else {"selected": {"params": selected}},
            "train_trials": [{"candidate_ordinal": index, "params_json": json.dumps({"fast": fast}), "run_id": run_id,
                              "state": "PLANNED" if run_id is None else "QUEUED"}
                             for index, (fast, run_id) in enumerate(trials, 1)]}


def _study(state="RUNNING", folds=None, holdout=None, failure=None):
    config = {"hypothesis": "fast SMA survives OOS", "objective": "NET_RETURN", "sampler": "grid", "candidate_budget": 2,
              "parameter_space": {"fast": [2, 3]}, "start_ms": 0, "end_ms": 200 * DAY}
    return {"study_id": "st_1", "state": state, "config_json": json.dumps(config), "folds": folds or [],
            "holdout": holdout, "oos_report": None, "failure": failure}


def _run(state, failure_code=None):
    return {"state": state, "failure_code": failure_code}


def test_a_study_is_shown_as_its_planned_runs_in_order():
    study = _study(folds=[_fold(1, [(2, "bt_a"), (3, "bt_b")], test_run_id="bt_t", selected={"fast": 3}),
                          _fold(2, [(2, "bt_c"), (3, None)])],
                   holdout={"state": "SEALED", "start_ms": 190 * DAY, "end_ms": 200 * DAY, "params_json": None, "run_id": None})
    runs = {"bt_a": _run("COMPLETED"), "bt_b": _run("COMPLETED"), "bt_t": _run("RUNNING"), "bt_c": _run("FAILED", "PROVIDER_ERROR")}
    members = study_members(study, runs)
    assert [(m["input"]["role"], m["input"].get("fold"), m["input"]["parameters"], m["state"]) for m in members] == [
        ("TRAIN", 1, {"fast": 2}, "COMPLETED"), ("TRAIN", 1, {"fast": 3}, "COMPLETED"), ("TEST", 1, {"fast": 3}, "RUNNING"),
        ("TRAIN", 2, {"fast": 2}, "FAILED"), ("TRAIN", 2, {"fast": 3}, "PENDING"), ("TEST", 2, None, "PENDING"),
        ("HOLDOUT", None, None, "PENDING")]
    assert [m["ordinal"] for m in members] == list(range(7))
    assert members[3]["error"] == {"code": "PROVIDER_ERROR", "message": "the run ended failed"}
    assert (members[2]["input"]["start_ms"], members[2]["input"]["end_ms"]) == (110 * DAY, 150 * DAY)
    row = {"experiment_id": "ex_1", "name": "SMA", "kind": "ROBUSTNESS", "strategy_json": "{}", "created_at_ms": 1,
           "cancelled_at_ms": None, "study_id": "st_1"}
    view = robustness_view(row, study, runs)
    assert (view["state"], view["terminal"], view["counts"]["active"], view["counts"]["total"]) == ("RUNNING", False, 4, 7)
    assert view["study"]["folds"][0]["selected"] == {"fast": 3} and view["study"]["holdout"]["state"] == "SEALED"


def test_a_waiting_or_stopped_study_has_no_active_runs():
    row = {"experiment_id": "ex_1", "name": "SMA", "kind": "ROBUSTNESS", "strategy_json": "{}", "created_at_ms": 1,
           "cancelled_at_ms": None, "study_id": "st_1"}
    holdout = {"state": "SEALED", "start_ms": 190 * DAY, "end_ms": 200 * DAY, "params_json": None, "run_id": None}
    waiting = robustness_view(row, _study("AWAITING_HOLDOUT", [_fold(1, [(2, "bt_a")], test_run_id="bt_t", selected={"fast": 2})],
                                          holdout), {"bt_a": _run("COMPLETED"), "bt_t": _run("COMPLETED")})
    assert (waiting["state"], waiting["terminal"], waiting["counts"]["active"]) == ("AWAITING_HOLDOUT", True, 0)
    failure = {"code": "SANDBOX_UNAVAILABLE", "message": "no sandbox", "failed_at_ms": 5}
    failed = robustness_view(row, _study("FAILED", [_fold(1, [(2, None)])], failure=failure), {})
    assert [m["state"] for m in failed["members"]] == ["CANCELLED", "CANCELLED"], "runs a stopped study never made"
    assert failed["study"]["error"] == failure and failed["state"] == "FAILED"
    gone = robustness_view(row, None, {})
    assert gone["state"] == "FAILED" and gone["study"]["error"]["code"] == "STUDY_NOT_FOUND"


class StudyPort:
    """The study service as a robustness experiment sees it."""

    def __init__(self, repository) -> None:
        self.repository = repository  # holds a row for each study, as the study service would
        self.studies: dict[str, dict] = {}
        self.calls: list[str] = []
        self.refuse: dict[str, str] = {}
        self.listeners: dict[tuple[str, str], object] = {}
        self.runs: dict[str, dict] = {}

    def _refused(self, step):
        if step in self.refuse:
            raise BacktestError(self.refuse.pop(step), "refused")

    async def create_study(self, body):
        self.calls.append(f"create {body['name']} {body['study_protocol_revision']} {body['hypothesis']}")
        self._refused("create")
        study_id = f"st_{len(self.studies)}"
        self.repository.insert_study({"study_id": study_id, "name": body["name"], "hypothesis": body["hypothesis"],
                                      "strategy_revision_id": "srv2_x", "config_json": "{}", "config_hash": "sha256:x",
                                      "state": "CREATED", "created_at_ms": 1})
        self.studies[study_id] = _study("CREATED")
        self.studies[study_id]["study_id"] = study_id
        return self.studies[study_id]

    async def start_study(self, study_id):
        self.calls.append(f"start {study_id}")
        self._refused("start")
        self.studies[study_id].update(state="RUNNING", folds=[_fold(1, [(2, None), (3, None)])])

    async def study(self, study_id):
        return self.studies.get(study_id)

    async def cancel_study(self, study_id):
        self.calls.append(f"cancel {study_id}")
        self.studies[study_id]["state"] = "CANCELLED"

    async def reveal_holdout(self, study_id):
        self.calls.append(f"reveal {study_id}")
        self.studies[study_id]["state"] = "RUNNING"

    async def run(self, run_id):
        return self.runs.get(run_id)

    def listen_study(self, study_id, wake):
        self.listeners[("study", study_id)] = wake
        return lambda: self.listeners.pop(("study", study_id), None)

    def listen_run(self, run_id, wake):
        self.listeners[("run", run_id)] = wake
        return lambda: self.listeners.pop(("run", run_id), None)


def robustness(key="robust-key-1", **study):
    return {"idempotency_key": key, "name": "SMA · robustness", "kind": "ROBUSTNESS",
            "strategy": {"draft_id": "draft-1", "language": "python"},
            "study": {"hypothesis": "fast SMA survives OOS", "strategy_revision_id": "srv2_x", **study}}


def test_an_experiment_creates_and_starts_its_study_once(service):
    port = StudyPort(service.repository)
    experiments = StrategyDataManager(service).experiments()
    created = asyncio.run(experiments.create(robustness(), port))
    assert port.calls == [f"create SMA · robustness {STUDY_PROTOCOL} fast SMA survives OOS", "start st_0"]
    assert (created["kind"], created["state"], created["study"]["study_id"], created["counts"]["total"]) == (
        "ROBUSTNESS", "RUNNING", "st_0", 3)
    again = asyncio.run(experiments.create(robustness(), port))
    assert again["experiment_id"] == created["experiment_id"] and len(port.studies) == 1, "the same key is the same study"
    with pytest.raises(BacktestError) as conflict:
        asyncio.run(experiments.create(robustness(seed=2), port))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    listed = asyncio.run(experiments.list(port))["experiments"]
    assert [item["experiment_id"] for item in listed] == [created["experiment_id"]]


def test_a_refused_study_or_start_leaves_no_experiment(service):
    port = StudyPort(service.repository)
    experiments = StrategyDataManager(service).experiments()
    port.refuse["create"] = "STUDY_SPLIT_LEAK"
    with pytest.raises(BacktestError, match="refused"):
        asyncio.run(experiments.create(robustness("robust-key-2"), port))
    port.refuse["start"] = "BUDGET_EXCEEDED"
    with pytest.raises(BacktestError, match="refused"):
        asyncio.run(experiments.create(robustness("robust-key-3"), port))
    assert port.calls[-1] == "cancel st_0", "a study that could not start is not left behind"
    assert asyncio.run(experiments.list(port))["experiments"] == []


def test_cancel_reveal_and_retry_act_on_the_study(service):
    port = StudyPort(service.repository)
    experiments = StrategyDataManager(service).experiments()
    created = asyncio.run(experiments.create(robustness(), port))
    experiment_id = created["experiment_id"]
    port.studies["st_0"]["state"] = "AWAITING_HOLDOUT"
    revealed = asyncio.run(experiments.reveal_holdout(experiment_id, port))
    assert port.calls[-1] == "reveal st_0" and revealed["state"] == "RUNNING"
    with pytest.raises(BacktestError) as retry:
        asyncio.run(experiments.retry(experiment_id, 0, port))
    assert retry.value.code == "EXPERIMENT_RULE_UNSUPPORTED"
    cancelled = asyncio.run(experiments.cancel(experiment_id, port))
    assert port.calls[-1] == "cancel st_0" and cancelled["state"] == "CANCELLED"
    assert [member["state"] for member in cancelled["members"]] == ["CANCELLED"] * 3


def test_the_stream_follows_the_study(service):
    port = StudyPort(service.repository)
    experiments = StrategyDataManager(service).experiments()

    async def watched():
        created = await experiments.create(robustness(), port)
        watch = await experiments.watch(created["experiment_id"], port)
        frames = []

        async def consume():
            async for frame in watch.events():
                frames.append(frame)
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        assert ("study", "st_0") in port.listeners, "the stream follows the study's own changes"
        port.studies["st_0"]["state"] = "COMPLETED"
        port.listeners[("study", "st_0")]()
        await asyncio.wait_for(task, 2)
        assert not port.listeners
        return frames

    frames = asyncio.run(watched())
    assert [frame["experiment"]["state"] for frame in frames if frame["type"] == "status"] == ["RUNNING", "COMPLETED"]


def test_the_frontend_contract_fixture_is_what_the_backend_serves(service):
    from tests import strategy_run_oracles as oracles

    port = StudyPort(service.repository)
    experiments = StrategyDataManager(service).experiments()
    experiments.clock_ms = lambda: 1_763_600_000_000
    created = asyncio.run(experiments.create(robustness(), port))
    port.runs.update({run_id: _run("COMPLETED") for run_id in ("bt_a", "bt_b", "bt_t", "bt_c", "bt_d", "bt_u")})
    study = port.studies["st_0"]
    study.update(state="AWAITING_HOLDOUT", folds=[
        _fold(1, [(2, "bt_a"), (3, "bt_b")], test_run_id="bt_t", selected={"fast": 3}, state="COMPLETED"),
        _fold(2, [(2, "bt_c"), (3, "bt_d")], test_run_id="bt_u", selected={"fast": 3}, state="COMPLETED")],
        holdout={"state": "SEALED", "start_ms": 190 * DAY, "end_ms": 200 * DAY, "params_json": None, "run_id": None},
        oos_report={"summary": {"fold_count": 2, "initial_equity": "1", "final_equity": "1.042", "total_return": "0.042"},
                    "folds": [{"ordinal": 1, "selected_params": {"fast": 3}, "test_run_id": "bt_t", "train_objective": "0.08",
                               "test_objective": "0.03", "train_test_gap": "0.05", "benchmark_return": "0.01"},
                              {"ordinal": 2, "selected_params": {"fast": 3}, "test_run_id": "bt_u", "train_objective": "0.06",
                               "test_objective": "0.012", "train_test_gap": "0.048", "benchmark_return": "-0.02"}],
                    "robustness": {"selection_bias_warning": "MULTIPLE_TRIALS_REQUIRE_HUMAN_REVIEW",
                                   "trade_order_bootstrap": {"samples": 200, "p05": "-0.01", "p50": "0.04", "p95": "0.09"}},
                    "equity": [{"event_time_ms": 1, "equity": "1"}]})
    view = asyncio.run(experiments.view(created["experiment_id"], port))
    assert "equity" not in view["study"]["oos"], "the equity curve stays with the test runs"
    oracles.assert_frontend_fixture("robustness", {**view, "experiment_id": "ex_fixture"}, kind="strategy-experiment")


@pytest.mark.parametrize("change", [
    {"members": []},
    {"study": {"hypothesis": "h", "name": "x"}},
    {"study": {"hypothesis": "h", "study_protocol_revision": "LEGACY_STUDY_V1"}},
    {"study": "not an object"},
])
def test_invalid_robustness_experiments_are_refused(change):
    with pytest.raises(BacktestError) as invalid:
        parse_create({**robustness(), **change})
    assert invalid.value.code == "EXPERIMENT_INVALID"
    with pytest.raises(BacktestError):
        parse_create({"idempotency_key": "inputs-key", "name": "x", "strategy": {}, "members": [], "study": {}})


def _study_v2(revision_id, **extra):
    return {"name": "SMA", "hypothesis": "fast SMA survives OOS", "study_protocol_revision": STUDY_PROTOCOL,
            "strategy_revision_id": revision_id, "dataset_id": "local-x", "data_epoch": "epoch-x",
            "dataset_snapshot_hash": "sha256:" + "1" * 64, "interval": "1d", "start_ms": 0, "end_ms": 200 * DAY,
            "train_ms": 110 * DAY, "test_ms": 40 * DAY, "step_ms": 40 * DAY, "parameter_space": {"fast": [2, 3]},
            "sampler": "grid", "candidate_budget": 2, "objective": "NET_RETURN", **extra}


def test_study_v2_runs_a_python_strategy_in_the_runtime_its_caller_may_use(tmp_path):
    settings = {"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1", "BACKTEST_STUDY_ENABLED": "1"}
    from app.backtest.service import BacktestService
    from app.core.config import load_backtest_settings
    service = BacktestService.start(load_backtest_settings(
        settings, data_dir=tmp_path, klines_db_path=tmp_path / "market.db", replay_db_path=tmp_path / "replay.db",
    ), enforce_registered_revisions=True)
    try:
        revision = service.create_strategy_revision({"name": "SMA", "language": "PYTHON_EDITOR", "source_text": PARAMETERISED,
                                                     "parameter_schema": []})["revision_id"]
        trusted = {"python_runtime_mode": "TRUSTED_LOCAL", "python_trusted_confirmed": True}

        def config(**kwargs):
            return json.loads(service.create_study(_study_v2(revision, **trusted), **kwargs)["config_json"])
        frozen = config(trusted=True)
        assert (frozen["python_runtime_mode"], frozen["python_trusted_confirmed"], frozen["output_mode"]) == (
            "TRUSTED_LOCAL", True, "SIGNAL")
        assert config()["python_runtime_mode"] == "SANDBOXED_LOCAL", "an untrusted origin cannot ask for local Python"
        with pytest.raises(BacktestError) as unconfirmed:
            service.create_study(_study_v2(revision, python_runtime_mode="TRUSTED_LOCAL"), trusted=True)
        assert unconfirmed.value.code == "PYTHON_TRUST_REQUIRED"
        builtin = json.loads(service.create_study(_study_v2("builtin-rsi-wilder-long-short-v1", parameter_space={
            "length": [20, 24]}, parameters={"trigger_mode": "LEVEL_TARGET_V1"}, **trusted), trusted=True)["config_json"])
        assert "python_runtime_mode" not in builtin, "a builtin study has no Python runtime"
        template = service.create_strategy_revision({"name": "RSI", "language": "BUILTIN_TEMPLATE", "source_text": "",
                                                     "parameter_schema": []})["revision_id"]
        with pytest.raises(BacktestError) as refused:
            service.create_study(_study_v2(template), trusted=True)
        assert refused.value.code == "SCHEMA_UNKNOWN_FIELD", "other saved revisions keep the registry rule"
        service.archive_strategy_revision(revision)
        with pytest.raises(BacktestError) as archived:
            service.create_study(_study_v2(revision, **trusted), trusted=True)
        assert archived.value.code == "IDENTITY_MUTATION"
    finally:
        service.shutdown()


def _contract_dataset(tmp_path, rows):
    """Daily bars with historical contract data (Study V2 runs LINEAR_PERP_ONE_WAY_V2), rising and falling."""
    from app.local_data.service import LocalDatasetService, LocalImportOptions
    start = 1_704_067_200_000

    def price(index):
        phase = index % 40
        return 130 - 3 * phase if phase < 20 else 70 + 3 * (phase - 20)
    previous, lines = price(0), []
    for index in range(rows):
        close = price(index)
        lines.append(f"{start + index * DAY},{previous},{max(previous, close) + 2},{min(previous, close) - 2},{close},100")
        previous = close
    csv = tmp_path / "bars.csv"
    csv.write_text("time,open,high,low,close,volume\n" + "\n".join(lines), encoding="utf-8")
    local = LocalDatasetService(tmp_path / "local")
    original = local.import_csv(csv, LocalImportOptions(name="robust", symbol="BTCUSDT", interval="1d", timestamp_unit="ms"))
    provenance = {"provider": "P5C3_FIXTURE", "source_url": "https://example.invalid/p5c3", "capture_receipt": "p5c3"}
    contract = {"schema_version": "candlescope.contract-history.v1",
                "identity": {"venue": "binance", "market_type": "usdm", "symbol": "BTCUSDT"}, "roles": {
        "MARK_INDEX": {"cadence_ms": DAY, "retention_policy": "test_local_immutable", "provenance": provenance, "records": [
            {"event_time_ms": start + i * DAY, "mark_price": str(price(i)), "index_price": str(price(i))} for i in range(rows)]},
        "FUNDING": {"period_ms": DAY, "retention_policy": "test_local_immutable", "provenance": provenance, "records": [
            {"settlement_time_ms": start + i * DAY, "period_id": f"p-{i}", "funding_rate": "0",
             "mark_price": str(price(min(i, rows - 1)))} for i in range(1, rows + 1)]},
        "INSTRUMENT_RULES": {"retention_policy": "test_local_immutable", "provenance": provenance, "records": [
            {"effective_from_ms": start, "effective_to_ms": start + rows * DAY - 1, "rule_version": "r1",
             "contract_multiplier": "1", "price_tick": "0.1", "quantity_step": "0.001", "min_quantity": "0.001",
             "max_quantity": "1000", "min_notional": "5", "maintenance_tiers": [{"notional_floor": "0",
             "notional_cap": "1000000", "maintenance_rate": "0.005", "maintenance_deduction": "0"}]}]}}}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    attached = local.import_contract_history(path, dataset_id=str(original["dataset_id"]), data_epoch=str(original["data_epoch"]))
    return attached, start


def test_a_python_robustness_experiment_runs_its_folds_and_holdout_end_to_end(tmp_path, monkeypatch):
    """Through the experiment route: the study smokes each window, runs each candidate and the selected
    one out of sample, waits for the holdout, and finishes once it is revealed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.strategy_experiments import router
    from app.backtest.runtime import BacktestRuntime
    from app.core.config import load_backtest_settings

    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "0")
    rows = 200
    dataset, start = _contract_dataset(tmp_path, rows)
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1", "BACKTEST_STUDY_ENABLED": "1"},
                                      data_dir=tmp_path, klines_db_path=tmp_path / "candlescope.db",
                                      replay_db_path=tmp_path / "replay.db")
    runtime = BacktestRuntime.start(settings, local_data_dir=tmp_path / "local")
    try:
        end = start + rows * DAY - 1
        preview = runtime.preview_snapshot(dataset_id=str(dataset["dataset_id"]), data_epoch=str(dataset["data_epoch"]),
                                           start_time_ms=start, end_time_ms=end, interval="1d",
                                           contract_data_mode="HISTORICAL_CONTRACT_V1",
                                           account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="OFF")
        revision = runtime.service.create_strategy_revision({"name": "SMA", "language": "PYTHON_EDITOR",
                                                             "source_text": PARAMETERISED, "parameter_schema": []})
        app = FastAPI()
        app.state.data_manager_core = type("Core", (), {"strategy": StrategyDataManager(runtime.service, runtime=runtime)})()
        app.include_router(router)
        study = {"hypothesis": "a faster SMA survives out of sample", "strategy_revision_id": revision["revision_id"],
                 "dataset_id": dataset["dataset_id"], "data_epoch": dataset["data_epoch"],
                 "dataset_snapshot_hash": preview["snapshot_hash"], "interval": "1d", "start_ms": start, "end_ms": end,
                 "train_ms": 110 * DAY, "test_ms": 40 * DAY, "step_ms": 40 * DAY, "holdout_ms": 10 * DAY,
                 "parameter_space": {"fast": [2, 3]}, "sampler": "grid", "candidate_budget": 2, "objective": "NET_RETURN",
                 "constraints": {"min_closed_trades": 1, "max_drawdown": "1", "cost_plus_25_must_be_positive": False},
                 "python_runtime_mode": "TRUSTED_LOCAL", "python_trusted_confirmed": True}
        body = {"idempotency_key": "robust-e2e-1", "name": "SMA · robustness", "kind": "ROBUSTNESS",
                "strategy": {"language": "python"}, "study": study}

        def wait(client, experiment_id, states):
            deadline = time.monotonic() + 90
            while True:
                view = client.get(f"/strategy-experiments/{experiment_id}").json()
                if view["state"] in states or time.monotonic() > deadline:
                    return view
                time.sleep(0.1)

        with TestClient(app) as client:
            created = client.post("/strategy-experiments", json=body, headers=TRUSTED).json()
            assert created["kind"] == "ROBUSTNESS", created
            experiment_id = created["experiment_id"]
            waiting = wait(client, experiment_id, {"AWAITING_HOLDOUT", "FAILED", "COMPLETED"})
            assert waiting["state"] == "AWAITING_HOLDOUT", waiting["study"]
            roles = [(member["input"]["role"], member["state"]) for member in waiting["members"]]
            assert roles == [("TRAIN", "COMPLETED"), ("TRAIN", "COMPLETED"), ("TEST", "COMPLETED")] * 2 + [("HOLDOUT", "PENDING")]
            assert all(fold["selected"] for fold in waiting["study"]["folds"])
            assert waiting["study"]["oos"]["summary"]["fold_count"] == 2
            revealed = client.post(f"/strategy-experiments/{experiment_id}/reveal-holdout").json()
            assert revealed["state"] == "RUNNING" and revealed["study"]["holdout"]["parameters"]
            done = wait(client, experiment_id, {"COMPLETED", "FAILED"})
            assert done["state"] == "COMPLETED", done["study"]
            assert done["members"][-1]["state"] == "COMPLETED"
            retried = client.post(f"/strategy-experiments/{experiment_id}/members/0/retry")
            assert retried.status_code == 409
        repository = runtime.service.repository
        windows = {json.loads(row["details_json"])["snapshotHash"] for row in repository.connection.execute(
            "SELECT details_json FROM backtest_strategy_smokes WHERE revision_id = ?", (revision["revision_id"],)).fetchall()}
        assert len(windows) == 5, "each training, test and holdout window is smoked once"
        configs = [json.loads(row["config_json"]) for row in repository.connection.execute(
            "SELECT config_json FROM backtest_runs WHERE strategy_revision_id = ?", (revision["revision_id"],)).fetchall()]
        assert len(configs) == 7 and {(c["python_runtime_mode"], c["output_mode"]) for c in configs} == {("TRUSTED_LOCAL", "SIGNAL")}
    finally:
        runtime.shutdown()
