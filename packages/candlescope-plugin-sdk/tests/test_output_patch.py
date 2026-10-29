from __future__ import annotations

import json

import pytest

from candlescope_plugin_sdk import (
    FEATURE_BATCH_EXECUTION_V1,
    FEATURE_RENDER_LINE_SERIES_V1,
    FEATURE_RENDER_OUTPUT_PATCH_V1,
    PROTOCOL_V1,
    BaseRuntimePlugin,
    Bar,
    ExecuteBatchRequest,
    ExecuteBatchResult,
    LanguageDescriptor,
    LinePoint,
    LineSeries,
    ListSplice,
    MarketContext,
    ProtocolError,
    RecordPatch,
    RenderCollections,
    RenderOutput,
    RenderPatch,
    RuntimeDescriptor,
    RuntimeDispatcher,
)


def _output(points: int, *, color: str = "#fff") -> RenderOutput:
    data = [{"time": i, "value": float(i)} for i in range(points)]
    colors = [{"time": i, "color": color} for i in range(points)]
    return RenderOutput(
        series=(LineSeries(id="a", title="A", points=tuple(LinePoint(**item) for item in data),
                           style={"color": color, "colorData": colors}),),
        collections=RenderCollections(
            lines=({"id": "a", "title": "A", "data": data, "style": {"colorData": colors}},),
            hlines=({"id": "h", "price": 1},),
            objects={"scene": [1, 2]},
        ),
        meta={"points": points},
    )


def _round_trip(patch: RenderPatch) -> RenderPatch:
    return RenderPatch.from_wire(json.loads(json.dumps(patch.to_wire())))


def test_patch_rebuilds_exactly_the_full_output() -> None:
    base, target = _output(5), _output(7, color="#000")
    patch = RenderPatch(
        base="r1",
        series=(RecordPatch(base=0, values={"style": {"color": "#000"}}, splices=(
            ListSplice(("data",), 4, tuple(point.to_wire() for point in target.series[0].points[4:])),
            ListSplice(("style", "colorData"), 0, tuple(target.series[0].style["colorData"])),
        )),),
        collections={
            "lines": (RecordPatch(base=0, splices=(
                ListSplice(("data",), 5, tuple(target.collections.lines[0]["data"][5:])),
                ListSplice(("style", "colorData"), 0, tuple(target.collections.lines[0]["style"]["colorData"])),
            )),),
        },
        meta={"points": 7},
    )
    patched = _round_trip(patch).apply(base)
    assert patched.series == target.series
    assert patched.collections.lines == target.collections.lines
    # Fields the patch does not name carry over from the base.
    assert patched.collections.hlines == base.collections.hlines
    assert patched.collections.objects == base.collections.objects
    assert patched.meta == {"points": 7}
    # The base is left untouched.
    assert base == _output(5)


def test_patch_replaces_records_and_value_fields_and_drops_missing_records() -> None:
    base = _output(3)
    patch = RenderPatch(base="r1", series=(), collections={
        "hlines": (RecordPatch(values={"id": "k", "price": 2}),),
        "lines": (),
        "objects": None,
    })
    patched = patch.apply(base)
    assert patched.series == ()
    assert patched.collections == RenderCollections(hlines=({"id": "k", "price": 2},))


@pytest.mark.parametrize(
    "patch",
    [
        RenderPatch(base="r1", series=(RecordPatch(base=1),)),
        RenderPatch(base="r1", series=(RecordPatch(base=0, splices=(ListSplice(("data",), 9),)),)),
        RenderPatch(base="r1", series=(RecordPatch(base=0, values={"unknown": 1}),)),
        RenderPatch(base="r1", series=(RecordPatch(base=0, splices=(ListSplice(("other",), 0),)),)),
        RenderPatch(base="r1", collections={"lines": (RecordPatch(base=0, splices=(ListSplice(("data",), 9),)),)}),
        RenderPatch(base="r1", collections={"lines": (RecordPatch(base=0, splices=(ListSplice(("id", "x"), 0),)),)}),
    ],
)
def test_patch_that_does_not_fit_its_base_is_rejected(patch: RenderPatch) -> None:
    with pytest.raises(ProtocolError):
        patch.apply(_output(3))


def test_patch_validates_new_values_like_a_full_output() -> None:
    with pytest.raises(ProtocolError, match="finite"):
        ListSplice(("data",), 0, ({"time": 1, "value": float("nan")},))
    with pytest.raises(ProtocolError, match="unique"):
        RecordPatch(values={"data": []}, splices=(ListSplice(("data",), 0),))
    with pytest.raises(ProtocolError, match="unsupported"):
        RenderPatch(base="r1", collections={"other": ()})
    point = RenderPatch(base="r1", series=(RecordPatch(base=0, splices=(
        ListSplice(("data",), 3, ({"time": 9, "value": "x"},)),)),))
    with pytest.raises(ProtocolError, match="number"):
        point.apply(_output(3))


def test_result_carries_output_or_patch_with_a_revision() -> None:
    patch = RenderPatch(base="r1")
    result = ExecuteBatchResult(ok=True, output_patch=patch, output_revision="r2")
    assert ExecuteBatchResult.from_wire(json.loads(json.dumps(result.to_wire()))) == result
    assert result.to_wire()["output"] is None
    # The series list is always complete; unnamed collections carry over.
    assert result.patched(_output(2)) == ExecuteBatchResult(ok=True, output=RenderOutput(
        collections=_output(2).collections), output_revision="r2")
    with pytest.raises(ProtocolError, match="outputRevision"):
        ExecuteBatchResult(ok=True, output_patch=patch)
    with pytest.raises(ProtocolError, match="output or outputPatch"):
        ExecuteBatchResult(ok=True, output=_output(1), output_patch=patch, output_revision="r2")
    assert "outputRevision" not in ExecuteBatchResult(ok=True, output=_output(1)).to_wire()


def _request(**changes) -> ExecuteBatchRequest:
    return ExecuteBatchRequest(
        source="plot(close)",
        context=MarketContext(exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m"),
        bars=(Bar(time=1, open=1, high=1, low=1, close=1, volume=1),),
        **changes,
    )


def test_request_names_its_stream_only_when_it_accepts_patches() -> None:
    assert "outputPatch" not in _request().to_wire()
    wire = _request(output_stream="live", output_base="r1").to_wire()
    assert wire["outputPatch"] == {"stream": "live", "base": "r1"}
    assert ExecuteBatchRequest.from_wire(wire) == _request(output_stream="live", output_base="r1")
    with pytest.raises(ProtocolError, match="stream"):
        _request(output_base="r1")


class _PatchingPlugin(BaseRuntimePlugin):
    def __init__(self, result: ExecuteBatchResult) -> None:
        self.result = result

    def describe(self) -> RuntimeDescriptor:
        return RuntimeDescriptor(
            id="patching-runtime", name="Patching", version="1.0.0", package="patching",
            languages=(LanguageDescriptor(id="p", name="P"),),
            features=(FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_LINE_SERIES_V1, FEATURE_RENDER_OUTPUT_PATCH_V1),
            required_host_features=(),
        )

    def analyze(self, request):  # pragma: no cover - not used
        raise NotImplementedError

    def execute_batch(self, request: ExecuteBatchRequest) -> ExecuteBatchResult:
        return self.result


def _dispatcher(result: ExecuteBatchResult, *features: str) -> RuntimeDispatcher:
    dispatcher = RuntimeDispatcher(_PatchingPlugin(result))
    dispatcher.dispatch("handshake", {"protocols": [PROTOCOL_V1], "host": {"name": "h", "version": "1"},
                                      "hostFeatures": [FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_LINE_SERIES_V1, *features]})
    return dispatcher


def test_dispatcher_enforces_negotiation_and_the_requested_base() -> None:
    full = ExecuteBatchResult(ok=True, output=_output(1))
    patch = ExecuteBatchResult(ok=True, output_patch=RenderPatch(base="r1"), output_revision="r2")
    old_host = _dispatcher(full)
    assert old_host.dispatch("executeBatch", _request().to_wire())["output"] is not None
    with pytest.raises(ProtocolError, match="render.output-patch/1"):
        old_host.dispatch("executeBatch", _request(output_stream="live").to_wire())

    host = _dispatcher(patch, FEATURE_RENDER_OUTPUT_PATCH_V1)
    assert host.dispatch("executeBatch", _request(output_stream="live", output_base="r1").to_wire())["outputPatch"]
    for request in (_request(), _request(output_stream="live"), _request(output_stream="live", output_base="r0")):
        with pytest.raises(ProtocolError, match="did not request"):
            host.dispatch("executeBatch", request.to_wire())
    revised = ExecuteBatchResult(ok=True, output=_output(1), output_revision="r2")
    with pytest.raises(ProtocolError, match="did not request"):
        _dispatcher(revised, FEATURE_RENDER_OUTPUT_PATCH_V1).dispatch("executeBatch", _request().to_wire())
