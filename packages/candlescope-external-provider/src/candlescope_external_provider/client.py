"""Explicit loopback HTTP delivery; no Host imports or database access."""

from __future__ import annotations

import http.client
import ipaddress
import os
import threading
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from .errors import ExternalProviderError
from .wire import MAX_MESSAGE_BYTES, decode, digest, encode

PROTOCOL = "candlescope.external-provider-connection/1"
ENDPOINT_SCHEMA = "candlescope.external-provider-endpoint/1"


class Model(Protocol):
    def prepare(self, context: dict[str, Any]) -> None: ...
    def warmup(self, observation: dict[str, Any]) -> None: ...
    def step(self, observation: dict[str, Any]) -> dict[str, Any] | None: ...
    def on_execution_report(self, report: dict[str, Any]) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...
    def restore(self, state: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


def _fail(message: str) -> None:
    raise ExternalProviderError("PROVIDER_PROTOCOL_VIOLATION", message)


def _file(path: Path, limit: int) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    value = decode(raw, max_bytes=limit)
    if type(value) is not dict:
        _fail("connection metadata must be an object")
    return value


class ExternalClient:
    def __init__(self, connection_file: Path, manifest: dict[str, Any], factory: Callable[[], Model], *,
                 request_timeout_s: float = 1.0, poll_interval_s: float = 0.025) -> None:
        self.connection_file = Path(connection_file)
        self.manifest = decode(encode(manifest))
        self.factory = factory
        self.request_timeout_s = request_timeout_s
        self.poll_interval_s = poll_interval_s
        if request_timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("external client timeouts must be positive")
        self.client_id = "sdk_" + uuid.uuid4().hex
        self._document: dict[str, Any] | None = None
        self._endpoint: tuple[str, int, str] | None = None
        self._http: http.client.HTTPConnection | None = None
        self._generation: int | None = None
        self._models: dict[str, dict[str, Any]] = {}
        self._pending: tuple[dict[str, Any], dict[str, Any]] | None = None

    def _load_document(self) -> None:
        if os.name != "nt" and self.connection_file.stat().st_mode & 0o077:
            raise ExternalProviderError("PROVIDER_UNAUTHORIZED_WRITE", "connection credential file must be private to its owner")
        document = _file(self.connection_file, 65_536)
        if set(document) != {"schema_version", "connection_id", "token", "host_endpoint_file", "scope"}:
            _fail("invalid private connection fields")
        if document["schema_version"] != PROTOCOL or type(document["scope"]) is not dict:
            _fail("unsupported private connection schema")
        connection_id = document["connection_id"]
        if (type(connection_id) is not str or len(connection_id) != 36 or not connection_id.startswith("epc_")
                or any(char not in "0123456789abcdef" for char in connection_id[4:])):
            _fail("invalid connection identity")
        if type(document["token"]) is not str or not 20 <= len(document["token"]) <= 256:
            _fail("invalid connection credential")
        endpoint_file = document["host_endpoint_file"]
        if type(endpoint_file) is not str or not Path(endpoint_file).is_absolute():
            _fail("Host endpoint file must be absolute")
        if document["scope"].get("manifest_hash") != digest(self.manifest):
            raise ExternalProviderError("IDENTITY_MUTATION", "model manifest differs from the frozen connection")
        self._document = document

    def _current_endpoint(self) -> tuple[str, int, str]:
        metadata = _file(Path(self._document["host_endpoint_file"]), 4096)
        if set(metadata) != {"schema_version", "host", "port", "instance_id"} or metadata["schema_version"] != ENDPOINT_SCHEMA:
            _fail("unsupported Host endpoint schema")
        host, port, instance = metadata["host"], metadata["port"], metadata["instance_id"]
        try:
            local = type(host) is str and ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if (not local or type(port) is not int or not 1 <= port <= 65535
                or type(instance) is not str or not 1 <= len(instance) <= 128):
            _fail("external client requires a valid numeric loopback Host endpoint")
        return host, port, instance

    def _response(self, maximum: int = MAX_MESSAGE_BYTES) -> tuple[int, dict[str, Any]]:
        response = self._http.getresponse()
        raw = response.read(maximum + 1)
        if len(raw) > maximum:
            self._disconnect()
            _fail("Host response exceeds its byte budget")
        payload = decode(raw, max_bytes=maximum)
        if type(payload) is not dict:
            _fail("Host response must be an object")
        return response.status, payload

    def _transport(self) -> None:
        endpoint = self._current_endpoint()
        if endpoint != self._endpoint:
            self._disconnect()
            self._generation = None
            self._drop_models()
            self._pending = None
            self._endpoint = endpoint
        if self._http is None:
            self._http = http.client.HTTPConnection(endpoint[0], endpoint[1], timeout=self.request_timeout_s)
            # Verify accidental port reuse before sending a capability token.
            self._http.request("GET", "/api/v1/backtests/provider-connections/endpoint")
            status, payload = self._response(4096)
            if status != 200 or payload != {"schema_version": ENDPOINT_SCHEMA, "instance_id": endpoint[2]}:
                self._disconnect()
                _fail("Host endpoint instance does not match its discovery file")

    def _post(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._transport()
        body = encode(payload).encode("utf-8")
        path = "/api/v1/backtests/provider-connections/" + self._document["connection_id"] + "/" + action
        self._http.request("POST", path, body=body,
                           headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._document["token"]})
        status, result = self._response()
        if status != 200:
            error = result.get("error")
            code = error.get("code") if type(error) is dict else None
            if type(code) is not str or len(code) > 80 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789" for char in code):
                code = "PROVIDER_PROTOCOL_VIOLATION"
            raise ExternalProviderError(code, "Host rejected the external connection request")
        return result

    def _connect(self) -> None:
        result = self._post("connect", {"schema_version": PROTOCOL, "client_id": self.client_id,
                                        "manifest_hash": digest(self.manifest)})
        if (result.get("scope") != self._document["scope"] or result.get("client_id") != self.client_id
                or type(result.get("client_generation")) is not int or result["client_generation"] < 1):
            _fail("Host lease does not match the frozen connection")
        self._generation = result["client_generation"]

    def _dispatch(self, packet: dict[str, Any]) -> dict[str, Any]:
        try:
            required = {"connection_id", "client_generation", "run_id", "host_generation", "cursor", "call_id",
                        "input_hash", "operation", "payload", "bootstrap"}
            if type(packet) is not dict or set(packet) != required or packet["connection_id"] != self._document["connection_id"]:
                _fail("invalid Host call identity")
            if (type(packet["client_generation"]) is not int or packet["client_generation"] != self._generation
                    or type(packet["host_generation"]) is not int or packet["host_generation"] < 1
                    or type(packet["cursor"]) is not int or packet["cursor"] < 1 or type(packet["run_id"]) is not str):
                _fail("invalid Host call generation or cursor")
            expected = digest({**{key: packet[key] for key in ("run_id", "cursor", "operation", "payload")},
                               "model_state_before_hash": packet["bootstrap"]["model_state_hash"]})
            if expected != packet["input_hash"]:
                _fail("Host call input hash is invalid")
            bootstrap = packet["bootstrap"]
            state, state_hash = bootstrap["model_state"], bootstrap["model_state_hash"]
            context = bootstrap["context"]
            if context["provider"]["manifest_hash"] != digest(self.manifest):
                _fail("Host call manifest differs from the frozen model")
            if (state_hash is None and state is not None) or (state_hash is not None and digest(state) != state_hash):
                _fail("Host model-state digest is invalid")
            run_id = packet["run_id"]
            context_hash = digest(context)
            entry = self._models.get(run_id)
            if entry is None or entry["generation"] != packet["host_generation"]:
                if len(self._models) >= 64 and entry is None:
                    raise ExternalProviderError("BUDGET_EXCEEDED", "external client active model ceiling reached")
                if entry is not None:
                    entry["model"].close()
                model = self.factory()
                entry = {"model": model, "generation": packet["host_generation"], "context_hash": context_hash, "state_hash": None}
                self._models[run_id] = entry
                if packet["operation"] != "prepare":
                    model.prepare(context["context"])
            if entry["context_hash"] != context_hash:
                _fail("Host changed a prepared model context")
            model = entry["model"]
            if state_hash is not None and entry["state_hash"] != state_hash:
                model.restore(decode(encode(state)))
            operation, payload = packet["operation"], packet["payload"]
            decision = None
            if operation == "prepare":
                model.prepare(payload["context"])
            elif operation in ("warmup", "step"):
                observation = payload["observation"]
                if (observation["run_id"] != run_id or observation["event_time_ms"] > observation["watermark_ms"]
                        or observation["phase"] != ("WARMUP" if operation == "warmup" else "EVALUATION")):
                    _fail("invalid Host observation clock")
                decision = model.warmup(observation) if operation == "warmup" else model.step(observation)
            elif operation == "onExecutionReport":
                model.on_execution_report(payload["report"])
            elif operation == "close":
                state = model.snapshot()
                model.close()
            else:
                _fail("unsupported Host operation")
            if operation != "close":
                state = model.snapshot()
            if type(state) is not dict:
                _fail("model snapshot must be an object")
            encode(state, max_bytes=8_388_608)
            result = {"decision": decision, "model_state": state}
            # Detach model-owned mutable state before any network retry.
            return decode(encode(result))
        except ExternalProviderError as exc:
            code = exc.code if exc.code in {"PROVIDER_PROTOCOL_VIOLATION", "BUDGET_EXCEEDED"} else "PROVIDER_PROTOCOL_VIOLATION"
        except Exception:  # noqa: BLE001 - arbitrary model errors become redacted protocol failures
            code = "PROVIDER_CRASH_UNRECOVERABLE"
        return {"error": {"code": code, "message": "external model lifecycle failed"}}

    def run(self, stopped: threading.Event | None = None) -> None:
        stopped = threading.Event() if stopped is None else stopped
        self._load_document()
        try:
            while not stopped.is_set():
                try:
                    self._transport()
                    if self._generation is None:
                        self._connect()
                    if self._pending is None:
                        delivery = self._post("poll", {"client_id": self.client_id, "client_generation": self._generation})
                        live = self._reconcile_sessions(delivery.get("active_sessions"))
                        packet = delivery.get("call")
                        if packet is None:
                            stopped.wait(self.poll_interval_s)
                            continue
                        if (packet.get("run_id"), packet.get("host_generation")) not in live:
                            continue  # Host retired it after selecting delivery.
                        self._pending = packet, self._dispatch(packet)
                    packet, result = self._pending
                    receipt = self._post("reply", {"client_id": self.client_id, "client_generation": self._generation,
                                                    **{key: packet[key] for key in ("run_id", "host_generation", "cursor", "call_id", "input_hash")},
                                                    "result": result})
                    state_hash = digest(result["model_state"]) if "model_state" in result else None
                    recorded = ({"decision": result["decision"], "model_state_hash": state_hash} if state_hash else result)
                    if receipt.get("call_id") != packet["call_id"] or receipt.get("reply_hash") != digest(recorded) or receipt.get("committed") is not True:
                        _fail("Host did not acknowledge the same external response")
                    entry = self._models.get(packet["run_id"])
                    if entry is not None:
                        entry["state_hash"] = state_hash
                    if packet["operation"] == "close" or "error" in result:
                        self._models.pop(packet["run_id"], None)
                    self._pending = None
                except (OSError, http.client.HTTPException):
                    self._disconnect()
                    self._generation = None
                    stopped.wait(0.1)
                except ExternalProviderError as exc:
                    if exc.code == "PROVIDER_STALE_GENERATION":
                        self._generation = None
                        self._pending = None
                        self._drop_models()
                        stopped.wait(0.025)
                    elif exc.code == "PROVIDER_CONNECTION_BUSY":
                        self._generation = None
                        stopped.wait(0.25)
                    else:
                        raise
        finally:
            self._disconnect()
            self._drop_models()

    def _drop_models(self) -> None:
        for entry in self._models.values():
            # A model cleanup error cannot mask the transport/model failure.
            with suppress(Exception):
                entry["model"].close()
        self._models.clear()

    def _reconcile_sessions(self, sessions: object) -> set[tuple[str, int]]:
        if type(sessions) is not list or len(sessions) > 64:
            _fail("invalid Host active model inventory")
        live = set()
        for entry in sessions:
            if (type(entry) is not dict or set(entry) != {"run_id", "host_generation"}
                    or type(entry["run_id"]) is not str or type(entry["host_generation"]) is not int
                    or entry["host_generation"] < 1):
                _fail("invalid Host active model identity")
            live.add((entry["run_id"], entry["host_generation"]))
        for run_id, entry in list(self._models.items()):
            if (run_id, entry["generation"]) not in live:
                with suppress(Exception):
                    entry["model"].close()
                del self._models[run_id]
        return live

    def _disconnect(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None
