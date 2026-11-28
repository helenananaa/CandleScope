# Read-only account through the proxy pool — dev preview (#575 PL-11c c)

Desktop dev build (Electron `desktop/main.mjs` + Vite + the branch backend through uvicorn), read-only account dock.

The account was seeded with the stale-marking harness (`docs/qa/readonly-account-stale-20261127/seed-fixture.py <data> error 0.5`), and the proxy settings with `seed-proxy-routes.py <data> okx`: pool mode, **HK 01** allows only Binance, **JP 02** allows every exchange. The backend ran through `preview_account_pool.py` (`uvicorn preview_account_pool:app --app-dir <this folder>`). This dev-only launcher replaces the Keychain read with fixed preview credentials and the synchronizer with one that makes no exchange calls. Route selection, the service loop, the state stream and the settings save path are the branch's real code.

| File | What it shows |
|---|---|
| `route-en.png` | The account runs on **JP 02**, because HK 01 doesn't allow OKX. The line explains failover and the IP allowlist consequence. |
| `route-zh.png` | The same in Simplified Chinese. |
| `no-route-en.png` | After `PUT /settings/proxy` made both routes Binance-only, the save restarted the account, which stopped with `ACCOUNT_PROXY_ROUTE_UNAVAILABLE` and its help text. It did not fall back to a direct connection. |

Also checked in the same run: a second `PUT` that allowed OKX on JP 02 again restarted the account, and the route line came back.

Not shown: failover between two live proxies. `backend/tests/test_readonly_account_proxy_pool.py` drives the service loop through it with fake clients.
