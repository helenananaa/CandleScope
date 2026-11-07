"""Inclusive acquisition ranges; never infer OI presence from a time grid."""


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
