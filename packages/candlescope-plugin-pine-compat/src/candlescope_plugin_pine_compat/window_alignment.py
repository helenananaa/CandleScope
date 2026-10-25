"""Translate a calculation window back onto the host's frozen chart timeline."""


def calculation_skip(engine, source, bars, options, execution_times, raw, count):
    """Resolve the actual root window, which root-context requests can expand."""
    if not count or not bars:
        return 0
    lengths = [len(row[key]) for kind in ("plots", "plotChars", "plotShapes", "plotArrows", "plotBars", "plotCandles", "bgColors", "barColors")
               for row in raw.get(kind, []) for key in ("values", "opens", "colors") if isinstance(row.get(key), list) and row[key]]
    if lengths:
        return max(0, len(bars) - max(lengths))
    def indices(output):
        return [row["barIndex"] for kind in ("lines", "labels", "boxes", "polylines", "lineFills", "tables")
                for item in output.get(kind, []) for row in item.get("snapshots", [])] + [row["barIndex"] for row in output.get("alerts", [])]
    if not indices(raw):
        return max(0, len(bars) - count)
    # Object-only scripts expose no series length or public input-origin field.
    # Locate their first output in fixed-history forks; its execution index
    # identifies the origin without modifying the user's source or its call sites.
    settings = dict(options)
    libraries = settings.pop("library_sources", None)
    if execution_times is not None:
        settings["execution_times"] = execution_times
    history = engine.compile_script(source, library_sources=libraries).historical_session(bars, **settings)
    low, high = 1, len(bars)
    while low < high:
        middle = (low + high) // 2
        if indices(history.fork().advance(middle)):
            high = middle
        else:
            low = middle + 1
    first = indices(history.fork().advance(low))
    if not first:
        raise ValueError("PINE_WINDOW_ORIGIN_UNAVAILABLE: cannot align native drawing history")
    return max(0, low - 1 - min(first))


def align_output(output, skip):
    for kind in ("plots", "plotChars", "plotShapes", "plotArrows", "plotBars", "plotCandles", "bgColors", "barColors", "fills"):
        for item in output.get(kind, []):
            for key, values in item.items():
                if isinstance(values, list):
                    item[key] = [None] * skip + values
    for event in output.get("alerts", []):
        event["barIndex"] += skip
    for kind in ("lines", "labels", "boxes", "polylines", "lineFills", "tables"):
        for item in output.get(kind, []):
            for snapshot in item.get("snapshots", []):
                snapshot["barIndex"] += skip
                if snapshot.get("xloc", "xloc.bar_index").endswith("bar_index"):
                    for key in ("x", "x1", "x2", "left", "right"):
                        if isinstance(snapshot.get(key), (int, float)):
                            snapshot[key] += skip
                    for point in snapshot.get("points", []):
                        if isinstance(point.get("index"), (int, float)):
                            point["index"] += skip
