"""Keep HTTP read-ahead separate from the canonical source acquisition."""
from bisect import bisect_right
from dataclasses import replace
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.series_identity import identity_from_metadata


def selected_fetch_rows(task, bars):
    windows = task.metadata.get('mixed_fetch_windows')
    if windows is None:
        return bars
    if not isinstance(windows, (list, tuple)) or not 0 <= len(windows) <= 4096:
        raise ValueError('invalid mixed fetch windows')
    previous = None
    starts, ends = [], []
    for first, last in windows:
        if (type(first) is not int or type(last) is not int
                or not task.start_ms <= first <= last <= task.end_ms
                or previous is not None and first <= previous):
            raise ValueError('invalid mixed fetch window range/order')
        starts.append(first)
        ends.append(last)
        previous = last
    return [bar for bar in bars if (index := bisect_right(starts, bar.open_time)-1) >= 0
            and bar.open_time <= ends[index]]

def coalesce_mixed_fetches(tasks, *, page_size, row_budget):
    """Bounded read-ahead across holes on one qualified canonical source grid.

    Only the declared exact source windows reach the canonical writer. Limit
    total fetched slots, including discarded read-ahead rows, to the existing
    mixed source budget.
    """
    total = sum(task.estimated_bars for task in tasks)
    groups = {}
    for task in tasks:
        key = (task.exchange, task.market_type, task.symbol, task.interval,
               task.metadata.get("history_composition_contract"), task.metadata.get("custom_interval"),
               repr(identity_from_metadata(task.exchange, task.metadata)))
        groups.setdefault(key, []).append(task)
    output = []
    for group in groups.values():
        group.sort(key=lambda task: task.start_ms)
        current = group[0]
        width = parse_interval_spec(current.interval).nominal_ms
        for task in group[1:]:
            end = max(current.end_ms, task.end_ms)
            slots = (end - current.start_ms) // width + 1
            extra = slots - current.estimated_bars - task.estimated_bars
            if (current.metadata.get("history_composition_contract") is not None
                    and 0 <= extra and slots <= page_size and total + extra <= row_budget):
                total += extra
                current = replace(current, end_ms=end, estimated_bars=slots,
                    metadata={**current.metadata, "mixed_fetch_read_ahead": True,
                              "ledger_range": {"start_ms": current.start_ms, "end_ms": end},
                              "mixed_fetch_windows": [*current.metadata.get("mixed_fetch_windows",
                                  [(current.start_ms, current.end_ms)]), (task.start_ms, task.end_ms)]})
            else:
                output.append(current)
                current = task
        output.append(current)
    return output
