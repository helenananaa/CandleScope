# Continuous chart UI on main261

Source `16d55ed774ce27d28051593b436111a722735389` merges qualified #253
`4a4d2618c908f2fd8f8a6e9fc1db6b4c06678945` into prior #254
`d0bc7afac86beb3fb1c1863baea839d37bcd0504`, without conflicts. Includes actual
main261 `0de39f37f2389b09a35fc91e3a6d8d5844137da8`. The continuous UI contract is
unchanged; main's chart/source/cache/interval changes are propagated explicitly.

Current combined backend regression: **374 passed / 2 Windows-only skips /
5 existing warnings**, including real HTTP/WS and chart SDK sample creation,
Manager lifecycle, source fencing, Python processes and account/transaction tests.
Initial invocation lacked the parent of pytest basetemp; its fixture setup errors
are retained, the directory was created and the unchanged test command passed.

Full `npm run check` exited0: **4909 regular tests, 1 independent performance
check, 130 desktop tests; zero skipped**. Architecture/plugin/i18n, TypeScript,
ESLint and production Vite build completed. Existing SingleChartPanes ref-cleanup
lint warning and large-chunk build warning remain; do not describe this as zero
warnings. Backend architecture has the same10 findings as actual main261.
Precise commands, source/file/tree identities and logs are adjacent.

No public exchange or user profile was used. These are source/component/build
checks, not real-browser interactions or current Native install/save/full-owned-
quit/restart or Windows qualification. Original evidence retains its source.
Keep Draft; propagate to repair/saved-reader/research layers. CI is background
until a main merge requires exact-head/current-base applicable checks.
