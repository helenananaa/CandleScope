# Pine plugin 0.3.2 qualification

The public plugin release is
[candlescope-plugin-pine-compat-v0.3.2](https://github.com/helenananaa/CandleScope/releases/tag/candlescope-plugin-pine-compat-v0.3.2).
Its packaging source is `93f5ddf2` and its upstream engine source is
`28ecae3c645e9269e2099d27cc9abbb1f52ee9ea` (Pine Runtime v0.3.2).

[Candidate qualification](https://github.com/helenananaa/CandleScope/actions/runs/38016820008)
and [tag release](https://github.com/helenananaa/CandleScope/actions/runs/38016901150)
both passed all four native CPython 3.12 jobs: Windows AMD64, Linux x86_64,
macOS arm64 and macOS x86_64. Each job checked the upstream manifest, verified
wheel digests, installed and rechecked a fresh offline managed environment,
and passed 12 installed-wheel native session tests. POSIX jobs also proved that
both runtime registry and sidecar launch retain the virtual environment's
interpreter identity. Source archive metadata is canonicalized without changing
wheel members or RECORD content; the SDK wheel is reused byte-for-byte.

The official catalog activates only assets downloaded from the published
release and checked against SHA256SUMS, frozen locks and qualified bundles.
The catalog activation commit does not change released wheel inputs.

| Platform | CSPKG SHA-256 | Bytes |
| --- | --- | ---: |
| Windows AMD64 | b70f4e2bcf1dbf65ae3ce57ce3c28114e846d19f45b48898c025f923415d388a | 4195533 |
| Linux x86_64 | f13a23587efbdaed64c407248028c1980a55922b047c480320dc4e4f481f21c7 | 4323464 |
| macOS arm64 | 69c9a617e95e58d3dd9e5ce14546a1d9be3d6fdedbb9a0c01fa5c04ce92adeb0 | 3995918 |
| macOS x86_64 | a0fed5c50d849d0ab0eb5b45279ca1249d86ed12d7d830a8d3cbba9e87ea4dbb | 4217447 |

This qualifies the Pine plugin installation and runtime path. Draft desktop
packaging PR #10 requires a rebuild with these host changes and separate
packaged UI acceptance. Other runtime availability, notarization, older macOS
compatibility and long-running workloads are not established by these jobs.
