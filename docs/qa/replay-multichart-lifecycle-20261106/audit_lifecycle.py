"""Independent archive audit: chart consumers and held-track CSV/Decimal valuation."""
import csv
import json
import sys
from decimal import Decimal as D, ROUND_CEILING
from pathlib import Path
from urllib.parse import urlsplit

root = Path(sys.argv[1])
receipt = json.loads((root / "acceptance.json").read_text())
seed = json.loads((root / "multimarket-identities.json").read_text())
requests = json.loads((root / "replay-requests.json").read_text())
assert receipt["passed"] and not receipt["errors"]
views = {s["name"]: s["evidence"] for s in receipt["steps"] if "state" in s["evidence"] and "dom" in s["evidence"]}
initial = views["initial-two-restored-charts"]
tracks = {t["track_id"]: t for t in seed["tracks"]}
assert {t["symbol"] for t in tracks.values()} == {"BTCUSDT", "ETHUSDT"}
sources = {}
for tid, track in tracks.items():
    name = "imported-replay.csv" if track["symbol"] == "BTCUSDT" else "second-replay.csv"
    with (root / name).open() as stream:
        sources[tid] = {int(row["time"]): {k: D(row[k]) for k in ("open", "high", "low", "close", "volume")}
                        for row in csv.DictReader(stream)}


def live(view, market):
    rows = view["sockets"][market]
    assert all(urlsplit(r["url"]).netloc == urlsplit(view["backend"]).netloc for r in rows)
    return [(r["url"], r["at"]) for r in rows if not r.get("closedAt")]


counts = {
    "initial-two-restored-charts": (2, 1),
    "secondary-chart-last-consumer-closed": (1, 0),
    "secondary-chart-reopened": (2, 1),
    "same-adapter-two-period-consumers": (3, 1),
    "one-of-two-consumers-closed": (2, 1),
    "last-secondary-consumer-closed-again": (1, 0),
    "hidden-full-track-global-advance": (1, 0),
    "single-chart-layout-restored": (1, 0),
    "hidden-track-reopened-after-restart": (2, 1),
}
assert set(views) == set(counts)
for name, (charts, eth_streams) in counts.items():
    v = views[name]
    assert len(v["dom"]) == charts and len(live(v, "eth")) == eth_streams, name
    assert len(live(v, "btc")) == 1, name
    assert len(v["viewer"]["tracks"]["tracks"]) == 2
    assert all(t["subscription_tier"] == "FULL" for t in v["viewer"]["tracks"]["tracks"])
shared = live(views["secondary-chart-reopened"], "eth")
assert shared == live(views["same-adapter-two-period-consumers"], "eth")
assert shared == live(views["one-of-two-consumers-closed"], "eth")
assert views["same-adapter-two-period-consumers"]["backend"] != views["single-chart-layout-restored"]["backend"]
assert {row["header"].splitlines()[-1] for row in views["same-adapter-two-period-consumers"]["dom"]
        if row["track"] == "track-2"} == {"1m", "5m"}
for name in ["secondary-chart-last-consumer-closed", "last-secondary-consumer-closed-again"]:
    assert views[name]["sockets"]["eth"] and all(r.get("closedAt") for r in views[name]["sockets"]["eth"])

config = initial["state"]["track-1"]["config"]
cash = D(config["initial_equity"])
fills = {}
for tid, state in initial["state"].items():
    assert len(state["components"]["fills"]) == 1
    fill = state["components"]["fills"][0]
    assert fill["side"] == "BUY" and D(fill["quantity"]) == D("0.1")
    visible = [at for at in sources[tid] if at + 59999 <= fill["event_time_ms"]]
    reference = sources[tid][max(visible)]["close"]
    price = reference * (1 + D(config["slippage_model"]["market_bps"]) / D(10000))
    fee = price * D(fill["quantity"]) * D(config["fee_model"]["taker_bps"]) / D(10000)
    assert D(fill["price"]) == price and D(fill["fee"]) == fee
    cash -= fee
    fills[tid] = fill

results = []
for name, view in views.items():
    portfolio = view["viewer"]["tracks"]["portfolio"]
    equity, margin, unrealized = cash, D(0), D(0)
    marks = {}
    for tid, state in view["state"].items():
        cursor = state["cursor"]
        visible = [at for at in sources[tid] if at + 59999 <= cursor["virtual_time_ms"]]
        at = max(visible)
        assert at == cursor["last_base_bar_open_ms"]
        mark = sources[tid][at]["close"]
        fill = fills[tid]
        assert state["components"]["fills"] == initial["state"][tid]["components"]["fills"]
        qty = D(fill["quantity"])
        pnl = qty * (mark - D(fill["price"]))
        amount = (qty * mark / D(config["max_leverage"])).quantize(D("0.00000001"), rounding=ROUND_CEILING)
        equity += pnl
        unrealized += pnl
        margin += amount
        position = next(p for p in portfolio["positions"] if p["track_id"] == tid)
        assert D(position["position"]["quantity"]) == qty
        assert D(position["position"]["mark_price"]) == mark
        assert D(position["position"]["unrealized_pnl"]) == pnl
        assert D(position["initial_margin"]) == amount
        marks[tid] = str(mark)
    for field, value in [("cash_balance", cash), ("equity", equity), ("unrealized_pnl", unrealized),
                         ("margin_used", margin), ("available_equity", equity - margin)]:
        assert D(portfolio[field]) == value, (name, field, portfolio[field], value)
    assert D(portfolio["reserved_margin"]) == 0
    assert portfolio["history"]["orders_total"] == portfolio["history"]["fills_total"] == 2
    assert portfolio["ledger"]["entry_count"] == 3
    results.append({"stage": name, "marks": marks, "equity": str(equity), "margin": str(margin),
                    "availableEquity": str(equity - margin), "charts": len(view["dom"]),
                    "ethStreams": len(live(view, "eth"))})
advanced = views["hidden-full-track-global-advance"]["state"]
for tid, state in advanced.items():
    old = initial["state"][tid]
    assert state["cursor"]["source_sequence"] - old["cursor"]["source_sequence"] == 3
    assert state["cursor"]["virtual_time_ms"] - old["cursor"]["virtual_time_ms"] == 180000
    assert state["data_epoch"] == old["data_epoch"]
assert advanced["track-1"]["cursor"]["virtual_time_ms"] == advanced["track-2"]["cursor"]["virtual_time_ms"]
for name in ["single-chart-layout-restored", "hidden-track-reopened-after-restart"]:
    for tid, state in views[name]["state"].items():
        for field in ["cursor", "components", "data_epoch"]:
            assert state[field] == advanced[tid][field]
assert not [r for r in requests if r["method"] == "POST" and r.get("body")
            and json.loads(r["body"]).get("type") == "place_order"]
result = {"passed": True, "source": receipt["sourceCommit"], "oracle": "stdlib CSV/Decimal and captured socket/DOM observations; no app imports",
          "views": results, "hiddenTrackAdvancedEvents": 3, "newOrders": 0,
          "scope": "same-run two FULL imported BAR tracks; consumer sharing/closure, single-chart layout restart and hidden held-track valuation"}
(root / "independent-lifecycle-oracle.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
