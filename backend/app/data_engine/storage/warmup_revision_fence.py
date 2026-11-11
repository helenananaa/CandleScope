"""Use bounded D126 change receipts for fixed-grid subscription warmup writes."""
from bisect import bisect_left
from dataclasses import dataclass, field

from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec

from .derived_history_fence import check_deletions
from .native_history_fence import MAX_SLOTS, MAX_WINDOWS
from .revisions import (
    IDENTITY_COLUMNS,
    StaleAcquisition,
    block_change_receipts,
    current_revision,
    series_change,
    series_values,
)


@dataclass
class WarmupView:
    source: tuple
    target: tuple
    source_ms: int
    target_ms: int
    windows: list[tuple[int, int]]
    owned: list[tuple[int, int]] = field(default_factory=list)

    def check_write(self, conn, scope, key, rows, source) -> int | None:
        """Return the pre-write head only when the whole batch has a scoped proof."""
        if key == self.source and source == "backfill":
            width, dependencies = self.source_ms, (self.source,)
        elif key == self.target and source == "backfill_aggregated":
            width, dependencies = self.target_ms, (self.source, self.target)
        else:
            return None
        if not rows or len(rows) > MAX_SLOTS:
            return None

        opens = sorted(row["open_time"] for row in rows)
        if any(row["open_time"] % width or row["close_time"] != row["open_time"] + width - 1
               or not any(start <= row["open_time"] and row["close_time"] <= end
                          for start, end in self.windows) for row in rows):
            return None
        check_deletions(conn, scope, self.source, self.target)

        # SQLite serializes the writer. Receipts from our previously committed
        # transactions belong to this acquisition, including their triggers.
        base = scope.revision
        if self.owned and self.owned[0][0] == base:
            base = self.owned[0][1]
        head = current_revision(conn)
        changed = {
            dependency for dependency in dependencies
            if (change := series_change(conn, dependency)) is not None and change["revision"] > base
        }
        if changed:
            receipts = block_change_receipts(conn, base, head)
            if not receipts:
                raise StaleAcquisition("warmup change receipts do not cover the acquisition")
            for receipt in receipts:
                if tuple(receipt[name] for name in IDENTITY_COLUMNS) not in changed:
                    continue
                if any(before < receipt["revision"] <= after for before, after in self.owned):
                    continue
                i = bisect_left(opens, receipt["start_ms"] - width + 1)
                if i < len(opens) and opens[i] <= receipt["end_ms"]:
                    raise StaleAcquisition("warmup inputs or target changed during acquisition")
        return head

    def accept(self, before: int, after: int) -> None:
        if after == before:
            return
        if self.owned and self.owned[-1][1] == before:
            self.owned[-1] = (self.owned[-1][0], after)
        else:
            self.owned.append((before, after))


def make_warmup_view(windows) -> WarmupView | None:
    if not windows or len(windows) > MAX_WINDOWS:
        return None
    first = windows[0]
    target = parse_interval_spec(first.metadata.get("custom_interval"))
    source = parse_interval_spec(first.interval)
    if (source is None or target is None or source.alignment is not IntervalAlignment.FIXED_EPOCH
            or target.alignment is not IntervalAlignment.FIXED_EPOCH or source.phase_ms or target.phase_ms
            or not 60_000 <= source.nominal_ms < target.nominal_ms
            or target.nominal_ms % source.nominal_ms):
        return None
    step, width = source.nominal_ms, target.nominal_ms
    identity = (first.exchange, first.market_type, first.symbol, source.canonical, target.canonical)
    spans = []
    slots = 0
    for task in sorted(windows, key=lambda window: window.start_ms):
        if (task.exchange, task.market_type, task.symbol, task.interval,
            task.metadata.get("custom_interval")) != identity:
            return None
        start, end = task.start_ms, task.end_ms
        if start > end or start % step or end % step:
            return None
        slots += (end - start) // step + 1
        if slots > MAX_SLOTS:
            return None
        if spans and start <= spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end + step - 1))
        else:
            spans.append((start, end + step - 1))
    if any(start % width or (end + 1) % width for start, end in spans):
        return None
    return WarmupView(
        series_values(first.symbol, source.canonical, first.exchange, first.market_type),
        series_values(first.symbol, target.canonical, first.exchange, first.market_type),
        step, width, spans,
    )
