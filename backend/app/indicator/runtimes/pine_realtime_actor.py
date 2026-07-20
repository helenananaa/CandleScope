"""Persistent process boundary for native Pine realtime sessions.

The native session is intentionally owned by the child process.  The parent
only exchanges versioned, request-correlated messages and tears the child down
on every timeout or protocol failure so a late response can never be consumed
as the result of a later bar update.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

from app.core import config


PINE_REALTIME_ACTOR_PROTOCOL_VERSION = 1
_MODULE_NAME = "pine_compat"


class PineRealtimeActorError(RuntimeError):
    """Base error with a stable CandleScope-facing code."""

    code = "PINE_REALTIME_PROCESS_FAILED"

    def __init__(self, message: str, *, remote_type: str | None = None) -> None:
        super().__init__(message)
        self.remote_type = remote_type


class PineRealtimeUnavailableError(PineRealtimeActorError):
    code = "PINE_REALTIME_UNAVAILABLE"


class PineRealtimeCapacityError(PineRealtimeActorError):
    code = "PINE_REALTIME_CAPACITY_EXCEEDED"


class PineRealtimeTimeoutError(PineRealtimeActorError):
    code = "PINE_REALTIME_TIMEOUT"


class PineRealtimeCrashedError(PineRealtimeActorError):
    code = "PINE_REALTIME_PROCESS_FAILED"


class PineRealtimeProtocolError(PineRealtimeActorError):
    code = "PINE_REALTIME_PROTOCOL_ERROR"


class PineRealtimeRemoteError(PineRealtimeActorError):
    code = "PINE_REALTIME_RUNTIME_ERROR"


_stats_lock = threading.Lock()
_stats: dict[str, int] = {
    "active": 0,
    "started": 0,
    "closed": 0,
    "startFailures": 0,
    "timeouts": 0,
    "crashes": 0,
    "protocolErrors": 0,
    "remoteErrors": 0,
    "requests": 0,
}


def pine_realtime_actor_snapshot() -> dict[str, Any]:
    with _stats_lock:
        snapshot = dict(_stats)
    snapshot.update({
        "enabled": bool(config.PINE_REALTIME_ENABLED),
        "maxSessions": max(int(config.PINE_REALTIME_MAX_SESSIONS), 0),
        "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
    })
    return snapshot


def _reserve_slot() -> None:
    if not bool(config.PINE_REALTIME_ENABLED):
        raise PineRealtimeUnavailableError("Pine realtime hosting is disabled")
    maximum = max(int(config.PINE_REALTIME_MAX_SESSIONS), 0)
    if maximum <= 0:
        raise PineRealtimeUnavailableError("Pine realtime session capacity is disabled")
    with _stats_lock:
        if _stats["active"] >= maximum:
            raise PineRealtimeCapacityError(
                f"Pine realtime session capacity is full ({_stats['active']}/{maximum})"
            )
        _stats["active"] += 1


def _release_slot() -> None:
    with _stats_lock:
        _stats["active"] = max(0, _stats["active"] - 1)
        _stats["closed"] += 1


def _record(name: str) -> None:
    with _stats_lock:
        _stats[name] += 1


def _load_native_module() -> Any:
    override = os.getenv("CANDLESCOPE_PINE_COMPAT_RUNTIME_PATH", "").strip()
    if override:
        resolved = str(Path(override).resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
    return importlib.import_module(_MODULE_NAME)


def _state_payload(session: Any) -> dict[str, Any]:
    return {
        "schemaVersion": int(session.schema_version),
        "seeded": bool(session.is_seeded),
        "confirmedBars": int(session.confirmed_bars),
        "lastConfirmedTime": session.last_confirmed_time,
        "formingTime": session.forming_time,
    }


def _worker_main(connection: Any, startup: dict[str, Any]) -> None:
    """Spawn-safe native-session owner."""
    try:
        delay = max(float(startup.get("worker_start_delay_seconds") or 0.0), 0.0)
        if delay:
            time.sleep(delay)
        module = _load_native_module()
        installed_schema = getattr(module, "REALTIME_SESSION_SCHEMA_VERSION", None)
        expected_schema = int(startup["session_schema_version"])
        if installed_schema != expected_schema:
            raise RuntimeError(
                "native realtime session schema mismatch: "
                f"installed={installed_schema!r}, expected={expected_schema}"
            )
        create_session = getattr(module, "create_realtime_session", None)
        if not callable(create_session):
            raise RuntimeError("native runtime does not expose create_realtime_session")
        options: dict[str, Any] = {
            "input_overrides": startup.get("input_overrides") or {},
        }
        if startup.get("chart_symbol"):
            options["chart_symbol"] = startup["chart_symbol"]
        if startup.get("chart_timeframe"):
            options["chart_timeframe"] = startup["chart_timeframe"]
        session = create_session(str(startup["script"]), **options)
        connection.send({
            "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
            "type": "ready",
            "state": _state_payload(session),
        })
    except BaseException as exc:  # pragma: no cover - child startup guard
        try:
            connection.send({
                "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
                "type": "start_error",
                "errorType": exc.__class__.__name__,
                "message": str(exc) or exc.__class__.__name__,
            })
        finally:
            connection.close()
        return

    try:
        while True:
            try:
                request = connection.recv()
            except EOFError:
                return
            request_id = request.get("requestId") if isinstance(request, dict) else None
            operation = request.get("operation") if isinstance(request, dict) else None
            if (
                not isinstance(request, dict)
                or request.get("protocolVersion") != PINE_REALTIME_ACTOR_PROTOCOL_VERSION
                or not isinstance(request_id, int)
                or not isinstance(operation, str)
            ):
                connection.send({
                    "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
                    "type": "protocol_error",
                    "requestId": request_id,
                    "message": "invalid Pine realtime actor request",
                })
                continue
            if operation == "close":
                connection.send({
                    "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
                    "type": "closed",
                    "requestId": request_id,
                })
                return
            try:
                if operation == "seed":
                    raw = session.seed(request.get("bars") or [])
                elif operation == "update_forming":
                    raw = session.update_forming(request.get("bar"))
                elif operation == "update_confirmed":
                    raw = session.update_confirmed(request.get("bar"))
                elif operation == "result":
                    raw = session.result()
                elif operation == "confirmed_result":
                    raw = session.confirmed_result()
                else:
                    raise ValueError(f"unknown Pine realtime operation: {operation}")
                connection.send({
                    "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
                    "type": "result",
                    "requestId": request_id,
                    "operation": operation,
                    "result": dict(raw),
                    "state": _state_payload(session),
                })
            except BaseException as exc:  # keep transactional native errors recoverable
                connection.send({
                    "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
                    "type": "runtime_error",
                    "requestId": request_id,
                    "operation": operation,
                    "errorType": exc.__class__.__name__,
                    "message": str(exc) or exc.__class__.__name__,
                    "state": _state_payload(session),
                })
    finally:
        connection.close()


def _terminate_process(process: multiprocessing.Process | None, grace_seconds: float) -> None:
    if process is None or not process.is_alive():
        return
    process.terminate()
    process.join(max(grace_seconds, 0.0))
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(max(grace_seconds, 0.0))


class PineRealtimeActor:
    """One request-at-a-time parent proxy for a persistent native session."""

    def __init__(
        self,
        *,
        script: str,
        input_overrides: dict[int, Any],
        chart_symbol: str | None,
        chart_timeframe: str | None,
        session_schema_version: int,
        timeout_seconds: float | None = None,
        grace_seconds: float | None = None,
        _worker_start_delay_seconds: float = 0.0,
    ) -> None:
        self._timeout = max(float(
            config.PINE_REALTIME_COMMAND_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        ), 0.0)
        self._grace = max(float(
            config.PINE_PROCESS_GRACE_SECONDS
            if grace_seconds is None
            else grace_seconds
        ), 0.0)
        self._lock = threading.RLock()
        self._connection: Any | None = None
        self._process: multiprocessing.Process | None = None
        self._request_id = 0
        self._closed = False
        self._slot_reserved = False
        self._state: dict[str, Any] = {}

        _reserve_slot()
        self._slot_reserved = True
        child: Any | None = None
        try:
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe(duplex=True)
            self._connection = parent
            startup = {
                "script": script,
                "input_overrides": input_overrides,
                "chart_symbol": chart_symbol,
                "chart_timeframe": chart_timeframe,
                "session_schema_version": int(session_schema_version),
                "worker_start_delay_seconds": max(float(_worker_start_delay_seconds), 0.0),
            }
            self._process = context.Process(
                target=_worker_main,
                args=(child, startup),
                daemon=True,
                name="pine-realtime-session",
            )
            self._process.start()
            child.close()
            message = self._receive(self._timeout, operation="start")
            if message.get("type") == "start_error":
                raise PineRealtimeUnavailableError(
                    str(message.get("message") or "Pine realtime actor failed to start"),
                    remote_type=str(message.get("errorType") or "") or None,
                )
            if message.get("type") != "ready":
                raise PineRealtimeProtocolError("Pine realtime actor did not send ready")
            self._validate_protocol(message)
            state = message.get("state")
            if not isinstance(state, dict) or state.get("schemaVersion") != session_schema_version:
                raise PineRealtimeProtocolError("Pine realtime actor returned an invalid session state")
            self._state = dict(state)
            _record("started")
        except PineRealtimeProtocolError:
            _record("protocolErrors")
            _record("startFailures")
            self._fatal_close()
            raise
        except Exception:
            _record("startFailures")
            self._fatal_close()
            raise
        finally:
            if child is not None and not child.closed:
                child.close()

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def is_alive(self) -> bool:
        return (
            not self._closed
            and self._process is not None
            and self._process.is_alive()
        )

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def seed(self, bars: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("seed", bars=bars)

    def update_forming(self, bar: dict[str, Any]) -> dict[str, Any]:
        return self._request("update_forming", bar=bar)

    def update_confirmed(self, bar: dict[str, Any]) -> dict[str, Any]:
        return self._request("update_confirmed", bar=bar)

    def result(self) -> dict[str, Any]:
        return self._request("result")

    def confirmed_result(self) -> dict[str, Any]:
        return self._request("confirmed_result")

    def _request(self, operation: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            if not self.is_alive or self._connection is None:
                _record("crashes")
                self._fatal_close()
                raise PineRealtimeCrashedError("Pine realtime actor is not alive")
            self._request_id += 1
            request_id = self._request_id
            request = {
                "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
                "requestId": request_id,
                "operation": operation,
                **payload,
            }
            try:
                self._connection.send(request)
            except (BrokenPipeError, EOFError, OSError) as exc:
                _record("crashes")
                self._fatal_close()
                raise PineRealtimeCrashedError(
                    f"Pine realtime actor pipe failed: {exc}"
                ) from exc
            _record("requests")
            message = self._receive(self._timeout, operation=operation)
            try:
                self._validate_protocol(message)
                if message.get("requestId") != request_id or message.get("operation") != operation:
                    raise PineRealtimeProtocolError(
                        "Pine realtime actor response does not match its request"
                    )
                state = message.get("state")
                if isinstance(state, dict):
                    self._state = dict(state)
                if message.get("type") == "runtime_error":
                    _record("remoteErrors")
                    raise PineRealtimeRemoteError(
                        str(message.get("message") or "Pine realtime update failed"),
                        remote_type=str(message.get("errorType") or "") or None,
                    )
                if message.get("type") != "result" or not isinstance(message.get("result"), dict):
                    raise PineRealtimeProtocolError("Pine realtime actor returned an invalid result")
                return dict(message["result"])
            except PineRealtimeProtocolError:
                _record("protocolErrors")
                self._fatal_close()
                raise

    def _receive(self, timeout: float, *, operation: str) -> dict[str, Any]:
        connection = self._connection
        if connection is None:
            raise PineRealtimeCrashedError("Pine realtime actor pipe is closed")
        if not connection.poll(timeout):
            _record("timeouts")
            self._fatal_close()
            raise PineRealtimeTimeoutError(
                f"Pine realtime {operation} exceeded {timeout:g} seconds"
            )
        try:
            message = connection.recv()
        except (EOFError, BrokenPipeError, OSError) as exc:
            _record("crashes")
            self._fatal_close()
            raise PineRealtimeCrashedError(
                f"Pine realtime actor exited during {operation}"
            ) from exc
        if not isinstance(message, dict):
            _record("protocolErrors")
            self._fatal_close()
            raise PineRealtimeProtocolError("Pine realtime actor returned a non-object message")
        return message

    @staticmethod
    def _validate_protocol(message: dict[str, Any]) -> None:
        if message.get("protocolVersion") != PINE_REALTIME_ACTOR_PROTOCOL_VERSION:
            raise PineRealtimeProtocolError("Pine realtime actor protocol version mismatch")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if self._connection is not None and self._process is not None and self._process.is_alive():
                    self._request_id += 1
                    request_id = self._request_id
                    try:
                        self._connection.send({
                            "protocolVersion": PINE_REALTIME_ACTOR_PROTOCOL_VERSION,
                            "requestId": request_id,
                            "operation": "close",
                        })
                        if self._connection.poll(self._grace):
                            message = self._connection.recv()
                            if (
                                not isinstance(message, dict)
                                or message.get("protocolVersion") != PINE_REALTIME_ACTOR_PROTOCOL_VERSION
                                or message.get("type") != "closed"
                                or message.get("requestId") != request_id
                            ):
                                _record("protocolErrors")
                            else:
                                self._process.join(self._grace)
                    except (BrokenPipeError, EOFError, OSError):
                        pass
            finally:
                self._fatal_close()

    def _fatal_close(self) -> None:
        if self._closed:
            return
        process = self._process
        connection = self._connection
        self._closed = True
        _terminate_process(process, self._grace)
        if process is not None:
            process.join(max(self._grace, 0.0))
        if connection is not None:
            connection.close()
        self._connection = None
        if self._slot_reserved:
            self._slot_reserved = False
            _release_slot()

    def __del__(self) -> None:  # pragma: no cover - defensive interpreter cleanup
        try:
            self.close()
        except Exception:
            pass
