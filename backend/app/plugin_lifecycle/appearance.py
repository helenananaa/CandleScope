"""Data-only workspace appearance contributions."""

from __future__ import annotations

import re

from candlescope_plugin_sdk.platform_v2 import JsonLimits, loads_strict

MAX_APPEARANCE_BYTES = 64 * 1024
APPEARANCE_KINDS = ("theme", "layout")

PAGE_SLOTS = {"topBar", "intervalSelector", "workspace", "featureSurfaces", "statusBar"}
WORKSPACE_SLOTS = {"toolbar", "chart", "bottomPanel", "rightRail", "exportOverlay"}
COLORS = {
    "bg-primary",
    "bg-secondary",
    "bg-tertiary",
    "bg-hover",
    "border-color",
    "text-primary",
    "text-secondary",
    "text-muted",
    "accent-blue",
    "accent-purple",
    "accent-cyan",
    "candle-up",
    "candle-down",
}


def validate_theme(theme):
    if (
        not isinstance(theme, dict)
        or set(theme) != {"base", "tokens"}
        or theme["base"] not in ("dark", "light")
    ):
        raise ValueError("Invalid theme")
    tokens = theme["tokens"]
    if (
        not isinstance(tokens, dict)
        or not tokens
        or tokens.keys()
        - COLORS
        - {
            "radius-sm",
            "radius-md",
            "font-sans",
            "font-mono",
            "control-height",
            "panel-gap",
            "panel-shadow",
        }
    ):
        raise ValueError("Unknown theme token")
    for key, value in tokens.items():
        if not isinstance(value, str) or len(value) > 200:
            raise ValueError("Invalid theme token")
        if key in COLORS and not re.fullmatch(r"#[a-fA-F0-9]{6}", value):
            raise ValueError("Theme colors must be six-digit hex values")
        if key in {
            "radius-sm",
            "radius-md",
            "control-height",
            "panel-gap",
        } and not re.fullmatch(r"(?:[0-9]|[1-6][0-9])px", value):
            raise ValueError("Invalid theme dimension")
        if key.startswith("font-") and not re.fullmatch(r"[A-Za-z0-9 ,'-]+", value):
            raise ValueError("Invalid theme font")
        if key == "panel-shadow" and not re.fullmatch(
            r"(?:none|[0-9px .-]+ #[a-fA-F0-9]{6})", value
        ):
            raise ValueError("Invalid theme shadow")
    return theme


def validate_layout(layout):
    if not isinstance(layout, dict) or set(layout) != {"page", "workspace"}:
        raise ValueError("Layout requires both host slot orders")
    for key, slots in (("page", PAGE_SLOTS), ("workspace", WORKSPACE_SLOTS)):
        order = layout[key]
        if (
            not isinstance(order, list)
            or not all(isinstance(item, str) for item in order)
            or len(order) != len(slots)
            or set(order) != slots
        ):
            raise ValueError("Layout must preserve each host slot exactly once")
    return layout


def appearance_kind(entry):
    return entry.id if entry.kind == "data" and entry.id in APPEARANCE_KINDS else None


def parse_appearance(kind, raw, trust):
    if kind == "layout" and trust != "full-trust":
        raise ValueError("Workspace layout requires full-trust")
    data = loads_strict(raw, limits=JsonLimits(max_message_bytes=MAX_APPEARANCE_BYTES))
    if (
        not isinstance(data, dict)
        or data.pop("schema", None) != f"candlescope.{kind}/1"
    ):
        raise ValueError(f"Invalid unified {kind} data schema")
    return validate_theme(data) if kind == "theme" else validate_layout(data)
