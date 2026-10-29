# CandleScope Pine plugin 0.3.3

This bridge uses the separately versioned downstream engine `0.3.2+cs.1`, built
from upstream `28ecae3c645e9269e2099d27cc9abbb1f52ee9ea` with the digest-pinned
`host-contracts-v1.patch`. It combines host-supplied candle boundaries and the
existing Renko event-series contract. It is not upstream Pine Runtime 0.3.3.

Host boundaries carry explicit timezone/calendar windows into `time_close`,
`request.security`, native strategy sessions and replay. The core does not read
host clocks, databases or network calendars. The existing Renko event cohort
semantics are retained. Pyne remains retired.

Release assets come from successful native `Pine host contracts` jobs for
Windows AMD64, Linux x86_64, macOS arm64 and macOS x86_64. Their receipts include
offline installation and protocol probes, engine calendar/Renko/realtime tests,
bridge tests, and real host DST/backtest/replay/restart tests. Published locks
and the official catalog use those exact qualified assets. Each platform passed
87 tests with no skips in [run 40835252471](https://github.com/helenananaa/CandleScope/actions/runs/40835252471),
on source `59f64ce6fcc31ff85ce64ca284ffaf79cf019eed`. The release includes wheel and
bundle hashes, four receipts, upstream source and downstream patch identities.
Linux wheels target the actual CI-built manylinux platform recorded in the
filename; no broader glibc compatibility is implied.

The previous 0.3.2 assets remain available for rollback. Old installed engines
without the boundary contract continue to reject unsupported calendar grids.
