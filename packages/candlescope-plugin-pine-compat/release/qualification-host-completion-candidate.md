# Windows Host completion candidate

This unpublished candidate uses the separate
`release-lock.host-completion-candidate.windows-x86_64.json`. The published
0.3.2 locks and catalog remain the rollback reference. The candidate retains
version 0.3.2; its wheel and bundle digests distinguish it from that release.

The engine base is `232b93dd109108d227a522ef3f3bcb32ed31a002`, with the
`renko-event-rows-v2.patch` source represented by
`199aca438a150a436d6724ceee0afd4595a76b92`. The exact source passed 7,999 Rust
workspace tests, 2,003 installed-wheel Python tests, strict all-target Clippy,
format, structure, host parity and generated WASM/Node smoke checks. The tooling
suite ran 172 cases: 171 passed and one platform-dependent case skipped.

The installed native SHA-256 is
`b0142f11d986f35a043a294cd844608140540b3ef4f2fa493947bc4d3119ca3f`.
On the same wheel, the bridge suite passed 153 cases without optional Renko
skips. Seven selected Host cases passed, including physical-price standard and
Renko execution on the actual frozen LTC tape and existing prefix controls.
These are controlled regression results, not arbitrary Renko/streaming-window
cross-product or TradingView construction equivalence.

The bundle SHA-256 is
`fba5c62093fb3b7b2b69e03dcc3be9eff0b3b5d7e1b54cf7a3cc5f7e9daf5111`.
The real managed installer verified its wheel digests, created a fresh offline
environment, passed both protocol probes, activated only its isolated candidate
registry and passed a second full installation check. The execution probe output
and hash remain equal to the published probe (Close x2 = 202, 204). The analysis
probe now reports the current Host requirements, including contract metadata and
the independent minimum/step quantity contract, so the candidate pins its new
analysis digest. An initial stale-analysis-hash installation was rejected and
its failed bundle and log were retained.

Full Host regression against this managed bundle, resources/long-history
qualification, packaged desktop UI and recovery acceptance, cross-platform
wheels and a separately versioned public release remain delivery gates. The
previous full Host result (970 cases) used the unpatched engine and cannot be
substituted for this candidate's full regression.
