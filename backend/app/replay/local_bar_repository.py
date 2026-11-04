"""Read-only bridge from the existing immutable local library to BAR replay.

The dataset ID occupies the venue namespace, so two imports with the same
symbol cannot resolve to each other's rows. Epochs use the library's existing
revision contract. No online repository, asset metadata or synthetic trade tape
is supplied by this adapter.
"""
from __future__ import annotations

from app.data_engine.interval_policy import parse_interval_ms
from app.local_data.service import LocalDatasetError, LocalDatasetService

from .catalog import ReplaySeriesIdentity
from .errors import ReplayDomainError, ReplayErrorCode

LOCAL_BAR_MARKET = "local_bar"


def _unavailable(reason: str, message: str) -> ReplayDomainError:
    return ReplayDomainError(ReplayErrorCode.DATASET_INCOMPLETE, message,
                             details={"reason": reason, "fallback_applied": False})


class LocalReplayBarRepository:
    def __init__(self, service: LocalDatasetService, *, max_rows: int) -> None:
        self.service = service
        self.max_rows = max_rows

    def list_series(self, custom_only=False, exchange=None, market_type=None):
        result = []
        for manifest in self.service.list_datasets():
            if exchange is not None and manifest["dataset_id"] != exchange:
                continue
            if market_type is not None and market_type != LOCAL_BAR_MARKET:
                continue
            result.append({"exchange": manifest["dataset_id"], "market_type": LOCAL_BAR_MARKET,
                           "symbol": manifest["symbol"], "interval": manifest["interval"],
                           "earliest_open_time": manifest["first_open_ms"],
                           "latest_open_time": manifest["last_open_ms"], "total_count": manifest["rows"],
                           "source_revision": manifest["data_epoch"]})
        return result

    def native_intervals(self, identity: ReplaySeriesIdentity):
        manifest = self._manifest(identity.symbol, exchange=identity.exchange, market_type=identity.market_type, check_contract=False)
        interval = str(manifest["interval"])
        return (interval,) if parse_interval_ms(interval) is not None else ()

    def _manifest(self, symbol, *, exchange, market_type, revision=None, check_contract=True):
        if market_type != LOCAL_BAR_MARKET or not isinstance(exchange, str) or not exchange.startswith("local-"):
            raise _unavailable("local_dataset_identity_invalid", "Select an imported BAR dataset; online fallback is disabled")
        try:
            manifest = (self.service.get_manifest(exchange) if revision is None
                        else self.service.revision_details(exchange, revision)["manifest"])
        except LocalDatasetError as exc:
            raise _unavailable("local_dataset_unavailable", str(exc)) from exc
        if manifest["symbol"] != symbol or manifest["dataset_id"] != exchange:
            raise _unavailable("local_dataset_identity_invalid", "Imported BAR identity does not match")
        if check_contract and (not manifest.get("volume_available", True) or not manifest.get("all_rows_final", False)
                or manifest.get("rows", self.max_rows + 1) > self.max_rows):
            raise _unavailable("local_bar_contract_unsupported", "Replay requires closed BAR rows with volume within its row budget")
        return manifest

    def _read(self, revision, symbol, interval, *, exchange, market_type):
        manifest = self._manifest(symbol, exchange=exchange, market_type=market_type, revision=revision)
        if interval != manifest["interval"] or parse_interval_ms(interval) is None:
            raise _unavailable("local_bar_interval_unsupported", "Use the imported fixed BAR interval as the replay source")
        try:
            actual, rows = self.service.load_canonical_bars(exchange, data_epoch=manifest["data_epoch"],
                max_rows=self.max_rows, interval=interval, pinned_revision=True)
        except LocalDatasetError as exc:
            raise _unavailable("local_dataset_unavailable", str(exc)) from exc
        if actual["symbol"] != symbol or actual["data_epoch"] != manifest["data_epoch"]:
            raise _unavailable("local_dataset_revision_changed", "Imported BAR revision changed while reading")
        if not rows:
            raise _unavailable("local_dataset_unavailable", "Imported BAR revision is empty")
        # Preserve decimal strings; translate field names without shifting open/close times.
        return actual, [{**row, "open_time": row["open_time_ms"], "close_time": row["close_time_ms"],
                         "source": "local_dataset"} for row in rows]

    def get_bounds(self, symbol, interval, exchange=None, market_type=None):
        return self.get_bounds_at_revision(None, symbol, interval, exchange=exchange, market_type=market_type)

    def get_bounds_at_revision(self, source_revision, symbol, interval, exchange=None, market_type=None):
        manifest, rows = self._read(source_revision, symbol, interval, exchange=exchange, market_type=market_type)
        return {"earliest_open_time": manifest["first_open_ms"], "latest_open_time": manifest["last_open_ms"],
                "total_count": len(rows), "source_revision": manifest["data_epoch"]}

    def query_bars(self, symbol, interval, start_ms=None, end_ms=None, limit=None, order="ASC", exchange=None, market_type=None):
        return self.query_bars_at_revision(None, symbol, interval, start_ms=start_ms, end_ms=end_ms,
            limit=limit, order=order, exchange=exchange, market_type=market_type)

    def query_bars_at_revision(self, source_revision, symbol, interval, start_ms=None, end_ms=None,
                               limit=None, order="ASC", exchange=None, market_type=None):
        if order not in {"ASC", "DESC"} or (limit is not None and (type(limit) is not int or limit < 1)):
            raise ValueError("Invalid imported BAR query order/limit")
        _, rows = self._read(source_revision, symbol, interval, exchange=exchange, market_type=market_type)
        rows = [row for row in rows if (start_ms is None or row["open_time_ms"] >= start_ms)
                and (end_ms is None or row["open_time_ms"] <= end_ms)]
        if order == "DESC":
            rows.reverse()
        return rows if limit is None else rows[:limit]

    def scan_gaps(self, symbol, interval, start_ms=None, end_ms=None, exchange=None, market_type=None,
                  limit=50_000, calendar=None):
        return self.scan_gaps_at_revision(None, symbol, interval, start_ms=start_ms, end_ms=end_ms,
            exchange=exchange, market_type=market_type, limit=limit, calendar=calendar)

    def scan_gaps_at_revision(self, source_revision, symbol, interval, start_ms=None, end_ms=None,
                              exchange=None, market_type=None, limit=50_000, calendar=None):
        _, all_rows = self._read(source_revision, symbol, interval, exchange=exchange, market_type=market_type)
        step = parse_interval_ms(interval)
        first = all_rows[0]["open_time_ms"] if start_ms is None else start_ms
        last = all_rows[-1]["open_time_ms"] if end_ms is None else end_ms
        rows = [row for row in all_rows if first <= row["open_time_ms"] <= last]
        if len(rows) > limit:
            return {"gaps": [], "scanned_bars": limit, "truncated": True, "calendar_id": "crypto.24x7.utc"}
        gaps = []
        expected = first
        for row in rows:
            current = row["open_time_ms"]
            if current > expected:
                gaps.append({"start_ms": expected, "end_ms": current - step,
                             "missing_bars": (current - expected) // step, "reason": "imported_bar_gap"})
            expected = current + step
        if expected <= last:
            gaps.append({"start_ms": expected, "end_ms": last,
                         "missing_bars": (last - expected) // step + 1, "reason": "imported_bar_gap"})
        return {"gaps": gaps, "scanned_bars": len(rows), "truncated": False, "calendar_id": "crypto.24x7.utc"}
