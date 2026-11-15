"""Keep HTTP read-ahead separate from the canonical source acquisition."""
from bisect import bisect_right


def selected_fetch_rows(task, bars):
    windows = task.metadata.get('mixed_fetch_windows')
    if windows is None:
        return bars
    if not isinstance(windows, (list, tuple)) or not 1 <= len(windows) <= 4096:
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
