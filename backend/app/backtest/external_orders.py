"""Host-owned order IDs and entry quantity allocation over one net account.

Lots allocate quantities only. Cash, PnL, fees and the average-cost position are
always the kernel ledger; this module never maintains a second account.
"""
from decimal import Decimal
from .errors import BacktestError

ZERO = Decimal(0)
LIVE = {"OPEN", "PARTIAL"}


class ExternalOrders:
    def __init__(self, kernel, *, price_tick=None, fidelity="BAR_APPROX"):
        self.kernel = kernel
        self.bindings, self.details = {}, {}
        self.lots, self.allocations = [], []
        self.pyramiding = None
        self.price_tick = None if price_tick is None else Decimal(str(price_tick))
        self.fidelity = fidelity
        kernel.execution_reporter = self.on_execution
        kernel.order_policy = self.prepare_order
        if hasattr(kernel, "_resting_filter_enabled"):
            kernel._resting_filter_enabled = False

    def configure(self, limit):
        if type(limit) is not int or not 1 <= limit <= 64:
            raise BacktestError("EXTERNAL_UNSUPPORTED", "pyramiding must be an integer from 1 to 64")
        if self.pyramiding is not None and self.pyramiding != limit:
            raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "pyramiding changed during the run")
        self.pyramiding = limit

    def owned(self, entry_id=None):
        return sum((lot["qty"] for lot in self.lots if not entry_id or lot["entry_id"] == entry_id), ZERO)

    def pending(self, entry_id=None):
        return [order for order in self.kernel.orders if order.status in LIVE
                and self.bindings.get(order.order_id, (None, None))[1] == "entry"
                and (not entry_id or self.bindings[order.order_id][0] == entry_id)]

    def cancel_order(self, order, reason):
        order.status = "CANCELLED"
        self.kernel._lifecycle(order, "CANCELLED", reason=reason)

    def prepare_order(self, order, event):
        if order.status not in LIVE:
            return False
        detail = self.details.get(order.order_id)
        if detail is None:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "unbound host order")
        if detail["kind"] == "entry":
            position, direction = self.kernel.account.position_qty, detail["direction"]
            own_lot = any(lot["order_id"] == order.order_id for lot in self.lots)
            if position * direction > 0 and not own_lot and len(self.lots) >= (self.pyramiding or 1):
                self.cancel_order(order, "EXTERNAL_PYRAMID_LIMIT")
                return False
            # Pending reversals use the live position, never the submission-time size.
            order.qty = detail["remaining"] + (abs(position) if position * direction < 0 else ZERO)
        else:
            position = self.owned(detail["owner"])
            if not position:
                if self.pending(detail["owner"]):
                    return False  # A bracket may precede its entry fill.
                self.cancel_order(order, "EXTERNAL_ENTRY_CLOSED")
                return False
            order.side = "SELL" if position > 0 else "BUY"
            order.qty = min(detail["remaining"], abs(position))
            if detail.get("distance") is not None or detail.get("trailing"):
                selected = [lot for lot in self.lots if not detail["owner"] or lot["entry_id"] == detail["owner"]]
                basis = sum((abs(lot["qty"])*lot["price"] for lot in selected), ZERO)/abs(position)
                if self.fidelity == "BAR_APPROX":
                    # One price basis per bar keeps the worst-case OCO scan and
                    # later matching consistent if another entry fills inside it.
                    if detail.get("basis_sequence") != event.sequence:
                        detail.update(basis_sequence=event.sequence, basis=basis)
                    basis = detail["basis"]
                direction = Decimal(1) if position > 0 else Decimal(-1)
                if detail.get("trailing"):
                    if detail.get("triggered"):
                        order.type = "MARKET"
                        return order.qty > 0
                    price = Decimal(str(event.payload["price"]))
                    activation = detail.get("trail_price")
                    if activation is None:
                        activation = basis + direction * detail["trail_points"] * self.price_tick
                    watermark = detail.get("watermark")
                    if watermark is None:
                        if (price-activation)*direction < 0:
                            return False
                        watermark = price
                    watermark = max(watermark, price) if direction > 0 else min(watermark, price)
                    detail["watermark"] = watermark
                    target = watermark - direction*detail["trail_offset"]*self.price_tick
                    order.stop_price = target
                else:
                    target = basis + direction * detail["distance"] * self.price_tick * (1 if order.type == "LIMIT" else -1)
                    if order.type == "LIMIT": order.limit_price = target
                    else: order.stop_price = target
                if target <= 0:
                    raise BacktestError("EXTERNAL_UNSUPPORTED", "distance exit produced a nonpositive price")
        return order.qty > 0

    def on_execution(self, event):
        fill = event.get("fill")
        if not fill:
            return
        order_id = event["order_id"]
        detail = self.details[order_id]
        if detail.get("trailing"):
            detail["triggered"] = True
        script_id, kind = self.bindings[order_id]
        qty = Decimal(str(fill["qty"]))
        before, after = Decimal(str(fill["position_before"])), Decimal(str(fill["position_after"]))
        direction = Decimal(1) if fill["side"] == "BUY" else Decimal(-1)
        closing = min(abs(before), qty) if before * direction < 0 else ZERO
        remaining_close, closed = closing, []
        for lot in self.lots:
            if remaining_close <= 0:
                break
            if kind != "entry" and detail["owner"] and lot["entry_id"] != detail["owner"]:
                continue
            take = min(abs(lot["qty"]), remaining_close)
            lot["qty"] -= (Decimal(1) if lot["qty"] > 0 else Decimal(-1)) * take
            remaining_close -= take
            closed.append({"entry_id":lot["entry_id"], "entry_order_id":lot["order_id"], "qty":str(take)})
        if remaining_close:
            raise BacktestError("EXTERNAL_ACCOUNT_MISMATCH", "fill exceeded the owned entry quantity")
        self.lots = [lot for lot in self.lots if lot["qty"]]
        opening = qty - closing
        if opening:
            if kind != "entry":
                raise BacktestError("EXTERNAL_ACCOUNT_MISMATCH", "exit opened a position")
            lot = next((lot for lot in self.lots if lot["order_id"] == order_id), None)
            price = Decimal(str(fill["price"]))
            if lot is None:
                self.lots.append({"entry_id":script_id,"order_id":order_id,"qty":opening*direction,"price":price})
            else:
                lot["price"] = (abs(lot["qty"])*lot["price"] + opening*price)/(abs(lot["qty"])+opening)
                lot["qty"] += opening*direction
        detail["remaining"] = max(ZERO, detail["remaining"] - (opening if kind == "entry" else qty))
        filled = next(order for order in self.kernel.orders if order.order_id == order_id)
        for order in self.kernel.orders:
            if order.order_id == order_id or order.status not in LIVE:
                continue
            sibling = self.details[order.order_id]
            if filled.oco_group and filled.oco_group.startswith("external-exit-") and order.oco_group == filled.oco_group:
                sibling["remaining"] = max(ZERO, sibling["remaining"] - qty)
                order.qty = sibling["remaining"]
                if not order.qty:
                    order.status = "CANCELLED_OCO"
                    self.kernel._lifecycle(order, order.status, reason="EXTERNAL_OCO_REDUCED")
            if sibling["kind"] != "entry" and not self.owned(sibling["owner"]) and not self.pending(sibling["owner"]):
                if order.status in LIVE:
                    self.cancel_order(order, "EXTERNAL_ENTRY_CLOSED")
        if self.owned() != after or after != self.kernel.account.position_qty:
            raise BacktestError("EXTERNAL_ACCOUNT_MISMATCH", "entry allocations differ from host position")
        self.allocations.append({"order_id":order_id,"sequence":fill["sequence"],"closed":closed,
            "opened": {"entry_id":script_id,"qty":str(opening)} if opening else None,
            "position_qty":str(after)})

    def feedback(self):
        if self.owned() != self.kernel.account.position_qty:
            raise BacktestError("EXTERNAL_ACCOUNT_MISMATCH", "entry allocations differ from host position")

    def translate(self, intents, sequence):
        kernel, staged = self.kernel, []
        def cancel(script_id=None):
            staged[:] = [row for row in staged if script_id is not None and row[1] != script_id]
            for order in kernel.orders:
                if order.status in LIVE and (script_id is None or self.bindings.get(order.order_id, (None,))[0] == script_id):
                    self.cancel_order(order, "SCRIPT_CANCEL_OR_REPLACE")
        def quantity(intent, available):
            if intent.get("qty") is not None:
                return min(available, Decimal(str(intent["qty"])))
            return available * Decimal(str(intent.get("qty_percent") or 100)) / 100
        for intent in intents:
            action, script_id = intent["action"], intent["id"]
            if action in {"cancel", "cancel_all"}:
                cancel(script_id if action == "cancel" else None)
                continue
            if action not in {"entry", "close", "close_all", "exit"}:
                raise BacktestError("EXTERNAL_UNSUPPORTED", "unknown order intent")
            position = kernel.account.position_qty
            if action == "entry":
                cancel(script_id)
                direction = Decimal(1) if intent["direction"] == "long" else Decimal(-1)
                if position * direction > 0 and len(self.lots) >= (self.pyramiding or 1):
                    continue
                opening = Decimal(str(intent["qty"]))
                qty = opening + (abs(position) if position * direction < 0 else ZERO)
                limit, stop = intent.get("limit"), intent.get("stop")
                # Explicit independent groups prevent the kernel's legacy
                # limit+stop heuristic from pairing unrelated script entries.
                order = {"side":"BUY" if direction > 0 else "SELL","qty":str(qty),
                    "oco_group":f"external-entry-{sequence}-{script_id}",
                    "type":"STOP_LIMIT" if limit is not None and stop is not None else "LIMIT" if limit is not None else "STOP" if stop is not None else "MARKET"}
                if limit is not None: order["limit_price"] = str(limit)
                if stop is not None: order["stop_price"] = str(stop)
                staged.append((order,script_id,{"kind":"entry","remaining":opening,"direction":direction}))
                continue
            trail_watermark = None
            trail_triggered = False
            owner = script_id if action == "close" else intent.get("from_entry") if action == "exit" else None
            position = self.owned(owner)
            if action == "exit":
                relative = any(intent.get(key) is not None for key in ("profit","loss","trail_points","trail_offset"))
                if relative and (self.price_tick is None or not self.price_tick.is_finite() or self.price_tick <= 0):
                    raise BacktestError("EXTERNAL_UNSUPPORTED", "tick-distance orders require an explicit positive host price_tick")
                if intent.get("trail_offset") is not None and self.fidelity == "BAR_APPROX":
                    raise BacktestError("EXTERNAL_UNSUPPORTED", "trailing stops require ordered trade events")
                if ((intent.get("profit") is not None and intent.get("limit") is not None)
                        or (intent.get("loss") is not None and intent.get("stop") is not None)):
                    raise BacktestError("EXTERNAL_UNSUPPORTED", "choose absolute price or tick distance for each exit leg")
                for old in kernel.orders:
                    if old.status not in LIVE or self.bindings[old.order_id][0] != script_id:
                        continue
                    meta = self.details[old.order_id]
                    if (meta.get("trailing") and meta.get("owner") == owner
                            and all(meta.get(key) == (None if intent.get(key) is None else Decimal(str(intent[key])))
                                    for key in ("trail_price","trail_points","trail_offset"))):
                        trail_watermark = meta.get("watermark")
                        trail_triggered = meta.get("triggered", False)
                cancel(script_id)
                if not position:
                    pending = [(row,meta) for row,sid,meta in staged if meta["kind"] == "entry" and (not owner or owner == sid)]
                    pending += [({"side":order.side}, self.details[order.order_id]) for order in self.pending(owner)]
                    if pending:
                        direction = Decimal(1) if pending[0][0]["side"] == "BUY" else Decimal(-1)
                        position = sum((meta["remaining"] for _,meta in pending if meta["direction"] == direction), ZERO)*direction
            if not position:
                continue
            qty = quantity(intent, abs(position))
            base = {"side":"SELL" if position > 0 else "BUY","qty":str(qty),"reduce_only":True}
            detail = {"kind":"exit" if action == "exit" else "close","owner":owner,"remaining":qty}
            if action != "exit":
                staged.append(({**base,"type":"MARKET"},script_id,detail))
            else:
                group = f"external-exit-{sequence}-{script_id}"
                for name,kind,distance in (("limit","LIMIT","profit"),("stop","STOP","loss")):
                    if intent.get(name) is not None or intent.get(distance) is not None:
                        meta = dict(detail)
                        if intent.get(distance) is not None:
                            meta["distance"] = Decimal(str(intent[distance]))
                        # A positive placeholder satisfies order admission. The price is
                        # bound to actual allocated fills before this order can match.
                        price = intent.get(name) if intent.get(name) is not None else 1
                        staged.append(({**base,"type":kind,name+"_price":str(price),"oco_group":group},script_id,meta))
                if intent.get("trail_offset") is not None:
                    meta = {**detail,"trailing":True,"watermark":trail_watermark,"triggered":trail_triggered,
                            **{key:Decimal(str(intent[key])) for key in ("trail_price","trail_points","trail_offset") if intent.get(key) is not None}}
                    staged.append(({**base,"type":"STOP","stop_price":"1","oco_group":group},script_id,meta))
        for index,(_,script_id,detail) in enumerate(staged):
            key = f"ord-{kernel._next_order_id+index}"
            self.bindings[key] = (script_id, detail["kind"])
            self.details[key] = detail
        return [row[0] for row in staged]

    def report(self):
        return {"model":"HOST_NET_AVERAGE_COST_ENTRY_QUANTITY_FIFO_V1", "price_tick":None if self.price_tick is None else str(self.price_tick),
                "open_entries":[{**lot,"qty":str(lot["qty"]),"price":str(lot["price"])} for lot in self.lots],
                "fill_allocations":self.allocations}
