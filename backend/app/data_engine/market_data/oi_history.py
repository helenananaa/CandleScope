"""Inclusive acquisition ranges and native Binance OI sampling evidence."""


def merge_ranges(ranges):
    result = []
    for item in sorted(ranges, key=lambda r: r["start_ms"]):
        item = dict(item)
        if result and item["start_ms"] <= result[-1]["end_ms"] + 1:
            result[-1]["end_ms"] = max(result[-1]["end_ms"], item["end_ms"])
        else:
            result.append(item)
    return result


def missing_ranges(start_ms, end_ms, covered):
    result = []
    cursor = start_ms
    for item in merge_ranges(covered):
        if item["end_ms"] < cursor:
            continue
        if item["start_ms"] > end_ms:
            break
        if cursor < item["start_ms"]:
            result.append({"start_ms": cursor, "end_ms": item["start_ms"] - 1})
        cursor = max(cursor, item["end_ms"] + 1)
    if cursor <= end_ms:
        result.append({"start_ms": cursor, "end_ms": end_ms})
    return result



def first_sample_at_or_after(timestamp_ms: int, step_ms: int) -> int:
    return (timestamp_ms + step_ms - 1) // step_ms * step_ms


def unsampled_prefixes(start_ms, end_ms, settled, step_ms):
    """The prefix before each next grid point requires no scheduled sample."""
    return [
        {"start_ms": gap["start_ms"], "end_ms": min(gap["end_ms"], first - 1)}
        for gap in missing_ranges(start_ms, end_ms, settled)
        if (first := first_sample_at_or_after(gap["start_ms"], step_ms)) > gap["start_ms"]
    ]


def verified_sample_ranges(timestamps, end_ms, step_ms):
    """Present on-grid samples prove their cells, bounded by the request."""
    return merge_ranges([
        {"start_ms": stamp, "end_ms": min(end_ms, stamp + step_ms - 1)}
        for stamp in timestamps if stamp % step_ms == 0
    ])
