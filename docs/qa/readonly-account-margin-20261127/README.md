# Read-only account: leverage, liquidation price and available margin (PL-8, #575)

Dev desktop run (Electron `desktop/main.mjs` + Vite, backend from this branch
under uvicorn), isolated scratch profile, `TZ=UTC`. The account is a synthetic
fixture written by `seed-fixture.py <data> paused 1` straight into the account
database: no credentials, no exchange calls. The fixture's raw OKX rows go
through this branch's `normalization.position`, so the panel shows exactly what
a real sync would store.

| Screenshot | Shows |
|---|---|
| `positions-zh.png`, `positions-en.png` | BTC-USDT-SWAP long, cross: margin mode, 10× leverage, est. liquidation price in USDT, initial margin used in USDT, settlement currency, exchange update time |
| `isolated-zh.png` | ETH-USD-SWAP short (coin-margined), isolated: liquidation price in USD, isolated margin in ETH, settles in ETH |
| `balances-zh.png`, `balances-en.png` | available margin per currency (`availEq`) with its unit and exchange update time; ETH has no available equity from the exchange, shown as "—" |

Not covered: a live OKX account (no read-only key was used); multi-currency
or portfolio margin accounts (their per-currency `availEq` is shown the same
way, with no account-level USD figure).
