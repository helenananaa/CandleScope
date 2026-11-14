# Joint native cold-start observations — NOT QUALIFIED

Product backend: `9b207f85a1df3a3fde6b78a0bc279037edaae967` (PR #407).
The retained macOS arm64 app had all 1,005 tracked backend files overlaid and
hashed. Its frontend and dependency paths were unchanged from the retained
`ef8f0e0fa6df299a823f4460b701eb1c3c98361f` build; this was not a fresh release
build. Backend/asar hashes and strict deep signatures passed before/after.

Both runs used fresh profiles, real exchange data and the ordinary application
routes. No source data was seeded and no network responses were substituted.
The four charts requested 89m, 97m, 101m and 10007m. Each had two local built-in
EMA indicators (20/60). The receipt's planned `indicatorsPerCell: 3` includes a
later JavaScript probe that was never reached.

| Fresh profile | Observed chart bars | Result |
| --- | --- | --- |
| OKX spot, 04:47–04:51 UTC | 47 / 44 / 42 / 0 | Failed initial viewport gate |
| Binance USD-M, 05:01–05:04 UTC | 0 / 0 / 0 / 0 | Failed initial viewport gate |

All cells remained unready. Both 10007m cells reported that preparing stored
history exceeded the current history limit. Both owned process trees exited
fully (10/10 processes). The screenshots were inspected directly: the OKX
progress image showed sparse 89m history and loading cells; the USD-M failure
image showed three loading cells and the 10007m limit error.

The drivers stopped at the initial viewport gate. They did **not** execute the
planned custom JavaScript indicator probe, ten-minute soak, hide/restore,
interval switching, lease release/recreation, save/full-quit/restart or strategy
comparison. This evidence does not qualify #126, #127 or #129 for closure.

`failed-qualification.json` contains terminal receipts and resource summaries.
The two unpaired failed runs peaked at 1,694,848 and 1,852,896 KiB summed process
RSS, respectively. Summed RSS includes shared pages; it is not unique physical
memory, a paired improvement result, or an allocation/GC measurement. Last
observed cumulative CPU was 359.06s / 236.82s over their respective sampled
windows. The raw finite samples are archived for inspection.

The retained USD-M database independently exposed a backend defect: a normal
221-target 89m query returned zero bars while the materialized-target reader
returned 133 committed bars. `evidence/partial-query-probe` retains the original
reproduction and a provisional candidate observation; the provisional candidate
metadata is superseded by the exact patch evidence in
`../partial-mixed-history-127-20261114`. Returning partial bars does not remove
the 10007m admission limit or qualify the original failed native runs.

`evidence-index.json` records original and archived payload hashes. Credential
strings in JSON are redacted as recorded in `redactions.json`. Profiles,
control credentials, app bundles and SQLite files are retained locally rather
than published here. The preparation/driver/archive scripts retain the exact
local reproduction paths and inputs.
