"""Exact OHLCV summaries without the account range's ordered price extrema."""

from decimal import Decimal, localcontext
from itertools import pairwise
from operator import itemgetter

_COLUMNS = tuple(itemgetter(index) for index in range(12))


def merge_display(left, right, base_ms):
    if left is None:
        return right
    if right is None:
        return left
    with localcontext() as context:
        context.prec = 1000  # same finite float64 archive domain as the index
        sums = tuple(
            None if left[i] is None or right[i] is None else left[i] + right[i]
            for i in range(4, 9)
        )
        return (
            left[0],
            max(left[1], right[1]),
            min(left[2], right[2]),
            right[3],
            *sums,
            left[9] + right[9],
            left[10],
            right[11],
            left[12] and right[12] and left[11] + base_ms == right[10],
        )


def summarize_display(rows, base_ms, *, include_auxiliary=True):
    if not rows:
        return None
    # A partial block contains at most 256 already-validated rows. Sum each
    # column once instead of constructing and merging a full valuation tuple
    # per minute. Optional columns are unknown if any source row is unknown.
    with localcontext() as context:
        context.prec = 1000
        sums = []
        for index in range(6, 11 if include_auxiliary else 7):
            # These immutable index columns contain strings/integers/None.
            # Keep column extraction and Decimal conversion in builtins: the
            # small per-bucket generators otherwise execute once per source
            # minute, per column, for every chart's complete indicator prefix.
            values = tuple(map(_COLUMNS[index], rows))
            if None in values:
                sums.append(None)
            elif index == 8:
                sums.append(sum(values))
            else:
                sums.append(sum(map(Decimal, values), Decimal(0)))
        if not include_auxiliary:
            sums.extend((None,) * 4)
        return (
            Decimal(rows[0][2]),
            max(map(Decimal, map(_COLUMNS[3], rows))),
            min(map(Decimal, map(_COLUMNS[4], rows))),
            Decimal(rows[-1][5]),
            *sums,
            len(rows),
            rows[0][0],
            rows[-1][0],
            all(a[0] + base_ms == b[0] for a, b in pairwise(rows)),
        )
