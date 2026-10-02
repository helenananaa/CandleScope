"""Resolve a market-scoped random start without downloading its full history."""
from __future__ import annotations

import asyncio
import secrets
import time

from app.data_engine.ingestion.models import StreamDescriptor, StreamType
from app.exchanges.symbol_catalog import get_cached_symbol_metadata
from .models import PreparationError

MINUTE = 60_000


def eligible_start_bounds(first_ms, end_ms, setup):
    history = max(setup["indicator_warmup_bars"] * MINUTE,
                  setup["visible_history_lookback"].get("duration_ms") or 0)
    first = ((first_ms + history + MINUTE - 1) // MINUTE) * MINUTE
    last = ((end_ms - setup["forward_cache_ms"]) // MINUTE) * MINUTE
    if first > last:
        raise PreparationError("MARKET_HISTORY_TOO_SHORT", "该商品的历史不足以满足预热和后续训练，请减少历史窗口或选择其他商品。")
    return first, last


def _opens(events, descriptor, now_ms):
    return sorted({event.data["open_time"] for event in events
        if event.exchange == descriptor.exchange and event.market_type == descriptor.market_type
        and event.symbol == descriptor.symbol and event.event_type == StreamType.KLINE
        and isinstance(event.data.get("open_time"), int)
        and event.data["open_time"] >= 0 and event.data["open_time"] % MINUTE == 0
        and event.data["open_time"] + MINUTE <= now_ms})


async def resolve_market_random(payload, factory, *, now_ms=None, randbelow=secrets.randbelow):
    setup = payload.setup.model_dump(mode="json")
    if (setup["start_mode"] != "RANDOM" or setup["source_kind"] != "BAR"
            or setup["account_data_mode"] != "APPROX_PROXY" or setup["book_mode"] != "OFF"
            or setup["funding_mode"] == "HISTORICAL_EXACT" or payload.progressive):
        raise PreparationError("MARKET_RANDOM_UNSUPPORTED", "按商品随机目前支持 K 线随机开局。")
    if factory is None or not hasattr(factory, "fetch_market"):
        raise PreparationError("MARKET_HISTORY_UNAVAILABLE", "历史行情连接不可用，无法确认该商品的可用范围。", retryable=True)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    descriptor = StreamDescriptor(payload.symbol, StreamType.KLINE, interval="1m",
                                  exchange=payload.exchange, market_type=payload.market_type)
    descriptor.validate()
    metadata = get_cached_symbol_metadata(payload.exchange, payload.market_type, payload.symbol) or {}
    listed = metadata.get("continuousTradingAtMs") or metadata.get("listedAtMs")
    # Binance's startTime pagination is ascending. Other providers require an
    # authoritative listing boundary; never infer it from a local cache edge.
    if not (type(listed) is int and listed >= 0) and payload.exchange != "binance":
        raise PreparationError("MARKET_LISTING_UNKNOWN", "无法确认该交易对的上市边界，请使用指定时间或指定范围随机。")
    start = listed if isinstance(listed, int) and listed >= 0 else 0
    ended = [v for v in (metadata.get("delistedAtMs"), metadata.get("expiryAtMs"))
             if isinstance(v, int) and 0 < v < now]
    end = min([now, *ended]) // MINUTE * MINUTE
    try:
        async with asyncio.timeout(25):
            first_events = await factory.fetch_market(descriptor, limit=1, start_ms=start,
                end_ms=end - 1, history=True, defer_on_rate_limit=True)
            latest_events = await factory.fetch_market(descriptor, limit=2, end_ms=end - 1,
                history=True, defer_on_rate_limit=True)
    except Exception as exc:
        raise PreparationError("MARKET_HISTORY_UNAVAILABLE", "无法读取该商品的历史边界，请稍后重试。", retryable=True) from exc
    firsts, lasts = _opens(first_events, descriptor, now), _opens(latest_events, descriptor, now)
    if not firsts or not lasts or firsts[0] < start or lasts[-1] >= end:
        raise PreparationError("MARKET_HISTORY_UNAVAILABLE", "该商品没有可验证的历史行情，无法随机开局。")
    first, last = eligible_start_bounds(firsts[0], lasts[-1] + MINUTE, setup)
    history = max(setup["indicator_warmup_bars"] * MINUTE,
                  setup["visible_history_lookback"].get("duration_ms") or 0)
    history = (history + MINUTE - 1) // MINUTE * MINUTE
    # Check only sampled windows, never materialize the entire listing history.
    # Known holes remove every start whose required window overlaps that hole.
    intervals = [(first, last)]
    pages = 0
    try:
        async with asyncio.timeout(30):
            for _ in range(8):
                count = sum((b - a) // MINUTE + 1 for a, b in intervals)
                if not count:
                    break
                offset = randbelow(count)
                for a, b in intervals:
                    size = (b - a) // MINUTE + 1
                    if offset < size:
                        chosen = a + offset * MINUTE
                        break
                    offset -= size
                cursor = (chosen - history) // MINUTE * MINUTE
                stop = (chosen + setup["forward_cache_ms"] + MINUTE - 1) // MINUTE * MINUTE
                missing = None
                while cursor < stop:
                    if pages >= 32:
                        raise PreparationError("MARKET_WINDOW_TOO_LARGE", "验证历史窗口需要读取过多数据，请缩短预热或后续行情范围后重试。")
                    page_stop = min(stop, cursor + 1000 * MINUTE)
                    events = await factory.fetch_market(descriptor, limit=(page_stop - cursor) // MINUTE,
                        start_ms=cursor, end_ms=page_stop - 1, history=True, defer_on_rate_limit=True)
                    pages += 1
                    opens = set(_opens(events, descriptor, now))
                    missing = next((t for t in range(cursor, page_stop, MINUTE) if t not in opens), None)
                    if missing is not None:
                        break
                    cursor = page_stop
                if missing is None:
                    setup.update(requested_start_ms=None, random_range_start_ms=chosen, random_range_end_ms=chosen)
                    return setup
                # Window [start - history, start + future) includes this hole.
                exclude_first = ((missing - setup["forward_cache_ms"]) // MINUTE + 1) * MINUTE
                exclude_last = ((missing + history) // MINUTE) * MINUTE
                remaining = []
                for a, b in intervals:
                    if b < exclude_first or a > exclude_last:
                        remaining.append((a, b))
                    else:
                        if a < exclude_first:
                            remaining.append((a, exclude_first - MINUTE))
                        if b > exclude_last:
                            remaining.append((exclude_last + MINUTE, b))
                intervals = remaining
    except PreparationError:
        raise
    except Exception as exc:
        raise PreparationError("MARKET_HISTORY_UNAVAILABLE", "暂时无法验证随机时点附近的连续行情，请稍后重试。", retryable=True) from exc
    raise PreparationError("MARKET_CONTIGUOUS_HISTORY_UNAVAILABLE", "多次抽取的历史区间存在缺失，未创建训练；请缩短窗口或选择其他商品。")
