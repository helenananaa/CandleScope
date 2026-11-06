# Source-prefix owner after main261

Integration source `8c9a24e5cae431cf2423a0d0a09755f3591927c4` merges main
`0de39f37f2389b09a35fc91e3a6d8d5844137da8` (#261) without conflict.
The source-prefix product/test changes from71284f77 are unchanged. This also
includes the coherent initial restoration state fix in the current Controller.

Single combined run: **413 passed / 5 existing warnings / zero skips**, extending
the 378-case source/runtime regression with actual continuous Controller and
creation-journal coverage. Exact command/environment/file fingerprints are in
`main261-source-manifest.json`. All 21 real Manager/HTTP/WS receipts again show
22 owned workers exit0 and absent, and subscriptions/leases/registry/source
watches empty. Original 39 dirty QA files remain excluded and byte-identical.

The first integrated run passed412 but failed the fresh-backend child import:
the retained installed SDK lacks FEATURE_STREAM_RELEASE_V1. Pytest conftest's
in-process source path did not propagate to that independent interpreter.
The final run explicitly uses repository SDK+backend in PYTHONPATH, preserving
the qualified core launcher and separate source-runner/isolated native registry.
The failed raw log is retained. No installed SDK, package or core was modified,
and this source run does not certify the old installed package. Previous378
and original268 records keep their own source/environment scope.

#261 merged only after exact head001ca7f0/current-basea1302842 had successful
pinned-fork and macOS arm64/x64 CI. Its merge tree equals the reviewed head.
This #227 head remains Draft: frontend domain lifetime/HTTP/WS acceptance and
renderer/Native original counter/deletion assertions remain required. No new
public market, installed-package, macOS restart or Windows claim is made.
