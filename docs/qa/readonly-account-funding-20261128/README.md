# Read-only account: funding account (PL-6, #575)

Dev desktop run (Electron `desktop/main.mjs` + Vite, backend from this branch
under uvicorn), isolated scratch profile per run, `TZ=UTC`. The account is a
synthetic fixture: `seed-account.py <data> synced 2` writes the trading
snapshots, `seed-funding.py <data> ok|error` writes the funding snapshots
straight into the account database. Every funding row is an OKX-shaped row
passed through this branch's `normalization.funding_balance`, `deposit`,
`withdrawal` and `transfer`, so the tab shows what a real sync would store.
The backend entry is `preview_account_live.py`: the account session starts
with a stand-in credential store and a stand-in synchronizer, so nothing reads
the Keychain or calls OKX. Because nothing refreshes, the trading snapshots
show "Out of date" in these shots; that badge is the harness, not the feature.

| Screenshot | Shows |
|---|---|
| `funding-balances-en.png` | the new Funding tab: funding account balances (balance, available, frozen per currency) apart from the trading account, with the help text that they are not margin and CandleScope can't move them |
| `funding-history-en.png` | deposits, withdrawals and transfers, newest first: deposits signed "+", with network and status (In progress, Completed) |
| `funding-history2-en.png` | a withdrawal signed "−" with its fee on its own row; a transfer with a bare amount and its route (Trading account → Funding account); a deposit On hold |
| `funding-history-zh.png` | the same in Simplified Chinese |
| `funding-history-ar.png` | Arabic: the route arrow reads right to left (حساب التمويل ← حساب التداول) |
| `funding-failed-en.png` | `seed-funding.py error`: the balance read failed (`ACCOUNT_NETWORK_UNAVAILABLE`); the last balances stay, with a warning and their older snapshot time |
| `funding-partial-en.png` | the history read hit its page budget: a warning says only the newest records were read |

Not covered:

- A live OKX account (no read-only key was used). The shapes of
  `asset/balances`, `asset/deposit-history`, `asset/withdrawal-history` and the
  type 1 rows of `account/bills-archive` come from OKX's v5 docs and CCXT's
  implicit API, not from real replies. The deposit and withdrawal state tables
  follow the documented codes; an undocumented code shows as "Unknown".
- Sub-account transfers. They may also be type 1 bills; the tab shows them
  with the accounts OKX names, but no real one was seen.
- Right-to-left signs: under Arabic and Hebrew a leading "+" or "−" renders
  after the number ("USDT 300−"). The rest of the dock does the same (no tab
  isolates numbers), so this is left for a dock-wide fix.
