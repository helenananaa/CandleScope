# Workspace and branch consolidation — 2026-09-19

## Result

- Active worktrees: 9 → 1 (`CandleScope`, `main`).
- Local branches: 21 → 3. Retain `main`, `codex/local-offline-mode`, and
  `codex/pine-interpreter`.
- Deleted 18 merged local branches and 5 branches already contained in remote
  `main`. Remote `codex/macbook-unique-20260911` remains until the local integration
  is published. Remote `main` was not pushed by this cleanup.
- All eight retired worktree directories were moved intact into the archive;
  their databases, history, environments and ignored QA artifacts were preserved.
  This reorganization does not reclaim their disk space.

## Integrated changes

- Pine 0.3 streaming adapter candidate and Pyne 0.4 adapter/workbench candidate,
  preserving existing production release selection.
- Mac branch: six locale catalogs, platform-aware bootstrap, stale plugin read
  invalidation, and replay sizing correction.
- Fifteen additional host locale catalogs and Thai/Dutch plugin translations.
  Combined nine conflicting files without dropping either locale set. Completed
  newer portfolio/event messages in the incoming catalogs, corrected the obsolete
  Dutch fallback test and Brazilian Portuguese portfolio terminology.
- Strategy performance branch, including its previously uncommitted trade
  optimizations and measurement receipts. Experimental round-7 JSON reuse and
  round-9 chart reuse remain disabled by default.
- Previously uncommitted Pyne input metadata and configured symbol preservation.
  Kept the current numeric-input validation and added price/disabled support.
- Explicitly allowed the existing shared replay parity JSON test fixture in the
  frontend architecture checker; typed the existing order-book wire test fixture.

## Legacy branches

The old offline branch has nine non-ancestor commits, but 29 of its 38 dirty or
untracked file contents already occur in main history. Its deterministic
resampling is already represented by `fe4c356b`; the current mainline adds later
localization and unified research behavior. Remaining differences include old
documentation, styling, package metadata and a local IDE path. Retain its branch,
patches and directory for provenance; do not merge the old product tree wholesale.

The old Pine branch has twelve non-ancestor commits. Its dirty source changes
primarily update upstream repository URLs in vendored runtime packages removed
from the current product. Main migrated to released sidecar runtimes (including
`9e739c61`) and now contains the newer adapter candidate. This is not proof that
every old runtime behavior has an equivalent implementation. Retain the branch
and complete archived directory for any future feature-level comparison.

The drawing worktree's remaining changes were DOM debugging probes; these were
archived, not promoted. The strategy-research worktree's only tracked difference
was an IDE interpreter path.

## Archive and recovery

Archive root:
`E:/Disk0Merged/H/program/CandleScope-workspace-archive-20260919/`

- `before-cleanup.bundle`: verified complete Git history and original refs.
- `refs-before.txt`, `worktrees-before.txt`: original registration inventory.
- `snapshot.json`: hashes and file lists for nine verified change snapshots.
- `<worktree>/working.patch`, `index.patch`, `changed-files.zip`: tracked and
  untracked source recovery. Main's `.local/` candidate environments remain in
  place and are excluded locally through Git's `info/exclude`.
- `retired/<worktree>/`: intact retired directories. Their obsolete `.git`
  pointer files were renamed `ARCHIVED-GITDIR.txt`; these are archives, not active
  checkouts. Do not run Git worktree repair against these pointers.
- `legacy-review.json`: source blob comparison against main history.
- Verification logs, JUnit receipts and the installed native-wheel receipt are
  stored beside the archive inventory.

To resume an old branch, create a fresh worktree with `git worktree add <new-path>
<branch>` and extract its `changed-files.zip` into that checkout. The snapshot
contains changed source files and untracked source, not the large ignored data;
copy any required data from `retired/<worktree>/` separately. Deleted branch refs
can be recovered from `before-cleanup.bundle` under a new local branch name.

## Verification scope

- Backend integration regression: 474 passed, 4 native-dependent collection skips.
- After rebuilding the Windows CPython 3.12 native extension: 147 native and
  performance-related tests passed, with no skips.
- Rebuilt native and SDK wheels were installed into a fresh target and verified
  with an isolated `python -I` process. Receipt: `native-installed-receipt.json`.
- Adapter/plugin suites: Pine 18, Pyne 38, workbench 38, market scanner 24 passed.
- Initial frontend suite: 3702 passed and 2 failed. Both failures were resolved;
  the affected locale/input suites then passed all 54 tests. The order-book
  regression passed 11 tests after its type-only repair.
- Locale catalog completeness, TypeScript checks and production build passed.
  Use the canonical `E:/Disk0Merged/H/program/CandleScope/frontend` directory for
  Vite builds: the `H:` alias can mix logical and physical HTML entry paths.
- Final frontend verification is recorded in the archive logs.

Test groups overlap and should not be summed into a unique test count. Existing
FastAPI deprecation and large-bundle warnings remain. No new browser performance,
cross-platform runtime qualification, deployment or production plugin activation
is claimed.
