import json
import sqlite3
from contextlib import closing

from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin

CONTEXT = MarketContext("binance", "spot", "BTCUSDT", "1m")
SOURCE = '//@version=6\nindicator("ticks")\nvarip int n = 0\nn += 1\nplot(n)\n'
LEGACY = {"seed_state": "seed", "apply_confirmed": "update_confirmed", "apply_forming": "update_forming"}


def bar(index, close, closed=True):
    return Bar(time=1700000000 + index * 60, open=close, high=close + 1,
               low=close - 1, close=close, volume=10, is_closed=closed)


def run(plugin, bars, *, source=SOURCE, identity="a"):
    return plugin.execute_batch(ExecuteBatchRequest(source=source, context=CONTEXT, bars=tuple(bars),
                                                    options={"pineSessionId": identity}))


def last(result):
    assert result.ok, result.diagnostics
    return result.output.series[0].points[-1].value


def journal(path):
    with closing(sqlite3.connect(path)) as db:
        sessions = db.execute("SELECT id, header, state, seq, bytes FROM journal_sessions").fetchall()
        operations = db.execute("SELECT session_id, seq, op FROM journal_operations ORDER BY session_id, seq").fetchall()
        legacy = db.execute("SELECT id, body FROM sessions").fetchall()
        budget = db.execute("SELECT sessions, bytes FROM journal_budget").fetchone()
    stored = sum(len(header) + len(state) for _, header, state, _, _ in sessions) + sum(len(op) for *_, op in operations)
    assert budget == (len(sessions) + len(legacy), stored + sum(len(body) for _, body in legacy))
    assert all(size == len(header) + len(state) + sum(len(op) for key, _, op in operations if key == id_)
               for id_, header, state, _, size in sessions)
    assert all(seq == sum(key == id_ for key, *_ in operations) for id_, _, _, seq, _ in sessions)
    return {"sessions": sessions, "operations": operations, "legacy": legacy, "budget": budget}


def test_commit_appends_only_operations_observed_since_the_previous_commit(tmp_path):
    path = tmp_path / "journal.sqlite3"
    plugin = PineCompatRuntimePlugin(journal_path=path)
    history = [bar(i, 10 + i) for i in range(64)]
    assert last(run(plugin, history + [bar(64, 80, False)])) == 65
    seeded = journal(path)
    assert [json.loads(op)[0] for *_, op in seeded["operations"]] == ["seed_state", "apply_forming"]
    for close in range(81, 91):
        last(run(plugin, history + [bar(64, close, False)]))
    ticked = journal(path)
    assert ticked["operations"][:2] == seeded["operations"]
    added = [json.loads(op) for *_, op in ticked["operations"][2:]]
    assert [name for name, *_ in added] == ["apply_forming"] * 10
    assert ticked["budget"][1] - seeded["budget"][1] < 2_000
    confirmed = run(plugin, history + [bar(64, 90), bar(65, 91, False)])
    assert last(confirmed) == 77
    assert [json.loads(op)[0] for *_, op in journal(path)["operations"][12:]] == ["apply_confirmed", "apply_forming"]
    plugin.shutdown()
    resumed = run(PineCompatRuntimePlugin(journal_path=path), history + [bar(64, 90), bar(65, 92, False)])
    assert resumed.meta["sessionRecovered"] and last(resumed) == 78


def test_reset_replaces_the_log_and_release_returns_its_budget(tmp_path):
    path = tmp_path / "journal.sqlite3"
    plugin = PineCompatRuntimePlugin(journal_path=path)
    history = [bar(i, 10 + i) for i in range(8)]
    for close in (30, 31, 32):
        run(plugin, history + [bar(8, close, False)])
    run(plugin, history, identity="b")
    corrected = [bar(0, 99)] + history[1:]
    replayed = run(plugin, corrected + [bar(8, 33, False)])
    assert replayed.meta["sessionReset"] and last(replayed) == 9
    state = journal(path)
    assert [op for key, _, op in state["operations"] if key == "a"][0].startswith('["seed_state",[[{"time":1700000000000,"open":99.0')
    assert len([key for key, *_ in state["operations"] if key == "a"]) == 2
    # A Core failure after an earlier bar was applied releases the session.
    source = SOURCE + 'if close > 1000\n    a=array.new_float(100000,1.0)\n    for i=0 to 99\n        b=array.copy(a)\n'
    run(plugin, history, source=source)
    failed = run(plugin, history + [bar(8, 40), bar(9, 2000)], source=source)
    assert not failed.ok and failed.diagnostics[0].code == "E_RESOURCE_BUDGET"
    assert {key for key, *_ in journal(path)["sessions"]} == {"b"}
    fresh = run(plugin, history + [bar(8, 40)], source=source)
    assert fresh.meta["sessionReset"] and not fresh.meta["sessionRecovered"]
    assert {key for key, *_ in journal(path)["sessions"]} == {"a", "b"}
    for key in ("a", "b"):
        plugin._sessions.release(key)
    assert journal(path)["budget"] == (0, 0)


def test_full_journal_rolls_back_and_the_next_request_continues_from_the_last_commit(tmp_path):
    path = tmp_path / "journal.sqlite3"
    plugin = PineCompatRuntimePlugin(journal_path=path)
    history = [bar(0, 10), bar(1, 20)]
    assert last(run(plugin, history + [bar(2, 30, False)])) == 3
    before = journal(path)
    plugin._sessions.journal.max_bytes = before["budget"][1]
    full = run(plugin, history + [bar(2, 31, False)])
    assert not full.ok and full.diagnostics[0].code == "PINE_SESSION_JOURNAL_FULL"
    assert journal(path) == before and "a" not in plugin._sessions.entries
    plugin._sessions.journal.max_bytes = 1 << 20
    resumed = run(plugin, history + [bar(2, 32, False)])
    assert resumed.meta["sessionRecovered"] and last(resumed) == 4


def test_schema_one_transcript_restores_old_names_deduplicates_and_migrates(tmp_path):
    current, path = tmp_path / "current.sqlite3", tmp_path / "legacy.sqlite3"
    plugin = PineCompatRuntimePlugin(journal_path=current)
    history = [bar(0, 10), bar(1, 20)]
    forming = history + [bar(2, 30, False)]
    assert last(run(plugin, forming)) == 3
    (_, header, state, _, _), = journal(current)["sessions"]
    header, state = json.loads(header), json.loads(state)
    operations = [[LEGACY[name], args, kwargs] for name, args, kwargs in
                  (json.loads(op) for *_, op in journal(current)["operations"])]
    rows = [{"time": item.time * 1000, **{key: getattr(item, key) for key in ("open", "high", "low", "close", "volume")}}
            for item in forming]
    transcript = {"schema": 1, "source": header["source"], "options": header["options"], "operations": operations,
                  "identity": header["identity"], "confirmed": rows[:2], "forming_time": state["formingTime"],
                  "clocks": None, "history_start": 0, "requested": None, "observed_at": None,
                  "lastObservation": {"bar": rows[2], "forming": True, "providers": [], "clock": None, "requested": None}}
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        db.execute("INSERT INTO sessions VALUES (?,?)", ("a", json.dumps(transcript, separators=(",", ":"))))
    legacy = PineCompatRuntimePlugin(journal_path=path)
    assert journal(path)["legacy"] and journal(path)["budget"][0] == 1
    duplicate = run(legacy, forming)
    assert duplicate.meta["sessionRecovered"] and last(duplicate) == 3
    migrated = journal(path)
    assert not migrated["legacy"] and [json.loads(op)[0] for *_, op in migrated["operations"]] == ["seed_state", "apply_forming"]
    legacy.shutdown()
    resumed = run(PineCompatRuntimePlugin(journal_path=path), history + [bar(2, 31, False)])
    assert resumed.meta["sessionRecovered"] and last(resumed) == 4


def test_shorter_confirmed_tail_replays_instead_of_truncating_native_history():
    history = [bar(i, 10 + i) for i in range(6)]
    for bars in (history[:4], history[:5] + [bar(5, 30, False)]):
        plugin = PineCompatRuntimePlugin()
        run(plugin, history)
        result = run(plugin, bars)
        assert result.ok and result.meta["sessionReset"]
        assert result.output == run(plugin, bars, identity=None).output
