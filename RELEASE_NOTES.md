# Release notes

## Unreleased

## 1.0.0 (2026-11-25)

This is the first public release of the CandleScope desktop app, for Windows and macOS (Apple Silicon and Intel). The same app also runs in the browser at [app.candlescope.app](https://app.candlescope.app). If you used the 0.3.0 test build from 2026-10-25, this release opens and upgrades your profile; read [Going back to 0.3.0](#going-back-to-030-after-upgrading) first if you may want to return to it.

### New since 0.3.0

**Interface**

- A redesigned interface with light and dark themes, one Settings dialog with the Plugin Center inside it, visible keyboard focus everywhere, and less motion when your system asks for it.
- 30 interface languages, including right-to-left Arabic and Hebrew.
- On first launch the app uses your system language when it is one of the 30, and English otherwise. A language you already chose stays.

**Charts and drawing**

- New drawing tools: arrows, multi-point arrow paths, editable polylines, parallel channels, rectangle zones, and price and time rulers.
- Each chart keeps its own appearance, and you can link styles across charts.
- Go to any date on a live chart.
- New drawings are blue by default. Drawings you already made keep their colour.

**Indicators and alerts**

- Python indicators in the desktop app: write a `compute(bars, params)` function that returns lines or histograms. They use the Python standard library and recalculate when a bar closes.
- Alerts on any output of a built-in indicator, with that indicator's own parameters.
- The chart legend marks built-in indicator values computed from too little history.

**Practice and review**

- Practice accounts with a trade journal (plan, notes while open, review after close), a quick replay of each trade, and stats by tag.
- Live paper trading holds several markets at once, in hedge mode with separate protective orders, and picks up again after a restart.
- Read-only OKX account sync: reconcile positions and fills, then journal and review the real trades.
- Replay training notes keep a version history and a screenshot of the chart, and link to the fills and closed trades they describe. Stop and target lines show when each was in effect.
- Replay training runs on imported bar data, offline.
- Historical study on each chart, with notes, finer intervals revealed as you step, and optional cursor linking across charts.

**Strategies**

- One way to run every strategy: drafts save automatically, versions are kept, any result can be rerun, and each result records the fees, slippage and fill model it ran under.
- Parameter batches and walk-forward robustness checks, and saved results side by side.
- Replay a strategy result on its own chart, with indicators and drawings.
- Python strategies can keep running on live 1-minute bars; see [Chart strategies and live bars](#chart-strategies-and-live-bars).
- Connect your own model through the SDK.

**Plugins**

- One install path for every plugin. Marketplace packages are signature-checked, ask for their permissions before they run, and roll back if they fail their health check. The Pine and Python indicator runtimes use the same path.

**Browser version**

- [app.candlescope.app](https://app.candlescope.app) runs charts, replay training and paper trading in the browser, with nothing to install. It also works on phone-sized screens and by touch.

**Desktop app**

- A Windows installer. Uninstalling keeps your data.
- If the backend stops unexpectedly, the app restarts it and tells you.
- A data folder that was moved, copied or restored from a backup to another location still starts.
- When an exchange is unreachable, its charts say they are offline instead of loading without end.
- Before upgrading a database, the app keeps a copy of it for going back; see [Going back to 0.3.0](#going-back-to-030-after-upgrading).
- Import a Clash proxy subscription and route market data through its nodes.

### Pyne is removed

CandleScope no longer runs Pyne. Pyne indicators and strategies from older builds are listed as retired and do not run. Their files stay where they were, unchanged. Pine and Python scripts and JavaScript indicators are supported.

### Large custom intervals load slowly the first time

A custom interval such as 89m is built from 1-minute bars. The first time a chart opens one, or scrolls back into history that is not stored yet, the app downloads and builds those bars first. That can take one to several minutes; the chart shows "正在加载更早数据…" ("Loading earlier data…") meanwhile, and the bars it shows have no holes. Later opens use the stored bars and are much faster, though still slower while other charts are loading history. Faster loads are planned for a later release.

### Chart strategies and live bars

A chart strategy's result covers the history on the chart; it does not extend itself as new bars close. To run a Python strategy on live bars, choose **Run mode → History + live** or **Live only** (运行模式 → 历史接实时 / 纯实时) in the strategy panel, on a 1-minute chart. Pine strategies on the chart run on history only in this release.

### Going back to 0.3.0 after upgrading

CandleScope 0.3.0 (the 2026-10-25 build) cannot open a profile after this release has opened it. Its backend stops at startup with `replay training schema 29 is obsolete`, and no window appears. Nothing is deleted, and this release still opens the profile.

Before this release moves a database's schema forward, it keeps a copy next to that database, for example `replay.db.pre-replay-training-v26-to-v29.sqlite`. The existing `candlescope.db.pre-basis-v1-<id>.sqlite` copy follows the same pattern. The app never changes or deletes these `*.pre-*` copies, and it keeps one per database and schema step.

To go back to 0.3.0:

1. Quit CandleScope.
2. Open the profile's data folder: `~/Library/Application Support/CandleScope Replay/data` on macOS, or `%APPDATA%\CandleScope Replay\data` on Windows.
3. For each `<database>.pre-*.sqlite` copy, move `<database>` and any `<database>-wal` and `<database>-shm` files into another folder, and keep them. Then rename the copy to `<database>`. If one database has several copies, use the oldest.
4. Start 0.3.0.

After the restore, 0.3.0 shows the data as it was at the upgrade. Anything created after upgrading, such as new replay runs, exists only in the files you moved aside. If you start this release again, it upgrades the restored files and keeps a new copy.
