"""Explicit source registration, independent of a venue's REST/CCXT adapter.

Built-in venues retain their production plugin factories. Additional vendors
register an explicit factory for a venue; discovery never auto-enables a source.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .archive import HistoricalArchiveProvider


class ArchiveSourceRegistry:
    def __init__(self):
        self._factories: dict[str, tuple[str, Callable, bool]] = {}

    def register(self, *, venue: str, source_id: str,
                 factory: Callable[[Any], HistoricalArchiveProvider], enabled: bool = False) -> None:
        if not venue or not source_id or venue in self._factories:
            raise ValueError("archive source registration requires a unique venue and source id")
        self._factories[venue] = (source_id, factory, enabled)

    def disabled_reason(self, venue, config):
        registration = self._factories.get(venue)
        if registration is not None:
            return None if registration[2] else "source_not_enabled"
        if venue == "okx" and not config.history_archive_okx_enabled:
            return "feature_flag_disabled"
        return None

    def resolve(self, venue: str, config: Any, plugins: Any):
        registration = self._factories.get(venue)
        if registration is not None:
            source_id, factory, enabled = registration
            if not enabled:
                return None, "source_not_enabled"
            provider = factory(config)
            if provider.id != source_id:
                raise ValueError("archive source factory identity mismatch")
            return provider, "registered_source"
        if venue == "okx" and not config.history_archive_okx_enabled:
            return None, "feature_flag_disabled"
        try:
            plugin = plugins.get_plugin(venue)
        except KeyError:
            return None, "venue_not_registered"
        factory = getattr(plugin, "history_archive_provider", None)
        provider = factory(config) if callable(factory) else None
        return provider, "plugin_source" if provider is not None else "archive_capability_unavailable"

    def probe_venues(self):
        return tuple(dict.fromkeys(("okx", *self._factories)))
