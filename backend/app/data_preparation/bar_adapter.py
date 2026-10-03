"""BAR acquisition through the existing host scheduler, then immutable publication."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from app.data_engine.data_manager.backfill_contracts import RepairRequest
from app.data_engine.kline_quality import source_is_trusted_final
from app.data_engine.storage.klines_repo import query_klines

from .models import PreparationError, PreparationRequest, Requirement, canonical, fingerprint
from .storage import storage_call


class BarPreparationAdapter:
    def __init__(self, root: Path, *, coordinator, replay_service=None, local_data=None,
                 query=query_klines, now_ms=lambda: int(time.time() * 1000), backtest_runtime=None,
                 host_history_path=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.coordinator = coordinator
        self.replay_service = replay_service
        self.local_data = local_data
        self.query = query
        self.now_ms = now_ms
        self.backtest_runtime = backtest_runtime
        self.publication_repository = None
        self._repair_requests = {}
        self.host_history_path = None if host_history_path is None else Path(host_history_path)
        from .trade_adapter import TradePreparationAdapter
        archive = getattr(replay_service, "raw_trade_archive", None)
        if not getattr(archive, "enabled", False):
            archive = getattr(backtest_runtime, "trade_archive", None)
        self.trades = TradePreparationAdapter(archive)

    def publication_scopes(self):
        scopes = []
        if self.replay_service is not None:
            root = getattr(getattr(self.replay_service, "settings", None), "replay_history_archive_dir", None)
            if root is not None:
                scopes.append((root, "replay_archive"))
            objects = getattr(getattr(self.replay_service, "store", None), "_dataset_objects", None)
            if objects is not None:
                scopes.append((objects.root, "replay_session_inputs"))
        if self.local_data is not None:
            scopes.append((self.local_data.root, "strategy_storage"))
        trade_root = getattr(self.trades.archive, "root", None)
        if trade_root is not None:
            scopes.append((trade_root, "trade_archive"))
        scopes.extend((path, "shared_host_history") for path in self._host_history_files())
        return scopes

    def _host_history_files(self):
        if self.host_history_path is None:
            return []
        return [Path(str(self.host_history_path) + suffix) for suffix in ("", "-wal", "-shm", "-journal")]

    def _record_host_history(self):
        if self.publication_repository is not None and self.host_history_path is not None:
            self.publication_repository.register_publications(
                [(path, "shared_host_history") for path in self._host_history_files()])
            self.publication_repository.refresh_publications(paths=self._host_history_files())
            self.publication_repository.check_physical_budget()

    def validate(self, request: PreparationRequest):
        if request.progressive:
            from .progressive import plan
            plan(request)
        if request.consumer == "REPLAY" and any(r.role == "BARS" for r in request.requirements):
            from app.replay.manual_history_import import import_unavailable_reason
            reason = import_unavailable_reason(self.replay_service)
            if reason:
                raise PreparationError("REPLAY_PREPARATION_UNAVAILABLE", reason)
        if request.consumer == "STRATEGY" and self.local_data is None:
            raise PreparationError("STRATEGY_PREPARATION_UNAVAILABLE", "Local dataset service is unavailable")
        if "replay_setup" in request.intent:
            from app.replay.request_contracts import TrainingRunSetupPayload
            from app.replay.training.models import TrainingRunSetupRequest
            from app.data_engine.interval_policy import parse_interval_spec
            try:
                payload = TrainingRunSetupPayload.model_validate(request.intent["replay_setup"])
                setup = TrainingRunSetupRequest.from_dict(payload.model_dump(mode="json")).to_dict()
            except (TypeError, ValueError) as exc:
                raise PreparationError("INVALID_REPLAY_SETUP", str(exc)) from exc
            if (setup["account_data_mode"] not in {"APPROX_PROXY", "HISTORICAL_EXACT"}
                    or setup["book_mode"] != "OFF"
                    or (setup["funding_mode"] == "HISTORICAL_EXACT" and setup["account_data_mode"] != "HISTORICAL_EXACT")):
                raise PreparationError("INPUT_UNSUPPORTED", "This replay needs precise auxiliary inputs; automatic acquisition is not yet available for this mode")
            display = parse_interval_spec(str(request.intent.get("display_interval", "1m")))
            if display is None or display.nominal_ms < 60_000 or display.nominal_ms % 60_000:
                raise PreparationError("INVALID_INTERVAL", "Display interval must be constructible from minute bars")
        estimate = 0
        for requirement in request.requirements:
            if requirement.role == "TRADES":
                self.trades.validate(requirement, self.now_ms())
                if request.consumer == "STRATEGY":
                    consumer_archive = getattr(self.backtest_runtime, "trade_archive", None)
                    if (consumer_archive is None or not hasattr(consumer_archive, "root")
                            or consumer_archive.root.resolve() != self.trades.archive.root.resolve()):
                        raise PreparationError("TRADE_ARCHIVE_MISMATCH", "Strategy and preparation must use the same verified trade archive")
                continue
            if requirement.role != "BARS" or requirement.interval != "1m":
                raise PreparationError("INPUT_UNSUPPORTED", "This acquisition adapter supplies one-minute BAR inputs only")
            if requirement.start_ms % 60_000 or requirement.end_ms % 60_000:
                raise PreparationError("INVALID_TIME_GRID", "BAR boundaries must align to complete minutes")
            if requirement.end_ms > self.now_ms() // 60_000 * 60_000:
                raise PreparationError("FUTURE_INPUT", "Only closed historical bars may be prepared")
            estimate += (requirement.end_ms - requirement.start_ms) // 60_000 * 1024
        if request.consumer == "STRATEGY" and estimate // 1024 > 200_000:
            raise PreparationError("STRATEGY_INPUT_LIMIT", "Strategy BAR input exceeds 200000 rows")
        if estimate > request.max_bytes:
            raise PreparationError("STORAGE_BUDGET", "Requested range exceeds the estimated input budget")

    def _rows(self, requirement):
        return self.query(requirement.symbol, requirement.interval,
                          start_ms=requirement.start_ms, end_ms=requirement.end_ms - 1,
                          limit=(requirement.end_ms - requirement.start_ms) // 60_000 + 1,
                          order="ASC", exchange=requirement.exchange, market_type=requirement.market_type)

    @staticmethod
    def _complete(rows, requirement, *, require_trusted_source=True):
        return len(rows) == (requirement.end_ms - requirement.start_ms) // 60_000 and all(
            int(row["open_time"]) == requirement.start_ms + i * 60_000
            and int(row["close_time"]) == requirement.start_ms + (i + 1) * 60_000 - 1
            and (not require_trusted_source or source_is_trusted_final(row.get("source")))
            for i, row in enumerate(rows))

    async def acquire(self, requirement: Requirement, key: str):
        if requirement.role == "TRADES":
            return await self.trades.acquire(requirement, storage_call, repository=self.publication_repository)
        # Reserve enough free disk for a bounded day and its publication copies.
        if shutil.disk_usage(self.root).free < 64 * 1024**2:
            raise PreparationError("STORAGE_BUDGET", "Insufficient free space to prepare history")
        archived = await storage_call(self._archive_rows, requirement)
        if archived is not None:
            return await storage_call(self._write, archived, requirement, "replay_archive")
        rows = await storage_call(self._rows, requirement)
        if not self._complete(rows, requirement):
            if self.coordinator is None:
                raise PreparationError("DOWNLOAD_UNAVAILABLE", "Historical download service is unavailable")
            repair = RepairRequest(
                symbol=requirement.symbol, interval=requirement.interval,
                start_ms=requirement.start_ms, end_ms=requirement.end_ms - 60_000,
                exchange=requirement.exchange, market_type=requirement.market_type,
                reason="data_preparation", priority=40, requester=f"preparation:{key}",
                wait_policy="wait", metadata={"requires_trusted_finality": True},
            )
            if hasattr(self.coordinator, "acquire_demand"):
                request_id = self.coordinator.request(repair)
                owner = f"prepared-input:{key}"
                await self.coordinator.acquire_demand(request_id, owner_id=owner)
                self._repair_requests[key] = request_id
                try:
                    await self.coordinator.wait_for_request(request_id)
                finally:
                    self._repair_requests.pop(key, None)
                    await self.coordinator.release_demand(request_id, owner_id=owner,
                                                          cancel_if_unobserved=True)
            else:
                await self.coordinator.request_and_wait(repair)
            rows = await storage_call(self._rows, requirement)
        if not self._complete(rows, requirement):
            raise PreparationError("COVERAGE_INCOMPLETE", "Historical source did not supply the complete requested range", retryable=True)
        await storage_call(self._record_host_history)
        return await storage_call(self._write, rows, requirement)

    def acquisition_waiting(self, key):
        request_id = self._repair_requests.get(key)
        progress = getattr(self.coordinator, "progress_for_request", None)
        if request_id is None or progress is None:
            return None
        snapshot = progress(request_id) or {}
        retry_at = snapshot.get("retry_at_ms")
        if snapshot.get("status") == "rate_limit_deferred" and type(retry_at) is int and retry_at > self.now_ms():
            return {"reason": "RATE_LIMIT", "retry_at_ms": retry_at}
        return None

    def _archive_rows(self, requirement):
        repository = getattr(self.replay_service, "_repository", None)
        if repository is None:
            return None
        from app.replay.history_archive import ReplayHistoryArchiveError
        try:
            rows = repository.query_bars(requirement.symbol, requirement.interval,
                start_ms=requirement.start_ms, end_ms=requirement.end_ms - 1,
                limit=(requirement.end_ms - requirement.start_ms) // 60_000 + 1,
                exchange=requirement.exchange, market_type=requirement.market_type)
        except ReplayHistoryArchiveError as exc:
            if "series is unavailable" in str(exc):
                return None
            raise
        return rows if self._complete(rows, requirement, require_trusted_source=False) else None

    def _write(self, rows, requirement, origin="host_history"):
        # Verify OHLC values with the existing importer at publication as well.
        # The shared copy is a recoverable acquisition cache, never an engine feed.
        raw = canonical({"requirement": requirement.model_dump(), "origin": origin, "rows": rows}).encode()
        digest = hashlib.sha256(raw).hexdigest()
        payload = gzip.compress(raw, mtime=0)
        path = self.root / f"{digest}.json.gz"
        receipt = {"sha256": digest, "rows": len(rows), "origin": origin}
        if self.publication_repository is not None:
            if path.exists():
                self.publication_repository.map_legacy_cache_receipt(receipt, path)
            self.publication_repository.reserve_cache_write(receipt, len(payload), reuse_existing=path.exists())
        if not path.exists():
            staging = self.root / f".{uuid.uuid4().hex}.tmp"
            try:
                with staging.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(staging, path)
            finally:
                staging.unlink(missing_ok=True)
                if not path.exists() and self.publication_repository is not None:
                    self.publication_repository.release_cache_write(receipt)
        if self.publication_repository is not None:
            self.publication_repository.map_legacy_cache_receipt(receipt, path)
        return receipt, len(payload)

    def read(self, chunk):
        digest = chunk["receipt"]["sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise PreparationError("INPUT_CORRUPT", "Invalid cached input identity")
        try:
            with gzip.open(self.root / f"{digest}.json.gz", "rb") as stream:
                raw = stream.read(16 * 1024**2 + 1)
            if len(raw) > 16 * 1024**2 or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("cached input checksum mismatch")
            data = json.loads(raw)
            if data["requirement"] != chunk.get("source_requirement", chunk["requirement"]):
                raise ValueError("cached input requirement mismatch")
            requirement = Requirement.model_validate(data["requirement"])
            if data["origin"] != chunk["receipt"].get("origin"):
                raise ValueError("cached input provenance mismatch")
            if not self._complete(data["rows"], requirement, require_trusted_source=data["origin"] != "replay_archive"):
                raise ValueError("cached input coverage mismatch")
            selected = chunk["requirement"]
            return [row for row in data["rows"] if selected["start_ms"] <= row["open_time"] < selected["end_ms"]]
        except (OSError, ValueError, KeyError) as exc:
            raise PreparationError("INPUT_CORRUPT", "Prepared input is missing or corrupt") from exc

    def remove_cached_object(self, receipt):
        if receipt.get("kind") == "verified_trades":
            return False  # Engine-owned archive is never acquisition-cache garbage.
        digest = receipt.get("sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise PreparationError("INPUT_CORRUPT", "Invalid cache object identity")
        path = self.root / f"{digest}.json.gz"
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def reconcile_cache(self, repository):
        """Run only under the preparation lease, before starting workers."""
        from .lease import PreparationLease
        lease = PreparationLease(self.root / ".preparation-owner.lock")
        lease.acquire()
        try:
            removed = self._reconcile_cache_locked(repository)
            # An interrupted write remains charged until its orphan is removed
            # or a retry publishes a chunk. Never forget a surviving byte object.
            for receipt in repository.pending_cache_writes():
                digest = receipt.get("sha256", "")
                if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                    if not (self.root / f"{digest}.json.gz").exists():
                        repository.release_cache_write(receipt)
            return removed
        finally:
            lease.release()

    def _reconcile_cache_locked(self, repository):
        owner = str(repository.path.resolve())
        marker = self.root / ".preparation-owner"
        if not marker.exists():
            existing_names = [path.name for path in self.root.iterdir()]
            staging = self.root / ("." + uuid.uuid4().hex + ".tmp")
            try:
                with staging.open("x", encoding="utf-8") as stream:
                    json.dump({"database": owner, "legacy_files": existing_names}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(staging, marker)
            finally:
                staging.unlink(missing_ok=True)
            # An older/unclassified directory may have another database's
            # files. Establish ownership without deleting anything on adoption.
            self._register_legacy_cache(repository, existing_names)
            return 0
        else:
            try:
                binding = json.loads(marker.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                raise PreparationError("CACHE_OWNER_UNKNOWN", "Cache directory ownership could not be verified") from exc
            if not isinstance(binding, dict) or binding.get("database") != owner:
                raise PreparationError("CACHE_OWNER_MISMATCH", "Cache directory belongs to another preparation database")
            legacy_files = binding.get("legacy_files")
            if not isinstance(legacy_files, list) or not all(isinstance(name, str) for name in legacy_files):
                raise PreparationError("CACHE_OWNER_UNKNOWN", "Cache directory ownership could not be verified")
            legacy_files = set(legacy_files)
        self._register_legacy_cache(repository, legacy_files)
        retained = {receipt.get("sha256") for receipt in repository.retained_cache_receipts()}
        removed = 0
        for path in self.root.iterdir():
            name = path.name
            if name in legacy_files:
                continue
            temporary = (name.startswith(".") and name.endswith(".tmp")
                and len(name) == 37 and all(c in "0123456789abcdef" for c in name[1:-4]))
            digest = name[:-8] if name.endswith(".json.gz") else ""
            orphan = (len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
                and digest not in retained)
            if (temporary or orphan) and path.is_file() and not path.is_symlink():
                path.unlink()
                removed += 1
        return removed

    def _register_legacy_cache(self, repository, names):
        known = {f"{receipt.get('sha256')}.json.gz" for receipt in repository.retained_cache_receipts()}
        scopes = []
        for name in names:
            if name in {".preparation-owner", ".preparation-owner.lock"} or name in known:
                continue
            if Path(name).name != name or name in {".", ".."}:
                raise PreparationError("CACHE_OWNER_UNKNOWN", "Cache ownership contains an invalid legacy filename")
            path = self.root / name
            if path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path):
                continue
            scopes.append((path, "acquisition_legacy"))
        repository.register_publication_scopes(scopes)

    async def prepare_dependencies(self, request: PreparationRequest):
        from .replay_dependencies import prepare_replay_dependencies
        references = await prepare_replay_dependencies(getattr(self.replay_service, "training", None), request)
        return {"replay_dependencies": references} if references else {}

    async def publish(self, request: PreparationRequest, chunks: list[dict], job_id: str):
        return await storage_call(self._publish, request, chunks, job_id)

    @contextmanager
    def _publication_space(self, rows, *, metadata_bytes=0):
        """Hold working-space allowance across one bounded publication unit.

        Serialized source size covers variable-width values; per-row headroom
        covers SQLite pages/range indexes, with fixed metadata/temp headroom.
        This is a conservative estimate, not an OS filesystem quota.
        """
        repository = self.publication_repository
        token = None
        if repository is not None:
            estimate = 1024**2 + len(canonical(rows).encode()) * 8 + len(rows) * 4096 + metadata_bytes * 3
            token = repository.reserve_publication(estimate)
        try:
            yield token
        except BaseException:
            if token is not None:
                repository.abandon_publication(token)
            raise

    def _record_dataset(self, dataset_id, *, reservation=None):
        if self.publication_repository is not None and self.local_data is not None:
            directory = self.local_data.root / dataset_id
            self.publication_repository.register_publications(
                ((path, "strategy_input") for path in directory.rglob("*") if path.is_file()),
                reservation=reservation)
            self.publication_repository.check_physical_budget()

    async def begin_progressive(self, request, job_id):
        from .progressive import plan
        from app.replay.catalog import ReplaySeriesIdentity
        planned, fragments = plan(request)
        requirement = request.requirements[0]
        feed = await storage_call(self.replay_service.progressive_history.create,
            f"preparation-{job_id}", ReplaySeriesIdentity(requirement.exchange,
                requirement.market_type, requirement.symbol), planned["start_ms"], planned["end_ms"])
        return {**planned, "feed_id": feed["id"]}, fragments

    async def publish_progressive(self, request, chunks, job_id, plan, fragment):
        history = self.replay_service.progressive_history
        start = max(plan["start_ms"], fragment.start_ms)
        if fragment.end_ms > start:
            feed = await storage_call(history.status, plan["feed_id"])
            if feed["ready_end_ms"] >= fragment.end_ms:
                # This immutable segment was committed before interruption.
                return {"job_id": job_id, "consumer": "REPLAY", "progressive": plan}
        published = await self.publish(request, chunks, job_id)
        if fragment.end_ms > start:
            await storage_call(history.publish, plan["feed_id"],
                published["inputs"][0]["source_revision"], start, fragment.end_ms)
        return {**published, "progressive": plan}

    async def reuse(self, request, job_id):
        resolution = request.intent.get("ready_resolution")
        if request.consumer != "STRATEGY" or resolution is None:
            return None
        from functools import partial
        context = request.intent["chart_context"]
        preview = await storage_call(partial(self.backtest_runtime.preview_snapshot,
            dataset_id=resolution["dataset_id"], data_epoch=resolution["data_epoch"],
            start_time_ms=context["start_time_ms"], end_time_ms=context["end_time_ms"],
            interval=context["interval"], fidelity_mode=resolution["fidelity"]["mode"],
            exchange=context["exchange"], market_type=context["market_type"]))
        if preview["snapshot_hash"] != resolution["snapshot_hash"]:
            raise PreparationError("INPUT_CHANGED", "Prepared strategy input changed before launch")
        resolution = {**resolution}
        if "preparation" in request.intent:
            resolution["preparation"] = request.intent["preparation"]
        return {"job_id": job_id, "consumer": "STRATEGY", "resolution": resolution,
                "inputs": [{"dataset_id": resolution["dataset_id"], "data_epoch": resolution["data_epoch"]}]}

    async def launch(self, request, result, job_id):
        from app.replay.storage.sqlite_store import dataset_object_write_budget
        with dataset_object_write_budget(self.publication_repository):
            try:
                return await self._launch(request, result, job_id)
            except Exception as exc:
                # Blind replay intentionally hides unexpected storage details.
                # Preserve the preparation policy's actionable, data-free code
                # without changing the replay engine's public error contract.
                cause, seen = exc, set()
                while cause is not None and id(cause) not in seen:
                    seen.add(id(cause))
                    if isinstance(cause, PreparationError) and cause.code == "STORAGE_BUDGET":
                        raise PreparationError("STORAGE_BUDGET", "Insufficient storage space to attach prepared inputs") from exc
                    cause = cause.__cause__
                raise

    async def _launch(self, request, result, job_id):
        if "native_strategy" in request.intent:
            from .native_plan import launch
            run = await storage_call(launch, self.backtest_runtime, request.intent["native_strategy"], result["native_inputs"], job_id)
            return {**result, "native_run": run}
        if request.consumer == "STRATEGY" and "chart_context" in request.intent:
            if self.backtest_runtime is None:
                raise PreparationError("STRATEGY_PREPARATION_UNAVAILABLE", "Strategy runtime is unavailable")
            resolution = result.get("resolution")
            if resolution is None:
                resolution = await storage_call(self.backtest_runtime.chart_context.resolve, request.intent["chart_context"])
            if resolution["status"] != "READY":
                raise PreparationError("CONTEXT_NOT_READY", "Prepared history does not meet the strategy input requirements")
            result = {**result, "resolution": resolution}
            if "strategy" in request.intent:
                from .strategy_launcher import launch
                result["strategy_run"] = await storage_call(launch, self.backtest_runtime,
                    request.intent["strategy"], resolution, job_id)
            return result
        if request.consumer != "REPLAY" or "replay_setup" not in request.intent:
            return result
        from app.replay.request_contracts import TrainingRunSetupPayload
        from app.replay.training.models import TrainingRunSetupRequest, TrainingRunMarketSelectionRequest
        payload = TrainingRunSetupPayload.model_validate(request.intent["replay_setup"])
        setup = TrainingRunSetupRequest.from_dict(payload.model_dump(mode="json"))
        progressive = result.get("progressive")
        prefix = progressive["initial_horizon_ms"] if progressive else None
        scope = request.requirements[0]
        market_options = ({"_market_identity": (scope.exchange, scope.market_type, scope.symbol)}
                          if request.intent.get("submission", {}).get("random_by_market") else {})
        created = await self.replay_service.training.create_empty_run(setup, preparation_id=job_id,
            _progressive_initial_horizon_ms=prefix, **market_options)
        if not created["run"].get("adapter_session_id"):
            requirement = request.requirements[0]
            if progressive:
                catalog = await self.replay_service.catalog(
                    warmup_bars=setup.to_dict()["indicator_warmup_bars"], horizon_ms=prefix,
                    quality_mode="exact", blind_mode=False, source_kind="BAR")
            else:
                catalog = await self.replay_service.training.market_catalog(created["run"]["run_id"])
            selected = await self.replay_service.training.select_initial_market(
                created["run"]["run_id"], TrainingRunMarketSelectionRequest.from_dict({
                    "catalog_epoch": catalog["catalog_epoch"], "exchange": requirement.exchange,
                    "market_type": requirement.market_type, "symbol": requirement.symbol,
                    "base_interval": "1m", "display_interval": request.intent.get("display_interval", "1m"),
                    "account_history_ref": None, "hedge_public_history_ref": None, "simulation_manifest_ref": None,
                    **result.get("replay_dependencies", {}),
                }), _progressive_feed_id=progressive["feed_id"] if progressive else None,
                _progressive_initial_horizon_ms=prefix)
            created = selected
        return {**result, "run": created["run"]}

    def _publish(self, request, chunks, job_id):
        result = {"job_id": job_id, "inputs": [], "consumer": request.consumer}
        trade_chunks = [chunk for chunk in chunks if chunk["requirement"]["role"] == "TRADES"]
        for chunk in trade_chunks:
            reference = self.trades.validate_receipt(chunk)
            result["inputs"].append({"role": "TRADES", "exchange": reference.exchange,
                "market_type": reference.market_type, "symbol": reference.symbol,
                "data_epoch": reference.data_epoch, "selection": chunk["requirement"],
                "dataset": reference.to_dict()})
        chunks = [chunk for chunk in chunks if chunk["requirement"]["role"] != "TRADES"]
        if request.consumer == "PREFETCH":
            # A READY prefetch has readable, verified objects too.
            for chunk in chunks:
                self.read(chunk)
            result["inputs"].extend({"key": c["key"], "requirement": c["requirement"]} for c in chunks)
            return result
        groups = {}
        for chunk in chunks:
            req = chunk["requirement"]
            group = (req["exchange"], req["market_type"], req["symbol"], req["interval"])
            groups.setdefault(group, []).append(chunk)
        for (exchange, market, symbol, interval), fragments in groups.items():
            if request.consumer == "REPLAY":
                from app.replay.catalog import ReplaySeriesIdentity
                from app.replay.history_archive import ReplayHistoryArchiveWriter, ReplayHistoryImportBatch
                writer = ReplayHistoryArchiveWriter(self.replay_service.settings.replay_history_archive_dir)
                identity = ReplaySeriesIdentity(exchange, market, symbol)
                # Publish bounded fragments; already completed immutable objects
                # survive interruption and are deduplicated by the writer.
                for fragment in fragments:
                    rows = self.read(fragment)
                    current = writer.current_manifest(identity, interval)
                    metadata_bytes = len(canonical(current.to_dict()).encode()) if current is not None else 0
                    with self._publication_space(rows, metadata_bytes=metadata_bytes) as reservation:
                        manifest = writer.import_batches(identity, interval, [ReplayHistoryImportBatch(
                            rows=rows, source_provider=f"automatic_{fragment['receipt']['origin']}_snapshot",
                            source_object_key=fragment["key"],
                            source_period=f"{fragment['requirement']['start_ms']}:{fragment['requirement']['end_ms']}",
                        )], listing_boundary_source="automatic_host_history_snapshot")
                        if self.publication_repository is not None:
                            from app.replay.shared_market_index import index_path
                            paths = []
                            for item in manifest.objects:
                                if item.source_object_key == fragment["key"]:
                                    path = writer.root / item.relative_path
                                    paths.extend([(path, "replay_bar"), (index_path(path), "replay_index")])
                            from app.replay.history_archive import _catalog_directory
                            catalog_dir = _catalog_directory(writer.root, identity, interval)
                            paths.extend([(catalog_dir / "current.json", "replay_catalog"),
                                (catalog_dir / (manifest.catalog_epoch.split(":")[-1] + ".json"), "replay_catalog")])
                            self.publication_repository.register_publications(paths, reservation=reservation)
                            self.publication_repository.check_physical_budget()
                result["inputs"].append({"exchange": exchange, "market_type": market, "symbol": symbol,
                                         "interval": interval, "source_revision": manifest.catalog_epoch})
            else:
                count = sum(c["receipt"]["rows"] for c in fragments)
                if count > 200_000:
                    raise PreparationError("STRATEGY_INPUT_LIMIT", "Strategy BAR input exceeds 200000 rows")
                rows_by_time = {row["open_time"]: row for c in fragments for row in self.read(c)}
                rows = [{**rows_by_time[key], "open_time_ms": key,
                         "close_time_ms": rows_by_time[key]["close_time"], "is_closed": True}
                        for key in sorted(rows_by_time)]
                context = fingerprint([{"key": c["key"], "selection": c["requirement"]} for c in fragments])
                with self._publication_space(rows) as reservation:
                    manifest = self.local_data.freeze_host_bars(
                        rows, dataset_id=f"local-{context[:32]}", name=f"{exchange} {symbol} {interval}",
                        exchange=exchange, market_type=market, symbol=symbol, interval=interval,
                        chart_context_hash=f"sha256:{context}")
                    self._record_dataset(manifest["dataset_id"], reservation=reservation)
                result["inputs"].append({"exchange": exchange, "market_type": market, "symbol": symbol,
                                         "interval": interval, "dataset_id": manifest["dataset_id"],
                                         "data_epoch": manifest["data_epoch"]})
        if request.consumer == "STRATEGY" and "chart_context" in request.intent:
            resolution = self.backtest_runtime.chart_context.resolve(request.intent["chart_context"])
            if resolution["status"] != "READY":
                raise PreparationError("CONTEXT_NOT_READY", "Prepared history does not meet strategy input requirements")
            result["resolution"] = resolution
            self._record_dataset(resolution["dataset_id"])
            if "preparation" in request.intent:
                resolution["preparation"] = request.intent["preparation"]
        if "native_strategy" in request.intent:
            from .native_plan import freeze_bindings
            result["native_inputs"] = freeze_bindings(self.backtest_runtime, request.intent["native_strategy"]["bindings"])
            for item in result["native_inputs"]:
                self._record_dataset(item["dataset_id"])
        if self.publication_repository is not None:
            self.publication_repository.check_physical_budget()
        return result
