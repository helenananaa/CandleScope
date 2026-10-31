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
suite ran 172 cases: 171 passed and one historical Linux-wheel identity control
skipped because its retained 0.3.0rc1 artifact is absent in the isolated checkout.

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

Full Host regression against this exact managed bundle passed 970 selected cases
across 78 modules, with no failures, errors or skips (16 Pyne cases deselected).
The source at `20772e0ac99ff5d707c8ba38e9e007a594f5ae22`, installed runtime and
registry remained unchanged: 1,317.21 seconds pytest, 1,331.25 seconds total.
This is distinct from the earlier full result on the unpatched engine.

A deeply nested managed install exposed Windows' executable path limit in the
native batch/session and qualification launches. Passing the same venv executable
as the explicit application name repairs it without selecting the base Python.
On the publication worktree, 59 checks passed against the actual 262-character
managed runtime path, covering long-path batch/session identity and reaping,
existing dual-clock/V2 regressions and an actual supervised Pine/cost worker.
The separate short-root managed installation supplied the full 970-case gate.

The chart book follow-up connects actual frozen inputs/identity, HTTP admission,
queued/colocated execution, independent costs, readback and the advanced research
upload control. In the isolated development checkout, 21 admission/actual-Pine
checks passed, including three book modes, historical V2 marks/funding and
non-unit multiplier observation, plus interruption recovery without rematching
old physical events. The broader runtime/context checks passed 69 cases. Research
frontend tests passed 36 cases; type checks and 30-locale i18n validation passed.
The publication worktree's full 81-module qualification then passed all 1,009
selected cases (16 Pyne deselected), including the new chart book path, with no
failures, errors or skips. This immutable gate used source
`56b8055822edd69ca4cb3b0abbc29bb707b00f45` and the actual managed candidate above:
1,535.78 seconds pytest and 1,541.36 seconds total. All 3,723 recorded source
files, installed runtime and registry remained unchanged during that gate.

The browser follow-up at `cb6d29f788514a2524cd8317432dbb4275443c34` changes only
eight frontend files and the chart-book documentation. A source-hash comparison
against the full gate confirms no backend or package file changed. Research
and i18n tests pass 76 cases on this publication source. The isolated browser
completed all three book modes through real HTTP/queued installed Pine workers.
A saved BOOK_DEPTH Run recreated without re-uploading has the same snapshot and
config hashes and fills. A saved BOOK_SAMPLED report and all three chart bars
remain readable after backend restart and page reload. An invalid replacement
file clears the old input and disables creation. The real strategy descriptor
uses `provider_kind: PINE_ENGINE`; a retained failing fixture exposed the old
hidden control. Korean and Brazilian Portuguese catalog failures from the
earlier macOS gate are retained, and the corrected 40-case i18n suite passes.
This is composed backend/frontend evidence, not a full Host gate at the later
frontend commit. The browser API uses deterministic fixtures and omits general
indicator and local-data routes; it is not packaged desktop acceptance.

Resources/long-history qualification, packaged desktop UI and
recovery acceptance, cross-platform wheels and a separately versioned public
release remain delivery gates.
