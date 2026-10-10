Pine adapter and engine 0.3.2 add digest-pinned offline plugin bundles for
Windows x86-64, Linux x86-64, macOS Apple Silicon and macOS Intel on CPython 3.12.

Each bundle is built from the public Pine engine GitHub Release, the frozen SDK
0.2.0 wheel and adapter 0.3.2. The Actions job verifies the engine manifest and
wheel digests, installs into a clean managed environment, runs the sidecar
protocol/result probe, rechecks the installation, and tests native indicator
session replacement, confirmation and subscription isolation.

The official download catalog can contain multiple platform variants of one
runtime ID. Selection uses the full host OS, architecture, Python implementation
and Python version. Duplicate variants for the same target are rejected.

The Pine runtime implementation and output schemas are unchanged from 0.3.1.
This release qualifies the Pine plugin path, not the complete CandleScope macOS
desktop UI, other required runtimes, long-running workloads or older macOS
versions than the engine wheel's compatibility tag. Existing managed sessions
activate a new native wheel on process restart; prior installations remain
available for rollback.
