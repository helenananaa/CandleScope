# Read-only account on Windows: keys in Credential Manager (PL-5, #575)

## Real store checks

- `backend/tests/test_readonly_account_windows.py::test_real_store_keeps_reads_and_forgets_an_account_key`
  runs the account service against the real OS store: connect (with a fake
  OKX client) saves the key, the session reads it back to open its client,
  and forgetting the account deletes it.
  - Windows: CI runs it in `windows-python-worker.yml`, in the Credential
    Manager step, with `CANDLESCOPE_REAL_CREDENTIAL_VAULT=1`.
  - macOS: it was run by hand on 2026-11-28 against the login Keychain and
    passed.

## Dev preview (macOS)

Dev desktop run (Electron `desktop/main.mjs` + Vite, backend from this branch
under uvicorn), isolated scratch profile, `TZ=UTC`. This Mac can't run Windows, so
two stand-ins are used. `preview_account_windows.py` makes the account service
report `windows-credential-manager` as its store; keys still go to this Mac's
Keychain. The connect form reads that status field. Failure help follows the
computer the panel runs on (its user agent), so for the failure shot the page
ran with a Windows user agent through CDP `Emulation.setUserAgentOverride`.
With the Mac user agent the same state shows the Keychain help instead. The
status stream, the help mapping and the store failure are real.

| Screenshot | Shows |
|---|---|
| `connect-windows-en.png` | no account; the connect form says the key is stored in Windows Credential Manager on this computer |
| `missing-key-windows-zh.png` | `seed-account.py <data> error 1`: a bound credential ID with no stored key, so the session stops with `KEYCHAIN_READ_FAILED`; the help names Windows 凭据管理器 and says to replace the credentials if the data folder came from another computer or Windows account |

Not covered: the packaged Windows app. Neither the panel nor a real OKX
connect has been tried on Windows; CI covers the store and the service with a
fake OKX client.
