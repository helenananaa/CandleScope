"""Read pinned local revisions for chart Pine, independently of the core."""

from bisect import bisect_right
from pathlib import Path

from pydantic import ValidationError

from app.backtest.errors import BacktestError
from app.backtest.native import timeframe
from app.backtest.native_contracts import RequestedNativeData
from app.data_engine.interval_policy import parse_interval_spec
from app.local_data.service import LocalDatasetError, LocalDatasetService
from app.market_dataset.adapters.local_bar import LocalBarSnapshotProvider
from app.market_dataset.models import DatasetRef
from app.market_dataset.snapshot import MarketDatasetError

MAX_REQUEST_BARS = 100_000


def normalize_contexts(values):
    if not isinstance(values, list) or len(values) > 16:
        raise BacktestError("PINE_REQUEST_DATA_INVALID", "Select at most 16 requested datasets.")
    contexts, keys = [], set()
    for value in values:
        try:
            item = RequestedNativeData.model_validate(value).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise BacktestError("PINE_REQUEST_DATA_INVALID", str(exc)) from exc
        key = item["symbol"], item["timeframe"]
        item["exchange"] = item["exchange"].lower()
        item["market_type"] = item["market_type"].lower()
        if key in keys or timeframe(item["interval"]) != item["timeframe"]:
            raise BacktestError("PINE_REQUEST_DATA_INVALID", "Duplicate context or mismatched timeframe.")
        keys.add(key)
        contexts.append(item)
    return contexts


def load_contexts(root, references):
    """Readonly snapshot admission, once at prepare/restore, never per bar."""
    references = normalize_contexts(references)
    if not references:
        return []
    if not root:
        raise BacktestError("PINE_REQUEST_DATA_REQUIRED", "The local dataset service is unavailable.")
    local = LocalDatasetService(Path(root))
    provider = LocalBarSnapshotProvider(local, max_rows=MAX_REQUEST_BARS, pinned_revisions=True)
    streams, total = [], 0
    try:
        for item in references:
            manifest = local.revision_details(item["dataset_id"], item["data_epoch"])["manifest"]
            ticker = item["symbol"].split(":")[-1]
            if item["exchange"].lower() == "binance" and item["market_type"] in {"usdm", "futures", "swap"}:
                ticker = ticker.removesuffix(".P")
            if ticker != manifest["symbol"]:
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Requested symbol differs from its frozen dataset.")
            venue, separator, _ = item["symbol"].partition(":")
            if separator and venue.lower() != item["exchange"].lower():
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Requested symbol and exchange differ.")
            for field in ("exchange", "market_type"):
                if manifest.get(field) and str(manifest[field]).lower() != str(item[field]).lower():
                    raise BacktestError("DATA_SNAPSHOT_MISMATCH", f"Requested {field} differs from dataset provenance.")
            ref = DatasetRef(dataset_id=item["dataset_id"], data_epoch=item["data_epoch"], snapshot_hash=item["snapshot_hash"],
                venue=item["exchange"], market_type=item["market_type"], symbol=manifest["symbol"],
                start_time_ms=item["start_time_ms"], end_time_ms=item["end_time_ms"], roles=("BARS",),
                interval=item["interval"], calendar_id="UTC_FIXED", source="local_immutable", retention_policy="user_local")
            snapshot = provider.open(ref)
            try:
                bars, closes = [], []
                interval = parse_interval_spec(item["interval"])
                for event in snapshot.events:
                    row = event.payload
                    opened, closed = int(row["open_time_ms"]), int(row["close_time_ms"])
                    if (opened < item["start_time_ms"] or closed > item["end_time_ms"]
                            or closed != interval.next_ms(opened) - 1
                            or (bars and not interval.is_successor(bars[-1]["time"] * 1000, opened))):
                        raise BacktestError("DATA_QUALITY_FAILED", "Requested data needs complete consecutive confirmed bars.")
                    if row["volume"] is None:
                        raise BacktestError("DATA_QUALITY_FAILED", "Requested Pine datasets require volume observations.")
                    bars.append({"time": opened // 1000,
                        **{name: float(row[name]) for name in ("open", "high", "low", "close", "volume")}})
                    closes.append(closed)
                    total += 1
                    if total > MAX_REQUEST_BARS:
                        raise BacktestError("BUDGET_EXCEEDED", "Requested datasets exceed 100000 combined bars.")
                if not bars:
                    raise BacktestError("DATA_QUALITY_FAILED", "Requested snapshot contains no bars.")
                streams.append({"symbol": item["symbol"], "timeframe": item["timeframe"], "bars": bars, "closes": closes,
                    **({"metadata": item["metadata"]} if item.get("metadata") else {})})
            finally:
                snapshot.close()
    except (LocalDatasetError, MarketDatasetError) as exc:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", str(exc)) from exc
    return streams


def visible_contexts(streams, boundary_ms):
    return [{"symbol": stream["symbol"], "timeframe": stream["timeframe"],
        "bars": stream["bars"][:bisect_right(stream["closes"], boundary_ms)],
        **({"metadata": stream["metadata"]} if stream.get("metadata") else {})} for stream in streams]
