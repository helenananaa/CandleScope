"""On-demand, display-only context for automatically prepared BAR runs.

The execution revision and account cursor never change. The preparation service
owns immutable, retained chunks and handles bounded downloads, retries and disk
budgets just as it does for initial training preparation.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

from app.replay.bars.builder import ReplayBarBuilder
from app.replay.errors import ReplayDomainError
from app.replay.canonical import canonical_sha256
from app.replay.dataset import validate_replay_repository_bar
from app.replay.display_time import SourceBucketTimeMapper
from app.replay.models import ReplaySessionConfig
from app.replay.training.errors import TrainingRunError
from app.replay.training.history import _decode_bar_snapshot, _bound_source_start_ms
from app.data_engine.interval_policy import compute_bucket_start_ms

from .models import PreparationError, PreparationRequest, Requirement, fingerprint


class ReplayHistoryContext:
    def __init__(self, preparation, *, wait_seconds=20):
        self.preparation = preparation
        self.wait_seconds = wait_seconds

    async def _rows(self, requirement):
        service = self.preparation
        request = PreparationRequest(
            idempotency_key="replay-context-" + fingerprint(requirement.model_dump()),
            consumer="PREFETCH", requirements=[requirement],
            intent={"purpose": "replay_display_history"},
        )
        job = await service.submit(request)
        if job["state"] in {"FAILED", "CANCELLED", "BLOCKED_STORAGE"}:
            try:
                job = await service.retry(job["id"])
            except PreparationError:
                # Another chart may already have retried this shared job.
                current = await service.storage(service.repository.get, job["id"])
                if current["state"] not in {"QUEUED", "RUNNING", "READY"}:
                    raise
                job = current
        deadline = asyncio.get_running_loop().time() + self.wait_seconds
        while job["state"] != "READY":
            if job["state"] in {"FAILED", "CANCELLED", "BLOCKED_STORAGE"}:
                raise PreparationError("HISTORY_DOWNLOAD_FAILED",
                    "Earlier history could not be prepared; retry to continue", retryable=True)
            if asyncio.get_running_loop().time() >= deadline:
                raise PreparationError("HISTORY_DOWNLOAD_PENDING",
                    "Earlier history is still downloading; retry to continue", retryable=True)
            await asyncio.sleep(0.15)
            job = await service.storage(service.repository.get, job["id"])
        rows = []
        for item in job["result"]["inputs"]:
            chunk = await service.storage(service.repository.chunk, item["key"], owner=job["id"])
            if chunk is None:
                raise PreparationError("HISTORY_CACHE_UNAVAILABLE",
                    "Prepared history is unavailable; retry the preparation", retryable=True)
            # A covering cache object may be larger than this job's selection.
            chunk = {**chunk, "source_requirement": chunk["requirement"],
                     "requirement": item["requirement"]}
            rows.extend(await service.storage(service.adapter.read, chunk))
        return sorted(rows, key=lambda row: row["open_time"])

    async def complete_projection(self, *, page, binding, persisted, repository):
        """Complete a coarse forming bucket whose prefix predates the warmup."""
        config = ReplaySessionConfig.from_dict(binding["config"])
        snapshot = _decode_bar_snapshot(persisted, config=config)
        actual_start = int(binding["history_policy"]["actual_replay_start_ms"])
        mapper = SourceBucketTimeMapper.create(interval=page["display_interval"],
            actual_replay_start_ms=actual_start, public_replay_start_ms=snapshot.replay_start_ms,
            source_bucket_anchor_ms=binding.get("display_source_bucket_anchor_ms"))
        end = actual_start + ((page["revealed_boundary_ms"] + 1 - snapshot.replay_start_ms) // 60_000) * 60_000
        start = mapper.actual_containing_bucket_open(end - 1)
        public_start = mapper.public_from_actual(start)
        if any(bar["open_time_ms"] == public_start for bar in page["bars"]):
            return page
        frozen_start, _ = await asyncio.to_thread(_bound_source_start_ms,
            repository=repository, config=config, snapshot=snapshot,
            actual_replay_start_ms=actual_start,
            fallback_start_ms=int(binding["history_policy"]["actual_visible_history_start_ms"]),
            interval_ms=60_000)
        if start >= frozen_start or start < 0 or public_start < 0:
            return page
        identity = snapshot.identity
        try:
            rows = await self._rows(Requirement(exchange=identity.exchange,
                market_type=identity.market_type, symbol=identity.symbol,
                start_ms=start, end_ms=frozen_start))
            rows.extend(await asyncio.to_thread(repository.query_bars_at_revision,
                snapshot.provenance.source_revision, identity.symbol, config.base_interval,
                exchange=identity.exchange, market_type=identity.market_type,
                start_ms=frozen_start, end_ms=end - 1,
                limit=(end - frozen_start) // 60_000, order="ASC"))
            projected = await asyncio.to_thread(project_context, rows, start, end, mapper,
                                               identity, include_active=True)
        except (PreparationError, ReplayDomainError) as exc:
            raise TrainingRunError(getattr(exc.code, "value", exc.code), str(exc), status_code=503,
                                   details={"retryable": True}) from exc
        bars = sorted([*page["bars"], *projected], key=lambda bar: bar["open_time_ms"])
        return {**page, "bars": bars, "history_before_ms": bars[0]["open_time_ms"],
                "projection_epoch": canonical_sha256({"frozen": page["projection_epoch"],
                                                      "context_tail": projected})}

    async def extend(self, *, page, binding, persisted, repository,
                     before_ms, limit, expected_history_epoch):
        epoch = canonical_sha256({"contract": "prepared-replay-context.v1",
                                  "frozen_history_epoch": page["history_epoch"]})
        if expected_history_epoch is not None and expected_history_epoch != epoch:
            raise TrainingRunError("HISTORY_EPOCH_MISMATCH", "training history epoch does not match")
        result = {**page, "history_epoch": epoch}
        if page["has_more"]:
            return result
        config = ReplaySessionConfig.from_dict(binding["config"])
        snapshot = _decode_bar_snapshot(persisted, config=config)
        actual_start = int(binding["history_policy"]["actual_replay_start_ms"])
        mapper = SourceBucketTimeMapper.create(
            interval=page["identity"]["display_interval"],
            actual_replay_start_ms=actual_start,
            public_replay_start_ms=snapshot.replay_start_ms,
        )
        cursor = page["bars"][0]["open_time_ms"] if page["bars"] else before_ms
        # Pages are exclusive and must never fetch future/execution inputs.
        public_end = compute_bucket_start_ms(cursor, mapper.interval_ms, interval=mapper.interval)
        end = mapper.actual_containing_bucket_open(min(mapper.actual_from_public(public_end), actual_start))
        ordinal = mapper.actual_bucket_ordinal(end)
        remaining = limit - len(page["bars"])
        count = min(remaining, max(1, 8192 // max(1, mapper.interval_ms // 60_000)))
        while count > 0 and (mapper.actual_bucket_open(ordinal - count) < 0
                            or mapper.public_bucket_open(ordinal - count) < 0):
            count -= 1
        result["history_boundary_ms"] = 0
        if count == 0:
            result["has_more"] = remaining == 0 or ordinal > 0
            return result
        start = mapper.actual_bucket_open(ordinal - count)
        frozen_start, _ = await asyncio.to_thread(_bound_source_start_ms,
            repository=repository, config=config, snapshot=snapshot,
            actual_replay_start_ms=actual_start,
            fallback_start_ms=int(binding["history_policy"]["actual_visible_history_start_ms"]),
            interval_ms=60_000)
        identity = snapshot.identity
        rows = []
        try:
            if start < frozen_start:
                rows = await self._rows(Requirement(
                    exchange=identity.exchange, market_type=identity.market_type, symbol=identity.symbol,
                    start_ms=start, end_ms=min(end, frozen_start),
                ))
            if end > frozen_start:
                # Preserve the original revision even if the host later corrects
                # overlapping bars. Only strictly older context is acquired.
                rows.extend(await asyncio.to_thread(repository.query_bars_at_revision,
                    snapshot.provenance.source_revision, identity.symbol, config.base_interval,
                    exchange=identity.exchange, market_type=identity.market_type,
                    start_ms=max(start, frozen_start), end_ms=end - 1,
                    limit=(end - max(start, frozen_start)) // 60_000, order="ASC"))
            added = await asyncio.to_thread(project_context, rows, start, end, mapper, identity)
        except (PreparationError, ReplayDomainError) as exc:
            raise TrainingRunError(getattr(exc.code, "value", exc.code), str(exc), status_code=503,
                                   details={"retryable": True}) from exc
        if not added:
            raise TrainingRunError("HISTORY_SOURCE_INCOMPLETE",
                                   "Earlier history could not form a complete chart bar", status_code=503)
        result["bars"] = added + page["bars"]
        result["next_before_ms"] = added[0]["open_time_ms"]
        result["has_more"] = start > 0 and added[0]["open_time_ms"] > 0
        return result


def project_context(rows, start, end, mapper, identity, *, include_active=False):
    if len(rows) != (end - start) // 60_000:
        raise PreparationError("HISTORY_SOURCE_INCOMPLETE", "Earlier history contains missing bars", retryable=True)
    bars = tuple(validate_replay_repository_bar(row, identity=identity, interval="1m",
        interval_ms=60_000, expected_open_ms=start + index * 60_000, now_ms=end)
        for index, row in enumerate(rows))
    builder = ReplayBarBuilder(base_interval="1m", display_interval=mapper.interval,
                              replay_start_ms=end, warmup_bars=bars,
                              max_closed_bars=max(1, len(bars)))
    result = []
    for bar in (*builder.closed_bars, *((builder.active_bar,) if include_active and builder.active_bar else ())):
        public = mapper.public_from_actual(bar.open_time_ms)
        # Match the replay's source bucket mapping, including blind calendars.
        public_end = mapper.public_bucket_end(public)
        components = (public_end - public) // 60_000
        result.append(replace(bar, open_time_ms=public, close_time_ms=public_end - 1,
            first_base_open_ms=public, last_base_open_ms=(public_end - 60_000 if bar.is_closed else public + bar.last_base_open_ms - bar.open_time_ms),
            component_count=(components if bar.is_closed else bar.component_count), expected_components=components).to_dict())
    return result
