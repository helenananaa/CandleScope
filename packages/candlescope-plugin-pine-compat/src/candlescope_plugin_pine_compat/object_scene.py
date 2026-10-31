"""Bound native object snapshots for a chart-coordinate renderer."""

KINDS = ("lines", "labels", "boxes", "polylines", "lineFills", "tables")


def object_scenes(raw, times, pane, settings=None):
    if not times:
        return []
    if sum(len(raw.get(kind) or []) for kind in KINDS) > 3000:
        raise ValueError("PINE_HOST_DRAWING_LIMIT: too many drawing objects")
    objects = []
    cells = points = 0
    for kind in KINDS:
        for item in raw.get(kind) or []:
            if not isinstance(item, dict) or not isinstance(item.get("snapshots"), list):
                raise TypeError("PINE_HOST_DRAWING_INVALID: native snapshots are required")
            visible = [
                state
                for state in item.get("snapshots", [])
                if state.get("barIndex", len(times)) < len(times)
            ]
            if not visible or not visible[-1].get("exists"):
                continue
            row = {
                key: value for key, value in {**item, **visible[-1]}.items() if key != "snapshots"
            }
            cells += len(row.get("cells") or [])
            points += len(row.get("points") or [])
            if kind == "tables" and row.get("rows", 0) * row.get("columns", 0) > 10000:
                raise ValueError("PINE_HOST_DRAWING_LIMIT: table exceeds 10000 cells")
            if cells > 10000 or points > 100000:
                raise ValueError("PINE_HOST_DRAWING_LIMIT: drawing geometry exceeds its budget")
            objects.append({"kind": kind.lower(), "row": row})
    for family in ("plotChars", "plotArrows", "plotBars", "plotCandles"):
        for item in raw.get(family) or []:
            style = settings(item) if settings else {"paneVisible": True}
            if not style["paneVisible"]:
                continue
            row = {**item, "family": family}
            if family == "plotArrows":
                row["arrowMaximum"] = max(
                    (
                        abs(v)
                        for v in item.get("values", [])
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    ),
                    default=1,
                )
            objects.append({"kind": "plotseries", "row": row})
    plots = {item["id"]: item for item in raw.get("plots") or []}
    hlines = {item["id"]: item for item in raw.get("hlines") or []}
    for item in raw.get("fills") or []:
        if not item.get("gradient"):
            continue
        style = settings(item) if settings else {"paneVisible": True}
        if not style["paneVisible"]:
            continue

        def values(endpoint, is_hline):
            if is_hline:
                return [hlines[endpoint]["price"]] * len(times)
            plot = plots[endpoint]
            offset = plot.get("offset", 0)
            visible = plot.get("showLast")
            data = [None] * len(times)
            for i, value in enumerate(plot.get("values") or []):
                if 0 <= i + offset < len(times) and (visible is None or i >= len(times) - visible):
                    data[i + offset] = value
            return data

        row = {
            **item,
            "firstValues": values(item["firstId"], item.get("firstIsHLine", False)),
            "secondValues": values(item["secondId"], item.get("secondIsHLine", False)),
        }
        objects.append({"kind": "gradientfills", "row": row})
    samples = sum(
        len(value) for item in objects for value in item["row"].values() if isinstance(value, list)
    )
    if samples > 5_000_000 or len(objects) > 3000:
        raise ValueError("PINE_HOST_DRAWING_LIMIT: native rendering output exceeds its budget")
    if not objects and not any(raw.get(kind) for kind in KINDS):
        return []
    # Preserve an empty scene so deletions replace the previous authoritative scene.
    line_panes = {
        item["row"]["id"]: ("main" if item["row"].get("forceOverlay") else pane)
        for item in objects
        if item["kind"] == "lines"
    }
    for item in objects:
        if item["kind"] == "linefills" and line_panes.get(item["row"].get("line1")) == "main":
            item["row"]["forceOverlay"] = True
    panes = {pane} | {"main" for item in objects if item["row"].get("forceOverlay")}
    return [
        {
            "id": "pine-native-objects-" + target,
            "pane": target,
            "asOf": times[-1],
            "times": times,
            "objects": [
                item
                for item in objects
                if ("main" if item["row"].get("forceOverlay") else pane) == target
            ],
        }
        for target in sorted(panes)
    ]
