# F113: a small valid order shows a zero budget and fee cap

Priority: P2. Original acceptance: REPLAY-15/REPLAY-17; related SIM-04/SIM-05.

The normal official desktop package at head de20cbfd reproduces this on a HEDGE/ISOLATED5x LTCUSDT run with pinned quote precision 1e-8. A valid BUY LONG LIMIT0.00015749@63.5 shows a budget and fee cap of `0 USDT`. The accepted unfilled order correctly reserves `0.00200514`: independently calculated margin `0.00200013` plus fee budget `0.00000501`. The account calculations and minimum-notional boundary are correct; the preview loses the nonzero amounts through formatting.

The order panel limited budget formatting to two fraction digits and fee formatting to four. Render both with the existing eight-digit formatter, retaining the currently supported quote-unit precision while trimming insignificant zeros. This is confined to the two preview values.

Native evidence is retained locally under `output/acceptance-delivery-20261016/batch-ah/`: AH114 above-threshold draft AX/screenshot, AH115 actual public orders and independent state proof, and F113-native-small-preview-zero.json. AH01 fixed the numerical expectations before the native run existed. The normal candidate still needs its own small-order preview verification before this issue is closed. Other sizing modes, extreme risk and the full acceptance scope require their own evidence.

Source validation: all 600 replay frontend tests, TypeScript checks, scoped ESLint and production build pass. The existing large-chunk build warning remains. Logs and source hashes are retained in `batch-ai/AI02-*`. These checks do not replace the exact candidate's official package and native preview gate.
