"""One loaded CCXT market table per venue rail, shared by long-lived clients.

``Exchange.load_markets()`` downloads the venue catalog and parses it on the
event loop (Binance spot ``exchangeInfo`` is ~18 MB: ``parse_market`` plus
``set_markets`` hold the loop for 1.8-3.9 s) and keeps the parsed tables on
that client.  Every transport config owns its own REST pool, and the ccxt.pro
websocket runtimes own further clients, so one backend used to load and keep
several copies of Binance spot (about 130 MB of heap each).

Clients of one rail now join a single load and then point at the same tables
through ccxt's ``Exchange.set_markets_from_exchange()``.  ccxt only reads the
tables after ``set_markets()`` builds them, and every load or reload builds new
objects, so sharing is safe; a reload re-points every live sharer.  The tables
are held by a detached ``_MarketTables`` snapshot rather than by the client
that loaded them, because ``close(clean_instance_data=True)`` resets that
client's attributes.  Each published table is excluded from cyclic garbage
collection once (see ``app.core.gc_policy``).
"""

from __future__ import annotations

import asyncio
import time
import weakref
from dataclasses import dataclass, field
from typing import Any

import ccxt.async_support as ccxt_async

from app.core.config import GC_UNTRACK_MARKET_TABLES
from app.core.gc_policy import untrack_acyclic_tree
from app.exchanges.public_admission import (
    PublicDemand, TrafficClass, current_demand, get_public_admission, public_demand,
)

# The tables ``Exchange.set_markets()`` builds and
# ``Exchange.set_markets_from_exchange()`` copies (ccxt 4.5.60).
MARKET_TABLE_ATTRIBUTES = (
    "markets",
    "markets_by_id",
    "symbols",
    "ids",
    "currencies",
    "currencies_by_id",
    "baseCurrencies",
    "quoteCurrencies",
    "codes",
)

# Options that select which markets ``fetch_markets()`` returns or how they
# are parsed.  ``defaultType``/``defaultSubType`` change the catalog on some
# venues, so clients of different market families never share by accident.
# Proxy and session settings only change the path to the same catalog.
_MARKET_OPTION_KEYS = (
    "defaultType",
    "defaultSubType",
    "fetchMarkets",
    "loadAllOptions",
    "sandboxMode",
    "enableDemoTrading",
    "fetchMargins",
    "fetchCurrencies",
)


async def untrack_ccxt_market_tables(holder: Any) -> int:
    """Keep a loaded, long-lived catalog out of full GC passes.

    ``holder`` is a client or a ``_MarketTables`` snapshot.  The tables are
    acyclic dict/list trees, so reference counting still frees them.
    """

    if not GC_UNTRACK_MARKET_TABLES:
        return 0
    return await untrack_acyclic_tree(
        *(getattr(holder, name, None) for name in MARKET_TABLE_ATTRIBUTES)
    )


def market_rail_key(exchange: Any) -> tuple[Any, ...] | None:
    """Identify clients whose ``load_markets()`` builds the same tables.

    Returns ``None`` for objects that are not ccxt async/pro exchanges (test
    doubles, adapters); those keep loading their own markets.
    """

    if not isinstance(exchange, ccxt_async.Exchange):
        return None
    options = exchange.options if isinstance(exchange.options, dict) else {}
    return (
        exchange.id,
        bool(getattr(exchange, "isSandboxModeEnabled", False)),
        # Private endpoints such as ``fetch_currencies`` only run with keys.
        bool(exchange.apiKey),
        *(repr(options.get(name)) for name in _MARKET_OPTION_KEYS),
    )


class _MarketTables:
    """The tables one ``load_markets()`` built, detached from its client.

    Exposes exactly what ``Exchange.set_markets_from_exchange()`` reads.
    """

    def __init__(self, exchange: Any) -> None:
        self.id = exchange.id
        for name in MARKET_TABLE_ATTRIBUTES:
            setattr(self, name, getattr(exchange, name))
        helpers = exchange.safe_list(exchange.options, "marketHelperProps", []) or []
        self.options = {
            "marketHelperProps": list(helpers),
            **{helper: exchange.options.get(helper) for helper in helpers},
        }


@dataclass(eq=False)
class _Rail:
    key: tuple[Any, ...]
    label: str
    # The per-loop registry that owns this rail.
    rails: dict[tuple[Any, ...], _Rail]
    tables: _MarketTables | None = None
    task: asyncio.Task[None] | None = None
    loader: Any = None
    demand: PublicDemand | None = None
    sharers: weakref.WeakSet[Any] = field(default_factory=weakref.WeakSet)
    loads: int = 0
    reloads: int = 0
    adoptions: int = 0
    load_failures: int = 0
    last_load_ms: float = 0.0


def _rail_label(exchange: Any) -> str:
    options = exchange.options if isinstance(exchange.options, dict) else {}
    parts = [str(exchange.id), str(options.get("defaultType") or "default")]
    if options.get("defaultSubType"):
        parts.append(str(options["defaultSubType"]))
    return ":".join(parts)


def _consume_task_outcome(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


class CcxtMarketTables:
    """Per-event-loop registry of shared market tables, keyed by rail."""

    def __init__(self) -> None:
        # Tasks belong to one loop.  Keying by loop also keeps independent
        # ``asyncio.run()`` callers (tests, tools) from adopting each other's
        # tables.
        self._loops: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop,
            dict[tuple[Any, ...], _Rail],
        ] = weakref.WeakKeyDictionary()
        self._membership: weakref.WeakKeyDictionary[Any, _Rail] = (
            weakref.WeakKeyDictionary()
        )

    async def load(self, exchange: Any) -> Any:
        """``exchange.load_markets()``, joining or reusing the rail's table."""

        return await self._load(exchange, reload=False, stale_markets=None)

    async def reload(self, exchange: Any, *, stale_markets: Any = None) -> Any:
        """Refresh the rail's table and re-point every client that shares it.

        ``stale_markets`` is the ``markets`` object a caller failed to resolve
        against.  When another client already published newer tables, they
        are adopted instead of downloading the catalog again.
        """

        return await self._load(exchange, reload=True, stale_markets=stale_markets)

    def release(self, exchange: Any) -> None:
        """Detach a client that is about to close.

        A load running on that client is cancelled (its session is going
        away); other waiters retry on their own client.  The rail's tables are
        dropped with the last sharer.
        """

        if not isinstance(exchange, ccxt_async.Exchange):
            return
        rail = self._membership.pop(exchange, None)
        if rail is None:
            return
        rail.sharers.discard(exchange)
        task = rail.task
        if task is not None and rail.loader is exchange and not task.done():
            task.cancel()
        if not rail.sharers:
            rail.tables = None
            if rail.rails.get(rail.key) is rail:
                rail.rails.pop(rail.key, None)

    def snapshot(self) -> dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return {"rails": []}
        rails = self._loops.get(loop) or {}
        return {
            "rails": [
                {
                    "rail": rail.label,
                    "loaded": rail.tables is not None,
                    "markets": len(rail.tables.markets or {})
                    if rail.tables is not None
                    else 0,
                    "loading": rail.task is not None and not rail.task.done(),
                    "sharers": len(rail.sharers),
                    "loads": rail.loads,
                    "reloads": rail.reloads,
                    "adoptions": rail.adoptions,
                    "load_failures": rail.load_failures,
                    "last_load_ms": round(rail.last_load_ms, 3),
                }
                for rail in rails.values()
            ]
        }

    async def _load(
        self,
        exchange: Any,
        *,
        reload: bool,
        stale_markets: Any,
    ) -> Any:
        key = market_rail_key(exchange)
        if key is None:
            if reload:
                markets = await exchange.load_markets(reload=True)
            else:
                markets = await exchange.load_markets()
            await untrack_ccxt_market_tables(exchange)
            return markets
        rail = self._attach(key, exchange)
        if (
            reload
            and stale_markets is not None
            and rail.tables is not None
            and rail.tables.markets is not stale_markets
        ):
            self._adopt(rail, exchange)
            return exchange.markets

        failed_elsewhere = False
        while True:
            task = rail.task
            ran_here = task is None
            if task is None:
                if not reload and rail.tables is not None:
                    self._adopt(rail, exchange)
                    return exchange.markets
                task = self._start(rail, exchange, reload=reload)
            if rail.demand is not None:
                rail.demand.inherit(current_demand())
                get_public_admission().manager.notify_change()
            # ``wait`` neither cancels the shared load when this caller is
            # cancelled nor raises the loader's failure here.
            await asyncio.wait((task,))
            if self._membership.get(exchange) is not rail:
                raise RuntimeError("CCXT client closed while loading markets")
            if not task.cancelled() and task.exception() is None:
                self._adopt(rail, exchange)
                return exchange.markets
            if ran_here or failed_elsewhere:
                if task.cancelled():
                    raise RuntimeError("CCXT market load was cancelled")
                raise task.exception()  # type: ignore[misc]
            # Another client's load failed or that client closed.  Its
            # session or proxy path may be the problem: try once more, on
            # this client unless a newer load is already running.
            failed_elsewhere = True

    def _attach(self, key: tuple[Any, ...], exchange: Any) -> _Rail:
        loop = asyncio.get_running_loop()
        rails = self._loops.get(loop)
        if rails is None:
            rails = {}
            self._loops[loop] = rails
        rail = rails.get(key)
        if rail is None:
            rail = _Rail(key=key, label=_rail_label(exchange), rails=rails)
            rails[key] = rail
        elif not rail.sharers and rail.task is None:
            # Every client that held these tables was dropped without
            # ``release()``.  A new client loads a fresh catalog, as before.
            rail.tables = None
        current = self._membership.get(exchange)
        if current is not None and current is not rail:
            current.sharers.discard(exchange)
        self._membership[exchange] = rail
        rail.sharers.add(exchange)
        return rail

    def _start(self, rail: _Rail, exchange: Any, *, reload: bool) -> asyncio.Task[None]:
        rail.demand = PublicDemand(TrafficClass.BACKGROUND, purpose="market_metadata")
        rail.demand.inherit(current_demand())
        with public_demand(rail.demand):
            task = asyncio.get_running_loop().create_task(
                self._run(rail, exchange, reload=reload),
                name=f"ccxt_markets_{rail.label}",
            )
        task.add_done_callback(_consume_task_outcome)
        rail.task = task
        rail.loader = exchange
        return task

    async def _run(self, rail: _Rail, exchange: Any, *, reload: bool) -> None:
        started = time.perf_counter()
        try:
            if reload:
                await exchange.load_markets(reload=True)
                rail.reloads += 1
            else:
                await exchange.load_markets()
                rail.loads += 1
            tables = self._publish(rail, exchange)
            # Waiters join this task, so they see the table already untracked.
            await untrack_ccxt_market_tables(tables)
        except asyncio.CancelledError:
            raise
        except BaseException:
            rail.load_failures += 1
            raise
        finally:
            rail.last_load_ms = (time.perf_counter() - started) * 1000.0
            if rail.task is asyncio.current_task():
                rail.task = None
                rail.loader = None
                rail.demand = None

    def _publish(self, rail: _Rail, loader: Any) -> _MarketTables:
        tables = rail.tables = _MarketTables(loader)
        for sharer in tuple(rail.sharers):
            if sharer is not loader:
                self._adopt(rail, sharer)
        return tables

    @staticmethod
    def _adopt(rail: _Rail, exchange: Any) -> None:
        tables = rail.tables
        # ccxt refuses to share an empty catalog; such a client keeps its own
        # state and recovers through the next reload.
        if tables is None or not tables.markets or exchange.markets is tables.markets:
            return
        exchange.set_markets_from_exchange(tables)
        rail.adoptions += 1


_SHARED = CcxtMarketTables()


def get_shared_ccxt_market_tables() -> CcxtMarketTables:
    return _SHARED
