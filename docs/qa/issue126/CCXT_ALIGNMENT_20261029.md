# D126 / CCXT integration qualification

PR #138 remains an independent draft. It now composes with PR #145's provider,
BarBasis, source journal, archive admission and durable-delivery contracts.
This does not complete #126's executor consumers or joint resource acceptance.

## Integration changes

- Source projection filtering, source rank selection and the D126 optimistic
  fence run in the same writer transaction. Archive rows, import metadata and
  cache-generation commit receipts retain one transaction.
- SQL cursor row counts report actual projected/archive rows; revision triggers
  must not inflate those counts through `connection.total_changes`.
- Archive cleanup lifecycle methods remain separate from the fenced and
  budgeted `run` operation.
- Published aggregation values preserve source references. Cloning a mutable
  builder detaches nested source references, with a regression for aliasing.
- The aggregator receives historical source-component reads through its
  DataManager owner; it does not import the SQLite storage implementation.
  This common fix is also included in #145.

## Evidence

One final joint run passed **1109 tests, 0 skipped**, in 131.83s. Four existing
FastAPI lifecycle deprecations remained. It covered revision/cache fencing,
source observations, immutable snapshots, deletion and repair, archive and
manual history, delivery recovery, backfill, retention, GC, indicator consumers,
aggregator contracts, K-line APIs and Pyne rejection. Backend architecture and
`git diff --check` also passed. Earlier failures are retained in local logs;
this final run followed their fixes.

The run used isolated SQLite directories and the pinned fork. Local evidence:
`output/ccxt-integration/revision-final.log` and `revision-final.xml` in the
CCXT integration worktree. Targeted repair results overlap this run and are
not added to its count. This run is backend qualification, not native UI,
public-network, throughput or whole-application resource acceptance.

## Remaining gates

Minimum #130/#127/#129 consumer integration and joint resource acceptance are
still required. #147 and #144 must consume the public revision/deletion and
budget contracts before their own merges. Historical measurements in
`D126_BACKEND_VERIFICATION.md` are not relabelled as fresh joint benchmarks.
Pyne remains retired; revision metadata is retained and downgrade to an older
writable binary remains unsupported.
