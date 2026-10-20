# F117: retain the completed tape candle in replay indicators

In a two-market replay, advancing from `07:59:59.999` to `08:00:00.000`
without another trade left the `07:59` chart candle marked as forming. The
indicator runtime correctly rejected a forming candle whose close was already
behind the replay clock. Its calculation window consequently lost that candle,
displayed the previous minute's SMA/RSI, and could restart recursive preparation.

The normal ARM64 package at `a2559b27` (the same complete tree as main
`63908bfe`) reproduced this with LTC and DOGE positions and four 1m charts.
The independent 20-close means were LTC `63.486` and DOGE `0.086047`, but
the UI displayed `63.4825` and `0.086044`. Account values remained correct.
The defect also survived a complete process exit and archive restore.

Tape projection now closes the last selected display bucket after the clock
passes its inclusive end, provided the next immutable source trade is outside
that bucket or the selected source is exhausted. Reading that single next
timestamp proves completeness; its price and quantity never enter the output.
An older source selection with an unconsumed same-bucket trade remains forming,
including partial equal-millisecond cohorts. This does not fabricate subsequent
empty minutes, consume another trade, or mutate an earlier cached selection.

Regression coverage checks both tracks, 1m/2m displays, ordinary and coalesced
trade timestamps, truncated selections, cache isolation, and HTTP indicator
consumption of the newly closed candle. Existing calendar, sparse-history,
cancellation, restart, source identity, and recursive-prefix tests remain relevant.

Source validation passed 39 related backend tests and 117 related frontend
tests. Normal official-package requalification remains pending. Four warm command samples do not establish a release P95 or
resolve the separate cold-history and initial indicator preparation gaps.
