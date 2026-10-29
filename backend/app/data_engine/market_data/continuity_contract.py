"""Provider capability view of subscription continuity; no exchange allowlist."""
from __future__ import annotations

from .models import DeliveryClass, MarketChannel, MarketStreamKey, TransportMode


def continuity_contract(key: MarketStreamKey) -> dict:
    from app.exchanges import bootstrap_default_adapters, get_exchange_registry

    bootstrap_default_adapters()
    capabilities = get_exchange_registry().get_capabilities(key.exchange)
    capability = capabilities.channel_capability(key.channel, key.market_type)
    if capability is None and key.channel is MarketChannel.KLINE and key.market_type in {"swap", "perpetual"}:
        capability = capabilities.channel_capability(key.channel, "futures")
    available = capability is not None and bool(capability.realtime)
    channel = key.channel
    strict = True
    reason = None
    if channel is MarketChannel.KLINE:
        guarantee, recovery = "final_bars", "verified_history"
        recoverable = bool(capability and capability.history)
    elif channel is MarketChannel.AGG_TRADE:
        guarantee, recovery = "monotonic_id", "verified_id_range"
        recoverable = bool(capability and capability.history
                           and capability.delivery is DeliveryClass.APPEND
                           and capability.sequence == "monotonic_id"
                           and capability.resync == "snapshot_replay"
                           and capability.supports_transport(TransportMode.REST_HISTORY, history=True)
                           and any(capability.supports_transport(mode) for mode in (
                               TransportMode.WEBSOCKET, TransportMode.PLUGIN_STREAM)))
        strict = recoverable
        available = available and recoverable
    elif channel in {MarketChannel.TRADE, MarketChannel.LIQUIDATION}:
        guarantee = "observed_trades" if channel is MarketChannel.TRADE else "sampled_liquidations"
        recovery, recoverable, strict = "unavailable", False, False
        reason = "source does not prove an exhaustive replayable event sequence"
    else:
        guarantee, recovery, recoverable = "current_state", "fresh_snapshot", True
    return {
        "key": key.to_dict(), "available": available,
        "policies": (["strict", "gap_aware"] if strict else ["gap_aware"]) if available else [],
        "guarantee": guarantee, "recovery": recovery,
        "recoverable": available and recoverable,
        "historical_transitions_replayed": False if guarantee == "current_state" else None,
        "reason": reason if available else "provider channel is unavailable",
    }
