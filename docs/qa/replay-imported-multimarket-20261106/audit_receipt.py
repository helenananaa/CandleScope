"""Independent Decimal/CSV oracle over actual Native receipts, without app imports."""
import base64
import csv
import hashlib
import json
import sys
from decimal import Decimal as D, ROUND_CEILING
from pathlib import Path

root = Path(sys.argv[1])
receipt = json.loads((root / "acceptance.json").read_text())
identity = json.loads((root / "multimarket-identities.json").read_text())
requests = json.loads((root / "replay-requests.json").read_text())
assert receipt["passed"] and not receipt["errors"]
initial = next(s["evidence"]["state"] for s in receipt["steps"] if s["name"] == "formal-replay-initialized")
added = next(s["evidence"]["afterAdd"] for s in receipt["steps"] if s["name"] == "two-imported-markets-added-through-native-ui")
reviews = [s["evidence"]["review"] for s in receipt["steps"] if s["name"] == "native-review-track-and-version"]
last = reviews[-1]
config = initial["config"]
assert config["slippage_model"]["kind"] == "fixed_bps"
slippage = D(config["slippage_model"]["market_bps"]) / D(10000)
fee_rate = D(config["fee_model"]["taker_bps"]) / D(10000)
leverage = D(config["max_leverage"])
equity = D(config["initial_equity"])
unrealized = D(0)
margin = D(0)
expected_fills = []
rows = []
image_hashes = []
orders = []
for request in requests:
    if request["method"] == "POST" and request.get("body"):
        body = json.loads(request["body"])
        if body.get("type") == "place_order":
            orders.append(body["payload"])
assert len(orders) == 2, orders
for track in identity["tracks"]:
    tid = track["track_id"]
    order = next(o for o in orders if o["client_order_id"] == "multi-buy-" + tid)
    assert order["side"] == "BUY" and order["order_type"] == "MARKET"
    quantity = D(order["quantity"])
    assert quantity == D("0.1")
    source = root / ("imported-replay.csv" if track["symbol"] == "BTCUSDT" else "second-replay.csv")
    with source.open() as stream:
        visible = [row for row in csv.DictReader(stream)
                   if int(row["time"]) + 59999 <= last["projection"]["cursor"]["virtual_time_ms"]]
    assert visible
    mark = D(visible[-1]["close"])
    fill_price = mark * (1 + slippage)
    fee = fill_price * quantity * fee_rate
    pnl = quantity * (mark - fill_price)
    equity += pnl - fee
    unrealized += pnl
    margin += (quantity * mark / leverage).quantize(D("0.00000001"), rounding=ROUND_CEILING)
    original, later = identity["originals"][tid], identity["later"][tid]
    assert original["trackId"] == later["trackId"] == tid
    assert original["id"] == later["id"] and original["revisionCount"] == 1 and later["revisionCount"] == 2
    assert original["links"] == [] and len(later["links"]) == 1
    link = later["links"][0]
    assert link["kind"] == "FILL" and link["side"] == "BUY"
    assert D(link["price"]) == fill_price and D(link["quantity"]) == quantity
    assert link["eventTimeMs"] == last["projection"]["cursor"]["virtual_time_ms"]
    capture = original["screenshots"][0]
    assert capture["trackId"] == tid and capture["dataEpoch"] == added[tid]["data_epoch"]
    upload = next(json.loads(r["body"]) for r in requests if r["method"] == "POST"
                  and r["path"].endswith(f"/tracks/{tid}/note-captures"))
    assert upload["context"]["trackId"] == upload["capturedContext"]["trackId"] == tid
    assert track["exchange"] in upload["chart"]["seriesKey"]
    assert track["symbol"] in upload["chart"]["seriesKey"]
    raw = base64.b64decode(upload["image"].split(",", 1)[1], validate=True)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    image_hashes.append(hashlib.sha256(raw).hexdigest())
    expected_fills.append((fill_price, quantity, fee))
    rows.append({"track": tid, "symbol": track["symbol"], "source": str(source),
                 "lastVisibleOpenMs": int(visible[-1]["time"]), "mark": str(mark),
                 "fillPrice": str(fill_price), "quantity": str(quantity), "fee": str(fee),
                 "linkId": link["id"], "imageSha256": image_hashes[-1]})
assert len(set(image_hashes)) == 2
observed = [(D(f["price"]), D(f["quantity"]), D(f["fee"])) for f in last["projection"]["fills"]]
assert sorted(observed) == sorted(expected_fills)
portfolio = last["projection"]["domain"]["portfolio"]
assert D(portfolio["equity"]) == equity
assert D(portfolio["unrealized_pnl"]) == unrealized
assert D(portfolio["margin_used"]) == margin
assert D(portfolio["reserved_margin"]) == 0
assert D(portfolio["available_equity"]) == equity - margin
assert sorted((p["track_id"], D(p["quantity"])) for p in portfolio["positions"]) == sorted((t["track_id"], D("0.1")) for t in identity["tracks"])
result = {"source": receipt["sourceCommit"], "oracle": "stdlib CSV and Decimal, no application imports; source closes and submitted quantity/configuration are the inputs",
          "orders": len(orders), "rows": rows, "equity": str(equity), "unrealizedPnl": str(unrealized),
          "margin": str(margin), "availableEquity": str(equity-margin),
          "collidingLocalFillIdsFencedByTrackAndPrice": rows[0]["linkId"] == rows[1]["linkId"], "passed": True}
(root / "financial-link-oracle.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
