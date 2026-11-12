"""Resolve indicator inputs from the exact DataManager chart generation."""
from __future__ import annotations

import time
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.async_cleanup import finish_cleanup
from app.data_engine.synthetic_series.core import SyntheticError
from app.data_engine.interval_policy import parse_interval_spec
from .synthetic import SyntheticRequest, _service
from .synthetic_sources import pinned_seed_loader


class ChartIndicatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: SyntheticRequest
    seriesId: str = Field(min_length=1, max_length=64)
    generation: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=0, strict=True)


async def resolve_chart_indicator_input(scope, reference, context, submitted):
    """The browser selects ordered keys, never supplies authoritative prices."""
    if reference is None:
        return submitted, {}
    body = reference.request
    source = body.source
    if (source.exchange.lower(), source.market_type.lower(), source.symbol.upper(), source.interval) != (
        context.exchange.lower(), context.marketType.lower(), context.symbol.upper(), context.interval
    ):
        raise HTTPException(409, "Chart indicator market identity mismatch")
    lease = None
    try:
        lease = await _service(scope).attach(body.definition(), seed_loader=pinned_seed_loader(scope, body))
        instance = lease.instance
        async with instance.lock:
            if (instance.key, instance.generation, instance.revision, instance.status) != (
                reference.seriesId, reference.generation, reference.revision, "ready"
            ):
                raise SyntheticError("Chart indicator generation changed; retry with the displayed revision")
            output, raw = instance.kernel.output, instance.kernel.source
            ordinal = body.config.transform != "heikin-ashi"
            by_key = {index + 1 if ordinal else int(row["time"]): (index, row)
                for index, row in enumerate(output)}
            resolved, clocks, closed = [], [], []
            previous = None
            for item in submitted:
                key = item.get("time")
                if isinstance(key, bool) or not isinstance(key, int) or key not in by_key:
                    raise SyntheticError("Unknown chart indicator row key")
                index, row = by_key[key]
                if previous is not None and index != previous + 1:
                    raise SyntheticError("Chart indicator input must be a contiguous ordered window")
                previous = index
                clock = row["time"]["sourceTime"] if ordinal else row["time"]
                provisional = row.get("customValues", {}).get("chartProjection", {}).get("provisional", False)
                resolved.append({"time": key, **{name: float(row[name]) for name in ("open", "high", "low", "close")},
                    "volume": float(row.get("volume", 0)), "is_closed": not provisional})
                clocks.append(int(clock))
                closed.append(not provisional)
            if not resolved:
                raise SyntheticError("Chart indicator input is empty")
            origin = body.origin
            if origin and origin.kind == "REPLAY":
                cutoff = origin.revealed_boundary_ms
            elif origin and origin.kind == "CAPTURED_WINDOW":
                cutoff = origin.cutoff_ms
            elif origin:
                last = raw[-1]
                start = int(last["time"]) * 1000
                cutoff = parse_interval_spec(source.interval).next_ms(start) - 1 if last.get("is_closed", True) else start
            else:
                cutoff = int(time.time() * 1000)
        return resolved, {"chartInput": {"contract": "candlescope.chart-indicator-input/1",
            "transform": body.config.transform, "sourceTimes": clocks, "closed": closed,
            "seriesId": reference.seriesId, "generation": reference.generation, "revision": reference.revision},
            "pineRevealedBoundaryMs": cutoff, "pineExecutionTimeMs": cutoff}
    except SyntheticError as error:
        raise HTTPException(409, str(error)) from error
    finally:
        if lease is not None:
            await finish_cleanup(lease.close())
