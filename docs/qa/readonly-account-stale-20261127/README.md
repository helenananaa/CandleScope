# Read-only account: out-of-date values (PL-9a, #575)

Dev desktop run (Electron `desktop/main.mjs` + Vite, backend from this branch
under uvicorn), isolated scratch profile, `TZ=UTC`. The account is a synthetic
fixture written by `seed-fixture.py` straight into the account database: no
credentials, no exchange calls.

| Screenshot | Fixture | Expected |
|---|---|---|
| `paused-zh.png`, `paused-sections-zh.png` | `seed-fixture.py <data> paused 25`: credentials removed, sync paused, snapshots 25 min old | header badge 已过期; notice with age + time and the paused reason; every section shows its age, an out-of-date badge and muted values |
| `sync-error-en.png` | `seed-fixture.py <data> error 8`: enabled account whose Keychain record does not exist, so the service stops with `KEYCHAIN_READ_FAILED`; snapshots 8 min old | notice says sync failed; the Keychain error alert stays below it |
| `local-service-lost-en.png` | same profile, backend process killed (`kill -9`) while the panel is open | notice says the local-service connection was lost; the stream error code is not repeated as a separate alert |

Not covered here: a live OKX account (no read-only key was used), and the
"sync running but slow" reason, which is covered by `accountFreshness.test.ts`.
