# Fixed-grid mixed history: bounded backend stage

PR #363; related #127/#130/#126/#132. Product `b2bda3ddd`, CI selector `480eb5811`.

The actual DataManager/QueryEngine facade can plan and read one fixed-grid target
through H127/B130/K130/D126. It does not enable an ordinary chart route.
Contract and remaining scope: [MIXED_HISTORY_H127](../../architecture/MIXED_HISTORY_H127.md).

- Final local selection: **313 passed**, 90.14 s. The two new suites and six related
  H127/prefix/shared-block/core/streaming modules use isolated SQLite and synthetic
  accepted inputs. No user database or public-source qualification is implied.
- Pinned-fork integration [43141553343](https://github.com/helenananaa/CandleScope/actions/runs/43141553343)
  passed after the new test files were added to the production CI selection.
- Backend architecture and whitespace checks passed.
- Exact cover/prime phases, local finer fallback after a failed multi-page coarse
  span, no duplicate volume, required/unknown fields, hot reuse, cross-span revision
  changes, deletion, cancellation, storage rebinding and resource release covered.
- [Logs/XML and SHA256 index](evidence/index.json). Overlapping selections are not added.

Original parent requirements remain. Automatic source selection/qualification,
default query/materialization consumers, calendar/session mixed plans, scheduling,
true cold/warm public history and native user/performance qualification are pending.
No parent issue is closed by this intermediate interface delivery.
