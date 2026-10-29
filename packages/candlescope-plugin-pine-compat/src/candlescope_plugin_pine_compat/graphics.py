"""Current native drawings, carried on a transparent pane anchor in Render IR."""
from candlescope_plugin_sdk import LineSeries, LinePoint

KINDS = ("lines", "labels", "boxes", "polylines", "lineFills", "tables")


def normalize(row):
    return {key.replace("_", "").lower(): value for key, value in row.items()}


def scene_series(raw, times, bars, pane, render_settings, required=False):
    if not times:
        return ()
    objects = []
    for kind in KINDS:
        for item in raw.get(kind) or []:
            snapshots = [row for row in item.get("snapshots", []) if row.get("barIndex", len(times)) < len(times)]
            if not snapshots or snapshots[-1].get("exists") is False:
                continue
            row = normalize({**item, **snapshots[-1]})
            row.pop("snapshots", None)
            for key in ("cells", "mergedcells", "points"):
                if key in row:
                    row[key] = [normalize(value) for value in row[key]]
            objects.append({"kind": kind.lower(), "row": row})
    if len(objects) > 5000:
        raise ValueError("PINE_GRAPHICS_LIMIT: more than 5000 active drawing objects")
    plots = {key: raw.get(key, []) for key in ("plotChars", "plotArrows", "plotBars", "plotCandles")}
    gradients = [item for item in raw.get("fills", []) if item.get("gradient")]
    if not required and not objects and not any(plots.values()) and not gradients:
        return ()
    scenes = {}
    def target(item):
        settings = render_settings(item, base_pane=pane, fallback_title="Native graphics")
        if not settings["paneVisible"]:
            return None
        return scenes.setdefault(settings["pane"], {"schemaVersion": 1, "times": times,
            "objects": [], "plots": {}, "highs": [bar["high"] for bar in bars], "lows": [bar["low"] for bar in bars],
            "gradients": [], "endpoints": {"plots": raw.get("plots", []), "hlines": raw.get("hlines", [])}})
    target({})
    if required:
        target({"forceOverlay": True})
    for item in objects:
        destination = target({"forceOverlay": bool(item["row"].get("forceoverlay"))})
        destination["objects"].append(item)
    for kind, items in plots.items():
        for item in items:
            destination = target(item)
            if destination is not None:
                destination["plots"].setdefault(kind, []).append(item)
    for item in gradients:
        destination = target(item)
        if destination is not None:
            destination["gradients"].append(item)
    return tuple(LineSeries(id=f"pine-native-scene-{target_pane}", title="Pine drawings", pane=target_pane, series_type="line",
        points=tuple(LinePoint(time=t, value=bar["close"]) for t, bar in zip(times, bars)),
        style={"color": "rgba(0,0,0,0)", "lineWidth": 1, "nativeScene": scene}) for target_pane, scene in scenes.items())
