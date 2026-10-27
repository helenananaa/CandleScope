"""Live output patches must leave the host with exactly the full snapshot."""

import json
import random
from dataclasses import replace

import pytest

from candlescope_plugin_sdk import (
    KNOWN_FEATURES_V1,
    PROTOCOL_V1,
    Bar,
    ExecuteBatchRequest,
    ExecuteBatchResult,
    MarketContext,
    ProtocolError,
    RuntimeDispatcher,
)
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin

CONTEXT = MarketContext("binance", "spot", "BTCUSDT", "1m")
SCRIPTS = {
    "plots-varip-offsets": (
        '//@version=6\nindicator("a")\nvarip int ticks = 0\nticks += 1\n'
        'plot(close, "c", color=close > open ? color.green : color.red)\n'
        'plot(close * 2, "ahead", offset=2)\n'
        'plot(close / 2, "behind", offset=-3, style=plot.style_histogram)\n'
        'plot(ticks % 7 == 0 ? na : ticks, "ticks")\n'
    ),
    "shapes-fills-alerts": (
        '//@version=6\nindicator("b", overlay=true)\na = ta.sma(close, 3)\n'
        'p1 = plot(a)\np2 = plot(close)\nh1 = hline(100.5)\nh2 = hline(99.5)\n'
        'fill(p1, p2, color=close > a ? color.new(color.blue, 80) : na)\n'
        'fill(h1, h2, color=color.new(color.gray, 90))\n'
        'plotshape(close > a, style=shape.circle, location=location.belowbar)\n'
        'plotshape(barstate.isrealtime and close > open, style=shape.square)\n'
        'bgcolor(bar_index % 3 == 0 ? color.new(color.red, 90) : na)\n'
        'barcolor(close > a ? color.lime : na)\n'
        'if close > a\n    alert("up " + str.tostring(close))\n'
    ),
    "drawings-scenes": (
        '//@version=6\nindicator("c", overlay=true, max_labels_count=5, max_lines_count=5)\n'
        'plotchar(close > open, char="x")\n'
        'if bar_index % 4 == 0\n    label.new(bar_index, high, str.tostring(close))\n'
        'var line l = na\nif barstate.islast\n    line.delete(l)\n'
        '    l := line.new(bar_index - 5, low, bar_index, high)\n'
        'a = plot(close + 2)\nb = plot(close - 2)\n'
    ),
    "gradient-fill": (
        '//@version=6\nindicator("g")\na = plot(close + 2)\nb = plot(close - 2)\n'
        'fill(a, b, close + 1, close - 1, color.green, color.red)\n'
    ),
    "calc-bars-count": '//@version=6\nindicator("d", calc_bars_count=50)\nplot(ta.ema(close, 5))\n',
    "show-last": '//@version=6\nindicator("e")\nplot(close, show_last=20)\nplot(close * 2)\n',
}


def make_bar(index, close, closed=True):
    return Bar(time=1_700_000_000 + index * 60, open=round(close - 0.25, 6), high=round(close + 0.5, 6),
               low=round(close - 0.5, 6), close=round(close, 6), volume=10, is_closed=closed)


class Host:
    """One subscription's host: JSON-RPC wire plus, optionally, the patch base."""

    def __init__(self, journal, *, patches):
        self.journal, self.patches = journal, patches
        self.base = None
        self.counts = {"patch": 0, "full": 0}
        self.start()

    def start(self):
        # A restarted plugin keeps its journal; a patching host keeps its stale base.
        if hasattr(self, "plugin"):
            self.plugin.shutdown()
        self.plugin = PineCompatRuntimePlugin(journal_path=self.journal)
        self.dispatcher = RuntimeDispatcher(self.plugin)
        self.dispatcher.dispatch("handshake", {"protocols": [PROTOCOL_V1], "host": {"name": "test", "version": "1"},
                                               "hostFeatures": list(KNOWN_FEATURES_V1)})

    def execute(self, request, stream="live"):
        if self.patches:
            request = replace(request, output_stream=stream, output_base=self.base[0] if self.base else None)
        self.wire = json.loads(json.dumps(self.dispatcher.dispatch("executeBatch", request.to_wire()), allow_nan=False))
        result = ExecuteBatchResult.from_wire(self.wire)
        assert result.ok, result.diagnostics
        if result.output_patch is not None:
            self.counts["patch"] += 1
            result = result.patched(self.base[1])
        elif self.patches:
            self.counts["full"] += 1
        if self.patches and stream == "live":
            self.base = (result.output_revision, result.output)
        return replace(result, output_revision=None)


def assert_same(patched, full):
    assert patched == full
    # Byte-identical wire, key order included.
    assert json.dumps(patched.to_wire()) == json.dumps(full.to_wire())


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_patched_live_updates_match_full_snapshots(tmp_path, name):
    source = SCRIPTS[name]
    rng = random.Random(f"output-patch-{name}")
    patched = Host(tmp_path / "patched.sqlite3", patches=True)
    full = Host(tmp_path / "full.sqlite3", patches=False)
    closes = [100 + rng.uniform(-1, 1) for _ in range(120)]
    window, forming = 0, None
    events = []

    def request(bars, identity="live"):
        return ExecuteBatchRequest(source=source, context=CONTEXT, bars=tuple(bars),
                                   options={"pineSessionId": identity})

    def step(event):
        events.append(event)
        bars = [make_bar(i, close) for i, close in enumerate(closes)][window:]
        if forming is not None:
            bars.append(make_bar(len(closes), forming, closed=False))
        assert_same(patched.execute(request(bars)), full.execute(request(bars)))

    step("seed")
    for _ in range(80):
        action = rng.choices(
            ["tick", "confirm", "catchup", "slide", "repeat", "correct", "shorten", "restart", "evict"],
            weights=[40, 12, 10, 8, 5, 3, 2, 2, 2])[0]
        if action == "tick":
            forming = (forming if forming is not None else closes[-1]) + rng.uniform(-0.6, 0.6)
        elif action == "confirm" and forming is not None:
            closes.append(forming)
            forming = None
        elif action == "catchup":
            # Several bars confirmed at once, the open bar among them.
            if forming is not None:
                closes.append(forming)
            closes.extend(closes[-1] + rng.uniform(-1, 1) for _ in range(rng.choice([2, 3, 3, 64])))
            forming = closes[-1] + 0.1 if rng.random() < 0.5 else None
        elif action == "slide":
            window = min(window + rng.randint(1, 8), len(closes) - 5)
        elif action == "correct":
            closes[rng.randrange(window, len(closes))] += 0.37
        elif action == "shorten" and forming is None and len(closes) - window > 10:
            closes.pop()
        elif action == "restart":
            patched.start()
            full.start()
        elif action == "evict":
            for other in range(9):
                bars = [make_bar(i, 100 + other) for i in range(5)]
                patched.execute(request(bars, f"other-{other}"), stream=f"other-{other}")
                full.execute(request(bars, f"other-{other}"))
        step(action)
    if name == "show-last":
        # show_last moves the visible start every bar; it always answers in full.
        assert patched.counts["patch"] == 0
    else:
        assert patched.counts["patch"] > 45, (patched.counts, events)
    assert patched.counts["full"] > 0


def test_forming_tick_patch_carries_only_the_changed_tail(tmp_path):
    host = Host(tmp_path / "journal.sqlite3", patches=True)
    history = [make_bar(i, 100 + i * 0.01) for i in range(2000)]
    source = SCRIPTS["plots-varip-offsets"]

    def run(close):
        bars = (*history, make_bar(2000, close, closed=False))
        host.execute(ExecuteBatchRequest(source=source, context=CONTEXT, bars=bars, options={"pineSessionId": "live"}))
        return host.wire

    full = run(120)
    tick = run(120.5)
    assert full["output"] is not None and "outputPatch" not in full
    assert tick["output"] is None and tick["outputPatch"]["base"] == full["outputRevision"]
    appended = [len(splice["append"]) for record in tick["outputPatch"]["series"] for splice in record["splice"]]
    assert appended and max(appended) <= 1
    assert len(json.dumps(tick)) * 50 < len(json.dumps(full))


def test_patches_require_negotiation_and_a_matching_base(tmp_path):
    plugin = PineCompatRuntimePlugin(journal_path=tmp_path / "journal.sqlite3")
    dispatcher = RuntimeDispatcher(plugin)
    dispatcher.dispatch("handshake", {"protocols": [PROTOCOL_V1], "host": {"name": "old", "version": "1"},
                                      "hostFeatures": [f for f in KNOWN_FEATURES_V1 if f != "render.output-patch/1"]})
    bars = tuple(make_bar(i, 100 + i) for i in range(5))
    request = ExecuteBatchRequest(source=SCRIPTS["calc-bars-count"], context=CONTEXT, bars=bars,
                                  options={"pineSessionId": "live"})
    # An old host never sees revisions or patches.
    answer = dispatcher.dispatch("executeBatch", request.to_wire())
    assert answer["output"] is not None and not {"outputPatch", "outputRevision"} & set(answer)
    with pytest.raises(ProtocolError, match="render.output-patch/1"):
        dispatcher.dispatch("executeBatch", replace(request, output_stream="live").to_wire())

    host = Host(tmp_path / "patched.sqlite3", patches=True)
    host.execute(request)
    stale = replace(request, bars=(*bars, make_bar(5, 106, closed=False)), output_stream="live", output_base="stale")
    answer = host.dispatcher.dispatch("executeBatch", stale.to_wire())
    assert answer["output"] is not None and "outputPatch" not in answer
