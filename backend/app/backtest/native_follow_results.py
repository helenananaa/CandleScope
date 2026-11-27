"""The results a native Pine FOLLOW keeps (ADR-BACKTEST-015 O2, confirmed 2026-11-27).

A Pine strategy on the chart follows live bars by rebuilding its latest prefix as a
FIXED run after each bar closes (O1). Each rebuild is an ordinary native run; this
module records which runs are rebuilds and of which user run (the *base*), so that
the store keeps only what a chart can still show:

- per base, the newest completed rebuild (the result the chart shows), any rebuild
  still running, and the newest failed one if it is newer than that result;
- results for at most ``KEPT_FOLLOWS`` bases, the most recently active first; older
  bases lose their rebuilds and fall back to the user's own run.

The user's own runs are never removed, nor a rebuild someone made a replay from.
Identical inputs share one rebuild (O2), so a run may be the result of several bases;
it goes only when no base keeps it.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

KEPT_FOLLOWS = 8
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"})


class FollowResults:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS native_follow_results (run_id TEXT NOT NULL, base_run_id TEXT NOT NULL, "
                   "linked_at_ms INTEGER NOT NULL, PRIMARY KEY (run_id, base_run_id))")
        db.execute("CREATE INDEX IF NOT EXISTS native_follow_results_base ON native_follow_results(base_run_id)")

    def is_rebuild(self, run_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM native_follow_results WHERE run_id=? LIMIT 1", (run_id,)).fetchone() is not None

    def link(self, run_id: str, base_run_id: str, now_ms: int) -> None:
        """``run_id`` is a rebuild of ``base_run_id``; linking it again marks it the base's newest."""
        self.db.execute("INSERT INTO native_follow_results VALUES (?,?,?) ON CONFLICT(run_id, base_run_id) "
                        "DO UPDATE SET linked_at_ms=max(linked_at_ms, excluded.linked_at_ms)",
                        (run_id, base_run_id, now_ms))

    def collect(self) -> list[str]:
        """Unlink superseded and evicted rebuilds; return the runs nothing keeps any more."""
        rows = self.db.execute(
            "SELECT f.run_id, f.base_run_id, f.linked_at_ms, f.rowid, json_extract(s.record,'$.state') "
            "FROM native_follow_results f LEFT JOIN native_run_summaries s ON s.id=f.run_id").fetchall()
        chains: dict[str, list[tuple[int, int, str, str | None]]] = defaultdict(list)
        for run_id, base, linked, rowid, state in rows:
            chains[base].append((linked, rowid, run_id, state))
        # Most recently active base first; ties by link order.
        ranked = sorted(chains.items(), key=lambda item: max(row[:2] for row in item[1]), reverse=True)
        unlinked: list[tuple[str, str]] = []
        for rank, (base, members) in enumerate(ranked):
            members.sort(reverse=True)
            shown = next((index for index, row in enumerate(members) if row[3] == "COMPLETED"), None)
            newest_terminal = next((index for index, row in enumerate(members) if row[3] in TERMINAL or row[3] is None), None)
            for index, (_linked, _rowid, run_id, state) in enumerate(members):
                if state is not None and state not in TERMINAL:
                    continue  # still running: it decides what the chart shows next
                keep = rank < KEPT_FOLLOWS and (index == shown or (index == newest_terminal
                                                                    and (shown is None or index < shown)))
                if not keep:
                    unlinked.append((run_id, base))
        if not unlinked:
            return []
        self.db.executemany("DELETE FROM native_follow_results WHERE run_id=? AND base_run_id=?", unlinked)
        candidates = sorted({run_id for run_id, _ in unlinked})
        removable = []
        for run_id in candidates:
            if self.db.execute("SELECT 1 FROM native_follow_results WHERE run_id=? OR base_run_id=? LIMIT 1",
                               (run_id, run_id)).fetchone():
                continue  # another base still shows it, or it is somebody's base
            if self.db.execute("SELECT 1 FROM native_replays WHERE json_extract(record,'$.run_id')=? LIMIT 1",
                               (run_id,)).fetchone():
                continue  # a replay was made from it: it is the user's now
            removable.append(run_id)
        return removable
