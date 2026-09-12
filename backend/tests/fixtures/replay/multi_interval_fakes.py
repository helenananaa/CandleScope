"""Actual BAR/HEDGE service fixture for multi-interval qualification."""

from dataclasses import replace
from pathlib import Path

from app.replay.training.models import ReplayV2CommandType as C
from tests.test_replay_v2_training_phase5 import _request, _acquire
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send
from tests.fixtures.replay.hedge_input_fakes import (
    prepare_hedge_request,
    import_hedge_track_public_inputs,
)
from tests.fixtures.replay.service_fakes import START_MS


async def make_multi(
    root: Path,
    *,
    enabled=True,
    tracks=2,
    horizon=300,
    margin_mode="CROSS",
    sides=("LONG",),
    prices=None,
    marks=None,
    quantity="0.1",
    initial_equity=None,
    funding_offset=0,
    warmup=2,
):
    root.mkdir(parents=True, exist_ok=True)
    symbols = (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "BNBUSDT",
        "DOGEUSDT",
        "AVAXUSDT",
    )[:tracks]
    s = await _risk_service(
        root / "run.db",
        symbols=symbols,
        bar_prices=prices
        or [str(100 + i % 7) for i in range(horizon + max(4, warmup))],
        leading_bars=max(4, warmup) - 4,
        now_ms=START_MS + (horizon + 100) * 60000,
        settings_overrides={
            "max_bar_dataset_rows": 100000,
            "max_warmup_bars": max(100, warmup),
            "event_buffer_size": 10000,
            "checkpoint_event_interval": 10000,
            "controller_ttl_seconds": 60,
            "replay_multi_bar_interval_enabled": enabled,
        },
    )
    s.settings = replace(
        s.settings,
        replay_multi_bar_interval_enabled=enabled,
        max_bar_dataset_rows=100000,
        event_buffer_size=10000,
        checkpoint_event_interval=10000,
        controller_ttl_seconds=60,
    )
    try:
        catalog = await s.catalog(
            warmup_bars=warmup,
            horizon_ms=horizon * 60000,
            quality_mode="exact",
            blind_mode=False,
        )
        base = replace(
            _sandbox_request(
                await _request(s),
                margin_mode=margin_mode,
                initial_equity=initial_equity,
            ),
            catalog_epoch=str(catalog["catalog_epoch"]),
            market_type="futures",
            warmup_bars=warmup,
            forward_cache_ms=horizon * 60000,
        )
        req = await prepare_hedge_request(
            s,
            base,
            root=root,
            prefix="multi",
            mark_prices=marks or [str(100 + i % 11) for i in range(horizon + 1)],
            required_symbols=list(symbols),
            book_mode="OFF",
            funding_event_offset_bars=funding_offset,
        )
        for j, symbol in enumerate(symbols[1:], 1):
            await import_hedge_track_public_inputs(
                s,
                req,
                root=root,
                prefix="multi",
                symbol=symbol,
                include_book=False,
                mark_prices=marks
                or [str(100 + (i + j) % 11) for i in range(horizon + 1)],
            )
        created = await s.training.create_run(req)
        run = created["run"]["run_id"]
        session = created["run"]["adapter_session_id"]

        async def send(cid, typ, payload):
            return await _send(
                s,
                run_id=run,
                session_id=session,
                command_id=cid,
                command_type=typ,
                payload=payload,
            )

        for symbol in symbols[1:]:
            await send(
                "add-" + symbol,
                C.ADD_TRACK,
                dict(
                    exchange="binance",
                    market_type="futures",
                    symbol=symbol,
                    settlement_asset="USDT",
                    subscription_tier="FULL",
                ),
            )
        await _acquire(s, run_id=run, selected_session_id=session, command_id="acquire")
        for j, symbol in enumerate(symbols):
            if j:
                viewer = await s.training.get_viewer_state(run)
                r = await send(
                    "select-" + symbol,
                    C.SELECT_TRACK,
                    dict(
                        track_id=f"track-{j + 1}",
                        expected_viewer_revision=viewer["semantic_view_revision"],
                    ),
                )
                session = r["session_id"]
            for side in sides:
                if margin_mode == "ISOLATED":
                    await send(
                        "allocate-" + symbol + side,
                        C.ALLOCATE_ISOLATED_MARGIN,
                        dict(
                            track_id=f"track-{j + 1}", position_side=side, amount="100"
                        ),
                    )
                await send(
                    "open-" + symbol + side,
                    C.PLACE_ORDER,
                    dict(
                        client_order_id="open-" + symbol + side,
                        side="BUY" if side == "LONG" else "SELL",
                        position_side=side,
                        order_type="MARKET",
                        quantity=quantity,
                        reduce_only=False,
                        limit_price=None,
                        stop_price=None,
                    ),
                )
        # Consume initial same-time input barriers before measuring a stable range.
        await send(
            "prime", C.ADVANCE, dict(basis="BASE_BAR", count=2, stop_on_event=False)
        )
        return s, run, session, send
    except BaseException:
        await s.shutdown(step_timeout=5)
        raise
