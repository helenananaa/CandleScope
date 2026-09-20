"""CandleScope chart timestamps are seconds; Pine runtime timestamps are milliseconds."""

def engine_bars(bars):
    return [{**bar, "time": int(bar["time"]) * 1000} for bar in bars]


def engine_magnifier(value):
    if not value:
        return None
    return {**value, "chartBars": [{**item, "bars": engine_bars(item["bars"])} for item in value["chartBars"]]}


def chart_records(rows):
    # Preserve the raw engine output; only the public chart record time fields use seconds.
    return [{key: value / 1000 if key in {"time", "entryTime", "exitTime"} and isinstance(value, (int, float)) else value
             for key, value in row.items()} for row in rows]
