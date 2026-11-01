"""Initial B130 consumer: bounded closed, fixed-grid coarse-history buckets.

The history executor still owns input reads, pagination, source qualification
and materialization. Two-leaf aligned blocks can be reused by 2d/4d/5d etc.;
partial, forming, irregular and large buckets retain the established reducer.
"""
from __future__ import annotations

from contextlib import ExitStack
from hashlib import sha256
from itertools import groupby

from .blocks import BlockKey
from .core import AcceptedComponent, combine, summarize
from .semantics import ClosePolicy


def aggregate_closed_history(manager, bars, *, source_key, source_seconds,
                             width, phase_seconds, acquired_at, fallback):
    from app.data_engine.data_manager.models import BarData
    ordered = bars if all(a.time <= b.time for a, b in zip(bars, bars[1:])) else sorted(bars, key=lambda b: b.time)
    outputs = []
    with manager.view((source_key,), acquired_at=acquired_at) as view:
        revision = view.revisions[0]
        for start, grouped in groupby(ordered, lambda bar: (bar.time - phase_seconds) // width * width + phase_seconds):
            rows = list(grouped)
            if (len(rows) > 64 or rows[0].time != start or rows[-1].time + source_seconds != start + width
                    or any(not row.is_closed or not row.trusted_final for row in rows)
                    or any(b.time - a.time != source_seconds for a, b in zip(rows, rows[1:]))):
                outputs.extend(fallback(rows))
                continue
            parts = []
            with ExitStack() as leases:
                cursor = 0
                while cursor < len(rows):
                    take = 2 if rows[cursor].time % (2 * source_seconds) == 0 and cursor + 1 < len(rows) else 1
                    leaves = rows[cursor:cursor + take]
                    def build(leaves=leaves):
                        return summarize([AcceptedComponent(source_key, row,
                            (row.time + source_seconds) * 1000, revision) for row in leaves], target=source_key)
                    if take == 1:
                        parts.append(build())
                    else:
                        # The legacy cache also carries accepted in-memory bars.
                        # Keep their complete normalized values/quality in this
                        # bounded digest in addition to the durable source view.
                        digest = sha256(repr(tuple((row.normalized_aggregation_values(), row.source)
                                                  for row in leaves)).encode()).hexdigest()
                        key = BlockKey(source_key, leaves[0].time_ms,
                                       (leaves[-1].time + source_seconds) * 1000, digest)
                        block = leases.enter_context(manager.acquire(key, view, build, work_bytes=16 * 1024))
                        parts.append(block.summary)
                    cursor += take
                summary = combine(parts)
                coverage = summary.evaluate(start * 1000, (start + width) * 1000,
                                            close_policy=ClosePolicy.SUCCESSOR)
                outputs.append(BarData(time=start, is_closed=coverage.closed,
                                       **summary.values.project(enhanced_complete=coverage.enhanced_complete)))
    return outputs
