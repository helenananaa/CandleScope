"""Resolve captured chart references through their existing backend owners.

No browser OHLCV, live fallback or financial execution belongs to this adapter.
The DataManager synthetic service owns calculation, sharing and lease lifetime.
"""
from __future__ import annotations

import json

from app.backtest.errors import BacktestError
from app.core.executors import run_storage
from app.data_engine.data_manager.replay import optional_replay_service_from_state
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.synthetic_series.core import MAX_SOURCE_ROWS, SyntheticError
from app.local_data.service import LocalDatasetError
from app.replay.training.errors import TrainingRunError
from app.replay.training.synthetic_source import read_synthetic_source
from app.research_data.access import access_from_request


def _run_rows(runtime, body):
    origin = body.origin
    record = runtime.service.get_run(origin.run_id)
    if origin.kind == "RUN_RESULT":
        report = runtime.service.get_report(origin.run_id)
        if (record["config_hash"] != origin.config_hash
                or report.get("hashes", {}).get("report") != origin.report_hash):
            raise SyntheticError("saved result identity changed")
    elif any(record.get(field) != getattr(origin, field)
            for field in ("dataset_id", "data_epoch", "snapshot_hash")):
        raise SyntheticError("frozen snapshot identity changed")
    chart = runtime.chart_data(origin.run_id)
    config = json.loads(record["config_json"])
    if (chart["chart_hash"] != origin.chart_hash or chart["symbol"] != body.source.symbol
            or chart["interval"] != body.source.interval
            or str(config.get("exchange") or "binance") != body.source.exchange
            or str(config.get("market_type") or "usdm") != body.source.market_type):
        raise SyntheticError("saved chart source identity changed")
    rows = [{**row, "is_closed": True} for row in chart["bars"]
            if body.anchor <= row["time"] <= body.through]
    return rows, chart["chart_hash"]


def _local_rows(service, body):
    interval = parse_interval_spec(body.source.interval)
    if interval is None:
        raise SyntheticError("invalid pinned interval")
    end = interval.next_ms(body.through * 1000) - 1
    manifest, selected = service.load_pinned_display_bars(body.origin.dataset_id,
        data_epoch=body.origin.data_epoch, interval=body.source.interval,
        through_ms=end, limit=MAX_SOURCE_ROWS + 1)
    if manifest["symbol"] != body.source.symbol:
        raise SyntheticError("pinned dataset symbol changed")
    rows = [{"time": int(row["open_time_ms"]) // 1000,
             **{field: row[field] for field in ("open", "high", "low", "close")},
             **({"volume": row["volume"]} if row.get("volume") is not None else {}),
             "is_closed": True} for row in selected
            if body.anchor * 1000 <= row["open_time_ms"] <= body.through * 1000]
    return rows, body.origin.data_epoch


def pinned_seed_loader(scope, body):
    if body.origin is None:
        return None
    # Validate every consumer before shared-instance lookup, not only the first
    # consumer that happens to prepare the immutable seed.
    if body.origin.kind in {"LOCAL_DATASET", "CAPTURED_WINDOW"} and not access_from_request(scope).allowed:
        raise SyntheticError("local research source requires trusted local access")

    async def load():
        if body.through is None:
            raise SyntheticError("pinned source requires an explicit right boundary")
        state = scope.app.state
        core = getattr(state, "data_manager_core", None)
        try:
            if body.origin.kind == "CAPTURED_WINDOW":
                manager = core if core is not None else getattr(state, "data_manager", None)
                if manager is None:
                    raise SyntheticError("captured source owner unavailable")
                return await manager.synthetic.captured_seed(body.definition())
            if body.origin.kind == "REPLAY":
                replay = optional_replay_service_from_state(state)
                training = getattr(replay, "training", None)
                if training is None:
                    raise SyntheticError("replay source unavailable")
                return await read_synthetic_source(training, body)
            if body.origin.kind == "LOCAL_DATASET":
                local = getattr(state, "local_data_service", None)
                if local is None:
                    raise SyntheticError("pinned dataset owner unavailable")
                return await run_storage(_local_rows, local, body)
            owner = getattr(core, "strategy", None) if core is not None else None
            runtime = getattr(owner, "runtime", None) if core is not None else getattr(state, "backtest_runtime", None)
            if runtime is None:
                raise SyntheticError("saved chart owner unavailable")
            if owner is not None:
                owner.control_plane()  # Reject a closed composition root.
            return await run_storage(_run_rows, runtime, body)
        except (BacktestError, LocalDatasetError, TrainingRunError) as error:
            raise SyntheticError(str(error)) from error

    return load
