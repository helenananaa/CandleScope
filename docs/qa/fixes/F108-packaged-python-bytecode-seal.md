# F108: packaged Python must retain signed bytecode after relocation

Scope: `PLATFORM-01`, package integrity following a normal launch/restart. This does not change indicator mathematics, account execution or application permissions.

The qualified N1 archive has timestamp-based bytecode for modules imported by the packaging interpreter. Its ordinary runtime later rewrote 42 `.pyc` files. Comparing all 16,250 archived files and links found no non-bytecode change; restoring the archive bytes made `codesign --verify --deep --strict` succeed. A representative signed header stored source mtime 1792327421 while the extracted source had mtime 1792327422.

The compile hook already requests checked-hash invalidation, but `compileall` can skip an existing current timestamp cache without converting its invalidation mode. The regression invokes the actual hook with such a cache, relocates the tree, shifts the source timestamp as an archive can, and imports with real isolated Python. Before the fix, the cache remains timestamp-based (flags 0) and its bytes change on import.

The desktop backend already sets `PYTHONDONTWRITEBYTECODE=1`; the rejected QA startup did not change any signed file. Isolated Python launches ignore that environment policy, so the packaging hook must still produce the promised checked-hash caches. This finding does not imply that every desktop backend launch rewrites them.

Force recompilation in the existing hook so all selected bytecode becomes checked-hash (flags 3) before signing. Preserve the existing compiler error handling, platform paths and exclusion for invalid unused CCXT BIP templates. The regression now requires checked-hash flags and exact cache bytes after relocation/import; it passed on macOS with no skips. The POSIX fixture explicitly skips Windows, whose package needs its independent verification.

Evidence: `output/acceptance-delivery-20261016/batch-o/native/{N1-bytecode-restore-summary.json,signed-bytecode-header-diagnosis.json,bytecode-hook-before-result.json,bytecode-regression-before.log,bytecode-regression-after.log}`.

Still required before delivery: integrated gates; one official package; verify signed bytes after extraction, native startup and complete quit/restart, including backend and first-party runtime imports. This source fix does not itself close that production gate or the cold recursive indicator P1.
