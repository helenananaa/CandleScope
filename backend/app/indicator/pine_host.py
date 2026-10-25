"""Host-owned Pine market bindings and compiled dependency discovery."""
from dataclasses import replace
from copy import deepcopy
from fractions import Fraction
import time

from candlescope_plugin_sdk import AnalyzeRequest, ExecuteBatchResult, Diagnostic
from app.core.executors import run_indicator
from app.data_engine.interval_policy import parse_interval_spec
from app.exchanges.symbol_catalog import get_cached_symbol_metadata


def pine_interval(value):
    import re
    if re.fullmatch(r"[1-9][0-9]*", value):
        return value + "m"
    match = re.fullmatch(r"([1-9][0-9]*)?([SDWM])", value)
    if not match:
        raise ValueError(f"PINE_REQUEST_INTERVAL_INVALID: {value}")
    return (match[1] or "1") + {"S": "s", "D": "d", "W": "w", "M": "M"}[match[2]]


def pine_timeframe(interval):
    spec = parse_interval_spec(interval)
    if spec is None:
        raise ValueError("PINE_REQUEST_INTERVAL_INVALID: unsupported chart interval")
    if spec.canonical.endswith("M"):
        return f"{spec.count}M"
    if spec.canonical.endswith("w"):
        return f"{spec.count}W"
    if spec.canonical.endswith("d"):
        return f"{spec.count}D"
    return str(spec.nominal_ms // 60_000) if spec.nominal_ms % 60_000 == 0 else f"{spec.nominal_ms // 1000}S"


def symbol_metadata(exchange, market_type, symbol):
    market_type = {"usdm": "futures", "swap": "futures"}.get(market_type, market_type)
    row = get_cached_symbol_metadata(exchange, market_type, symbol.removesuffix(".P"))
    if market_type == "coinm" or (row and row.get("inverseContract")):
        raise ValueError("PINE_INVERSE_CONTRACT_UNSUPPORTED: inverse contract accounting is unavailable")
    if not row or not row.get("priceTickSize"):
        return None
    tick = Fraction(str(row["priceTickSize"]))
    if tick <= 0 or max(tick.numerator, tick.denominator) > 4294967295:
        raise ValueError("PINE_PRICE_GRID_INVALID: instrument price grid is outside the runtime contract")
    metadata = {"minMove": tick.numerator, "priceScale": tick.denominator}
    for source, dest in (("quantityStep", "quantityStep"), ("minQuantity", "minContract")):
        if row.get(source):
            metadata[dest] = str(row[source])
    multiplier = row.get("contractMultiplier")
    if multiplier:
        metadata["pointValue"] = float(multiplier)
    currency = row.get("currency") or row.get("quoteAsset")
    if currency:
        metadata["currency"] = currency
    return metadata


def compiled_contexts(requirements, chart_symbol, chart_timeframe, explicit=()):
    from itertools import product
    found = []
    inventory = requirements.get("requests", [])
    symbols = {chart_symbol} | {item["symbol"]["value"] for item in inventory if item["symbol"]["kind"] == "literal" and item["symbol"].get("value")}
    timeframes = {chart_timeframe} | {item["timeframe"]["value"] for item in inventory if item["timeframe"]["kind"] == "literal" and item["timeframe"].get("value")}
    for item in inventory:
        pair = []
        for name, current in (("symbol", chart_symbol), ("timeframe", chart_timeframe)):
            value = item[name]
            if value["kind"] == "literal":
                pair.append([value["value"]] if value.get("value") else sorted(symbols if name == "symbol" else timeframes))
            elif value["kind"] in {"rootChartSymbol", "rootChartTimeframe"}:
                pair.append([current])
            elif value["kind"] in {"currentContextSymbol", "currentContextTimeframe"}:
                # HIR inventory deliberately omits the evaluation nesting. Bind
                # every statically possible current context, not just the root.
                pair.append(sorted(symbols if name == "symbol" else timeframes))
            elif explicit:
                pair = []
                break
            else:
                raise ValueError("PINE_DYNAMIC_CONTEXT_REQUIRED: supply explicit requested contexts for runtime symbol/timeframe expressions")
        if len(pair) == 2:
            for candidate in product(*pair):
                if candidate != (chart_symbol, chart_timeframe) and candidate not in found:
                    found.append(candidate)
        if len(found) > 32:
            raise ValueError("PINE_CONTEXT_LIMIT: conservative context inventory exceeds 32 providers; use fixed request bindings")
    return found


class PineHostInputs:
    def __init__(self, data_manager):
        self.data_manager = data_manager
        self.leases = {}

    async def release(self, owner):
        manager = self.data_manager()
        for stream in self.leases.pop(owner, {}).values():
            if manager is not None:
                await manager.release_stream(**stream)

    async def stop(self):
        for owner in list(self.leases):
            await self.release(owner)

    async def reconcile(self, owner, wanted):
        manager = self.data_manager()
        leased = self.leases.get(owner, {})
        for key in list(leased):
            if key not in wanted:
                if manager is not None:
                    await manager.release_stream(**leased[key])
                del leased[key]
        if not leased:
            self.leases.pop(owner, None)

    async def subscribe(self, owner, manager, symbol, interval, exchange, market_type):
        import hashlib
        key = (symbol, interval, exchange, market_type)
        leased = self.leases.setdefault(owner, {})
        if key in leased:
            return
        stream = {"symbol": symbol, "interval": interval, "exchange": exchange, "market_type": market_type,
                  "focus_scope": "websocket", "subscription_tier": "indicator",
                  "consumer_id": "pine-request:" + hashlib.sha256(str((owner, key)).encode()).hexdigest()}
        await manager.ensure_stream(**stream)
        leased[key] = stream

    async def prepare(self, request, host, runtime_id):
        if request.language != "pine":
            return request, None
        try:
            sdk = request.to_sdk_request()
            supplied = deepcopy(request.options.get("pineHost") or request.params.get("__pineHost") or {})
            if not isinstance(supplied, dict):
                raise ValueError("PINE_HOST_INPUT_INVALID: host inputs must be an object")
            alert_inputs = deepcopy(supplied)
            params = {key: value for key, value in request.params.items() if not key.startswith("__pine")}
            metadata = symbol_metadata(request.exchange, request.market_type, request.symbol)
            if metadata and not supplied.get("chartMetadata"):
                supplied["chartMetadata"] = metadata
            options = {**request.options, "pineHost": supplied,
                       "pineAlerts": request.params.get("__pineAlerts") is True,
                       "pineAlertInputs": alert_inputs}
            analysis = await host.analyze(runtime_id, AnalyzeRequest(request.source, sdk.context, options))
            if not analysis.ok or not analysis.executable:
                return request, ExecuteBatchResult(ok=False, diagnostics=analysis.diagnostics)
            requirements = analysis.meta.get("hostRequirements") or {}
            bindings = analysis.meta.get("hostBindings") or {}
            symbol = bindings.get("chartSymbol")
            timeframe = bindings.get("chartTimeframe")
            contexts = list(supplied.get("contexts") or [])
            pairs = compiled_contexts(requirements, symbol, timeframe, contexts)
            owner = request.options.get("pineLeaseId") if request.transport.startswith("websocket.") else None
            known = {(item["symbol"], item["timeframe"]) for item in contexts}
            wanted = set()
            for requested_symbol, requested_timeframe in pairs:
                if (requested_symbol, requested_timeframe) not in known:
                    exchange, raw_symbol = (requested_symbol.split(":", 1) if ":" in requested_symbol else (request.exchange, requested_symbol))
                    wanted.add((raw_symbol.removesuffix(".P"), pine_interval(requested_timeframe), exchange.lower(), request.market_type))
            if owner:
                await self.reconcile(owner, wanted)
            from app.data_preparation.native_plan import requested_lookbacks
            lookbacks = requested_lookbacks("\n".join([request.source, *supplied.get("libraries", {}).values()]),
                symbol=symbol, interval=request.interval, explicit=True)
            bars = sdk.bars
            spec = parse_interval_spec(request.interval)
            if bars and spec:
                times = [bar.time * 1000 if bar.time < 100_000_000_000 else bar.time for bar in bars]
                now = int(time.time() * 1000)
                if (requirements.get("execution") or {}).get("clock") == "explicitTimestampWhenEvaluated" and "executionTimes" not in supplied:
                    supplied["executionTimes"] = [spec.next_ms(t) - 1 if bar.is_closed else now for t, bar in zip(times, bars)]
                known = {(item["symbol"], item["timeframe"]) for item in contexts}
                manager = self.data_manager()
                for requested_symbol, requested_timeframe in pairs:
                    if (requested_symbol, requested_timeframe) in known:
                        continue
                    if manager is None:
                        raise ValueError("PINE_REQUEST_DATA_MISSING: market data service is unavailable")
                    exchange, raw_symbol = (requested_symbol.split(":", 1) if ":" in requested_symbol else (request.exchange, requested_symbol))
                    interval = pine_interval(requested_timeframe)
                    requested_spec = parse_interval_spec(interval)
                    if requested_spec is None:
                        raise ValueError("PINE_REQUEST_INTERVAL_INVALID: unsupported requested interval")
                    if owner:
                        await self.subscribe(owner, manager, raw_symbol.removesuffix(".P"), interval, exchange.lower(), request.market_type)
                    warmup = (supplied.get("requestWarmupBars") or {}).get(f"{requested_symbol}:{requested_timeframe}",
                        lookbacks.get((requested_symbol, requested_timeframe)))
                    if type(warmup) is not int or not 0 <= warmup <= 5000:
                        raise ValueError(f"PINE_REQUEST_WARMUP_REQUIRED: declare requestWarmupBars for {requested_symbol}:{requested_timeframe}")
                    start = requested_spec.floor_ms(times[0])
                    for _ in range(max(1, warmup)):
                        start = requested_spec.previous_ms(start)
                    end = spec.next_ms(times[-1]) - 1 if bars[-1].is_closed else min(now, spec.next_ms(times[-1]) - 1)
                    result = await run_indicator(manager.query, raw_symbol.removesuffix(".P"), interval,
                        start_ms=start, end_ms=end, limit=100_000, exchange=exchange.lower(),
                        market_type=request.market_type, auto_backfill=True, backfill_reason="pine_request")
                    if result.missing_ranges or result.history_state == "pending":
                        raise ValueError(f"PINE_REQUEST_DATA_PENDING: requested history has gaps for {requested_symbol} {requested_timeframe}")
                    rows = []
                    provider_forming = False
                    for bar in result.bars:
                        stamp = int(bar.time)
                        millis = stamp * 1000 if stamp < 100_000_000_000 else stamp
                        if millis <= end and (not bars[-1].is_closed or requested_spec.next_ms(millis) - 1 <= end):
                            rows.append({"time": millis // 1000, **{k: float(getattr(bar, k)) for k in ("open", "high", "low", "close", "volume")}})
                            provider_forming = not bool(getattr(bar, "is_closed", True))
                    if not rows:
                        raise ValueError(f"PINE_REQUEST_DATA_MISSING: waiting for {requested_symbol} {requested_timeframe}")
                    contexts.append({"symbol": requested_symbol, "timeframe": requested_timeframe, "bars": rows, "forming": provider_forming})
                    remote_metadata = symbol_metadata(exchange.lower(), request.market_type, raw_symbol)
                    if remote_metadata:
                        supplied.setdefault("symbolMetadata", {})[requested_symbol] = remote_metadata
                supplied["contexts"] = contexts
            return replace(request, params=params, options={**options, "pineHost": supplied}), None
        except ValueError as exc:
            code, _, message = str(exc).partition(":")
            return request, ExecuteBatchResult(ok=False, diagnostics=(Diagnostic(
                code=code if code.startswith("PINE_") else "PINE_HOST_INPUT_INVALID",
                severity="error", message=message.strip() or str(exc)),))
