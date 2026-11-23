"""Frozen root ticker descriptors, separate from standard requested symbols."""

import json


def symbol(context, config):
    transform = config.get("transform")
    chart = {
        "heikin-ashi": "heikinashi",
        "line-break": "linebreak",
        "point-and-figure": "pointfigure",
    }.get(transform, transform)
    if chart not in {"heikinashi", "renko", "kagi", "linebreak", "pointfigure"}:
        raise ValueError("EXTERNAL_UNSUPPORTED: chart signal definition required")
    descriptor = dict(chart=chart, symbol=context["symbol"])
    if chart == "linebreak":
        descriptor["lines"] = config.get("number_of_lines", 3)
    elif chart != "heikinashi":
        descriptor.update(
            style="ATR" if config.get("mode") == "atr" else "Traditional",
            param=(
                config.get("atr_length", 14)
                if config.get("mode") == "atr"
                else (
                    config.get("reversal_amount", 3)
                    if chart == "kagi"
                    else config.get("box_size", 1)
                )
            ),
        )
        if chart == "pointfigure":
            descriptor.update(source="close", reversal=config.get("reversal_amount", 3))
    return json.dumps(descriptor, separators=(",", ":"))
