# Known requested history windows

Historical incremental feeds must distinguish the complete initial requested
endpoint from the prices currently available to Pine. Without that distinction,
`request.security(..., calc_bars_count=1)` can incorrectly anchor its window to
the first delivered row and accumulate later rows from that origin. A retained
actual-chart failure produces 100,300,600,1000,1500 where independent native
historical execution retains only the final requested value, 500.

The negotiated `candlescope.pine-request-window-plan/1` capability sends a list
of exact symbol/timeframe keys and ordered `times_ms` arrays once, with the fixed
chart plan. These headers contain no OHLCV, account feedback or strategy output.
Core owns count/inheritance semantics and nested requested evaluators. Actual
provider rows still arrive only through causally available update deltas.
Realtime continuation retains the initial window origin; it does not silently
turn an initial calculation window into a rolling one.

Chart and Workbench historical streams derive these headers from their frozen
requested sources. Opening records them in the stream checkpoint. Recovery
checks their exact agreement with the frozen feed before reconstructing Pine;
source, cursor, response and ledger pairing checks still apply. The chart
provider builds the metadata once instead of comparing the complete header
arrays on every observation. A worker lacking this capability rejects historical
requested streaming rather than returning the incorrect bounded-window result.

Controlled coverage compares native and streamed values at all four vertices,
including bounded lower-timeframe arrays and nested requests. It checks invalid
metadata atomicity, future-price rejection, historical-to-realtime continuation,
chart/Workbench skipped windows, header mutation and durable replay. These
checks do not finish the full combined gate, dynamic observed-feedback/rebase,
long-history resources or formal packaged acceptance.
