"""Experiments: one strategy, run by a rule (ADR-BACKTEST-015 §3.6, steps P5b and P5c3).

An experiment is a set of FIXED runs plus the rule that generated them.

- INPUTS (batch and multi-market research): a list of inputs. Each member is submitted once, either
  as a strategy data preparation that launches its run when the exchange history is ready, or
  directly as a run over a frozen snapshot. The experiment owns only which members exist and how
  they were submitted.
- ROBUSTNESS: a Study V2 (ADR-011): parameter candidates trained on walk-forward folds, one selected
  per fold and tested out of sample, then an optional sealed holdout. The study plans and creates
  its runs in the worker; the experiment shows them as its members and the study's verdict.

A member's state is read from its preparation or run, so a restart, a closed page or a switched
chart never loses or cancels a member.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Protocol

from app.core.committed_updates import committed_updates_for

from .errors import BacktestError
from .strategy.protocol import canonical_hash
from .study_v2 import STUDY_PROTOCOL_V2

SCHEMA = "candlescope.strategy-experiment/1"
STREAM_SCHEMA = "candlescope.strategy-experiment-stream/1"
ID_PREFIX = "ex_"
KINDS = ("INPUTS", "ROBUSTNESS")
STUDY_PROTOCOL = STUDY_PROTOCOL_V2
MAX_STUDY_BYTES = 64 * 1024
# A study's own states, as an experiment reads them. AWAITING_HOLDOUT waits for the user to reveal it.
STUDY_STATES = {"CREATED": "RUNNING", "RUNNING": "RUNNING", "AWAITING_HOLDOUT": "AWAITING_HOLDOUT",
                "COMPLETED": "COMPLETED", "FAILED": "FAILED", "CANCELLED": "CANCELLED"}
MAX_MEMBERS = 8
MAX_LIST = 50
MAX_BODY_BYTES = 4 * 1024 * 1024
MEMBER_KINDS = ("PREPARATION", "RUN")
ACTIVE = ("PENDING", "PREPARING", "QUEUED", "RUNNING")
PREPARATION_TERMINAL = ("READY", "FAILED", "CANCELLED", "BLOCKED_STORAGE")
# A host run's own states, as the run facade groups them; anything else (FAILED, INTERRUPTED) failed.
RUN_STATES = {
    "DRAFT": "QUEUED", "VALIDATING": "QUEUED", "QUEUED": "QUEUED", "PREPARING": "QUEUED",
    "RUNNING": "RUNNING", "PAUSING": "RUNNING", "PAUSED": "RUNNING", "COMPLETING": "RUNNING", "CANCELLING": "RUNNING",
    "COMPLETED": "COMPLETED", "CANCELLED": "CANCELLED",
}


class ExperimentPort(Protocol):
    """How members reach the backend's preparation and run services, and wake a watching stream."""

    async def submit_preparation(self, body: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    async def submit_run(self, body: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    async def preparation(self, job_id: str) -> dict[str, Any] | None: ...
    async def run(self, run_id: str) -> dict[str, Any] | None: ...
    async def cancel_preparation(self, job_id: str) -> None: ...
    async def cancel_run(self, run_id: str) -> None: ...
    def listen_preparation(self, job_id: str, wake: Callable[[], None]) -> Callable[[], None]: ...
    def listen_run(self, run_id: str, wake: Callable[[], None]) -> Callable[[], None]: ...
    # A robustness experiment's study (ROBUSTNESS).
    async def create_study(self, body: dict[str, Any]) -> dict[str, Any]: ...
    async def start_study(self, study_id: str) -> None: ...
    async def study(self, study_id: str) -> dict[str, Any] | None: ...
    async def cancel_study(self, study_id: str) -> None: ...
    async def reveal_holdout(self, study_id: str) -> None: ...
    def listen_study(self, study_id: str, wake: Callable[[], None]) -> Callable[[], None]: ...


def _invalid(message: str) -> BacktestError:
    return BacktestError("EXPERIMENT_INVALID", message)


def _text(value: Any, name: str, maximum: int, minimum: int = 1) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise _invalid(f"{name} must be text of {minimum}–{maximum} characters")
    return value


def _object(value: Any, name: str, maximum_bytes: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(f"{name} must be an object")
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > maximum_bytes:
        raise _invalid(f"{name} is too large")
    return value


def parse_create(body: Any) -> dict[str, Any]:
    """Validate an experiment request: a name, the strategy it runs (described), and its members."""
    if not isinstance(body, dict):
        raise _invalid("an experiment is an object")
    if len(json.dumps(body, ensure_ascii=False, separators=(",", ":"))) > MAX_BODY_BYTES:
        raise BacktestError("REQUEST_TOO_LARGE", "the experiment request is too large")
    unknown = set(body) - {"idempotency_key", "name", "kind", "strategy", "members", "study"}
    if unknown:
        raise _invalid(f"unknown fields: {', '.join(sorted(unknown))}")
    kind = body.get("kind", "INPUTS")
    if kind not in KINDS:
        raise _invalid("kind must be INPUTS or ROBUSTNESS")
    common = {
        "idempotency_key": _text(body.get("idempotency_key"), "idempotency_key", 128, 8),
        "name": _text(body.get("name"), "name", 120),
        "kind": kind,
        "strategy": _object(body.get("strategy"), "strategy", 16_384),
    }
    if kind == "ROBUSTNESS":
        if "members" in body:
            raise _invalid("a robustness experiment's runs are planned by its study")
        study = _object(body.get("study"), "study", MAX_STUDY_BYTES)
        if {"name", "study_protocol_revision"} & set(study):
            raise _invalid("the study's name and protocol are the experiment's")
        return {**common, "study": study, "members": []}
    if "study" in body:
        raise _invalid("an inputs experiment has members, not a study")
    members = body.get("members")
    if not isinstance(members, list) or not 1 <= len(members) <= MAX_MEMBERS:
        raise _invalid(f"an experiment has 1–{MAX_MEMBERS} members")
    parsed = []
    for index, member in enumerate(members):
        if not isinstance(member, dict) or set(member) - {"input", "preparation", "run"}:
            raise _invalid(f"member {index} has unknown fields")
        submissions = [name for name in ("preparation", "run") if name in member]
        if len(submissions) != 1:
            raise _invalid(f"member {index} is either a preparation or a run")
        submission = submissions[0]
        request = _object(member[submission], f"member {index} {submission}", MAX_BODY_BYTES)
        if "idempotency_key" in request:
            raise _invalid(f"member {index} keys are assigned by the experiment")
        parsed.append({"input": _object(member.get("input"), f"member {index} input", 4096),
                       "kind": "PREPARATION" if submission == "preparation" else "RUN", "request": request})
    return {**common, "members": parsed}


def _error(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    code, message = value.get("code"), value.get("message")
    return {"code": str(code or "FAILED"), "message": str(message or code or "failed")}


def member_view(member: Mapping[str, Any], preparation: Mapping[str, Any] | None,
                run: Mapping[str, Any] | None) -> dict[str, Any]:
    """One member's state, read from its preparation and run."""
    error = _error(json.loads(member["error_json"])) if member.get("error_json") else None
    run_id = member.get("run_id") or None
    preparation_view = None
    if preparation is not None:
        launched = (preparation.get("result") or {}).get("strategy_run")
        if run_id is None and isinstance(launched, Mapping) and isinstance(launched.get("run_id"), str):
            run_id = launched["run_id"]
        preparation_view = {
            "id": preparation["id"], "state": preparation["state"], "stage": preparation.get("stage"),
            "completed": int(preparation.get("completed") or 0), "total": int(preparation.get("total") or 0),
            "waiting": preparation.get("waiting"), "error": _error(preparation.get("error")),
        }
    if error is not None:
        state = "FAILED"
    elif run is not None:
        source = str(run.get("state"))
        state = RUN_STATES.get(source, "FAILED")
        if state == "FAILED":
            error = {"code": str(run.get("failure_code") or source), "message": f"the run ended {source.lower()}"}
    elif preparation is not None:
        source = str(preparation["state"])
        if source == "CANCELLED":
            state = "CANCELLED"
        elif source in ("FAILED", "BLOCKED_STORAGE"):
            state, error = "FAILED", preparation_view["error"] if preparation_view else None
        elif source == "READY":
            # Ready without a run: the launch failed; the run would otherwise be read above.
            state = "QUEUED" if run_id else "FAILED"
            if not run_id:
                error = {"code": "STRATEGY_RUN_MISSING", "message": "the prepared input did not start a run"}
        else:
            state = "PREPARING"
    elif member.get("preparation_id") or member.get("run_id"):
        state, error = "FAILED", {"code": "MEMBER_NOT_FOUND", "message": "the member's preparation or run is gone"}
    else:
        state = "PENDING"
    return {"ordinal": int(member["ordinal"]), "input": json.loads(member["input_json"]), "kind": member["kind"],
            "attempt": int(member["attempt"]), "state": state, "preparation": preparation_view,
            "run_id": run_id, "error": error}


def experiment_view(row: Mapping[str, Any], members: list[dict[str, Any]]) -> dict[str, Any]:
    states = [member["state"] for member in members]
    counts = {"total": len(states), "completed": states.count("COMPLETED"), "failed": states.count("FAILED"),
              "cancelled": states.count("CANCELLED"), "active": sum(state in ACTIVE for state in states)}
    cancelled = row.get("cancelled_at_ms") is not None
    if counts["active"]:
        state = "RUNNING"
    elif cancelled:
        state = "CANCELLED"
    elif counts["completed"] == counts["total"]:
        state = "COMPLETED"
    else:
        state = "FAILED"
    return {"schema": SCHEMA, "experiment_id": row["experiment_id"], "name": row["name"], "kind": row["kind"],
            "strategy": json.loads(row["strategy_json"]), "created_at_ms": int(row["created_at_ms"]),
            "cancelled_at_ms": row.get("cancelled_at_ms"), "state": state, "terminal": state != "RUNNING",
            "counts": counts, "members": members}


def _window(start_ms: Any, end_ms: Any) -> dict[str, int]:
    """A study window, start inclusive and end exclusive."""
    return {"start_ms": int(start_ms), "end_ms": int(end_ms)}


def _run_member(ordinal: int, input_: dict[str, Any], run_id: Any, run: Mapping[str, Any] | None,
                planned_state: str) -> dict[str, Any]:
    """A study run as an experiment member; a run not created yet is PENDING or, once the study has
    stopped, CANCELLED."""
    error = None
    if run_id and run is not None:
        source = str(run.get("state"))
        state = RUN_STATES.get(source, "FAILED")
        if state == "FAILED":
            error = {"code": str(run.get("failure_code") or source), "message": f"the run ended {source.lower()}"}
    elif run_id:
        state, error = "FAILED", {"code": "MEMBER_NOT_FOUND", "message": "the study's run is gone"}
    else:
        state = planned_state
    return {"ordinal": ordinal, "input": input_, "kind": "RUN", "attempt": 0, "state": state, "preparation": None,
            "run_id": str(run_id) if run_id else None, "error": error}


def study_members(study: Mapping[str, Any], runs: Mapping[str, Mapping[str, Any] | None]) -> list[dict[str, Any]]:
    """Every run a Study V2 planned, in order: each fold's candidates on its training window, its
    selected candidate on its test window, then the holdout. ``runs`` holds the created runs by id."""
    stopped = STUDY_STATES.get(str(study["state"])) in ("FAILED", "CANCELLED")
    planned = "CANCELLED" if stopped else "PENDING"
    members: list[dict[str, Any]] = []
    for fold in study.get("folds") or []:
        number = int(fold["ordinal"])
        for trial in fold.get("train_trials") or []:
            run_id = trial.get("run_id")
            trial_planned = "CANCELLED" if str(trial.get("state")) == "CANCELLED" else planned
            members.append(_run_member(len(members), {
                "role": "TRAIN", "fold": number, "candidate": int(trial["candidate_ordinal"]),
                "parameters": json.loads(str(trial["params_json"])),
                **_window(fold["train_start_ms"], fold["train_end_ms"])}, run_id, runs.get(str(run_id)), trial_planned))
        receipt = fold.get("selection_receipt") or {}
        selected = (receipt.get("selected") or {}).get("params") if isinstance(receipt, Mapping) else None
        run_id = fold.get("test_run_id")
        members.append(_run_member(len(members), {
            "role": "TEST", "fold": number, "parameters": selected,
            **_window(fold["test_start_ms"], fold["test_end_ms"])}, run_id, runs.get(str(run_id)), planned))
    holdout = study.get("holdout")
    if isinstance(holdout, Mapping):
        parameters = json.loads(str(holdout["params_json"])) if holdout.get("params_json") else None
        run_id = holdout.get("run_id")
        members.append(_run_member(len(members), {
            "role": "HOLDOUT", "parameters": parameters, **_window(holdout["start_ms"], holdout["end_ms"])},
            run_id, runs.get(str(run_id)), planned))
    return members


def study_view(study: Mapping[str, Any]) -> dict[str, Any]:
    """What a robustness experiment shows of its study: the rule, each fold's selection, the holdout
    and the out-of-sample verdict (its equity curve stays with the test runs)."""
    config = json.loads(str(study["config_json"]))
    holdout = study.get("holdout")
    oos = study.get("oos_report")
    return {
        "study_id": study["study_id"], "state": study["state"], "hypothesis": config.get("hypothesis"),
        "objective": config.get("objective"), "sampler": config.get("sampler"),
        "candidates": config.get("candidate_budget"), "parameter_space": config.get("parameter_space"),
        "window": _window(config["start_ms"], config["end_ms"]),
        "folds": [{"ordinal": int(fold["ordinal"]), "state": fold["state"],
                   "train": _window(fold["train_start_ms"], fold["train_end_ms"]),
                   "test": _window(fold["test_start_ms"], fold["test_end_ms"]),
                   "selected": ((fold.get("selection_receipt") or {}).get("selected") or {}).get("params")}
                  for fold in study.get("folds") or []],
        "holdout": None if not isinstance(holdout, Mapping) else {
            "state": holdout["state"], **_window(holdout["start_ms"], holdout["end_ms"]),
            "parameters": json.loads(str(holdout["params_json"])) if holdout.get("params_json") else None},
        "oos": None if not isinstance(oos, Mapping) else {
            "summary": oos.get("summary"), "folds": oos.get("folds"), "robustness": oos.get("robustness")},
        "error": study.get("failure"),
    }


def _study_run_ids(study: Mapping[str, Any]) -> list[str]:
    ids = [trial.get("run_id") for fold in study.get("folds") or [] for trial in fold.get("train_trials") or []]
    ids += [fold.get("test_run_id") for fold in study.get("folds") or []]
    holdout = study.get("holdout")
    if isinstance(holdout, Mapping):
        ids.append(holdout.get("run_id"))
    return [str(run_id) for run_id in ids if run_id]


def robustness_view(row: Mapping[str, Any], study: Mapping[str, Any] | None,
                    runs: Mapping[str, Mapping[str, Any] | None]) -> dict[str, Any]:
    if study is None:
        members: list[dict[str, Any]] = []
        state, detail = "FAILED", {"study_id": row.get("study_id"), "state": "MISSING", "error": {
            "code": "STUDY_NOT_FOUND", "message": "the experiment's study is gone"}}
    else:
        members, state, detail = study_members(study, runs), STUDY_STATES.get(str(study["state"]), "FAILED"), study_view(study)
    view = experiment_view(row, members)
    counts = view["counts"]
    return {**view, "state": state, "terminal": state != "RUNNING", "study": detail,
            "counts": {**counts, "active": counts["active"] if state == "RUNNING" else 0}}


def _not_found(experiment_id: str) -> BacktestError:
    return BacktestError("EXPERIMENT_NOT_FOUND", f"unknown experiment {experiment_id}")


class StrategyExperiments:
    """Experiments kept in the backtest store, with commit wakeups for their streams."""

    def __init__(self, repository, *, heartbeat_seconds: float = 15.0,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000)) -> None:
        self.repository = repository
        self.heartbeat_seconds = heartbeat_seconds
        self.clock_ms = clock_ms
        self.updates = committed_updates_for(repository.path, "strategy-experiments")

    async def _record(self, experiment_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        value = await asyncio.to_thread(self.repository.get_strategy_experiment, experiment_id)
        if value is None:
            raise _not_found(experiment_id)
        return value

    async def create(self, body: Any, port: ExperimentPort) -> dict[str, Any]:
        """Create an experiment and submit its members; the same key returns the same experiment."""
        spec = parse_create(body)
        request_hash = canonical_hash({key: value for key, value in spec.items() if key != "idempotency_key"})
        existing = await asyncio.to_thread(self.repository.strategy_experiment_by_key, spec["idempotency_key"])
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise BacktestError("IDEMPOTENCY_CONFLICT", "this key belongs to a different experiment")
            if spec["kind"] == "INPUTS":
                await self._submit_pending(existing["experiment_id"], port)
            return await self.view(existing["experiment_id"], port)
        experiment_id = f"{ID_PREFIX}{uuid.uuid4().hex}"
        row = {"experiment_id": experiment_id, "idempotency_key": spec["idempotency_key"], "request_hash": request_hash,
               "name": spec["name"], "kind": spec["kind"], "created_at_ms": self.clock_ms(),
               "strategy_json": json.dumps(spec["strategy"], ensure_ascii=False, separators=(",", ":"))}
        if spec["kind"] == "ROBUSTNESS":
            return await self._create_robustness(row, spec["study"], port)
        members = [{"experiment_id": experiment_id, "ordinal": index, "kind": member["kind"],
                    "input_json": json.dumps(member["input"], ensure_ascii=False, separators=(",", ":")),
                    "request_json": json.dumps(member["request"], ensure_ascii=False, separators=(",", ":"))}
                   for index, member in enumerate(spec["members"])]
        await asyncio.to_thread(self.repository.insert_strategy_experiment, row, members)
        await self._submit_pending(experiment_id, port)
        return await self.view(experiment_id, port)

    async def _create_robustness(self, row: dict[str, Any], study: dict[str, Any], port: ExperimentPort) -> dict[str, Any]:
        """Create and start the study, then keep it as the experiment. The study validates the rule;
        a refused study or start leaves no experiment, and a started study is never left unowned."""
        created = await port.create_study({**study, "name": row["name"], "study_protocol_revision": STUDY_PROTOCOL})
        study_id = str(created["study_id"])
        try:
            await port.start_study(study_id)
            await asyncio.to_thread(self.repository.insert_strategy_experiment, row, [], study_id)
        except BaseException as failure:
            try:
                await port.cancel_study(study_id)
            except BacktestError:
                pass
            existing = await asyncio.to_thread(self.repository.strategy_experiment_by_key, row["idempotency_key"])
            if isinstance(failure, Exception) and existing is not None:  # the same key won a race
                if existing["request_hash"] != row["request_hash"]:
                    raise BacktestError("IDEMPOTENCY_CONFLICT", "this key belongs to a different experiment") from None
                return await self.view(existing["experiment_id"], port)
            raise
        self.updates.notify(row["experiment_id"])
        return await self.view(row["experiment_id"], port)

    async def _submit_pending(self, experiment_id: str, port: ExperimentPort) -> None:
        row, members = await self._record(experiment_id)
        if row["cancelled_at_ms"] is not None:
            return
        for member in members:
            if member["preparation_id"] is None and member["run_id"] is None and member["error_json"] is None:
                await self._submit(experiment_id, member, port)

    async def _submit(self, experiment_id: str, member: Mapping[str, Any], port: ExperimentPort) -> None:
        # One key per attempt: a retry is a new submission; a repeated create reuses the attempt's key.
        key = f"{experiment_id}:{member['ordinal']}:{member['attempt']}"
        request = json.loads(member["request_json"])
        preparation_id = run_id = error = None
        try:
            if member["kind"] == "PREPARATION":
                preparation_id = str((await port.submit_preparation(request, key))["id"])
            else:
                run_id = str((await port.submit_run(request, key))["run_id"])
        except BacktestError as failure:
            error = json.dumps({"code": failure.code, "message": failure.message}, ensure_ascii=False)
        await asyncio.to_thread(self.repository.set_strategy_experiment_member, experiment_id, int(member["ordinal"]),
                                attempt=int(member["attempt"]), preparation_id=preparation_id, run_id=run_id,
                                error_json=error, now_ms=self.clock_ms())
        self.updates.notify(experiment_id)

    async def _member(self, member: Mapping[str, Any], port: ExperimentPort) -> dict[str, Any]:
        preparation = await port.preparation(member["preparation_id"]) if member["preparation_id"] else None
        launched = (preparation or {}).get("result") or {}
        run_id = member["run_id"] or (launched.get("strategy_run") or {}).get("run_id")
        run = await port.run(run_id) if isinstance(run_id, str) else None
        return member_view(member, preparation, run)

    async def view(self, experiment_id: str, port: ExperimentPort) -> dict[str, Any]:
        row, members = await self._record(experiment_id)
        if row["kind"] == "ROBUSTNESS":
            study = await port.study(str(row["study_id"])) if row.get("study_id") else None
            runs = {} if study is None else {
                str(run_id): await port.run(str(run_id)) for run_id in _study_run_ids(study)}
            return robustness_view(row, study, runs)
        return experiment_view(row, [await self._member(member, port) for member in members])

    async def list(self, port: ExperimentPort, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= MAX_LIST:
            raise _invalid(f"limit must be 1–{MAX_LIST}")
        ids = await asyncio.to_thread(self.repository.list_strategy_experiments, limit)
        return {"experiments": [await self.view(experiment_id, port) for experiment_id in ids]}

    async def cancel(self, experiment_id: str, port: ExperimentPort) -> dict[str, Any]:
        """Stop the experiment: members still preparing or running are cancelled; finished ones stay."""
        row, _ = await self._record(experiment_id)
        await asyncio.to_thread(self.repository.cancel_strategy_experiment, experiment_id, self.clock_ms())
        if row["kind"] == "ROBUSTNESS":
            if row.get("study_id"):
                try:
                    await port.cancel_study(str(row["study_id"]))  # stops its active runs; finished ones stay
                except BacktestError:
                    pass  # a study that already finished keeps its outcome
            self.updates.notify(experiment_id)
            return await self.view(experiment_id, port)
        current = await self.view(experiment_id, port)
        for member in current["members"]:
            if member["state"] not in ACTIVE:
                continue
            try:
                if member["run_id"]:
                    await port.cancel_run(member["run_id"])
                elif member["preparation"] is not None:
                    await port.cancel_preparation(member["preparation"]["id"])
            except BacktestError:
                pass  # a member that is finishing keeps its own outcome
        self.updates.notify(experiment_id)
        return await self.view(experiment_id, port)

    async def retry(self, experiment_id: str, ordinal: int, port: ExperimentPort) -> dict[str, Any]:
        """Submit a failed or cancelled member again, as a new attempt with the same request."""
        row, members = await self._record(experiment_id)
        if row["kind"] == "ROBUSTNESS":
            raise BacktestError("EXPERIMENT_RULE_UNSUPPORTED",
                                "a robustness study is not retried run by run; start the study again")
        if row["cancelled_at_ms"] is not None:
            raise BacktestError("EXPERIMENT_CANCELLED", "a cancelled experiment is not resumed")
        member = next((item for item in members if int(item["ordinal"]) == ordinal), None)
        if member is None:
            raise BacktestError("EXPERIMENT_MEMBER_NOT_FOUND", f"the experiment has no member {ordinal}")
        if (await self._member(member, port))["state"] not in ("FAILED", "CANCELLED"):
            raise BacktestError("EXPERIMENT_MEMBER_ACTIVE", "only a failed or cancelled member is retried")
        await self._submit(experiment_id, {**member, "attempt": int(member["attempt"]) + 1}, port)
        return await self.view(experiment_id, port)

    async def reveal_holdout(self, experiment_id: str, port: ExperimentPort) -> dict[str, Any]:
        """Open a robustness study's sealed holdout: its most selected candidate runs once on it."""
        row, _ = await self._record(experiment_id)
        if row["kind"] != "ROBUSTNESS" or not row.get("study_id"):
            raise BacktestError("EXPERIMENT_RULE_UNSUPPORTED", "only a robustness experiment has a holdout")
        await port.reveal_holdout(str(row["study_id"]))
        self.updates.notify(experiment_id)
        return await self.view(experiment_id, port)

    async def watch(self, experiment_id: str, port: ExperimentPort) -> ExperimentWatch:
        watch = ExperimentWatch(self, experiment_id, port)
        await watch.prepare()
        return watch


class ExperimentWatch:
    """One consumer's stream of an experiment: a status frame per committed change of it or its members."""

    def __init__(self, owner: StrategyExperiments, experiment_id: str, port: ExperimentPort) -> None:
        self.owner = owner
        self.experiment_id = experiment_id
        self.port = port
        self._updates = owner.updates.subscribe(experiment_id)
        self._bridges: dict[tuple[str, str], Callable[[], None]] = {}
        self._first: dict[str, Any] | None = None

    def _wake(self) -> None:
        self.owner.updates.notify(self.experiment_id)

    def _bridge(self, view: Mapping[str, Any]) -> None:
        """Follow every member's preparation and run as they appear, and a robustness study's own changes."""
        study = view.get("study")
        if isinstance(study, Mapping) and study.get("study_id") and ("study", study["study_id"]) not in self._bridges:
            self._bridges[("study", str(study["study_id"]))] = self.port.listen_study(str(study["study_id"]), self._wake)
        for member in view["members"]:
            pairs = []
            if member["preparation"] is not None:
                pairs.append(("preparation", member["preparation"]["id"]))
            if member["run_id"]:
                pairs.append(("run", member["run_id"]))
            for pair in pairs:
                if pair not in self._bridges:
                    listen = self.port.listen_preparation if pair[0] == "preparation" else self.port.listen_run
                    self._bridges[pair] = listen(pair[1], self._wake)

    async def _read(self) -> dict[str, Any]:
        self._updates.clear_before_read()
        view = await self.owner.view(self.experiment_id, self.port)
        self._bridge(view)
        return {"schema": STREAM_SCHEMA, "type": "status", "terminal": view["terminal"], "experiment": view}

    async def prepare(self) -> None:
        try:
            self._first = await self._read()
        except BaseException:
            self.close()
            raise

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        previous = None
        try:
            frame, self._first = self._first, None
            while not self._updates.closed:
                if frame is None:
                    frame = await self._read()
                if frame != previous:
                    yield frame
                    previous = frame
                if frame["terminal"]:
                    return
                frame = None
                while not self._updates.closed:
                    try:
                        if not await asyncio.wait_for(self._updates.wait(), self.owner.heartbeat_seconds):
                            return
                        break
                    except TimeoutError:
                        yield {"schema": STREAM_SCHEMA, "type": "heartbeat", "terminal": False}
        except BacktestError as exc:
            yield {"schema": STREAM_SCHEMA, "type": "error", "terminal": True,
                   "error": {"code": exc.code, "message": exc.message}}
        finally:
            self.close()

    def close(self) -> None:
        self._first = None
        for release in self._bridges.values():
            release()
        self._bridges.clear()
        self._updates.close()
