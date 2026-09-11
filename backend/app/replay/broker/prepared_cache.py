"""Disposable, versioned interval cache. Never part of recovery authority.

Only JSON scalars are stored, compressed with a corruption-detecting checksum.
Closed builder bars are shared across checkpoints instead of serializing the
entire retained window every 128 events. A mismatch always rebuilds the index.
"""

import json
import os
from copy import copy
from dataclasses import fields
from decimal import Decimal, InvalidOperation
from pathlib import Path
from operator import attrgetter
from uuid import uuid4
import zlib

from ..bars.builder import ReplayDisplayBar
from ..canonical import canonical_sha256, orjson
from ..dataset import ReplayBar
from ..errors import ReplayDomainError
from .interval_index import BarInteractionIndex, PriceRangeIndex
from .prepared_display import PreparedDisplay
from .prepared_interval import PreparedBarInterval, _BarListMarket, _PreparedChains
from .shared_prepared import AccountRanges

VERSION = "prepared-market-cache.v5"
MAGIC = (VERSION + "\n").encode("ascii")
STATE_FIELDS = (
    "_closed_count",
    "_closed_prefix_count",
    "_closed_prefix_hash",
    "_closed_chain_hash",
    "_last_base_open_ms",
    "_replay_events_applied",
)
BAR_FIELDS = tuple(field.name for field in fields(ReplayBar))
DISPLAY_FIELDS = tuple(field.name for field in fields(ReplayDisplayBar))
_BAR_ROW = attrgetter(*BAR_FIELDS)
_DISPLAY_ROW = attrgetter(*DISPLAY_FIELDS)


def _binding(source, builder):
    ref = source.snapshot_ref()
    ref = ref.to_dict() if hasattr(ref, "to_dict") else dict(ref)
    return canonical_sha256(
        {
            "version": VERSION,
            "source": ref,
            "builder": list(PreparedBarInterval.configuration(builder)),
            "replay_start": builder._replay_start_ms,
            "schedule": builder._schedule.fingerprint,
        }
    )


def save(path, index, binding):
    """Best effort atomic replacement; failed writes cannot break replay."""
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        pool, checkpoints = [], []
        previous_count = None
        for offset, builder in sorted(index.builders.items()):
            # Checkpoints follow one append-only trajectory. Store only newly
            # closed bars and describe each retained window as a pool slice.
            # Avoid walking/encoding the same 2,048 ordinals every 128 events.
            count = builder._closed_count
            added = (
                len(builder._closed_bars)
                if previous_count is None
                else min(count - previous_count, len(builder._closed_bars))
            )
            if added < 0:
                raise ValueError("prepared checkpoints are not ordered")
            if added:
                pool.extend(map(_DISPLAY_ROW, builder._closed_bars[-added:]))
            retained = [len(pool) - len(builder._closed_bars), len(pool)]
            previous_count = count
            checkpoints.append(
                [
                    offset,
                    [getattr(builder, field) for field in STATE_FIELDS],
                    retained,
                    None
                    if builder._active_bar is None
                    else _DISPLAY_ROW(builder._active_bar),
                ]
            )
        value = {
            "version": VERSION,
            "binding": binding,
            "start": index.start,
            "terminal": index.terminal,
            "bars": list(map(_BAR_ROW, index.bars)),
            "prefix": list(map(_BAR_ROW, index.display_prefix)),
            "chain_seed": index._chain_seed,
            "chain_mode": "legacy" if index._next_hash is not None else "range",
            "pool": pool,
            "checkpoints": checkpoints,
            "revision": index.display.revision,
            "valuation": None
            if index.valuation is None
            else {
                key: index.valuation[key]
                for key in ("key", "basis", "ledger_hash")
                if key in index.valuation
            },
        }
        # These are owned, validated scalar arrays, not an arbitrary object
        # graph requiring another canonicalization traversal.
        if orjson is not None:
            try:
                raw = orjson.dumps(value)
            except orjson.JSONEncodeError:
                raw = json.dumps(value, separators=(",", ":")).encode()
        else:
            raw = json.dumps(value, separators=(",", ":")).encode()
        encoded = zlib.compress(raw, level=1)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(MAGIC + encoded)
        os.replace(temporary, path)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load(path, source, builder, chain_hash, binding):
    try:
        with Path(path).open("rb") as stream:
            # Obsolete caches can be large. Reject their version before reading
            # and decoding the whole payload during first preparation.
            if stream.read(len(MAGIC)) != MAGIC:
                return None
            value = json.loads(zlib.decompress(stream.read()))
        if value["version"] != VERSION or value["binding"] != binding:
            return None
        index = object.__new__(PreparedBarInterval)
        index.start = value["start"]
        index.terminal = value["terminal"]
        from ..source_chain import next_source_chain_hash
        index._chain_seed = value["chain_seed"]
        mode = value["chain_mode"]
        if mode not in {"legacy", "range"}:
            return None
        index._next_hash = next_source_chain_hash if mode == "legacy" else None
        index.chains = _PreparedChains(index)
        index.builder_key = PreparedBarInterval.configuration(builder)
        index.bars = [ReplayBar(*row) for row in value["bars"]]
        if (
            not 0 < len(index.bars) <= 100_000
            or len(index.chains) != len(index.bars) + 1
        ):
            return None
        if not index.compatible(source, builder, chain_hash):
            return None
        pool = [ReplayDisplayBar(*row) for row in value["pool"]]
        index.builders = {}
        for offset, state, retained, active in value["checkpoints"]:
            candidate = copy(builder)
            for field, item in zip(STATE_FIELDS, state, strict=True):
                setattr(candidate, field, item)
            first, last = retained
            if not 0 <= first <= last <= len(pool):
                return None
            candidate._closed_bars = pool[first:last]
            candidate._closed_encoding_cache = {}
            candidate._active_bar = (
                None if active is None else ReplayDisplayBar(*active)
            )
            index.builders[offset] = candidate
        if 0 not in index.builders:
            return None
        # Bind to the actual restored builder, including its retained window,
        # partial bucket and chain. This is one bounded check, not N snapshots.
        offset = source.cursor().source_sequence - index.start
        if index.builder_at(offset).snapshot() != builder.snapshot():
            return None
        index.times = tuple(bar.close_time_ms for bar in index.bars)
        index.interactions = BarInteractionIndex(index.bars)
        index.closes = PriceRangeIndex(
            [(Decimal(bar.close), Decimal(bar.close)) for bar in index.bars]
        )
        index.display_prefix = [ReplayBar(*row) for row in value["prefix"]]
        index.display = PreparedDisplay(
            index.display_prefix + index.bars,
            builder._base_interval_ms,
            value["revision"],
        )
        index.market = _BarListMarket(index.bars, builder._base_interval_ms)
        index.valuation = value["valuation"]
        if index.valuation is not None:
            basis = index.valuation.get("basis")
            if not isinstance(basis, dict):
                return None
            index.valuation["ranges"] = AccountRanges(index, basis)
            bars = index.bars
            from .shared_prepared import LazySequence, account_sample

            index.valuation["samples"] = LazySequence(
                len(bars), lambda i: account_sample(basis, bars[i].close)
            )
        index.loaded_from_cache = True
        return index
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        InvalidOperation,
        zlib.error,
        ReplayDomainError,
    ):
        return None


def prepare(source, broker, chain_hash, next_hash, path=None):
    builder = broker._bar_builder
    binding = _binding(source, builder) if path is not None else None
    index = (
        load(path, source, builder, chain_hash, binding) if path is not None else None
    )
    if index is None:
        index = PreparedBarInterval(source, builder, chain_hash, next_hash)
        index.loaded_from_cache = False
        index.prepare_valuation(broker)
        if path is not None:
            save(path, index, binding)
    else:
        index.prepare_valuation(broker)
    return index
