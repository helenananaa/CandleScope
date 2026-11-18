"""Plan and singleflight the official-archive lane for historical backfill."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.core.executors import run_archive
from app.data_engine.ingestion.metrics import LayerMetrics
from app.data_engine.interval_policy import parse_interval_ms
from app.exchanges import bootstrap_default_adapters, get_exchange_registry
from app.exchanges.archive import (
    ArchiveCompatibilityError,
    ArchiveDataError,
    ArchiveGranularity,
    ArchiveObjectRef,
    ArchiveRequestContext,
    HistoricalArchiveProvider,
)

from app.exchanges.archive_sources import ArchiveSourceRegistry
from app.exchanges.rate_limits import RateLimitDeferred

from .archive_cache import (
    AiohttpArchiveHttpClient,
    HistoricalArchiveCache,
)
from .config import BackfillConfig
from .archive_cleanup import ArchiveImportCleanup, ImportProofLookup
from .models import BackfillTask, FetchedBar


logger = logging.getLogger("backfill.HistoricalSourceRouter")

# Match the bounded native write-view footprints. Object count alone allows
# three minute-grid monthly ZIPs to turn a 1,000-row task into 130,000 rows.
MAX_USDM_ARCHIVE_OBJECT_ROWS = 8192
MAX_USDM_ARCHIVE_ROUTE_ROWS = 32768
MAX_COMPOSED_ARCHIVE_AMPLIFICATION = 4
MAX_COMPOSED_MULTI_EDGE_AMPLIFICATION = 12
SMALL_COMPOSED_ARCHIVE_ROWS = 256


@dataclass(frozen=True, slots=True)
class ArchiveObjectResult:
    ref: ArchiveObjectRef
    bars: tuple[FetchedBar, ...]
    content_sha256: str
    provider_checksum: str | None
    cache_hit: bool
    revision_changed: bool
    size_bytes: int
    cache_elapsed_ms: int
    download_elapsed_ms: int
    verify_elapsed_ms: int
    parse_elapsed_ms: int
    cache_generation: str = ""

    def receipt(self) -> dict[str, Any]:
        return {
            "object_key": self.ref.object_key,
            "provider_id": self.ref.provider_id,
            "exchange": self.ref.exchange,
            "market_type": self.ref.market_type,
            "symbol": self.ref.symbol,
            "interval": self.ref.interval,
            "granularity": self.ref.granularity.value,
            "period": self.ref.period,
            "start_ms": self.ref.start_ms,
            "end_ms": self.ref.end_ms,
            "content_sha256": self.content_sha256,
            "provider_checksum": self.provider_checksum,
            "row_count": len(self.bars),
            "source_url": self.ref.url,
            "revision_changed": self.revision_changed,
            "import_version": "history-archive-import.v1",
            "cache_generation": self.cache_generation,
        }


@dataclass(slots=True)
class ArchiveRoutePlan:
    refs_by_task: dict[str, tuple[ArchiveObjectRef, ...]]
    futures: dict[str, asyncio.Task[ArchiveObjectResult]]
    owner_task_by_object: dict[str, str]
    deferred_prefetch: tuple[
        tuple[HistoricalArchiveProvider, ArchiveObjectRef],
        ...,
    ] = ()
    foreground_demand: bool = True
    decisions_by_task: dict[str, dict[str, Any]] = field(default_factory=dict)

    def refs_for(self, task: BackfillTask) -> tuple[ArchiveObjectRef, ...]:
        return self.refs_by_task.get(task.task_key, ())

    def future_for(self, ref: ArchiveObjectRef) -> asyncio.Task[ArchiveObjectResult]:
        return self.futures[ref.object_key]

    def owns_object(self, task: BackfillTask, ref: ArchiveObjectRef) -> bool:
        return self.owner_task_by_object.get(ref.object_key) == task.task_key


class HistoricalSourceRouter:
    """Select closed archive objects while leaving tails and holes to REST."""

    def __init__(
        self,
        config: BackfillConfig,
        *,
        cache: HistoricalArchiveCache | None = None,
        http: AiohttpArchiveHttpClient | Any | None = None,
        proxy_resolver=None,
        request_runner=None,
        import_proof_lookup: ImportProofLookup | None = None,
        deferred_prefetch_delay_seconds: float = 15.0,
        sources: ArchiveSourceRegistry | None = None,
    ) -> None:
        self._cfg = config
        self._sources = sources or ArchiveSourceRegistry()
        self._source_reasons: dict[str, str] = {}
        self._probe_passed: set[str] = set()
        self._probe_tasks: dict[str, asyncio.Task] = {}
        self._probe_retry_at: dict[str, float] = {}
        self._cache = cache or HistoricalArchiveCache(
            config.history_archive_cache_dir,
            max_bytes=config.history_archive_cache_max_bytes,
            revalidate_seconds=config.history_archive_revalidate_seconds,
            max_download_bytes=config.history_archive_max_download_bytes,
        )
        timeout = config.fetch_timeout if config.fetch_timeout > 0 else 60
        self._http = http or AiohttpArchiveHttpClient(
            timeout_seconds=timeout,
            proxy_resolver=proxy_resolver,
            request_runner=request_runner,
        )
        self._cleanup = (
            ArchiveImportCleanup(config, self._cache, import_proof_lookup)
            if import_proof_lookup is not None else None
        )
        self._downloads = asyncio.Semaphore(
            max(1, int(config.history_archive_download_concurrency))
        )
        self._singleflight_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[ArchiveObjectResult]] = {}
        self._background_launchers: set[asyncio.Task[None]] = set()
        self._deferred_objects: OrderedDict[
            str,
            tuple[HistoricalArchiveProvider, ArchiveObjectRef],
        ] = OrderedDict()
        self._deferred_prefetch_delay_seconds = max(
            0.0,
            float(deferred_prefetch_delay_seconds),
        )
        self._foreground_archive_ready = False
        # Filled only after BackfillEngine reports a successful reconciliation
        # pass.  This prevents the next scheduler page from carrying the same
        # 32 parent objects through parsing/import/custom aggregation again,
        # without making a failed or cancelled write disappear from retries.
        self._acknowledged_imports: OrderedDict[str, float] = OrderedDict()
        self._acknowledged_imports_max_objects = 2_048
        # A not-yet-published daily object is commonly requested again by
        # foreground chart polling while the same GapLedger range is being
        # repaired.  Remember failures briefly so every poll does not repeat
        # the same CHECKSUM/ZIP request.  This is only transport backoff: the
        # object remains eligible after the TTL and never becomes history-end
        # evidence.
        self._failed_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._failed_cache_ttl_seconds = 300
        self._failed_cache_max_objects = 256
        # One scheduler page may carry a much larger GapLedger parent range.
        # Let the first page import a bounded set of already-selected archive
        # objects in one reconciliation pass, instead of paying one complete
        # fetch/reconcile/materialize cycle per 1,000-row planner chunk.
        self._prefilled_objects: OrderedDict[str, float] = OrderedDict()
        self._parent_prefill_max_objects = 32
        # Scheduler chunks reach the fetcher through separate engine runs.
        # Keep a bounded parsed-object LRU so those runs share CSV parsing as
        # well as the on-disk ZIP.  Entries expire with checksum revalidation.
        self._parsed_cache: OrderedDict[
            str,
            tuple[float, ArchiveObjectResult],
        ] = OrderedDict()
        self._parsed_cache_bars = 0
        self._parsed_cache_max_bars = max(
            100_000,
            min(250_000, int(config.fetch_max_total_bars) * 2),
        )
        self._providers: dict[str, HistoricalArchiveProvider] = {}
        self._disabled_providers: dict[str, str] = {}
        self._metrics = LayerMetrics("HistoricalSourceRouter")

    @property
    def metrics(self) -> LayerMetrics:
        return self._metrics

    def _provider(self, exchange: str):
        reason = self._sources.disabled_reason(exchange, self._cfg)
        if reason:
            self._source_reasons[exchange] = reason
            return None
        if exchange in self._providers:
            return self._providers[exchange]
        provider, reason = self._sources.resolve(exchange, self._cfg, get_exchange_registry())
        self._source_reasons[exchange] = reason
        if provider is not None:
            self._providers[exchange] = provider
        return provider

    async def probe_enabled_capabilities(self) -> dict[str, Any]:
        bootstrap_default_adapters()
        result = {}
        for exchange in self._sources.probe_venues():
            if not self._cfg.history_archive_enabled:
                result[exchange] = {"enabled": False, "reason": "history_archive_disabled"}
                continue
            provider = self._provider(exchange)
            if provider is None:
                result[exchange] = {"enabled": False, "reason": self._source_reasons[exchange]}
                continue
            result[exchange] = await self._probe_provider(exchange, provider)
        return result

    async def _probe_provider(self, exchange, provider):
        # Startup warming and foreground demand share one qualification. A
        # cancelled waiter must not cancel work still needed by another reader.
        task = self._probe_tasks.get(provider.id)
        if task is None:
            task = asyncio.create_task(self._run_probe_provider(exchange, provider))
            self._probe_tasks[provider.id] = task
            def finished(completed):
                if self._probe_tasks.get(provider.id) is completed:
                    self._probe_tasks.pop(provider.id, None)
                if not completed.cancelled():
                    completed.exception()  # Retrieve failure even if all waiters left.
            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _run_probe_provider(self, exchange, provider):
        if exchange in self._disabled_providers:
            return {"enabled": False, "reason": self._disabled_providers[exchange]}
        if time.monotonic() < self._probe_retry_at.get(provider.id, 0):
            return {"enabled": False, "reason": "probe_retry_deferred"}
        capabilities = provider.capabilities("spot")
        if not capabilities.probe_symbol or provider.id in self._probe_passed:
            return {"enabled": True, "provider_id": provider.id}
        try:
            now_ms = int(time.time() * 1_000)
            candidates = provider.plan_objects(
                market_type=capabilities.probe_market_type,
                symbol=capabilities.probe_symbol, interval=capabilities.intervals[0],
                start_ms=now_ms - 7 * 86_400_000, end_ms=now_ms - 4 * 86_400_000, now_ms=now_ms,
            )
            resolved = await provider.resolve_objects(candidates, self._http_for(exchange))
            if not resolved:
                raise ArchiveCompatibilityError("archive capability probe returned no object")
            value = await self._load_object(provider, max(resolved, key=lambda item: item.start_ms))
            self._metrics.inc("archive_capability_probe_success")
            self._probe_passed.add(provider.id)
            return {"enabled": True, "provider_id": provider.id, "sample_rows": len(value.bars)}
        except (asyncio.CancelledError, RateLimitDeferred):
            raise
        except Exception as exc:
            if isinstance(exc, ArchiveCompatibilityError):
                self._disable_provider(exchange, exc)
            else:
                self._probe_retry_at[provider.id] = time.monotonic() + 60
            self._metrics.inc("archive_capability_probe_failures")
            return {"enabled": False, "reason": str(exc)[:500]}

    async def prepare(self, tasks: list[BackfillTask]) -> ArchiveRoutePlan:
        decisions = {task.task_key: _route_decision(task) for task in tasks}
        if not self._cfg.history_archive_enabled or not tasks:
            return ArchiveRoutePlan({}, {}, {}, decisions_by_task=decisions)
        bootstrap_default_adapters()
        refs_by_task: dict[str, list[ArchiveObjectRef]] = {}
        futures: dict[str, asyncio.Task[ArchiveObjectResult]] = {}
        owner_task_by_object: dict[str, str] = {}
        deferred_prefetch: dict[
            str,
            tuple[HistoricalArchiveProvider, ArchiveObjectRef],
        ] = {}
        scheduled_object_keys: set[str] = set()
        now_ms = int(time.time() * 1_000)
        foreground_demand = any(
            _is_foreground_archive_demand(task)
            for task in tasks
        )
        self._metrics.set(
            "last_route_requesters",
            sorted({
                str(task.metadata.get("requester") or "")
                for task in tasks
            }),
        )
        self._metrics.set(
            "last_route_reasons",
            sorted({
                str(task.metadata.get("reason") or "")
                for task in tasks
            }),
        )
        self._metrics.set(
            "last_route_foreground_demand",
            foreground_demand,
        )

        groups: dict[tuple[str, str, str, str], list[BackfillTask]] = {}
        for task in tasks:
            groups.setdefault(
                (task.exchange, task.market_type, task.symbol, task.interval),
                [],
            ).append(task)

        for (exchange, market_type, symbol, interval), group in groups.items():
            if exchange in self._disabled_providers:
                for task in group:
                    decisions[task.task_key]['reason'] = 'provider_disabled'
                continue
            provider = self._provider(exchange)
            if provider is None:
                for task in group:
                    decisions[task.task_key]['reason'] = self._source_reasons[exchange]
                self._metrics.set("last_route_skip_reason", f"{self._source_reasons[exchange]}:{exchange}")
                continue
            capabilities = provider.capabilities(market_type)
            if not capabilities.supports(market_type=market_type, interval=interval):
                for task in group:
                    decisions[task.task_key]['reason'] = 'unsupported_interval'
                self._metrics.set("last_route_skip_reason", f"unsupported:{exchange}:{market_type}:{interval}")
                continue

            for run in _task_runs(group, interval):
                route_start_ms, route_end_ms = _archive_decision_range(run)
                for task in run:
                    decisions[task.task_key].update(route_start_ms=route_start_ms,
                        route_end_ms=route_end_ms, reason='no_published_archive')
                candidates = provider.plan_objects(
                    market_type=market_type,
                    symbol=symbol,
                    interval=interval,
                    start_ms=route_start_ms,
                    end_ms=route_end_ms,
                    now_ms=now_ms,
                )
                planned_count = len(candidates)
                candidates = _filter_daily_candidates(
                    candidates,
                    range_start_ms=route_start_ms,
                    range_end_ms=route_end_ms,
                    interval=interval,
                    rest_page_size=capabilities.rest_page_size,
                    minimum_pages=max(1, self._cfg.history_archive_min_rest_pages),
                    tasks=run,
                )
                threshold_count = len(candidates)
                rejected = {}
                if exchange == 'binance' and market_type == 'futures':
                    bounded = _bounded_usdm_archive_candidates(candidates, run, interval,
                                                               rejected=rejected)
                    self._metrics.inc('archive_source_budget_skips', len(candidates)-len(bounded))
                    candidates = bounded
                for task in run:
                    decisions[task.task_key].update(candidate_objects=planned_count,
                        below_rest_threshold_objects=planned_count-threshold_count,
                        eligible_objects=len(candidates), archive_rejections=dict(rejected))
                    if planned_count and not candidates:
                        decisions[task.task_key]['reason'] = 'archive_cost_rejected'
                if not candidates:
                    continue
                # A composed daily window often fits one REST page even when
                # it straddles two months. Avoid extra archive transactions
                # and whole-object imports without changing canonical slots.
                if (exchange == 'binance' and market_type == 'futures' and interval == '1d'
                        and all(_composed_group_key(task) for task in run)
                        and (page_size := min(self._cfg.fetch_batch_size, capabilities.rest_page_size)) > 0
                        and sum(_ceil_div((task.end_ms-task.start_ms)//86_400_000+1, page_size)
                                for task in run) <= len(candidates)):
                    self._metrics.inc('archive_composed_daily_rest_preferred', len(candidates))
                    for task in run:
                        decisions[task.task_key].update(
                            reason='composed_daily_rest_cheaper', eligible_objects=0,
                            archive_rejections={**rejected, 'composed_daily_rest_cheaper': len(candidates)},
                        )
                    continue
                # Local ZIPs are usable without contacting the resolver or
                # acquiring any proxy route (even with no enabled routes).
                cached = await asyncio.gather(*(self._cache.resolve_fresh(ref) for ref in candidates))
                warm = [ref for ref in cached if ref is not None]
                cold = [ref for ref, hit in zip(candidates, cached) if hit is None]
                if cold and capabilities.probe_symbol and provider.id not in self._probe_passed:
                    probe = await self._probe_provider(exchange, provider)
                    if not probe.get("enabled"):
                        if exchange in self._disabled_providers:
                            continue
                        cold = []
                try:
                    resolved = warm + (await provider.resolve_objects(cold, self._http_for(exchange))
                                       if cold else [])
                except RateLimitDeferred:
                    raise
                except ArchiveCompatibilityError as exc:
                    self._disable_provider(exchange, exc)
                    continue
                except Exception as exc:
                    self._metrics.inc("archive_resolver_errors")
                    self._metrics.mark("last_error_at")
                    logger.warning(
                        "rest_fallback archive resolver failed exchange=%s symbol=%s: %s",
                        exchange,
                        symbol,
                        exc,
                    )
                    resolved = warm
                actual_start_ms = min(task.start_ms for task in run)
                actual_end_ms = max(task.end_ms for task in run)
                # Resolve from the complete parent demand, but only make the
                # current foreground chunk await objects it actually touches.
                # The first touching task owns the full-object import; sibling
                # page tasks consume its coverage without duplicating writes.
                resolved_refs = _unique_refs(resolved)
                needed_refs = [
                    ref
                    for ref in resolved_refs
                    if any(
                        _intersects(
                            task.start_ms,
                            task.end_ms,
                            ref.start_ms,
                            ref.end_ms,
                        )
                        for task in run
                    )
                ]
                needed_keys = {ref.object_key for ref in needed_refs}
                # Order the complete parent demand with objects touching the
                # foreground chunk first.  Cold objects are launched only
                # after this fetch pass has finished its visible REST work;
                # otherwise even a separate archive semaphore competes for
                # the same physical network and regresses first paint.  Warm
                # objects can be consumed immediately, which preserves fast
                # empty-database rebuilds from the persistent ZIP cache.
                ordered_refs = [
                    *needed_refs,
                    *sorted(
                        (
                            ref
                            for ref in resolved_refs
                            if ref.object_key not in needed_keys
                            and ref.object_key not in self._acknowledged_imports
                        ),
                        key=lambda ref: _range_distance(
                            actual_start_ms,
                            actual_end_ms,
                            ref.start_ms,
                            ref.end_ms,
                        ),
                    ),
                ]
                selected_refs = ordered_refs[: self._parent_prefill_max_objects]
                newly_prefetched = await self._claim_eager_prefill(selected_refs)
                newly_prefetched_keys = {
                    ref.object_key for ref in newly_prefetched
                }
                fresh_flags = await asyncio.gather(
                    *(self._cache.has_fresh(ref) for ref in newly_prefetched)
                )
                fresh_new_keys = {
                    ref.object_key
                    for ref, is_fresh in zip(newly_prefetched, fresh_flags)
                    if is_fresh
                }
                cold_new_keys = newly_prefetched_keys - fresh_new_keys
                composed_run = bool(
                    run and all(task.metadata.get("history_composition_contract") for task in run)
                )
                parent_prefill = (
                    not composed_run
                    and (
                        route_start_ms < actual_start_ms
                        or route_end_ms > actual_end_ms
                    )
                )
                warm_parent_batch = (
                    parent_prefill
                    and bool(fresh_new_keys)
                )
                if warm_parent_batch:
                    # A deleted K-line database with persistent ZIPs should
                    # batch every fresh object immediately.  A single newest
                    # not-yet-published daily object may remain cold/404 and
                    # stay deferred without forcing all local objects back
                    # through one scheduler cycle each.
                    self._metrics.inc("archive_warm_parent_batches")
                parent_batch_enabled = (
                    self._foreground_archive_ready or warm_parent_batch
                )
                deferred_cold_keys = (
                    cold_new_keys
                    if parent_prefill and not self._foreground_archive_ready
                    else set()
                )
                foreground_rest_once = bool(deferred_cold_keys & needed_keys)
                newly_deferred = [
                    (provider, ref)
                    for ref in selected_refs
                    if ref.object_key in deferred_cold_keys
                ]
                pending_deferred_keys = await self._register_deferred(
                    newly_deferred
                )
                for provider_ref, archive_ref in newly_deferred:
                    deferred_prefetch.setdefault(
                        archive_ref.object_key,
                        (provider_ref, archive_ref),
                    )
                for ref in selected_refs:
                    scheduled_object_keys.add(ref.object_key)
                    if ref.object_key in pending_deferred_keys:
                        self._metrics.inc("archive_background_prefetch_objects")
                        continue
                    future = await self._singleflight(provider, ref)
                    if ref.object_key not in needed_keys:
                        if parent_batch_enabled and run:
                            # Once the protected first screen has passed, let
                            # one physical scheduler task own the bounded
                            # parent batch.  Fetcher/Reconciler already accept
                            # non-intersecting prefill receipts, so this turns
                            # dozens of download/write/materialize cycles into
                            # one range publication and lets the coordinator
                            # discard every covered page chunk at once.
                            owner = run[0]
                            futures.setdefault(ref.object_key, future)
                            owner_task_by_object.setdefault(
                                ref.object_key,
                                owner.task_key,
                            )
                            refs_by_task.setdefault(
                                owner.task_key,
                                [],
                            ).append(ref)
                            self._metrics.inc(
                                "archive_parent_batch_objects"
                            )
                        else:
                            self._metrics.inc(
                                "archive_background_prefetch_objects"
                            )
                        continue
                    futures.setdefault(ref.object_key, future)
                    touching_tasks = [
                        task
                        for task in run
                        if _intersects(
                            task.start_ms,
                            task.end_ms,
                            ref.start_ms,
                            ref.end_ms,
                        )
                    ]
                    if touching_tasks and ref.object_key not in owner_task_by_object:
                        owner_task_by_object[ref.object_key] = touching_tasks[0].task_key
                    if len(touching_tasks) > 1:
                        self._metrics.inc(
                            "archive_singleflight_waiters",
                            len(touching_tasks) - 1,
                        )
                    for task in touching_tasks:
                        refs_by_task.setdefault(task.task_key, []).append(ref)
                if foreground_rest_once:
                    self._metrics.inc("archive_foreground_rest_bypasses")

        normalized_refs = {
            task_key: tuple(_unique_refs(values))
            for task_key, values in refs_by_task.items()
        }
        for task in tasks:
            refs = normalized_refs.get(task.task_key, ())
            decision = decisions[task.task_key]
            if refs:
                decision['reason'] = 'archive_selected'
            elif decision['eligible_objects']:
                decision['reason'] = 'archive_unavailable_or_deferred'
            decision['selected_object_count'] = len(refs)
            decision['selected_objects'] = [dict(object_key=ref.object_key,
                interval=ref.interval, start_ms=ref.start_ms, end_ms=ref.end_ms,
                owns_import=owner_task_by_object.get(ref.object_key) == task.task_key)
                for ref in refs[:32]]
            decision['selected_objects_truncated'] = len(refs) > 32
        self._metrics.inc("archive_route_plans")
        self._metrics.inc("archive_objects_planned", len(scheduled_object_keys))
        self._metrics.set(
            "last_archive_objects_planned",
            len(scheduled_object_keys),
        )
        return ArchiveRoutePlan(
            normalized_refs,
            futures,
            owner_task_by_object,
            tuple(deferred_prefetch.values()),
            foreground_demand,
            decisions,
        )

    def start_deferred_prefetch(self, route_plan: ArchiveRoutePlan) -> None:
        """Launch cold parent objects after foreground fetch work completes."""
        if not route_plan.deferred_prefetch and not self._deferred_objects:
            if route_plan.foreground_demand:
                # A warm-cache or complete-object foreground fetch has
                # already paid its archive cost.  Future left-drags must not
                # receive another synthetic "first screen" grace period.
                self._foreground_archive_ready = True
            return
        if not route_plan.foreground_demand:
            self._metrics.inc("archive_prefetch_parked_for_foreground")
            return
        if any(not task.done() for task in self._background_launchers):
            return
        launcher = asyncio.create_task(
            self._launch_deferred(),
            name="history-archive-deferred-prefetch",
        )
        self._background_launchers.add(launcher)
        launcher.add_done_callback(self._background_launchers.discard)

    def acknowledge_imports(self, object_keys: set[str]) -> None:
        """Remember objects whose complete reconciliation pass succeeded."""
        now = time.monotonic()
        for object_key in object_keys:
            normalized = str(object_key or "").strip()
            if not normalized:
                continue
            self._acknowledged_imports.pop(normalized, None)
            self._acknowledged_imports[normalized] = now
        while (
            len(self._acknowledged_imports)
            > self._acknowledged_imports_max_objects
        ):
            self._acknowledged_imports.popitem(last=False)
            self._metrics.inc("archive_import_ack_evictions")
        self._metrics.inc("archive_import_acks", len(object_keys))

    def _http_for(self, exchange: str, ref: ArchiveObjectRef | None = None):
        if isinstance(self._http, AiohttpArchiveHttpClient):
            return self._http.for_exchange(exchange, context=ArchiveRequestContext(
                ref.provider_id if ref else getattr(self._providers.get(exchange), "id", exchange),
                ref.object_key if ref else "discovery",
            ))
        return self._http

    def request_cleanup(self) -> None:
        if self._cleanup is not None:
            self._cleanup.request()

    async def close(self) -> None:
        probes = tuple(self._probe_tasks.values())
        for task in probes:
            task.cancel()
        await asyncio.gather(*probes, return_exceptions=True)
        self._probe_tasks.clear()
        launchers = tuple(self._background_launchers)
        for task in launchers:
            task.cancel()
        await asyncio.gather(*launchers, return_exceptions=True)
        inflight = tuple(self._inflight.values())
        for task in inflight:
            task.cancel()
        await asyncio.gather(*inflight, return_exceptions=True)
        if self._cleanup is not None:
            await self._cleanup.close()

    async def _launch_deferred(self) -> None:
        if self._deferred_prefetch_delay_seconds:
            await asyncio.sleep(self._deferred_prefetch_delay_seconds)
        self._foreground_archive_ready = True
        async with self._singleflight_lock:
            deferred = tuple(self._deferred_objects.values())
            self._deferred_objects.clear()
        for provider, ref in deferred:
            await self._singleflight(provider, ref)
        self._metrics.inc("archive_deferred_prefetch_batches")

    async def _register_deferred(
        self,
        values: list[tuple[HistoricalArchiveProvider, ArchiveObjectRef]],
    ) -> set[str]:
        async with self._singleflight_lock:
            for provider, ref in values:
                if len(self._deferred_objects) >= 64:
                    self._metrics.inc("archive_deferred_queue_full")
                    break
                self._deferred_objects.setdefault(
                    ref.object_key,
                    (provider, ref),
                )
            return set(self._deferred_objects)

    def _capability_snapshot(self):
        from dataclasses import asdict
        return {exchange: asdict(provider.capabilities("spot"))
                for exchange, provider in self._providers.items()}

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": bool(self._cfg.history_archive_enabled),
            "okx_enabled": bool(self._cfg.history_archive_okx_enabled),
            "okx_probe_passed": "okx-public-kline-page-v1" in self._probe_passed,
            "source_capabilities": self._capability_snapshot(),
            "source_reasons": dict(self._source_reasons),
            "cleanup": (
                self._cleanup.snapshot() if self._cleanup is not None else
                {"policy": self._cfg.history_archive_cleanup_policy, "reason": "atomic_import_proof_lookup_unavailable"}
            ),
            "download_concurrency": max(
                1,
                int(self._cfg.history_archive_download_concurrency),
            ),
            "minimum_rest_pages": max(
                1,
                int(self._cfg.history_archive_min_rest_pages),
            ),
            "singleflight_inflight": len(self._inflight),
            "capability_probes_inflight": len(self._probe_tasks),
            "deferred_prefetch_launchers": len(self._background_launchers),
            "deferred_prefetch_objects": len(self._deferred_objects),
            "deferred_prefetch_delay_seconds": (
                self._deferred_prefetch_delay_seconds
            ),
            "foreground_archive_ready": self._foreground_archive_ready,
            "acknowledged_import_objects": len(self._acknowledged_imports),
            "negative_cache_objects": len(self._failed_cache),
            "negative_cache_ttl_seconds": self._failed_cache_ttl_seconds,
            "prefilled_objects": len(self._prefilled_objects),
            "parent_prefill_max_objects": self._parent_prefill_max_objects,
            "parsed_cache_objects": len(self._parsed_cache),
            "parsed_cache_bars": self._parsed_cache_bars,
            "parsed_cache_max_bars": self._parsed_cache_max_bars,
            "disabled_providers": dict(self._disabled_providers),
            "cache": self._cache.snapshot(),
            "metrics": self._metrics.snapshot(),
        }

    async def _singleflight(
        self,
        provider: HistoricalArchiveProvider,
        ref: ArchiveObjectRef,
    ) -> asyncio.Task[ArchiveObjectResult]:
        async with self._singleflight_lock:
            cached = self._parsed_cache.get(ref.object_key)
            if cached is not None:
                cached_at, value = cached
                age_seconds = time.monotonic() - cached_at
                if age_seconds < max(
                    1,
                    int(self._cfg.history_archive_revalidate_seconds),
                ):
                    self._parsed_cache.move_to_end(ref.object_key)
                    self._metrics.inc("archive_parsed_cache_hits")
                    return asyncio.create_task(
                        self._return_parsed_cache_hit(value),
                        name=f"archive-parsed-cache:{ref.object_key}",
                    )
                self._parsed_cache.pop(ref.object_key, None)
                self._parsed_cache_bars = max(
                    0,
                    self._parsed_cache_bars - len(value.bars),
                )
            failed = self._failed_cache.get(ref.object_key)
            if failed is not None:
                failed_at, message = failed
                if (
                    time.monotonic() - failed_at
                    < self._failed_cache_ttl_seconds
                ):
                    self._failed_cache.move_to_end(ref.object_key)
                    self._metrics.inc("archive_negative_cache_hits")
                    return asyncio.create_task(
                        self._raise_cached_failure(message),
                        name=f"archive-negative-cache:{ref.object_key}",
                    )
                self._failed_cache.pop(ref.object_key, None)
            existing = self._inflight.get(ref.object_key)
            if existing is not None and not existing.done():
                self._metrics.inc("archive_singleflight_joins")
                return existing
            if existing is not None:
                self._remember_completed_failure(ref.object_key, existing)
                self._inflight.pop(ref.object_key, None)
                failed = self._failed_cache.get(ref.object_key)
                if failed is not None:
                    self._metrics.inc("archive_negative_cache_hits")
                    return asyncio.create_task(
                        self._raise_cached_failure(failed[1]),
                        name=f"archive-negative-cache:{ref.object_key}",
                    )
            if len(self._inflight) >= 64:
                return asyncio.create_task(self._raise_cached_failure("archive object queue full"))
            task = asyncio.create_task(
                self._load_and_remember(provider, ref),
                name=f"archive:{ref.exchange}:{ref.symbol}:{ref.period}",
            )
            self._inflight[ref.object_key] = task
            task.add_done_callback(
                lambda completed, key=ref.object_key: asyncio.create_task(
                    self._forget(key, completed)
                )
            )
            return task

    async def _claim_eager_prefill(
        self,
        refs: list[ArchiveObjectRef],
    ) -> list[ArchiveObjectRef]:
        claimed: list[ArchiveObjectRef] = []
        async with self._singleflight_lock:
            for ref in refs:
                if ref.object_key in self._prefilled_objects:
                    self._prefilled_objects.move_to_end(ref.object_key)
                    self._metrics.inc("archive_object_prefill_joins")
                    continue
                self._prefilled_objects[ref.object_key] = time.monotonic()
                claimed.append(ref)
            while len(self._prefilled_objects) > 256:
                self._prefilled_objects.popitem(last=False)
            self._metrics.inc("archive_object_prefill_owners", len(claimed))
        return claimed

    @staticmethod
    async def _return_parsed_cache_hit(
        value: ArchiveObjectResult,
    ) -> ArchiveObjectResult:
        return replace(
            value,
            cache_hit=True,
            cache_elapsed_ms=0,
            download_elapsed_ms=0,
            verify_elapsed_ms=0,
            parse_elapsed_ms=0,
        )

    @staticmethod
    async def _raise_cached_failure(message: str) -> ArchiveObjectResult:
        raise ArchiveDataError(message)

    async def _load_and_remember(
        self,
        provider: HistoricalArchiveProvider,
        ref: ArchiveObjectRef,
    ) -> ArchiveObjectResult:
        value = await self._load_object(provider, ref)
        async with self._singleflight_lock:
            self._failed_cache.pop(ref.object_key, None)
            previous = self._parsed_cache.pop(ref.object_key, None)
            if previous is not None:
                self._parsed_cache_bars = max(
                    0,
                    self._parsed_cache_bars - len(previous[1].bars),
                )
            self._parsed_cache[ref.object_key] = (time.monotonic(), value)
            self._parsed_cache_bars += len(value.bars)
            while (
                self._parsed_cache
                and self._parsed_cache_bars > self._parsed_cache_max_bars
            ):
                evicted_key, (_, evicted) = self._parsed_cache.popitem(last=False)
                self._parsed_cache_bars = max(
                    0,
                    self._parsed_cache_bars - len(evicted.bars),
                )
                self._metrics.inc("archive_parsed_cache_evictions")
                logger.debug("Evicted parsed archive object %s", evicted_key)
            self._metrics.set(
                "archive_parsed_cache_bars",
                self._parsed_cache_bars,
            )
        return value

    async def _forget(
        self,
        key: str,
        completed: asyncio.Task[ArchiveObjectResult],
    ) -> None:
        async with self._singleflight_lock:
            self._remember_completed_failure(key, completed)
            if self._inflight.get(key) is completed:
                self._inflight.pop(key, None)

    def _remember_completed_failure(
        self,
        key: str,
        completed: asyncio.Task[ArchiveObjectResult],
    ) -> None:
        if completed.cancelled():
            return
        try:
            error = completed.exception()
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            return
        if error is None or isinstance(error, RateLimitDeferred):
            return
        self._failed_cache.pop(key, None)
        self._failed_cache[key] = (time.monotonic(), str(error)[:500])
        while len(self._failed_cache) > self._failed_cache_max_objects:
            self._failed_cache.popitem(last=False)
            self._metrics.inc("archive_negative_cache_evictions")

    async def _load_object(
        self,
        provider: HistoricalArchiveProvider,
        ref: ArchiveObjectRef,
    ) -> ArchiveObjectResult:
        download_started = time.monotonic()
        async with self._downloads:
            try:
                async with self._cache.materialize(ref, provider, self._http_for(ref.exchange, ref)) as cached:
                    cache_elapsed_ms = int(
                        (time.monotonic() - download_started) * 1_000
                    )
                    parse_started = time.monotonic()
                    try:
                        archive_bars = await run_archive(
                            provider.parse_bars,
                            Path(cached.path),
                            ref,
                        )
                    except ArchiveCompatibilityError as exc:
                        self._disable_provider(ref.exchange, exc)
                        await self._cache.invalidate(ref.object_key)
                        raise
                    except BaseException:
                        await self._cache.invalidate(ref.object_key)
                        raise
                    parse_elapsed_ms = int((time.monotonic() - parse_started) * 1_000)
            except RateLimitDeferred:
                self._metrics.inc("archive_admission_deferred")
                raise
            except BaseException:
                self._metrics.inc("archive_object_errors")
                self._metrics.mark("last_error_at")
                raise

        bars = tuple(
            FetchedBar(
                symbol=ref.symbol,
                interval=ref.interval,
                open_time=bar.open_time,
                close_time=bar.close_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                exchange=ref.exchange,
                market_type=ref.market_type,
                quote_volume=bar.quote_volume,
                trades=bar.trades,
                taker_buy_base=bar.taker_buy_base,
                taker_buy_quote=bar.taker_buy_quote,
                source=bar.source,
                enhanced_fields=bar.enhanced_fields,
                archive_object_key=ref.object_key,
            )
            for bar in archive_bars
        )
        self._metrics.inc("archive_objects_loaded")
        self._metrics.inc("archive_rows_parsed", len(bars))
        self._metrics.inc("archive_cache_elapsed_ms_total", cache_elapsed_ms)
        self._metrics.inc("archive_parse_elapsed_ms_total", parse_elapsed_ms)
        self._metrics.set("last_cache_elapsed_ms", cache_elapsed_ms)
        self._metrics.set(
            "last_download_elapsed_ms",
            cached.download_elapsed_ms,
        )
        self._metrics.set("last_verify_elapsed_ms", cached.verify_elapsed_ms)
        self._metrics.set("last_parse_elapsed_ms", parse_elapsed_ms)
        return ArchiveObjectResult(
            ref=ref,
            bars=bars,
            content_sha256=cached.content_sha256,
            provider_checksum=cached.provider_checksum,
            cache_hit=cached.cache_hit,
            revision_changed=cached.revision_changed,
            size_bytes=cached.size_bytes,
            cache_elapsed_ms=cache_elapsed_ms,
            download_elapsed_ms=cached.download_elapsed_ms,
            verify_elapsed_ms=cached.verify_elapsed_ms,
            parse_elapsed_ms=parse_elapsed_ms,
            cache_generation=cached.cache_generation,
        )

    def _disable_provider(self, exchange: str, error: BaseException) -> None:
        normalized = str(exchange or "").strip().lower()
        reason = str(error)[:500]
        self._disabled_providers[normalized] = reason
        self._metrics.inc("archive_capability_disabled")
        self._metrics.set("last_disabled_provider", normalized)
        logger.error(
            "archive capability disabled exchange=%s reason=%s",
            normalized,
            reason,
        )


def _composed_group_key(task: BackfillTask) -> tuple[str, str] | None:
    contract = task.metadata.get("history_composition_contract")
    custom_interval = task.metadata.get("custom_interval")
    if not contract or not custom_interval:
        return None
    return (str(contract), str(custom_interval))


def _task_runs(tasks: list[BackfillTask], interval: str) -> list[list[BackfillTask]]:
    interval_ms = parse_interval_ms(interval) or 1
    ordered = sorted(tasks, key=lambda item: (item.start_ms, item.end_ms))
    runs: list[list[BackfillTask]] = []
    for task in ordered:
        if not runs:
            runs.append([task])
            continue
        prev_run = runs[-1]
        prev = prev_run[-1]
        same_policy = _archive_run_policy(task) == _archive_run_policy(prev)
        adjacent = task.start_ms <= prev.end_ms + interval_ms
        composed_key = _composed_group_key(task)
        same_composed_batch = (
            composed_key is not None
            and composed_key == _composed_group_key(prev)
            and (max(prev.end_ms, task.end_ms) - min(prev_run[0].start_ms, task.start_ms)) // interval_ms + 1
            <= MAX_USDM_ARCHIVE_ROUTE_ROWS
        )
        if same_policy and (adjacent or same_composed_batch):
            prev_run.append(task)
        else:
            # A neighbouring legacy demand must not revoke a qualified page's
            # actual-task envelope by making the all-tasks contract false.
            runs.append([task])
    return runs


def _is_foreground_archive_demand(task: BackfillTask) -> bool:
    """Keep speculative warm-start work from consuming the first-screen gate."""
    metadata = task.metadata or {}
    requester = str(metadata.get("requester") or "").strip().lower()
    reason = str(metadata.get("reason") or "").strip().lower()
    source = str(metadata.get("source") or "").strip().lower()
    if source == "background-prefetch" or reason == "background_prefetch":
        return False
    explicit = metadata.get("archive_explicit_demand")
    if explicit in {True, 1, "1", "true", "True"}:
        return True
    return (
        requester in {
            "klines_history",
            "klines_range",
            "mixed",
            "manual_history_download",
        }
        or "initial_history" in reason
        or "visible_range_gap" in reason
        or reason == "manual_history_download"
    )


def _filter_daily_candidates(
    candidates: list[ArchiveObjectRef],
    *,
    range_start_ms: int,
    range_end_ms: int,
    interval: str,
    rest_page_size: int,
    minimum_pages: int,
    tasks: list[BackfillTask] | None = None,
) -> list[ArchiveObjectRef]:
    monthly_candidates = [
        item
        for item in candidates
        if item.granularity is not ArchiveGranularity.DAILY
    ]
    daily = [item for item in candidates if item.granularity is ArchiveGranularity.DAILY]
    interval_ms = parse_interval_ms(interval)
    if interval_ms is None or interval_ms <= 0:
        return []
    composed_tasks = bool(
        tasks and all(task.metadata.get("history_composition_contract") for task in tasks)
    )
    monthly: list[ArchiveObjectRef] = []
    for ref in monthly_candidates:
        overlap_bars = max(
            0,
            (
                min(ref.end_ms, range_end_ms)
                - max(ref.start_ms, range_start_ms)
            ) // interval_ms + 1,
        )
        complete_requested_month = (
            range_start_ms <= ref.start_ms
            and range_end_ms >= ref.end_ms
        )
        composed_windows = (
            _composed_archive_window_stats(tasks, ref, interval_ms)[1]
            if composed_tasks
            else 0
        )
        if (complete_requested_month
                or _ceil_div(overlap_bars, rest_page_size) >= minimum_pages
                or composed_windows >= max(2, minimum_pages)):
            monthly.append(ref)
    if monthly:
        daily = [
            ref
            for ref in daily
            if not any(
                month.start_ms <= ref.start_ms
                and ref.end_ms <= month.end_ms
                for month in monthly
            )
        ]
    if not daily:
        return monthly
    daily_bars = sum(
        max(
            0,
            (
                min(ref.end_ms, range_end_ms)
                - max(ref.start_ms, range_start_ms)
            ) // interval_ms + 1,
        )
        for ref in daily
        if _intersects(
            range_start_ms,
            range_end_ms,
            ref.start_ms,
            ref.end_ms,
        )
    )
    if _ceil_div(daily_bars, rest_page_size) < minimum_pages:
        return monthly
    return monthly + daily


def _bounded_history_page(tasks):
    return bool(tasks) and all(task.exchange == 'binance' and task.market_type == 'futures'
        and task.metadata.get('bounded_history_batch_contract') == 'binance.usdm.trade-klines/base-utc/1'
        for task in tasks)


def _archive_run_policy(task):
    # Both qualifications are evaluated over all tasks in a run. A legacy
    # neighbour must not erase either the bounded envelope or the exact-slot
    # amplification limit used by required mixed-history sources.
    return (_bounded_history_page([task]),
            bool(task.metadata.get('history_composition_contract')))


def _bounded_usdm_archive_candidates(refs, tasks, interval, *, rejected=None):
    """Bound imports/prefetch by native rows and the current work envelope.

    A persistent warm ZIP is not free reduction work. Oversized monthly or
    distant parent objects stay out of this page's acquisition; normal bounded
    REST pages remain available. The shared archive cache is left untouched.
    """
    width = parse_interval_ms(interval)
    if not width or not tasks:
        return []
    first, last = min(task.start_ms for task in tasks), max(task.end_ms for task in tasks)
    ordered = sorted(refs, key=lambda ref: _range_distance(first, last, ref.start_ms, ref.end_ms))
    selected, rows = [], 0
    composed = all(task.metadata.get('history_composition_contract') for task in tasks) or _bounded_history_page(tasks)
    for ref in ordered:
        count = (ref.end_ms-ref.start_ms)//width+1
        lo, hi = min(first, ref.start_ms), max(last, ref.end_ms)
        reason = None
        if count > MAX_USDM_ARCHIVE_OBJECT_ROWS:
            reason = 'object_row_budget'
        elif rows+count > MAX_USDM_ARCHIVE_ROUTE_ROWS:
            reason = 'route_row_budget'
        elif (hi-lo)//width+1 > MAX_USDM_ARCHIVE_ROUTE_ROWS:
            reason = 'route_envelope_budget'
        elif composed:
            needed, window_count = _composed_archive_window_stats(tasks, ref, width)
            amplification = (
                MAX_COMPOSED_MULTI_EDGE_AMPLIFICATION
                if window_count >= 3
                else MAX_COMPOSED_ARCHIVE_AMPLIFICATION
            )
            if (needed == 0 or count > max(SMALL_COMPOSED_ARCHIVE_ROWS,
                                           amplification * needed)):
                reason = 'source_amplification' if needed else 'no_required_slots'
        if reason:
            if rejected is not None:
                rejected[reason] = rejected.get(reason, 0) + 1
            continue
        selected.append(ref)
        rows += count
        first, last = lo, hi
    return selected


def _composed_archive_window_stats(tasks, ref, width) -> tuple[int, int]:
    """Price exact canonical windows and distinct edge count, excluding holes."""
    spans = []
    for task in tasks:
        windows = task.metadata.get('mixed_fetch_windows', [(task.start_ms, task.end_ms)])
        if not isinstance(windows, (list, tuple)) or len(spans)+len(windows) > 4096:
            return 0, 0
        for first, last in windows:
            lo, hi = max(first, ref.start_ms), min(last, ref.end_ms)
            if lo <= hi:
                spans.append((lo, hi))
    merged = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1]+width:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return sum((hi-lo)//width+1 for lo, hi in merged), len(merged)


def _composed_archive_slots(tasks, ref, width):
    """Price exact canonical windows, excluding HTTP read-ahead holes."""
    return _composed_archive_window_stats(tasks, ref, width)[0]


def _archive_decision_range(tasks: list[BackfillTask]) -> tuple[int, int]:
    """Use qualified task envelopes; preserve legacy parent prefill."""
    actual_start = min(task.start_ms for task in tasks)
    actual_end = max(task.end_ms for task in tasks)
    if _bounded_history_page(tasks):
        return actual_start, actual_end
    starts = [actual_start]
    ends = [actual_end]
    for task in tasks:
        raw = task.metadata.get("ledger_range")
        if not isinstance(raw, dict):
            continue
        try:
            parent_start = int(raw["start_ms"])
            parent_end = int(raw["end_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        if parent_start <= parent_end:
            starts.append(parent_start)
            ends.append(parent_end)
    return min(starts), max(ends)


def _route_decision(task: BackfillTask) -> dict[str, Any]:
    """Scalar provenance only: no payloads, owners or arbitrary metadata."""
    parent = task.metadata.get('ledger_range')
    parent = parent if isinstance(parent, dict) else {}
    return dict(task_key=task.task_key, exchange=task.exchange,
        market_type=task.market_type, symbol=task.symbol, interval=task.interval,
        requested_interval=str(task.metadata.get('custom_interval')
            or task.metadata.get('requested_interval') or task.interval)[:64],
        task_start_ms=task.start_ms, task_end_ms=task.end_ms,
        ledger_start_ms=parent.get('start_ms') if type(parent.get('start_ms')) is int else None,
        ledger_end_ms=parent.get('end_ms') if type(parent.get('end_ms')) is int else None,
        route_start_ms=task.start_ms, route_end_ms=task.end_ms,
        bounded_history_page=_bounded_history_page([task]),
        candidate_objects=0, eligible_objects=0, selected_object_count=0,
        selected_objects=[], reason='archive_disabled')


def _unique_refs(values: list[ArchiveObjectRef]) -> list[ArchiveObjectRef]:
    unique: dict[str, ArchiveObjectRef] = {}
    for item in values:
        if item.url:
            unique[item.object_key] = item
    return sorted(unique.values(), key=lambda item: (item.start_ms, item.object_key))


def _range_distance(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> int:
    if _intersects(left_start, left_end, right_start, right_end):
        return 0
    if right_end < left_start:
        return left_start - right_end
    return right_start - left_end


def _intersects(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start <= right_end and right_start <= left_end


def _ceil_div(value: int, divisor: int) -> int:
    return (max(0, int(value)) + max(1, int(divisor)) - 1) // max(1, int(divisor))


__all__ = [
    "ArchiveObjectResult",
    "ArchiveRoutePlan",
    "HistoricalSourceRouter",
]
