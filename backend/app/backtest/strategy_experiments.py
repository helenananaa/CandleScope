"""Experiments: one strategy, run over several inputs (ADR-BACKTEST-015 §3.6, step P5b).

An experiment is a set of FIXED runs plus the rule that generated them. Here the rule is a list of
inputs (batch and multi-market research): each member is submitted once, either as a strategy data
preparation that launches its run when the exchange history is ready, or directly as a run over a
frozen snapshot. The backend's own queues schedule them; the experiment owns only which members
exist and how they were submitted. A member's state is read from its preparation or run, so a
restart, a closed page or a switched chart never loses or cancels a member.
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

SCHEMA = "candlescope.strategy-experiment/1"
STREAM_SCHEMA = "candlescope.strategy-experiment-stream/1"
ID_PREFIX = "ex_"
KINDS = ("INPUTS",)
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
    unknown = set(body) - {"idempotency_key", "name", "kind", "strategy", "members"}
    if unknown:
        raise _invalid(f"unknown fields: {', '.join(sorted(unknown))}")
    kind = body.get("kind", "INPUTS")
    if kind not in KINDS:
        raise _invalid("kind must be INPUTS")
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
    return {
        "idempotency_key": _text(body.get("idempotency_key"), "idempotency_key", 128, 8),
        "name": _text(body.get("name"), "name", 120),
        "kind": kind,
        "strategy": _object(body.get("strategy"), "strategy", 16_384),
        "members": parsed,
    }


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
            await self._submit_pending(existing["experiment_id"], port)
            return await self.view(existing["experiment_id"], port)
        experiment_id = f"{ID_PREFIX}{uuid.uuid4().hex}"
        row = {"experiment_id": experiment_id, "idempotency_key": spec["idempotency_key"], "request_hash": request_hash,
               "name": spec["name"], "kind": spec["kind"], "created_at_ms": self.clock_ms(),
               "strategy_json": json.dumps(spec["strategy"], ensure_ascii=False, separators=(",", ":"))}
        members = [{"experiment_id": experiment_id, "ordinal": index, "kind": member["kind"],
                    "input_json": json.dumps(member["input"], ensure_ascii=False, separators=(",", ":")),
                    "request_json": json.dumps(member["request"], ensure_ascii=False, separators=(",", ":"))}
                   for index, member in enumerate(spec["members"])]
        await asyncio.to_thread(self.repository.insert_strategy_experiment, row, members)
        await self._submit_pending(experiment_id, port)
        return await self.view(experiment_id, port)

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
        return experiment_view(row, [await self._member(member, port) for member in members])

    async def list(self, port: ExperimentPort, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= MAX_LIST:
            raise _invalid(f"limit must be 1–{MAX_LIST}")
        ids = await asyncio.to_thread(self.repository.list_strategy_experiments, limit)
        return {"experiments": [await self.view(experiment_id, port) for experiment_id in ids]}

    async def cancel(self, experiment_id: str, port: ExperimentPort) -> dict[str, Any]:
        """Stop the experiment: members still preparing or running are cancelled; finished ones stay."""
        await self._record(experiment_id)
        await asyncio.to_thread(self.repository.cancel_strategy_experiment, experiment_id, self.clock_ms())
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
        if row["cancelled_at_ms"] is not None:
            raise BacktestError("EXPERIMENT_CANCELLED", "a cancelled experiment is not resumed")
        member = next((item for item in members if int(item["ordinal"]) == ordinal), None)
        if member is None:
            raise BacktestError("EXPERIMENT_MEMBER_NOT_FOUND", f"the experiment has no member {ordinal}")
        if (await self._member(member, port))["state"] not in ("FAILED", "CANCELLED"):
            raise BacktestError("EXPERIMENT_MEMBER_ACTIVE", "only a failed or cancelled member is retried")
        await self._submit(experiment_id, {**member, "attempt": int(member["attempt"]) + 1}, port)
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
        """Follow every member's preparation and run as they appear."""
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
