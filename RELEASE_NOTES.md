# Release notes

## Unreleased

### Large custom intervals load slowly the first time

A custom interval such as 89m is built from 1-minute bars. The first time a
chart opens one, or scrolls back into history that is not stored yet, the app
downloads and builds those bars first. That can take one to several minutes;
the chart shows "正在加载更早数据…" ("Loading earlier data…") meanwhile, and
the bars it shows have no holes. Later opens use the stored bars and are much
faster, though still slower while other charts are loading history. Faster
loads are planned for a later release.

### Chart strategies and live bars

A chart strategy's result covers the history on the chart; it does not extend
itself as new bars close. To run a Python strategy on live bars, choose
**Run mode → History + live** or **Live only** (运行模式 → 历史接实时 / 纯实时)
in the strategy panel, on a 1-minute chart. Pine strategies on the chart run on
history only in this release.

### Going back to 0.3.0 after upgrading

CandleScope 0.3.0 (the 2026-10-25 build) cannot open a profile after this
release has opened it. Its backend stops at startup with `replay training
schema 29 is obsolete`, and no window appears. Nothing is deleted, and this
release still opens the profile.

Before this release moves a database's schema forward, it keeps a copy next to
that database, for example `replay.db.pre-replay-training-v26-to-v29.sqlite`.
The existing `candlescope.db.pre-basis-v1-<id>.sqlite` copy follows the same
pattern. The app never changes or deletes these `*.pre-*` copies, and it keeps
one per database and schema step.

To go back to 0.3.0:

1. Quit CandleScope.
2. Open the profile's data folder: `~/Library/Application Support/CandleScope Replay/data`
   on macOS, or `%APPDATA%\CandleScope Replay\data` on Windows.
3. For each `<database>.pre-*.sqlite` copy, move `<database>` and any
   `<database>-wal` and `<database>-shm` files into another folder, and keep
   them. Then rename the copy to `<database>`. If one database has several
   copies, use the oldest.
4. Start 0.3.0.

After the restore, 0.3.0 shows the data as it was at the upgrade. Anything
created after upgrading, such as new replay runs, exists only in the files you
moved aside. If you start this release again, it upgrades the restored files
and keeps a new copy.
