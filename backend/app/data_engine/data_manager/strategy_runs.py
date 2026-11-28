"""One run facade over every strategy run family (ADR-BACKTEST-015 step P2).

Each family keeps its own store and executor. This facade resolves a run id to
its family, reports its lifecycle as ``candlescope.strategy-run/1`` and
delegates result reads and controls. A run id's prefix only picks the store to
ask; that store must then know the id, so no prefix reaches another family.

Families:

- ``host``: ``/backtests/runs`` (``bt_``), authority HOST, clock FIXED.
- ``native``: ``/backtests/native/runs`` (``native_``), authority SCRIPT, clock FIXED.
- ``external``: ``/backtests/external/runs`` (``native_``, execution mode
  CANDLESCOPE), a Pine script matched by the host: authority HOST, clock FIXED.
- ``continuous``: ``/backtests/continuous/runs`` (``cs_``), authority HOST,
  clock FORWARD. Its committed account is projected onto the same run result
  (step P2d) and changes with every commit; it is never COMPLETED.
- ``follow``: ``/strategy-follows`` (``fl_``), authority HOST, clock FOLLOW
  (step P4b). A chart's live run, in memory and held by chart-cell leases; it
  recomputes as its next generation when its processed bars are revised, and
  reads as CANCELLED once no chart holds it. It is never COMPLETED.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any, get_args

from app.backtest.errors import BacktestError

if TYPE_CHECKING:
    from .strategy import StrategyDataManager


STATUS_SCHEMA = "candlescope.strategy-run/1"
STREAM_SCHEMA = "candlescope.strategy-run-stream/1"
CAPABILITIES_SCHEMA = "candlescope.strategy-run-capabilities/1"
FAMILIES = ("host", "native", "external", "continuous", "follow")
STATES = ("QUEUED", "RUNNING", "PAUSED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED")
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
MAX_RUN_ID = 128

# Every state a family can report, mapped onto the shared lifecycle. A state
# missing here is a contract change: the facade refuses it instead of guessing.
HOST_STATES = {
    "DRAFT": "QUEUED", "VALIDATING": "QUEUED", "QUEUED": "QUEUED", "PREPARING": "QUEUED",
    "RUNNING": "RUNNING", "PAUSING": "RUNNING", "COMPLETING": "RUNNING", "CANCELLING": "RUNNING",
    "PAUSED": "PAUSED", "COMPLETED": "COMPLETED", "FAILED": "FAILED", "CANCELLED": "CANCELLED",
}
NATIVE_STATES = {
    "QUEUED": "QUEUED", "RUNNING": "RUNNING", "COMPLETED": "COMPLETED", "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
    # The host restarted before the engine finished; the run must be rerun explicitly.
    "INTERRUPTED": "FAILED",
}
CONTINUOUS_PHASES = {
    "CATCHING_UP": "RUNNING", "LIVE": "RUNNING", "PAUSED": "PAUSED",
    # Its input changed under it; it waits for a repair rather than for the user.
    "REPAIR_REQUIRED": "BLOCKED", "FAILED": "FAILED", "CANCELLED": "CANCELLED",
}
FOLLOW_PHASES = {
    "CATCHING_UP": "RUNNING", "LIVE": "RUNNING",
    # The source cannot supply its closed bars yet; it continues once they arrive.
    "WAITING_DATA": "BLOCKED", "FAILED": "FAILED",
}
# A forward run that has not been committed yet still reports its creation request.
CONTINUOUS_CREATION_PHASES = {
    "REQUESTED": "QUEUED", "WATCHED": "QUEUED", "READY": "QUEUED", "PAUSED": "PAUSED",
    "FAILED": "FAILED", "CANCELLED": "CANCELLED",
}


def _not_found(run_id: str) -> BacktestError:
    return BacktestError("RUN_NOT_FOUND", f"unknown strategy run {run_id}")


def store_for(run_id: str) -> str:
    """The store that may hold ``run_id``: ``host``, ``native`` (native or external), ``continuous`` or ``follow``."""
    if not isinstance(run_id, str) or not 0 < len(run_id) <= MAX_RUN_ID:
        raise _not_found(str(run_id)[:MAX_RUN_ID])
    if run_id.startswith("bt_"):
        return "host"
    if run_id.startswith("native_"):
        return "native"
    if run_id.startswith("cs_"):
        return "continuous"
    if run_id.startswith("fl_"):
        return "follow"
    raise _not_found(run_id)


def _lifecycle(states: Mapping[str, str], source_state: object, family: str) -> str:
    try:
        return states[str(source_state)]
    except KeyError:
        raise BacktestError("RUN_STATE_UNKNOWN", f"{family} run reported an unknown state {source_state!r}") from None


def _error(value: object) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, Mapping):
        message = value.get("message")
        return {"code": str(value.get("code") or "RUN_FAILED"), "message": None if message is None else str(message)}
    return {"code": str(value), "message": None}


def _status(run_id: str, family: str, *, authority: str, clock_policy: str, fidelity: str | None,
            language: str | None, source_state: str, state: str, generation: int | None,
            result_available: bool, error: object, version_hash: str | None = None) -> dict[str, Any]:
    return {
        "schema": STATUS_SCHEMA, "run_id": run_id, "family": family,
        "authority": authority, "clock_policy": clock_policy, "fidelity": fidelity, "language": language,
        "state": state, "source_state": source_state, "terminal": state in TERMINAL,
        "generation": generation, "result_available": result_available, "error": _error(error),
        # The content-addressed version of the run's code (P3b); null while it cannot be known yet.
        "version_hash": version_hash,
    }


class StrategyRuns:
    """Status, result and cancel for any run id, plus one capability matrix."""

    def __init__(self, owner: StrategyDataManager) -> None:
        self.owner = owner

    # -- resolution -------------------------------------------------------

    def _runtime(self):
        self.owner._require_open()
        if self.owner.runtime is None:
            raise BacktestError("FLAG_DISABLED", "backtest worker runtime is not started")
        return self.owner.runtime

    def _host_record(self, run_id: str) -> dict[str, Any]:
        service = self.owner.control_plane()
        try:
            return service.get_run(run_id)
        except BacktestError as exc:
            # The host service reports an unknown id as an unknown field.
            if exc.code == "SCHEMA_UNKNOWN_FIELD":
                raise _not_found(run_id) from None
            raise

    # -- versions (P3b) ---------------------------------------------------

    def _version(self, run_id: str, family: str, read_material) -> str | None:
        """The run's version hash; a run without a link yet is linked from its own record, once."""
        from app.backtest.strategy_versions import StrategyVersions
        versions = StrategyVersions(self.owner.service.repository)
        try:
            found = versions.for_run(run_id)
            if found is not None:
                return found
            return versions.record(read_material(), run_id=run_id, family=family, now_ms=int(time.time() * 1000))
        except BacktestError:
            return None  # e.g. a legacy record that does not hold its code
        except Exception:
            logging.getLogger(__name__).warning("Strategy version of run %s is unavailable", run_id, exc_info=True)
            return None

    # -- status -----------------------------------------------------------

    async def status(self, run_id: str) -> dict[str, Any]:
        store = store_for(run_id)
        if store == "host":
            return await asyncio.to_thread(self._host_status, run_id)
        if store == "native":
            return await asyncio.to_thread(self._native_status, run_id)
        if store == "follow":
            return (await self._follow_view(run_id))[0]
        return await self._continuous_status(run_id)

    def _host_status(self, run_id: str) -> dict[str, Any]:
        return self._host_view(run_id)[0]

    def _host_view(self, run_id: str) -> tuple[dict[str, Any], dict[str, int] | None]:
        """The host run's status and latest checkpoint, read in one transaction."""
        self.owner._require_open()
        value = self.owner.service.repository.read_run_progress(run_id)
        if value is None:
            raise _not_found(run_id)
        record, checkpoint = value["run"], value["checkpoint"]
        source_state = str(record["state"])
        state = _lifecycle(HOST_STATES, source_state, "host")
        def material():
            from app.backtest.strategy_versions import host_material
            service = self.owner.service
            return host_material(service.repository, service.strategy_registry, service.repository.get_run_by_id(run_id))
        status = _status(run_id, "host", authority="HOST", clock_policy="FIXED",
                         fidelity=str(record["fidelity_mode"]), language=None, source_state=source_state,
                         state=state, generation=int(record["generation"]), result_available=state == "COMPLETED",
                         error=value["failure"] or record.get("failure_code"),
                         version_hash=self._version(run_id, "host", material))
        progress = None if checkpoint is None else {
            "sequence": int(checkpoint["sequence"]), "created_at_ms": int(checkpoint["created_at_ms"])}
        return status, progress

    def _native_status(self, run_id: str) -> dict[str, Any]:
        summary = self._runtime().native.status_summary(run_id)
        external = summary["execution_mode"] == "CANDLESCOPE"
        if not external and summary["execution_mode"] != "NATIVE":
            raise BacktestError("NATIVE_INPUT_UNSUPPORTED", f"unknown strategy execution mode {summary['execution_mode']!r}")
        source_state = str(summary["state"])
        state = _lifecycle(NATIVE_STATES, source_state, "native")
        family = "external" if external else "native"

        def material():
            from app.backtest.strategy_versions import native_material
            return native_material(self._runtime().native.get(run_id))
        return _status(run_id, family,
                       authority="HOST" if external else "SCRIPT", clock_policy="FIXED",
                       # A native run fills by the script's own model; there is no host fidelity.
                       fidelity=str(summary.get("execution_fidelity") or "BAR_APPROX") if external else None,
                       language=summary.get("language"), source_state=source_state, state=state, generation=None,
                       result_available=state == "COMPLETED" and summary["result_present"],
                       error=summary.get("error"), version_hash=self._version(run_id, family, material))

    async def _continuous_status(self, run_id: str) -> dict[str, Any]:
        return (await self._continuous_view(run_id))[0]

    async def _continuous_view(self, run_id: str) -> tuple[dict[str, Any], dict[str, int] | None]:
        """A forward run's status and its committed revision (each commit changes its result)."""
        self.owner._require_open()
        try:
            value = await self.owner.continuous_access().status(run_id)
        except BacktestError as exc:
            if exc.code == "CONTINUOUS_RUN_NOT_FOUND":
                raise _not_found(run_id) from None
            raise
        run, creation = value.get("run"), value.get("creation")
        if run is None:
            source_state = str((creation or {}).get("phase"))
            state = _lifecycle(CONTINUOUS_CREATION_PHASES, source_state, "continuous")
            generation, error = None, (creation or {}).get("error")
        else:
            source_state = str(run["phase"])
            state = _lifecycle(CONTINUOUS_PHASES, source_state, "continuous")
            generation, error = int(run["generation"]), run.get("error")
        version = None
        if run is not None:
            # A committed forward run holds its prepared provider in its definition.
            from app.backtest.strategy_versions import StrategyVersions, continuous_material
            version = await asyncio.to_thread(StrategyVersions(self.owner.service.repository).for_run, run_id)
            if version is None:
                try:
                    definition = (await self.owner.continuous_access().describe(run_id))["definition"]
                except BacktestError:
                    definition = None
                if definition is not None:
                    version = await asyncio.to_thread(
                        self._version, run_id, "continuous", lambda: continuous_material(definition))
        # A committed forward account always has a result; it changes with every commit.
        status = _status(run_id, "continuous", authority="HOST", clock_policy="FORWARD", fidelity="BAR_APPROX",
                         language=None, source_state=source_state, state=state, generation=generation,
                         result_available=run is not None, error=error, version_hash=version)
        progress = None if run is None else {
            "sequence": int(run["checkpoint_revision"]), "created_at_ms": int(run["event_time_ms"])}
        return status, progress

    def _follows(self, run_id: str):
        self.owner._require_open()
        follows = self.owner.follows_or_none()
        if follows is None:
            raise _not_found(run_id)
        return follows

    async def _follow_view(self, run_id: str) -> tuple[dict[str, Any], dict[str, int] | None]:
        """A chart's live run: its phase, and how far it has applied bars (each applied page changes its result)."""
        follows = self._follows(run_id)
        session = follows.sessions_or_none(run_id)
        if session is None:
            ended = follows.ended.get(run_id)
            if ended is None:
                raise _not_found(run_id)
            # No chart holds it any more: it stopped, and keeps no result.
            definition, generation, error = ended["definition"], ended["generation"], ended["error"]
            source_state, state, available, progress = "STOPPED", "CANCELLED", False, None
        else:
            definition, generation = session.definition, session.generation
            source_state = session.phase
            state = _lifecycle(FOLLOW_PHASES, source_state, "follow")
            available = session.caught_up and session.failed is None
            error = None if session.failed is None else _follow_error(session.failed)
            progress = {"sequence": session.revision, "created_at_ms": session.through_ms or 0}
        version = await asyncio.to_thread(follows.version_hash, run_id, definition)
        status = _status(run_id, "follow", authority="HOST", clock_policy="FOLLOW", fidelity="BAR_APPROX",
                         language=str(definition.get("language") or "builtin"), source_state=source_state,
                         state=state, generation=generation, result_available=available, error=error,
                         version_hash=version)
        return status, progress

    # -- watch ------------------------------------------------------------

    async def watch(self, run_id: str) -> RunWatch:
        """A commit-driven status stream for one run (steps P2b, P2d).

        The first status is read before this returns, so an unknown run fails
        before a stream starts. Releasing the watch never cancels the run. A
        forward run's frames carry its committed revision as progress, so each
        commit that changes its result is a frame.
        """
        store = store_for(run_id)
        if store == "continuous":
            self.owner._require_open()
            updates = self.owner.continuous_access().controller().store.updates
            read = self._continuous_view
        elif store == "follow":
            updates = self._follows(run_id).updates
            read = self._follow_view
        elif store == "host":
            self.owner._require_open()
            updates = self.owner.service.repository.run_updates
            read = _in_thread(self._host_view)
        else:
            updates = self._runtime().native.run_updates
            read = _in_thread(lambda value: (self._native_status(value), None))
        # Check capacity before subscribing, so a refused watch leaves no subscription behind.
        self.owner._require_capacity()
        return await self.owner._admit(RunWatch(self.owner, run_id, updates, read))

    # -- result -----------------------------------------------------------

    async def result(self, run_id: str) -> dict[str, Any]:
        """The run as ``candlescope.run-result/1``: a finished fixed run, or a forward run's committed account."""
        store = store_for(run_id)
        if store == "host":
            def host() -> dict[str, Any]:
                self._host_record(run_id)
                return self._runtime().run_result(run_id)
            return await asyncio.to_thread(host)
        if store == "native":
            from app.backtest.run_result import from_native_record
            return await asyncio.to_thread(lambda: from_native_record(self._runtime().native.get(run_id)))
        if store == "follow":
            session = self._follows(run_id).sessions_or_none(run_id)
            if session is None:
                raise _not_found(run_id)  # a stopped FOLLOW run keeps no result
            if not session.caught_up:
                raise BacktestError("RUN_RESULT_NOT_READY", "the FOLLOW run has not reached the chart's newest bar")
            return await asyncio.to_thread(session.result)
        from app.backtest.run_result import from_host_result
        self.owner._require_open()
        try:
            value = await self.owner.continuous_access().committed_result(run_id)
        except BacktestError as exc:
            if exc.code != "CONTINUOUS_RUN_NOT_FOUND":
                raise
            # A requested run that has not committed yet has no account; an unknown id is not found.
            await self._continuous_status(run_id)
            raise BacktestError("RUN_RESULT_NOT_READY", "the forward run has not committed its first result") from None
        return await asyncio.to_thread(lambda: from_host_result(
            value["result"], interval=value["interval"], fidelity="BAR_APPROX", clock_policy="FORWARD"))

    # -- controls ---------------------------------------------------------

    async def cancel(self, run_id: str) -> dict[str, Any]:
        """Cancel a run and return its status. Cancelling a finished run changes nothing."""
        current = await self.status(run_id)
        if current["terminal"]:
            return current
        if current["family"] == "continuous":
            # Forward-run controls require the account's full committed identity.
            raise BacktestError("RUN_CONTROL_UNSUPPORTED", "stop a forward run from its account controls")
        if current["family"] == "follow":
            raise BacktestError("RUN_CONTROL_UNSUPPORTED", "a FOLLOW run stops when no chart holds it")

        def cancel() -> None:
            if current["family"] == "host":
                try:
                    self.owner.control_plane().cancel_run(run_id)
                except BacktestError as exc:
                    # It finished between the read and the cancel.
                    if exc.code != "IDENTITY_MUTATION" or not self._host_status(run_id)["terminal"]:
                        raise
            else:
                self._runtime().native.cancel(run_id)
        await asyncio.to_thread(cancel)
        return await self.status(run_id)

    # -- capabilities -----------------------------------------------------

    async def capabilities(self) -> dict[str, Any]:
        """Which run profiles this backend can create, as one matrix.

        Each profile is a family × language × authority × clock policy with the
        fidelities the family's contract accepts. A strategy revision can narrow
        them (its input modes), and data-dependent checks — an archived trade
        tape, an uploaded book dataset — still happen when the run is created.
        """
        self.owner._require_open()
        families: dict[str, dict[str, Any]] = {}
        profiles: list[dict[str, Any]] = []

        async def collect(names: tuple[str, ...], read) -> None:
            try:
                found, rows = await read()
            except BacktestError as exc:
                families.update({name: {"available": False, "reason": exc.code} for name in names})
                return
            families.update(found)
            profiles.extend(rows)

        await collect(("host",), lambda: asyncio.to_thread(self._host_capabilities))
        await collect(("native", "external"), lambda: asyncio.to_thread(self._native_capabilities))
        await collect(("continuous",), self._continuous_capabilities)
        await collect(("follow",), self._follow_capabilities)
        profiles.sort(key=lambda row: (FAMILIES.index(row["family"]), row["language"]))
        return {"schema": CAPABILITIES_SCHEMA, "states": list(STATES),
                "families": {name: families[name] for name in FAMILIES}, "profiles": profiles}

    def _host_capabilities(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        from app.backtest.strategy.pine_engine import REVISION as PINE_ENGINE_REVISION

        payload = self.owner.control_plane().capabilities()
        flags = payload.get("flags") or {}
        fidelities = list(payload.get("fidelity_modes") or ())
        languages = {"builtin": None}
        if PINE_ENGINE_REVISION in (payload.get("strategy_revisions") or ()):
            languages["pine"] = None
        languages["python"] = None if flags.get("BACKTEST_PYTHON_STRATEGY_ENABLED") else "FLAG_DISABLED"
        available = bool(flags.get("BACKTEST_ENABLED")) and bool(fidelities)
        family = _family(available, None if available else "FLAG_DISABLED")
        from app.backtest.chart_book import BOOK_MODES

        # Pine book fidelities belong to CandleScope matching (the external family, ADR-BACKTEST-015 P6d).
        rows = [_profile("host", language, authority="HOST", clock_policy="FIXED",
                         fidelities=[mode for mode in fidelities if language != "pine" or mode not in BOOK_MODES],
                         available=available and reason is None, reason=family["reason"] or reason,
                         account_models=list(payload.get("account_models") or ()), intervals=None, cancel=True)
                for language, reason in languages.items()]
        return {"host": family}, rows

    def _native_capabilities(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        from app.backtest.native_contracts import ExternalRunRequest

        runtime = self._runtime()
        enabled = bool(runtime.settings.bar_effective)
        payload = runtime.native.capabilities()
        external_fidelities = list(get_args(ExternalRunRequest.model_fields["execution_fidelity"].annotation))
        rows: list[dict[str, Any]] = []
        for engine in payload.get("engines") or ():
            language = str(engine["language"])
            reason = None if enabled else "FLAG_DISABLED"
            if reason is None and not engine.get("available"):
                reason = "ENGINE_UNAVAILABLE"
            rows.append(_profile("native", language, authority="SCRIPT", clock_policy="FIXED", fidelities=None,
                                 available=reason is None, reason=reason, account_models=None, intervals=None,
                                 cancel=True))
            external_reason = reason
            if external_reason is None and not engine.get("external_available"):
                external_reason = "ENGINE_UNAVAILABLE"
            rows.append(_profile("external", language, authority="HOST", clock_policy="FIXED",
                                 fidelities=external_fidelities, available=external_reason is None,
                                 reason=external_reason, account_models=None, intervals=None, cancel=True))
        def family(name: str) -> dict[str, Any]:
            if not enabled:
                return _family(False, "FLAG_DISABLED")
            available = any(row["available"] for row in rows if row["family"] == name)
            return _family(available, None if available else "ENGINE_UNAVAILABLE")
        return {"native": family("native"), "external": family("external")}, rows

    async def _continuous_capabilities(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        from app.backtest.continuous_contracts import ACCOUNT_MODELS, LANGUAGES, ContinuousCreate

        controller = self.owner.continuous_access().controller()
        enabled = controller.execution_enabled is not False
        reason = None if enabled else "READ_ONLY"
        settings = self.owner.service.settings
        # External models run only where the Host enables their connections (B-333c).
        external = None if settings.enabled and settings.external_provider_enabled else "EXTERNAL_PROVIDER_DISABLED"
        starts = list(get_args(ContinuousCreate.model_fields["mode"].annotation))

        def language_reason(language: str) -> str | None:
            return reason or (external if language == "external" else None)

        rows = [{**_profile("continuous", language, authority="HOST", clock_policy="FORWARD",
                            fidelities=["BAR_APPROX"], available=language_reason(language) is None,
                            reason=language_reason(language),
                            account_models=list(ACCOUNT_MODELS), intervals=None, cancel=False),
                 # Any fixed-length interval of whole minutes (B-333).
                 "starts": starts, "fixed_intervals_only": True} for language in LANGUAGES]
        return {"continuous": _family(enabled, reason)}, rows


    async def _follow_capabilities(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        from app.backtest.continuous_contracts import ACCOUNT_MODELS, FOLLOW_LANGUAGES

        enabled = self.owner.market_manager is not None
        reason = None if enabled else "FOLLOW_UNAVAILABLE"
        rows = [{**_profile("follow", language, authority="HOST", clock_policy="FOLLOW", fidelities=["BAR_APPROX"],
                            available=enabled, reason=reason, account_models=list(ACCOUNT_MODELS), intervals=None,
                            cancel=False),
                 # Any chart interval of fixed length; weeks and months are not followed.
                 "fixed_intervals_only": True} for language in FOLLOW_LANGUAGES]
        return {"follow": _family(enabled, reason)}, rows


def _follow_error(failure: BaseException) -> dict[str, Any]:
    code = getattr(failure, "code", None)
    if isinstance(code, str) and code:
        return {"code": code[:64], "message": str(getattr(failure, "message", "") or "")[:256] or None}
    return {"code": "FOLLOW_FAILED", "message": "The strategy failed on a closed bar; it recomputes when its bars are revised."}


def _in_thread(read):
    """A blocking store read, run off the event loop."""
    async def threaded(run_id: str):
        return await asyncio.to_thread(read, run_id)
    return threaded


def _family(available: bool, reason: str | None) -> dict[str, Any]:
    return {"available": available, "reason": None if available else reason}


def _profile(family: str, language: str, *, authority: str, clock_policy: str, fidelities: list[str] | None,
             available: bool, reason: str | None, account_models: list[str] | None, intervals: list[str] | None,
             cancel: bool) -> dict[str, Any]:
    return {
        "family": family, "language": language, "authority": authority, "clock_policy": clock_policy,
        # None: the script fills by its own model, so no host fidelity applies.
        "fidelities": fidelities,
        "available": available, "reason": None if available else reason,
        # None: the script owns its account; any interval the chart offers.
        "account_models": account_models, "intervals": intervals,
        "controls": {"cancel": cancel},
    }


class RunWatch:
    """One consumer's view of a fixed run: a status frame per committed change, then the terminal one.

    Frames are ``candlescope.strategy-run-stream/1``. A wakeup carries no data;
    each frame is read from the committed store, so coalesced commits only
    skip intermediate states, never the terminal one.
    """

    def __init__(self, owner: StrategyDataManager, run_id: str, updates, read) -> None:
        self.owner = owner
        self.run_id = run_id
        self._read_view = read
        self._updates = updates.subscribe(run_id)
        self._generation: int | None = None
        self._first: dict[str, Any] | None = None
        self._iterating = False

    async def _read(self) -> dict[str, Any]:
        # Clear before reading: a commit racing with the read schedules another read.
        self._updates.clear_before_read()
        status, progress = await self._read_view(self.run_id)
        if self._updates.closed:
            raise asyncio.CancelledError
        if self._generation is not None and status["generation"] != self._generation:
            return {"schema": STREAM_SCHEMA, "type": "error", "terminal": True, "run_id": self.run_id,
                    "error": {"code": "RUN_IDENTITY_CHANGED",
                              "message": "The run's generation changed; reconnect to the current run."}}
        self._generation = status["generation"]
        return {"schema": STREAM_SCHEMA, "type": "status", "terminal": status["terminal"],
                "status": status, "progress": progress}

    async def prepare(self) -> None:
        self._first = await self._read()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if self._iterating:
            raise RuntimeError("a run watch has one consumer")
        self._iterating = True
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
                        # Keep the transport alive without polling the store.
                        yield {"schema": STREAM_SCHEMA, "type": "heartbeat", "terminal": False}
        except BacktestError as exc:
            yield {"schema": STREAM_SCHEMA, "type": "error", "terminal": True, "run_id": self.run_id,
                   "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            yield {"schema": STREAM_SCHEMA, "type": "error", "terminal": True, "run_id": self.run_id,
                   "error": {"code": "STRATEGY_STREAM_FAILED",
                             "message": "The run's committed status could not be read; reconnect to inspect it."}}
        finally:
            self.close()

    def close(self) -> None:
        self._first = None
        self._updates.close()
        self.owner._subscriptions.discard(self)
