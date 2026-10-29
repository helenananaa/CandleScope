"""Pinned CCXT 4.5.60 hooks at each HTTP attempt (including internal retries).

Response observations are task-local, never read from last_response_headers.
CCXT's own throttler remains enabled as a second, vendor-specific safety layer.
"""
from __future__ import annotations

import contextvars
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import ccxt

from app.exchanges.public_admission import acquire_public
from app.exchanges.rate_limits import HistoricalRequest, scope_rate_limit_rule

_observation: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "ccxt_physical_response", default=None,
)


def quota_error_feedback(error: BaseException) -> dict[str, Any]:
    status = getattr(error, "status_code", None)
    if isinstance(error, ccxt.RateLimitExceeded):
        status = 429
    if isinstance(error, ccxt.BaseError):
        match = re.search(r"(?:^|\s)(418|429)(?:\s|:|$)", str(error))
        if match:
            status = int(match[1])
    return {"status_code": status, "headers": getattr(error, "headers", None),
            "body_code": _body_code(str(error))}


def _body_code(body: str) -> str | None:
    try:
        value = json.loads(body[body.index("{"):])
        code = value.get("code")
        return str(code) if code is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def bind_public_client(exchange: Any, config: Any, market_type: str) -> Any:
    exchange._candlescope_public_config = config
    if exchange.id in {"binance", "binanceusdm", "binancecoinm", "okx"}:
        market_type = "spot" if market_type == "spot" else "futures"
    exchange._candlescope_public_market_type = market_type
    return exchange


class PublicCcxtAdmissionMixin:
    def client(self, url: str) -> Any:
        from app.exchanges.public_ws import install_ccxt_ws_admission
        client = super().client(url)
        config = getattr(self, "_candlescope_public_config", None)
        exchange = "binance" if self.id in {"binance", "binanceusdm", "binancecoinm"} else self.id
        return install_ccxt_ws_admission(client, exchange,
            getattr(self, "_candlescope_public_market_type", "spot"),
            getattr(config, "proxy_egress_group", None))

    async def fetch(self, url: str, method: str = "GET", headers: Any = None,
                    body: Any = None) -> Any:
        # Only public CandleScope clients are constructed with this mixin.
        parts = urlsplit(url)
        params = {key: values[-1] for key, values in parse_qs(parts.query).items()}
        exchange_id = "binance" if self.id in {"binance", "binanceusdm", "binancecoinm"} else self.id
        market_type = getattr(self, "_candlescope_public_market_type", "spot")
        if parts.path.startswith(("/fapi/", "/futures/")):
            market_type = "futures"
        if exchange_id == "okx" and params.get("instType"):
            market_type = "spot" if params["instType"] == "SPOT" else "futures"
        config = getattr(self, "_candlescope_public_config", None)
        egress = getattr(config, "proxy_egress_group", None)
        request = HistoricalRequest(
            exchange=exchange_id, market_type=market_type, endpoint=parts.path,
            symbol=params.get("symbol", params.get("instId", "")),
            interval=params.get("interval"),
            limit=int(params["limit"]) if params.get("limit", "").isdigit() else None,
            params=params, egress_group=egress,
        )
        policy = getattr(self, "_candlescope_rate_limit_policy", None)
        if policy is None:
            from app.exchanges.registry import bootstrap_default_adapters, get_exchange_registry
            bootstrap_default_adapters()
            policy = get_exchange_registry().get_plugin(exchange_id).rate_limit_policy(config)
        rule = scope_rate_limit_rule(policy.rule_for(request), egress)
        manager = getattr(self, "_candlescope_rate_limit_manager", None)
        permit = await acquire_public([rule], request, manager=manager)
        observation: dict[str, Any] = {}
        token = _observation.set(observation)
        try:
            result = await super().fetch(url, method, headers, body)
            permit.finish(**(observation or {"status_code": 200}))
            return result
        except BaseException as exc:
            feedback = observation or quota_error_feedback(exc)
            if feedback.get("status_code") is None and feedback.get("body_code") is None:
                feedback = {"response_unknown": True}
            permit.finish(**feedback)
            raise
        finally:
            _observation.reset(token)
            if not permit.settled:
                permit.finish(response_unknown=True)

    def on_rest_response(self, code: int, reason: str, url: str, method: str,
                         response_headers: Any, response_body: str,
                         request_headers: Any, request_body: Any) -> Any:
        observation = _observation.get()
        if observation is not None:
            observation.update(status_code=code, headers=dict(response_headers or {}),
                               body_code=_body_code(response_body))
        return super().on_rest_response(code, reason, url, method, response_headers,
                                        response_body, request_headers, request_body)
