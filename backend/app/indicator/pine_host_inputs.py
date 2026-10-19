"""Host-owned exchange metadata and observation clock for Pine indicators."""

from __future__ import annotations

import re
import time

from app.data_engine.interval_policy import parse_interval_spec
from app.exchanges.symbol_catalog import get_cached_symbol_metadata


def indicator_host_options(request, options):
    options = dict(options)
    options.setdefault("pineExecutionTimeMs", int(time.time() * 1000))
    metadata = get_cached_symbol_metadata(
        request.exchange, request.market_type, request.symbol
    )
    if metadata and metadata.get("priceTickSize"):
        options.setdefault(
            "pineChartMetadata", {"priceTickSize": metadata["priceTickSize"]}
        )
        quote = metadata.get("quoteAsset")
        if isinstance(quote, str) and re.fullmatch(r"[A-Z]{1,20}", quote) and isinstance(options["pineChartMetadata"], dict):
            options["pineChartMetadata"] = {"currency": quote, **options["pineChartMetadata"]}
    return options


def requested_data(request, requirements, data_manager):
    """Read already-local standard candles, without fetching or substituting markets."""
    requests = requirements.get("requests", [])
    if not requests or not request.bars:
        return {}
    if len(requests) > 16:
        return {"pineRequestError": "At most 16 requested contexts are supported."}
    if data_manager is None:
        return {
            "pineRequestError": "Requested market data is unavailable until the data service is ready."
        }
    bars = request.bars
    last = bars[-1]
    asof = parse_interval_spec(request.context.interval).next_ms(last.time * 1000)
    if not last.is_closed:
        asof = min(asof, request.options.get("pineExecutionTimeMs", int(time.time() * 1000)))
    try:
        contexts = requested_contexts(request, requests)
    except ValueError as exc:
        return {"pineRequestError": str(exc)}
    supplied = {}
    total = 0
    for symbol, timeframe, market_type in contexts:
        venue, separator, ticker = symbol.partition(":")
        if not separator:
            ticker, venue = symbol or request.context.symbol, request.context.exchange
        if not venue or not ticker:
            return {"pineRequestError": "A requested symbol must name an exact exchange and instrument."}
        if symbol == chart_pine_symbol(request.context):
            # The Pine chart alias is a proven mapping of this chart's storage
            # instrument (e.g. BINANCE:BTCUSDT.P -> BTCUSDT in usdm), not a guess
            # that an arbitrary requested perpetual is a spot market.
            ticker = request.context.symbol
        key = f"{symbol}:{timeframe}"
        if key in supplied:
            continue
        try:
            interval = parse_interval_spec(
                pine_interval(timeframe or request.context.interval)
            )
            result = data_manager.query(
                ticker,
                interval.canonical,
                end_ms=asof - 1,
                limit=100_001 - total,
                exchange=venue.lower(),
                market_type=market_type,
                auto_backfill=False,
            )
        except (ValueError, KeyError) as exc:
            return {"pineRequestError": str(exc)}
        if not result.bars or getattr(result, "missing_ranges", ()):
            return {
                "pineRequestError": f"Prepare complete local data for {symbol} / {timeframe} first."
            }
        if len(result.bars) + total > 100_000:
            return {
                "pineRequestError": "Requested contexts exceed the combined 100000-bar budget."
            }
        rows = []
        for bar in result.bars:
            timestamp = int(bar.time)
            if (
                getattr(bar, "is_closed", True)
                and interval.next_ms(timestamp * 1000) <= asof
            ):
                rows.append(
                    {
                        "time": timestamp * 1000,
                        **{
                            key: float(getattr(bar, key))
                            for key in ("open", "high", "low", "close", "volume")
                        },
                    }
                )
        supplied[key] = rows
        total += len(rows)
    return {"pineRequestBars": supplied}


def requested_contexts(request, requirements):
    """Resolve finite provider keys, never evaluate source or guess a dynamic key.

    Explicit contexts also specify the market type on a different exchange.
    An unqualified context retains the chart's market type, never a spot fallback.
    """
    explicit = request.options.get("pineRequestContexts", [])
    if not isinstance(explicit, list) or len(explicit) > 16:
        raise ValueError("Declare at most 16 Pine requested contexts.")
    contexts = {}
    for item in explicit:
        if not isinstance(item, dict) or set(item) - {"symbol", "timeframe", "marketType"}:
            raise ValueError("Each Pine context needs symbol, timeframe and optional marketType.")
        symbol, timeframe = item.get("symbol"), item.get("timeframe")
        market = item.get("marketType", request.context.market_type)
        if (
            not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9._:/!-]{1,120}", symbol)
            or not isinstance(timeframe, str) or not re.fullmatch(r"(?:[1-9][0-9]*[SDWM]?|[SDWM])", timeframe)
            or not isinstance(market, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", market)
        ):
            raise ValueError("Invalid Pine context symbol, timeframe or marketType.")
        key = symbol, timeframe
        if key in contexts and contexts[key] != market:
            raise ValueError("A Pine provider key cannot name two market types.")
        contexts[key] = market
    chart_symbol = chart_pine_symbol(request.context)
    chart_timeframe = host_pine_timeframe(request.context.interval)
    unresolved = False
    for item in requirements:
        if item.get("function") not in {"security", "request.security", "request.security_lower_tf"}:
            raise ValueError("This requested data provider is not supported by the chart host.")
        resolved = []
        for field, inherited, kinds in (
            ("symbol", chart_symbol, {"currentContextSymbol", "rootChartSymbol"}),
            ("timeframe", chart_timeframe, {"currentContextTimeframe"}),
        ):
            argument = item.get(field, {})
            if argument.get("kind") == "literal":
                resolved.append(str(argument.get("value", "")) or inherited)
            elif argument.get("kind") in kinds:
                resolved.append(inherited)
            else:
                unresolved = True
                resolved.append(None)
        if None not in resolved:
            contexts.setdefault(tuple(resolved), request.context.market_type)
    if unresolved and not explicit:
        raise ValueError("Dynamic Pine requests need explicit symbol/timeframe contexts in the indicator's data settings.")
    if len(contexts) > 16:
        raise ValueError("At most 16 requested contexts are supported.")
    return [(symbol, timeframe, market) for (symbol, timeframe), market in contexts.items()]


def host_pine_timeframe(value):
    interval = parse_interval_spec(value).canonical
    match = re.fullmatch(r"(\d+)([smhdwM])", interval)
    if match is None:
        raise ValueError("Unsupported chart timeframe for Pine requests.")
    amount, unit = match.groups()
    return str(int(amount) * 60) if unit == "h" else amount if unit == "m" else amount + unit.upper()


def chart_pine_symbol(context):
    ticker = context.symbol
    if context.exchange.lower() == "binance" and context.market_type.lower() in {"futures", "swap", "usdm"} and not ticker.endswith(".P"):
        ticker += ".P"
    return f"{context.exchange.upper()}:{ticker}"


def pine_interval(value):
    if value.isdigit():
        return f"{int(value)}m"
    if value[-1:] in {"S", "D", "W", "M"}:
        return (value[:-1] or "1") + {"S": "s", "D": "d", "W": "w", "M": "M"}[value[-1]]
    return value
