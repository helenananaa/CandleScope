"""Read only a captured chart window through replay's public history owners."""
from app.data_engine.interval_policy import compute_bucket_end_ms, parse_interval_ms
from app.data_engine.synthetic_series.core import MAX_SOURCE_ROWS, SyntheticError


async def read_synthetic_source(training, request):
    origin, source = request.origin, request.source
    binding = await training.store.history_binding(session_id=origin.session_id, track_id=origin.track_id)
    if any(binding[field] != value for field, value in (
            ("exchange", source.exchange), ("market_type", source.market_type), ("symbol", source.symbol))):
        raise SyntheticError("replay market identity changed")
    if (origin.revealed_boundary_ms > binding["virtual_time_ms"]
            or origin.source_sequence > binding["source_sequence"]
            or request.through * 1000 > origin.revealed_boundary_ms):
        raise SyntheticError("synthetic request is ahead of the revealed replay prefix")
    options = dict(track_id=origin.track_id, data_epoch=origin.data_epoch,
        revealed_boundary_ms=origin.revealed_boundary_ms, display_interval=source.interval)
    width = parse_interval_ms(source.interval)
    if not width:
        raise SyntheticError("invalid replay display interval")
    tape = binding["source_kind"] == "AGG_TRADE"
    rows, epoch, tail_bars = {}, origin.history_epoch, []
    if tape:
        next_open = compute_bucket_end_ms(request.through * 1000, width, interval=source.interval)
        before = next_open if next_open <= origin.revealed_boundary_ms else None
    else:
        if width != parse_interval_ms(binding["base_interval"]):
            tail = await training.display_projection(origin.session_id, **options, limit=1)
            tail_bars = tail["bars"]
        before = request.through * 1000 + 1
    for _ in range(MAX_SOURCE_ROWS // 500 + 2):
        if tape:
            page = await training.tape_projection(origin.session_id, **options,
                source_sequence=origin.source_sequence, history_epoch=epoch, before_ms=before, limit=500)
            if page["status"] != "ready":
                raise SyntheticError("replay tape source is preparing")
        else:
            page = await training.history_page(origin.session_id, **options,
                history_epoch=epoch, before_ms=before, limit=500)
        if epoch is not None and epoch != page["history_epoch"]:
            raise SyntheticError("replay history epoch changed during synthetic seed")
        epoch = page["history_epoch"]
        _admit(rows, page["bars"], request, origin.revealed_boundary_ms)
        if len(rows) > MAX_SOURCE_ROWS:
            raise SyntheticError("synthetic source budget exceeded")
        cursor = page["next_before_ms"]
        if not page["has_more"] or cursor <= request.anchor * 1000:
            break
        if before is not None and cursor >= before:
            raise SyntheticError("replay source cursor did not progress")
        before = cursor
    else:
        raise SyntheticError("replay synthetic source page budget exceeded")
    _admit(rows, tail_bars, request, origin.revealed_boundary_ms)
    return [rows[key] for key in sorted(rows)], epoch


def _admit(target, bars, request, boundary):
    for raw in bars:
        # The source authority supplies only the selected public prefix. Check
        # lineage too: a forming coarse bar may close after the public clock.
        if (raw["open_time_ms"] > boundary or raw["last_base_open_ms"] > boundary
                or (raw["is_closed"] and raw["close_time_ms"] > boundary)):
            raise SyntheticError("replay source exposed future data")
        time = raw["open_time_ms"] // 1000
        if request.anchor <= time <= request.through:
            target[time] = {"time": time,
                **{field: raw[field] for field in ("open", "high", "low", "close", "volume")},
                "is_closed": raw["is_closed"]}
