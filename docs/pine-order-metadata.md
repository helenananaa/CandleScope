# Pine order annotations

The development worker negotiates `candlescope.pine-order-metadata/1` with
chart adapter `pine-chart/7` and external adapter `pine-external/11`. Core
`f9e7ba148` exports `EXTERNAL_ORDER_METADATA_SCHEMA_VERSION == 1`; its Python
batch/session APIs require explicit `order_metadata=True`. Older Host callers
therefore keep rejecting executed annotation arguments instead of silently
discarding them after a core upgrade.

Entry, generic order, close and close-all commands preserve evaluated comments,
alert messages and the alert-disable flag. Exit commands also preserve separate
profit/loss/trailing annotations. Host matching binds annotations to accepted
orders; each actual exit leg selects its own fields with generic fallback.
Empty strings override generic text. Selection follows the filled order leg,
rather than the sign of profit after costs. Partial fills and replacement orders
retain their own submitted annotations. Financial fills and fees are unchanged
by `disable_alert`.
Accepted pending and cancelled orders also retain their annotations in order
reports, without inventing a fill or a fill-role record for an unfilled order.

Snapshots retain the negotiated contract, order annotations, selected roles and
fill allocations. Restore validates the contract and annotation types; a live
stream cannot downgrade its contract. Chart reports bind annotation rows to the
actual order/sequence pair. Workbench exposes the same selected fields in its
financial fills. The production report table shows comment, literal alert text
and enabled/suppressed status. These records do not send external notifications
or expand message templates. Immediate-close matching and exit OCA-name support
remain outside this contract.

## Controlled verification, 2026-10-21

- Core: 14 focused Rust external/session/default checks, all 1,863 fresh-wheel
  Python checks (25 metadata cases), all-target workspace Clippy, formatting,
  source structure/host parity and generated WASM/Node smoke passed.
- Host: 67 contract/allocation/report checks passed. Seven actual chart/Workbench
  cases covered spot and V1/V2 perpetual accounts, profit/loss selection and a
  saved-prefix replay restored to the identical complete report. The 19 existing
  chart-engine cases also passed. A further real Workbench case verified entry,
  generic order, partial close and close-all annotations through actual fills.
  A cancelled, unfilled order case separately verifies retained order comments
  and zero financial fills. The final metadata execution module contains nine
  cases, including those earlier seven account/leg/replay cases.
- SDK: all 121 tests passed, including three real subprocess tests which begin
  with a legacy stdio code page. All native transport entrypoints now explicitly
  use UTF-8. This repaired a real Windows failure when Chinese script text was
  sent to an isolated Python worker; environment variables alone cannot fix
  interpreters launched with `-I`.
- Frontend: type checking, the 30-locale catalog/source check and 53 targeted
  report/analytics/locale tests passed. Portuguese and Korean cost/account copy
  missing from the preceding checkpoint was completed during closeout.
- A real browser operated the production editor, account-file chooser, run
  button and fill table against the isolated API. UTF-8 source matches the
  retained run (with editor newline normalization), fills are `[5,2,3,4]`, Chinese
  comments and literal template text are visible, the alert flags are
  `[false,false,true,true]`, position ends flat, and cost baselines reexecute.
  Console: zero errors/warnings. Screenshot and API/source verification receipt:
  `output/playwright/pine-metadata-20261021/`.

The core wheel SHA256 is
`a84c3fee61d5dfea19d2e56e5d9ce6f730779cb20538b49cdf7f86c10251ef77`.
Core evidence is retained in `.local/host-completion/order-metadata/`; Host,
bridge and rebuilt SDK artifacts are retained in
`output/pine-host/completion-goal/order-metadata/`. Failed diagnostics are kept:
the normalized exit-slot guard, UTF-8 transport failure and fixture diagnostics
for mixed exit legs, callback repetition and existing V2 admission requirements.

The default-sizing 24-module historical attempt was interrupted with no live
process and no complete result; its original `historical-20261020-05` receipt
and log remain intact beside an interruption observation. The final 26-module
profile at Host `236f24c0` passed all 392 cases, zero failures/errors/skips,
in 939.735 seconds including fingerprint checks. Source, all runtime files and
the registry remained unchanged. Receipt:
`output/pine-host/completion-goal/historical-20261021-closeout/receipt.json`.
This controlled component entry
evidence is separate from full application packaging, resource qualification
and official TradingView output comparison. Multipliers, growing requests and
later tick schedulers remain open in the capability ledger.
