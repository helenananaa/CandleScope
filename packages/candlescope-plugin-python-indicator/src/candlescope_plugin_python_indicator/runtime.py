"""Python batch indicators through the existing public script runtime SDK."""
from candlescope_plugin_sdk import (
    AnalyzeResult, BaseRuntimePlugin, Diagnostic, ExecuteBatchResult,
    FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_HISTOGRAM_SERIES_V1,
    FEATURE_RENDER_LINE_SERIES_V1, FEATURE_SOURCE_ANALYSIS_V1,
    LanguageDescriptor, LinePoint, LineSeries, RenderOutput, RuntimeDescriptor,
)
from .author import analyze, AuthorError, MAX_BARS
from .executor import execute

RUNTIME_ID = "candlescope.python-indicator"
STARTER = '''INDICATOR = {
    "name": "Python SMA", "overlay": True, "window": 500,
    "parameters": [{"name": "length", "type": "int", "default": 20, "min": 1, "max": 500}],
    "outputs": [{"id": "ma", "title": "SMA", "type": "line", "color": "#f59e0b"}],
}

def compute(bars, params):
    length = params["length"]
    close = bars["close"]
    values = [None] * len(close)
    for i in range(length - 1, len(close)):
        values[i] = sum(close[i-length+1:i+1]) / length
    return {"lines": {"ma": values}}
'''


def inputs(declaration):
    return tuple({**p, "key": p["name"], "title": p.get("title", p["name"])}
                 for p in declaration.parameters)


def diagnostic(error):
    return Diagnostic(code="PYTHON_INDICATOR_ERROR", severity="error", message=str(error),
                      span={"line": error.line, "column": error.column or 1} if error.line else None)


class PythonIndicatorRuntime(BaseRuntimePlugin):
    def describe(self):
        return RuntimeDescriptor(
            id=RUNTIME_ID, name="Python Indicators", version="0.1.0",
            package="candlescope-plugin-python-indicator",
            languages=(LanguageDescriptor(id="python", name="Python", extensions=(".py",)),),
            features=(FEATURE_SOURCE_ANALYSIS_V1, FEATURE_BATCH_EXECUTION_V1,
                      FEATURE_RENDER_LINE_SERIES_V1, FEATURE_RENDER_HISTOGRAM_SERIES_V1),
            required_host_features=(FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_LINE_SERIES_V1,
                                    FEATURE_RENDER_HISTOGRAM_SERIES_V1),
            meta={"closedBarsOnly": True, "formingBar": False, "incremental": False,
                  "executorBoundary": "fresh-process-per-batch", "dependencyProfile": "stdlib",
                  "historyPlanning": "declared-finite-window", "causality": "unverified",
                  "ui": {"languages": {"python": {"monacoLanguage": "python", "starterSource": STARTER}}}},
        )

    def analyze(self, request):
        try:
            declaration = analyze(request.source)
            return AnalyzeResult(ok=True, executable=True, inputs=inputs(declaration),
                                 meta=declaration.to_wire())
        except AuthorError as error:
            return AnalyzeResult(ok=False, executable=False, diagnostics=(diagnostic(error),))

    def execute_batch(self, request):
        try:
            if len(request.bars) > MAX_BARS:
                raise AuthorError("At most 10000 standard OHLCV bars are supported")
            declaration = analyze(request.source)
            bars = request.bars
            # Only a forming tail is permitted. Dropping an interior unconfirmed
            # bar would silently change adjacency and the author's formula.
            confirmed = len(bars)
            while confirmed and not bars[confirmed-1].is_closed:
                confirmed -= 1
            if any(not bar.is_closed for bar in bars[:confirmed]):
                raise AuthorError("Unconfirmed interior bars require source repair")
            start = max(0, confirmed - declaration.window)
            selected = [bar.to_wire() for bar in bars[start:confirmed]]
            declaration, values = execute(request.source, selected, request.params)
            series = tuple(LineSeries(
                id=output["id"], title=output.get("title", output["id"]),
                series_type=output.get("type", "line"),
                pane="main" if declaration.overlay else "python-indicator",
                style={"color": output.get("color", "#f59e0b"), "lineWidth": 2},
                points=tuple(LinePoint(bar.time, value) for bar, value in zip(bars,
                    [None]*start + values[output["id"]] + [None]*(len(bars)-confirmed))),
            ) for output in declaration.outputs)
            meta={**declaration.to_wire(), "inputWindow": {"requestedBars": len(bars),
                  "confirmedBars": confirmed, "computedBars": len(selected), "offset": start,
                  "formingBarsExcluded": len(bars)-confirmed}, "closedBarsOnly": True}
            return ExecuteBatchResult(ok=True, output=RenderOutput(series=series, meta=meta),
                                      inputs=inputs(declaration), meta=meta)
        except AuthorError as error:
            return ExecuteBatchResult(ok=False, diagnostics=(diagnostic(error),))
