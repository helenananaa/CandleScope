"""Check a Twelve Data key with the account's own usage endpoint."""
from __future__ import annotations

from typing import Any

from app.data_engine.ingestion.config import IngestionConfig
from app.exchanges.catalog_http import CatalogHttpError, fetch_catalog_json
from app.exchanges.rate_limits import RateLimitDeferred

from .adapter import TwelveDataExchangeAdapter

# The adapter describes the Basic WebSocket entitlement (runtime._symbol_limit).
WEBSOCKET_SYMBOL_LIMIT = 8


class TwelveDataCheckError(RuntimeError):
    def __init__(self, code: str, *, retry_after_seconds: int | None = None):
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


def _count(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def usage_summary(payload: Any) -> dict:
    if not isinstance(payload, dict) or payload.get("status") == "error":
        code = payload.get("code") if isinstance(payload, dict) else None
        raise TwelveDataCheckError("DATA_SOURCE_KEY_REJECTED" if code in {401, 403, "401", "403"}
                                   else "DATA_SOURCE_RESPONSE_INVALID")
    minute_limit = _count(payload.get("plan_limit"))
    if minute_limit is None:
        raise TwelveDataCheckError("DATA_SOURCE_RESPONSE_INVALID")
    daily_limit = _count(payload.get("plan_daily_limit"))
    plan = payload.get("plan_category")
    return {
        "plan": plan.strip()[:40] if isinstance(plan, str) and plan.strip() else None,
        "minuteCredits": {"used": _count(payload.get("current_usage")), "limit": minute_limit},
        "dailyCredits": (None if daily_limit is None
                         else {"used": _count(payload.get("daily_usage")), "limit": daily_limit}),
        "websocketSymbols": WEBSOCKET_SYMBOL_LIMIT,
    }


async def check_twelve_data_key(api_key: str, config: Any | None = None) -> dict:
    """Plan and credit usage for ``api_key``; raises TwelveDataCheckError with a code."""
    cfg = config or IngestionConfig()
    adapter = TwelveDataExchangeAdapter()
    try:
        payload = await fetch_catalog_json(
            exchange=adapter.id,
            market_type="stock",
            base_urls=adapter.get_http_base_urls("stock", config=cfg),
            path="/api_usage",
            headers={"Authorization": f"apikey {api_key}", "Accept-Encoding": "gzip, deflate"},
            timeout_seconds=float(getattr(cfg, "http_timeout", 8)),
            proxy=getattr(cfg, "http_proxy", None),
            config=cfg,
        )
    except RateLimitDeferred as exc:
        raise TwelveDataCheckError("DATA_SOURCE_RATE_LIMITED",
                                   retry_after_seconds=max(1, int(exc.retry_after_seconds))) from None
    except CatalogHttpError as exc:
        status, body = exc.status_code, exc.body_code
        if status in {401, 403} or body in {"401", "403"}:
            raise TwelveDataCheckError("DATA_SOURCE_KEY_REJECTED") from None
        if status == 429 or body == "429":
            raise TwelveDataCheckError("DATA_SOURCE_RATE_LIMITED") from None
        raise TwelveDataCheckError("DATA_SOURCE_UNREACHABLE") from None
    except Exception:
        raise TwelveDataCheckError("DATA_SOURCE_UNREACHABLE") from None
    return usage_summary(payload)


__all__ = ["TwelveDataCheckError", "check_twelve_data_key", "usage_summary"]
