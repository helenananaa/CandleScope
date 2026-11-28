# Scheduled subscription refresh — dev preview (#575 PL-11c b)

Desktop dev build (Electron `desktop/main.mjs` + Vite + the branch backend through uvicorn), Settings → Network → Multiple routes → Proxy subscription.

The profile was seeded with `seed-fixture.py <data_dir>`: pool mode, three routes from two subscriptions, and refresh history (one source updated a node 2 hours ago and lost one; the other failed with HTTP 503 half an hour ago). No snapshot files or Keychain item exist, so the proxy core stays down and the scheduled check skips both sources while keeping their history. Only the panel is shown.

| File | What it shows |
|---|---|
| `auto-refresh-en.png` | English: per-source result under each Refresh button and the interval select (24 hours). |
| `auto-refresh-zh.png` | Simplified Chinese. |
| `auto-refresh-ru.png` | Russian. The options read "Каждые 6 часов" and "Каждые 24 часа": the hour unit comes from `Intl.NumberFormat`, so each language gets its own plural form. |

Also checked in the same run: choosing "Every 6 hours" in the select wrote `interval_hours: 6` to `proxy-subscription-refresh.json` and the GET endpoint returned it.

Not shown: a real refresh against a provider; the backend tests cover that with a fake core (`backend/tests/test_proxy_subscription_scheduled_refresh.py`).
