from __future__ import annotations

import json
from dataclasses import replace

import pytest

from candlescope_plugin_sdk import (
    BARS_PATCH_BASE_UNKNOWN,
    FEATURE_BATCH_BARS_PATCH_V1,
    FEATURE_BATCH_EXECUTION_V1,
    FEATURE_RENDER_LINE_SERIES_V1,
    MAX_BARS_STREAMS,
    PROTOCOL_V1,
    Bar,
    BarsBase,
    BaseRuntimePlugin,
    Diagnostic,
    ExecuteBatchRequest,
    ExecuteBatchResult,
    LanguageDescriptor,
    MarketContext,
    ProtocolError,
    RenderOutput,
    RuntimeDescriptor,
    RuntimeDispatcher,
)

CONTEXT = MarketContext("binance", "spot", "BTCUSDT", "1m")


def _bar(index: int, close: float = 100.0, closed: bool = True) -> Bar:
    return Bar(time=1_700_000_000 + index * 60, open=close, high=close + 1, low=close - 1,
               close=close, volume=1, is_closed=closed)


def _request(bars, **fields) -> ExecuteBatchRequest:
    return ExecuteBatchRequest(source="plot(close)", context=CONTEXT, bars=tuple(bars), **fields)


class _RecordingPlugin(BaseRuntimePlugin):
    def __init__(self) -> None:
        self.seen: list[ExecuteBatchRequest] = []
        self.result = ExecuteBatchResult(ok=True, output=RenderOutput())

    def describe(self) -> RuntimeDescriptor:
        return RuntimeDescriptor(
            id="bars-runtime", name="Bars", version="1.0.0", package="bars",
            languages=(LanguageDescriptor(id="p", name="P"),),
            features=(FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_LINE_SERIES_V1, FEATURE_BATCH_BARS_PATCH_V1),
            required_host_features=(),
        )

    def analyze(self, request):  # pragma: no cover - not used
        raise NotImplementedError

    def execute_batch(self, request: ExecuteBatchRequest) -> ExecuteBatchResult:
        self.seen.append(request)
        return self.result


def _dispatcher(*features: str) -> tuple[RuntimeDispatcher, _RecordingPlugin]:
    plugin = _RecordingPlugin()
    dispatcher = RuntimeDispatcher(plugin)
    dispatcher.dispatch("handshake", {"protocols": [PROTOCOL_V1], "host": {"name": "h", "version": "1"},
                                      "hostFeatures": [FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_LINE_SERIES_V1, *features]})
    return dispatcher, plugin


def _send(dispatcher: RuntimeDispatcher, request: ExecuteBatchRequest) -> dict:
    # Through JSON, as over the sidecar transport.
    return dispatcher.dispatch("executeBatch", json.loads(json.dumps(request.to_wire())))


def test_request_names_its_bars_base_only_when_it_has_one() -> None:
    bars = (_bar(0), _bar(1))
    assert "barsPatch" not in _request(bars).to_wire()
    assert _request(bars, bars_stream="live").to_wire()["barsPatch"] == {"stream": "live", "base": None}
    patched = _request(bars, bars_stream="live", bars_base=BarsBase("b1", 2, 30))
    wire = patched.to_wire()
    assert wire["barsPatch"] == {"stream": "live", "base": "b1", "skip": 2, "keep": 30}
    assert ExecuteBatchRequest.from_wire(json.loads(json.dumps(wire))) == patched
    with pytest.raises(ProtocolError, match="stream"):
        _request(bars, bars_base=BarsBase("b1", 0, 1))
    with pytest.raises(ProtocolError, match="negative"):
        BarsBase("b1", 0, -1)
    for invalid in ({"stream": "live", "base": None, "keep": 3}, {"stream": "live", "base": "b1"},
                    {"base": None}, {"stream": "live", "base": 7, "skip": 0, "keep": 0}):
        with pytest.raises(ProtocolError):
            ExecuteBatchRequest.from_wire({**_request(bars).to_wire(), "barsPatch": invalid})
    result = ExecuteBatchResult(ok=True, output=RenderOutput(), bars_revision="b2")
    assert ExecuteBatchResult.from_wire(json.loads(json.dumps(result.to_wire()))) == result
    with pytest.raises(ProtocolError, match="must not contain output"):
        ExecuteBatchResult(ok=False, diagnostics=(Diagnostic("E", "error", "failed"),), bars_revision="b2")


def test_dispatcher_rebuilds_the_window_from_the_base_it_holds() -> None:
    dispatcher, plugin = _dispatcher(FEATURE_BATCH_BARS_PATCH_V1)
    window = [_bar(i) for i in range(10)] + [_bar(10, 101, closed=False)]
    first = _send(dispatcher, _request(window, bars_stream="live"))
    held = plugin.seen[-1].bars
    assert held == tuple(window) and first["barsRevision"]

    # Slide by two, re-form the open bar and append one more.
    window = window[2:10] + [_bar(10, 102), _bar(11, 103, closed=False)]
    tail = window[8:]
    second = _send(dispatcher, _request(tail, bars_stream="live", bars_base=BarsBase(first["barsRevision"], 2, 8)))
    rebuilt = plugin.seen[-1]
    assert rebuilt.bars == tuple(window) and rebuilt.bars_base is None and rebuilt.bars_stream == "live"
    # Kept bars are the very objects the runtime already held.
    assert all(a is b for a, b in zip(rebuilt.bars[:8], held[2:10]))
    assert second["barsRevision"] != first["barsRevision"]

    # Only the latest revision is a base.
    with pytest.raises(ProtocolError) as error:
        _send(dispatcher, _request(tail, bars_stream="live", bars_base=BarsBase(first["barsRevision"], 0, 1)))
    assert error.value.code == BARS_PATCH_BASE_UNKNOWN
    # The rejected request dropped the base too: only a full window is accepted next.
    with pytest.raises(ProtocolError, match="resend all bars"):
        _send(dispatcher, _request(tail, bars_stream="live", bars_base=BarsBase(second["barsRevision"], 0, 8)))
    latest = _send(dispatcher, _request(window, bars_stream="live"))["barsRevision"]
    # The kept bars must lie inside the base window.
    with pytest.raises(ProtocolError, match="resend all bars"):
        _send(dispatcher, _request(tail, bars_stream="live", bars_base=BarsBase(latest, 1, 10)))


def test_failed_requests_and_eviction_drop_bases() -> None:
    dispatcher, plugin = _dispatcher(FEATURE_BATCH_BARS_PATCH_V1)
    window = [_bar(i) for i in range(4)]
    revision = _send(dispatcher, _request(window, bars_stream="live"))["barsRevision"]
    plugin.result = ExecuteBatchResult(ok=False, diagnostics=(Diagnostic("E", "error", "failed"),))
    failed = _send(dispatcher, _request(window[3:], bars_stream="live", bars_base=BarsBase(revision, 0, 3)))
    assert failed["ok"] is False and "barsRevision" not in failed
    with pytest.raises(ProtocolError, match="resend all bars"):
        _send(dispatcher, _request(window[3:], bars_stream="live", bars_base=BarsBase(revision, 0, 3)))

    plugin.result = ExecuteBatchResult(ok=True, output=RenderOutput())
    revisions = {name: _send(dispatcher, _request(window, bars_stream=name))["barsRevision"]
                 for name in ["live", *(f"other-{index}" for index in range(MAX_BARS_STREAMS))]}
    with pytest.raises(ProtocolError, match="resend all bars"):
        _send(dispatcher, _request((), bars_stream="live", bars_base=BarsBase(revisions["live"], 0, 4)))
    _send(dispatcher, _request((), bars_stream="other-0", bars_base=BarsBase(revisions["other-0"], 0, 4)))
    assert plugin.seen[-1].bars == tuple(window)


def test_dispatcher_owns_bars_revisions_and_negotiation() -> None:
    old_host, plugin = _dispatcher()
    bars = (_bar(0), _bar(1))
    answer = _send(old_host, _request(bars))
    assert answer["ok"] and "barsRevision" not in answer
    with pytest.raises(ProtocolError, match="batch-execution.bars-patch/1"):
        _send(old_host, _request(bars, bars_stream="live"))

    dispatcher, plugin = _dispatcher(FEATURE_BATCH_BARS_PATCH_V1)
    assert "barsRevision" not in _send(dispatcher, _request(bars))
    plugin.result = replace(plugin.result, bars_revision="forged")
    with pytest.raises(ProtocolError, match="must not set barsRevision"):
        _send(dispatcher, _request(bars, bars_stream="live"))
