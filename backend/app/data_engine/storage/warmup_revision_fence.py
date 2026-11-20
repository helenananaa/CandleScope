"""Use bounded D126 change receipts for fixed-grid subscription warmup writes."""
from bisect import bisect_left
from dataclasses import dataclass, field

from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec

from .derived_history_fence import check_deletions
from .native_history_fence import MAX_SLOTS, MAX_WINDOWS
from .revisions import (
    IDENTITY_COLUMNS,
    BLOCK_CHANGE_WINDOW,
    StaleAcquisition,
    block_change_receipts,
    current_revision,
    series_change,
    series_range_spans,
    series_values,
    span_overlaps_half_open,
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
        changed = [
            dependency for dependency in dependencies
            if (change := series_change(conn, dependency)) is not None and change["revision"] > base
        ]
        if changed:
            receipts = block_change_receipts(conn, base, head)
            if receipts:
                changed_set = set(changed)
                for receipt in receipts:
                    if tuple(receipt[name] for name in IDENTITY_COLUMNS) not in changed_set:
                        continue
                    if any(before < receipt["revision"] <= after for before, after in self.owned):
                        continue
                    i = bisect_left(opens, receipt["start_ms"] - width + 1)
                    if i < len(opens) and opens[i] <= receipt["end_ms"]:
                        raise StaleAcquisition("warmup inputs or target changed during acquisition", details={
                            'reason': 'warmup_overlapping_change', 'acquisition_revision': scope.revision,
                            'base_revision': base, 'head_revision': head, 'change_revision': receipt['revision'],
                            'change_start_ms': receipt['start_ms'], 'change_end_ms': receipt['end_ms'],
                            'start_ms': opens[0], 'end_ms': opens[-1]})
            else:
                for dependency in changed:
                    spans = series_range_spans(conn, dependency, base, head)
                    if spans is None:
                        raise StaleAcquisition("warmup change receipts do not cover the acquisition", details={
                            'reason': 'warmup_receipt_suffix_unavailable', 'acquisition_revision': scope.revision,
                            'base_revision': base, 'head_revision': head, 'receipt_limit': BLOCK_CHANGE_WINDOW,
                            'start_ms': opens[0], 'end_ms': opens[-1], 'owned_commits': len(self.owned)})
                    for span in spans:
                        first_rev, last_rev = int(span["first_revision"]), int(span["last_revision"])
                        if any(before < first_rev and last_rev <= after for before, after in self.owned):
                            continue
                        lo, hi, step = int(span["start_ms"]), int(span["end_ms"]), int(span["step_ms"])
                        if step <= width:
                            i = bisect_left(opens, lo - width + 1)
                            overlapped = i < len(opens) and opens[i] <= hi
                        else:
                            overlapped = any(span_overlaps_half_open(span, op, op + width) for op in opens)
                        if overlapped:
                            raise StaleAcquisition("warmup inputs or target changed during acquisition", details={
                                'reason': 'warmup_overlapping_change', 'acquisition_revision': scope.revision,
                                'base_revision': base, 'head_revision': head, 'change_revision': last_rev,
                                'change_start_ms': lo, 'change_end_ms': hi,
                                'start_ms': opens[0], 'end_ms': opens[-1]})
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
