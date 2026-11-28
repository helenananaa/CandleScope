"""seed-account-pool.py <data_dir> <okx|none>: pool routes; with 'none' no route allows OKX."""
import json, sys
from pathlib import Path
data = Path(sys.argv[1])
okx = sys.argv[2] == "okx"
routes = [
    {"id": "hk01", "name": "HK 01 · Binance only", "url": "http://127.0.0.1:17901", "egress_group": "hk", "enabled": True, "exchanges": ["binance"], "max_concurrency": 4},
    {"id": "jp02", "name": "JP 02", "url": "http://127.0.0.1:17902", "egress_group": "jp", "enabled": True, "exchanges": [] if okx else ["binance"], "max_concurrency": 4},
]
(data / "proxy_settings.json").write_text(json.dumps({"mode": "pool", "custom_proxy": None, "routes": routes, "strategy": "failover"}))
