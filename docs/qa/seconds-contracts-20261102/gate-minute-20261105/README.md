# Gate minute admission and actual packaged interaction

Source026a1fb6e82a554532a58729397f5cc923e55b88 on main18cd6f34.
The earlier5f7ed32a packaged Gate1s parameter/recompute/new-indicator and
resize tests passed, then 1m switching failed with native_bar_basis_unknown.
That failure's profile and app remain preserved; the original failure receipt
is included. Both history/realtime regressions reproduced it before the fix.

The narrow fix declares Gate spot1m boundaries with official WS example and
captured public REST evidence; other unknown periods and markets remain
unqualified. 77 relevant backend regressions pass after the fix. Initial setup
attempts lacked pytest or the test temporary parent; these did not qualify the
change. The retained before/after logs are actual product regression outcomes.

The fresh source-verified local arm64 package passed **18 stages**: independent
Binance1s MA5 sibling, actual Gate MA parameter input5->7/Enter/recalculate,
new MA11, exact visible numerical MA7/11, canonical1s OHLCV, later closed BAR,
navigation,1400x900 and1060x780 content sizes, Gate1s->1m->1s, refresh,
save/full owned quit/restart and restored exact indicator definitions and
numerical/canonical checks. Both saved/restored screenshots were inspected.
No source responses or masks were substituted. The snapshots are historical
views with back-to-live controls, not a pixel-identical viewport assertion.

Both normal complete owned exits covered11 processes,15316/15337ms;
all22 recorded PIDs were separately verified absent. Renderer page errors=[];
no new418 observed. 1063 source/SDK files,164 build files,9 plugin assets and
76 plugin source files match; strict signature passed before and after exits.
Runtime was reused via APFS clone, not independently rebuilt or a CI installer.

This supplements the earlier5f7ed32a four-source27-stage Native receipt;
it does not silently reattribute that older full four-source run to026a1fb6.
Windows, broader131/157, USD-M1s and1s replay archives remain open. PR200
stays Draft while final head/base review and CI remain pending. Development
continues without waiting for CI.
