"""seed-proxy.py <data_dir>: pool routes from two subscriptions plus refresh history.
No snapshot files and no keychain item: the core stays down; only the panel is shown."""
import hashlib, json, sys, time
from pathlib import Path
data = Path(sys.argv[1]); data.mkdir(parents=True, exist_ok=True)
now = int(time.time() * 1000)
def sid(url): return hashlib.sha256(url.encode()).hexdigest()[:16]
def key(source, name): return source + hashlib.sha256(name.encode()).hexdigest()[:16]
a, b = sid("https://provider-a.invalid/sub"), sid("https://provider-b.invalid/sub")
rev_a, rev_b = "a" * 64, "b" * 64
def route(source, rev, name):
    k = key(source, name)
    return {"id": "sub_" + k, "name": name, "url": f"mihomo://{rev}/{k}", "egress_group": "shared",
            "enabled": True, "exchanges": [], "max_concurrency": 4, "max_ws_subscriptions": 64}
routes = [route(a, rev_a, "HK 01 · Trojan"), route(a, rev_a, "JP 02 · VLESS Reality"), route(b, rev_b, "SG 03 · VMess ws")]
(data / "proxy_settings.json").write_text(json.dumps({"mode": "pool", "custom_proxy": None, "routes": routes, "strategy": "failover"}))
hour = 3_600_000
(data / "proxy-subscription-refresh.json").write_text(json.dumps({"interval_hours": 24, "sources": {
    a: {"last_attempt_ms": now - 2 * hour, "last_success_ms": now - 2 * hour, "last_change_ms": now - 2 * hour,
        "updated": 1, "missing": 1, "error": None},
    b: {"last_attempt_ms": now - hour // 2, "last_success_ms": now - 26 * hour, "error": "Subscription returned HTTP 503"},
}}))
print(a, b)
