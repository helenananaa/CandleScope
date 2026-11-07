# PR #267 on main through #269

Current main `bc067c16f3daf8b235d7c1dd1292a0b37fb2a71d` was merged into the prior PR head `35082148de14612ae67b8842abff00ba272b524e`. Tested product head `e7ed487f83885bca2bc950bc8641308a97d7fe33` adds the main changes from #268 and #269. Frontend, packages and workflow trees match the prior PR head.

Backend architecture passed. One invocation over 58 suites passed 698 tests, with zero skips and seven warnings. This includes the previous indicator and replay matrix, Kline enhancement normalization, and trade Kline parity. The first harness used a deleted temporary path. The second got four Node-backed replay failures because the new worktree lacked the locked `tsx` dependency. Both logs are retained. The passing run used a fresh test root and the dependencies from a checkout with the identical lockfile.

The earlier 55-stage Native result remains evidence for the previous candidate. This refresh provides exact-source backend results. CI and Native package acceptance remain separately scoped.

[Commands and evidence hashes](receipt.json)
