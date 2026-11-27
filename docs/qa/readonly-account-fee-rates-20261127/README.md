# Read-only account: fee rate estimates (PL-7, #575)

Dev desktop run (Electron `desktop/main.mjs` + Vite, backend from this branch
under uvicorn), isolated scratch profile, `TZ=UTC`. The account is a synthetic
fixture written by `seed-fixture.py <data> paused 1` straight into the account
database: no credentials, no exchange calls. The fee row is an OKX
`account/trade-fee` SWAP row passed through this branch's
`normalization.fee_rates`, so the panel shows what a real sync would store.

| Screenshot | Shows |
|---|---|
| `fee-rates-zh.png` | separate "fee rate estimates" section: USDT-margined maker is a rebate (OKX `makerU` +0.00005), shown as 返佣 0.005% rather than a negative fee; coin-margined maker/taker; tier and exchange update time |
| `fee-rates-last-read-en.png` | `FEE_ERROR=ACCOUNT_NETWORK_UNAVAILABLE`: the latest read failed, the last rates stay with a warning |

Not covered: a live OKX account (no read-only key was used), so the
`account/trade-fee` response shape is taken from OKX's v5 docs and CCXT's
parser, not from a real reply.
