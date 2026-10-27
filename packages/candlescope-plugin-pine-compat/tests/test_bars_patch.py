"""Bar patches must hand the plugin exactly the full request, and the host the full result."""

import json
import random
from bisect import bisect_left
from dataclasses import replace

import pytest

from candlescope_plugin_sdk import (
    BARS_PATCH_BASE_UNKNOWN,
    KNOWN_FEATURES_V1,
    PROTOCOL_V1,
    Bar,
    BarsBase,
    ExecuteBatchRequest,
    ExecuteBatchResult,
    ProtocolError,
    RuntimeDispatcher,
)
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
from test_output_patch import CONTEXT, SCRIPTS, make_bar


def delta(base, bars):
    """The supervisor's rule: keep only the very Bars sent at those base positions."""
    if not base or not bars:
        return None
    skip = bisect_left(base, bars[0].time, key=lambda bar: bar.time)
    if skip >= len(base) or base[skip] is not bars[0]:
        return None
    keep = 0
    while keep < min(len(bars), len(base) - skip) and bars[keep] is base[skip + keep]:
        keep += 1
    return skip, keep


class Host:
    """One host over the JSON wire; with patches it keeps output and bars bases.

    Unlike RuntimeSupervisor it keeps a stale base across plugin restarts and
    evictions, so those reach the runtime's BARS_PATCH_BASE_UNKNOWN answer and
    the full-request retry.
    """

    def __init__(self, journal, *, patches):
        self.journal, self.patches = journal, patches
        self.bars, self.outputs = {}, {}
        self.counts = {"patched": 0, "full": 0, "retried": 0, "sent": 0}
        self.start()

    def start(self):
        if hasattr(self, "plugin"):
            self.plugin.shutdown()
        self.plugin = PineCompatRuntimePlugin(journal_path=self.journal)
        self.seen = []
        execute = self.plugin.execute_batch

        def spy(request):
            self.seen.append(request)
            return execute(request)

        self.plugin.execute_batch = spy
        self.dispatcher = RuntimeDispatcher(self.plugin)
        self.dispatcher.dispatch("handshake", {"protocols": [PROTOCOL_V1], "host": {"name": "test", "version": "1"},
                                               "hostFeatures": list(KNOWN_FEATURES_V1)})

    def send(self, request):
        self.counts["sent"] += len(request.bars)
        wire = json.loads(json.dumps(request.to_wire(), allow_nan=False))
        return json.loads(json.dumps(self.dispatcher.dispatch("executeBatch", wire), allow_nan=False))

    def execute(self, request, stream="live"):
        if not self.patches:
            return ExecuteBatchResult.from_wire(self.send(request))
        held, output = self.bars.pop(stream, None), self.outputs.pop(stream, None)
        sent = replace(request, output_stream=stream, output_base=output[0] if output else None, bars_stream=stream)
        window = delta(held[1], request.bars) if held is not None else None
        if window is not None:
            sent = replace(sent, bars=request.bars[window[1]:], bars_base=BarsBase(held[0], *window))
        try:
            wire = self.send(sent)
            self.counts["patched" if window is not None else "full"] += 1
        except ProtocolError as error:
            assert error.code == BARS_PATCH_BASE_UNKNOWN and window is not None
            self.counts["retried"] += 1
            wire = self.send(replace(sent, bars=request.bars, bars_base=None, output_base=None))
            output = None
        result = ExecuteBatchResult.from_wire(wire)
        if result.output_patch is not None:
            result = result.patched(output[1])
        if result.ok:
            self.bars[stream] = (result.bars_revision, request.bars)
            self.outputs[stream] = (result.output_revision, result.output)
        return replace(result, output_revision=None, bars_revision=None)


def assert_same(patched, full, hosts):
    assert patched == full
    assert json.dumps(patched.to_wire()) == json.dumps(full.to_wire())
    # The plugin saw the same request: the window rebuilt from the base is the full one.
    seen = [replace(host.seen[-1], output_stream=None, output_base=None, bars_stream=None) for host in hosts]
    assert seen[0] == seen[1]


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_patched_requests_match_full_requests(tmp_path, name):
    source = SCRIPTS[name]
    rng = random.Random(f"bars-patch-{name}")
    patched = Host(tmp_path / "patched.sqlite3", patches=True)
    full = Host(tmp_path / "full.sqlite3", patches=False)
    closes = [100 + rng.uniform(-1, 1) for _ in range(120)]
    window, forming = 0, None
    # The host reuses the Bar of an unchanged row, as IndicatorRuntimeRequest does.
    built = {}
    events = []

    def bar(index, close, closed=True):
        key = (index, round(close, 6), closed)
        if key not in built:
            built[key] = make_bar(index, close, closed)
        return built[key]

    def request(bars, identity="live"):
        return ExecuteBatchRequest(source=source, context=CONTEXT, bars=tuple(bars),
                                   options={"pineSessionId": identity})

    def step(event):
        events.append(event)
        bars = [bar(i, close) for i, close in enumerate(closes)][window:]
        if forming is not None:
            bars.append(bar(len(closes), forming, closed=False))
        assert_same(patched.execute(request(bars)), full.execute(request(bars)), (patched, full))

    step("seed")
    for _ in range(80):
        action = rng.choices(
            ["tick", "confirm", "catchup", "slide", "repeat", "correct", "shorten", "restart", "evict", "rebuild"],
            weights=[40, 12, 10, 8, 5, 4, 2, 2, 2, 2])[0]
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
            # Anywhere in the window, the last confirmed bar included.
            index = rng.choice([len(closes) - 1, rng.randrange(window, len(closes))])
            closes[index] += 0.37
        elif action == "shorten" and forming is None and len(closes) - window > 10:
            closes.pop()
        elif action == "restart":
            # A restarted plugin keeps its journal; the patching host keeps its stale bases.
            patched.start()
            full.start()
        elif action == "evict":
            for other in range(9):
                bars = [make_bar(i, 100 + other) for i in range(5)]
                patched.execute(request(bars, f"other-{other}"), stream=f"other-{other}")
                full.execute(request(bars, f"other-{other}"))
        elif action == "rebuild":
            # Equal values in new Bar objects: correct, only not reusable.
            built.clear()
        step(action)
    assert patched.counts["patched"] > 50, (patched.counts, events)
    assert patched.counts["retried"] > 0 and patched.counts["full"] > 0, (patched.counts, events)
    # Restarts, evictions and rebuilt Bars resend whole windows; ticks send the tail.
    assert patched.counts["sent"] * 4 < full.counts["sent"], (patched.counts, full.counts)


def test_forming_tick_sends_only_the_open_bar(tmp_path):
    host = Host(tmp_path / "journal.sqlite3", patches=True)
    history = tuple(make_bar(i, 100 + i * 0.01) for i in range(2000))
    source = SCRIPTS["plots-varip-offsets"]
    sent = []
    send = host.send

    def recording(request):
        sent.append(request)
        return send(request)

    host.send = recording
    for close in (120, 120.5, 121):
        host.execute(ExecuteBatchRequest(source=source, context=CONTEXT, bars=(*history, make_bar(2000, close, closed=False)),
                                         options={"pineSessionId": "live"}))
    assert [len(request.bars) for request in sent] == [2001, 1, 1]
    assert sent[1].bars_base.skip == 0 and sent[1].bars_base.keep == 2000
    assert host.seen[-1].bars[:2000] == history


def test_invalid_windows_fail_exactly_like_full_requests(tmp_path):
    source = SCRIPTS["calc-bars-count"]
    history = [make_bar(i, 100 + i * 0.1) for i in range(20)]
    open_bar = make_bar(20, 103, closed=False)
    later = make_bar(21, 104)
    windows = {
        # The kept forming bar is no longer the final bar.
        "forming-in-the-middle": [*history, open_bar, later],
        "duplicate": [*history, open_bar, make_bar(20, 103)],
        "unsorted": [*history, open_bar, make_bar(3, 100)],
        "invalid-high": [*history, open_bar, Bar(time=later.time, open=104, high=103, low=100, close=104, volume=1)],
    }
    for name, bars in windows.items():
        answers = []
        for patches in (True, False):
            host = Host(tmp_path / f"{name}-{patches}.sqlite3", patches=patches)

            def run(window):
                return host.execute(ExecuteBatchRequest(source=source, context=CONTEXT, bars=tuple(window),
                                                        options={"pineSessionId": "live"}))

            assert run([*history, open_bar]).ok
            answers.append(run(bars))
        assert answers[0] == answers[1] and not answers[0].ok, name
        assert answers[0].diagnostics[0].code.startswith("PINE_"), name
