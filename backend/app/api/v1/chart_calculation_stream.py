"""One live writer joins the chart domain that HTTP already hydrated."""
import asyncio
from collections import deque
from copy import deepcopy
from time import time
from pydantic import ValidationError

from app.core.executors import run_storage
from app.data_engine.data_manager.models import DataEventType
from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.indicator.calculation_contract import CalculationReference, reference_for
from app.indicator.calculation_owner import CalculationOwnerError
from app.indicator.data_manager_bridge import (
    indicator_correction_event_id, indicator_dirty_range_for_interval, is_zero_bar_backfill_completion,
)
from app.indicator.serialization import build_ws_error_payload
from app.api.v1.stream_script_subscriptions import register_script_correction
from app.api.v1.stream_indicator_payloads import IndicatorRangeNotReadyError

MAX_PENDING_CHART_INPUTS = 64


async def handle_chart_calculation_subscribe(*, dm, service, meta, reference, client_id,
        stream_consumer_id, client_meta, custom_handles, custom_tasks, correction_state,
        send_json, queue, queue_critical, unsubscribe_client, coordinator=None):
    if service is None or not hasattr(service,'calculations'):
        raise CalculationOwnerError('INDICATOR_CALCULATION_BINDING_UNSUPPORTED')
    try:
        reference = CalculationReference.model_validate(reference)
    except ValidationError as exc:
        raise CalculationOwnerError('INDICATOR_CALCULATION_CONTRACT_INVALID') from exc
    registry = service.calculations
    async with registry.borrow(reference.domainId) as chart:
        chart.matches(meta)
    await unsubscribe_client(client_id)
    hold = registry.hold(reference.domainId)
    chart = await hold.__aenter__()
    entry = {**meta, 'streamConsumerId':stream_consumer_id}
    client_meta[client_id] = entry
    ready = asyncio.Event()
    pending = deque()
    source_waiting = False

    async def release():
        pending.clear()
        chart.detach(stream_consumer_id)
        await hold.__aexit__(None,None,None)
    entry['_releaseRuntimeInputs'] = release

    async def closed():
        await unsubscribe_client(client_id)
        await queue_critical(queue, build_ws_error_payload('INDICATOR_CALCULATION_CLOSED',
            'Chart calculation was closed.', client_id=client_id))

    await chart.attach(reference, writer_id=stream_consumer_id, dispose=closed)
    await dm.ensure_stream(meta['symbol'], meta['interval'], exchange=meta['exchange'],
        market_type=meta['market_type'], focus_scope='websocket', subscription_tier='indicator',
        consumer_id=stream_consumer_id)

    async def require_resync(_error):
        if entry.get('_disposed'): return
        chart.invalidate()
        pending.clear()
        entry['_disposed'] = True
        # Unsubscribing cancels the bus recovery task that called us. Publish
        # the terminal notice before that owned cleanup can cancel this waiter.
        try:
            await queue_critical(queue, build_ws_error_payload('INDICATOR_CALCULATION_SOURCE_CHANGED',
                'Chart source delivery requires recovery.', client_id=client_id,
                detail=_error.to_dict() if isinstance(_error, ConsumerRecoveryRequired) else None))
        finally:
            await unsubscribe_client(client_id)

    async def pump():
        nonlocal source_waiting
        await ready.wait()
        try:
            while pending and not entry.get('_disposed'):
                batch = pending.popleft()
                if batch['bar'] is not None and batch['bar'].is_closed:
                    # The venue can finalize just before the local query's
                    # closed boundary. Keep the ordered input while waiting
                    # outside the calculation borrow and owner lock.
                    close_ms = chart.source.end_ms(batch['through']) + 1
                    while (remaining_ms := close_ms - int(time() * 1000)) > 0:
                        await asyncio.sleep(remaining_ms / 1000)
                try:
                    await chart.wait_corrections()
                    async with registry.borrow(reference.domainId) as current:
                        payload = await current.live(writer_id=stream_consumer_id, client_id=client_id,
                            through=batch['through'], input_bar=batch['bar'])
                        if batch['watermark'] is not None:
                            current.acknowledge_delivery(stream_consumer_id, batch['watermark'])
                except (IndicatorRangeNotReadyError, CalculationOwnerError) as exc:
                    if isinstance(exc, CalculationOwnerError) and exc.code not in {
                            'INDICATOR_CALCULATION_SOURCE_CHANGED', 'INDICATOR_CALCULATION_REBUILD_REQUIRED'}:
                        raise
                    # A new preview may precede its predecessor's durable close.
                    # Keep source ownership so that the eventual close can wake
                    # recovery. No input is admitted through the gap; fence once
                    # and require a full-origin generation on the next success.
                    if not source_waiting:
                        source_waiting = True
                        chart.invalidate()
                        await queue_critical(queue, build_ws_error_payload(
                            'INDICATOR_CALCULATION_RECOVERY_REQUIRED', str(exc), client_id=client_id))
                    # A repair may have arrived while execution was fenced.
                    # Keep one recovery wakeup, never its old preview payload.
                    wakeup = pending[-1]['through'] if pending else None
                    pending.clear()
                    if wakeup is not None:
                        pending.append({'through': wakeup, 'bar': None, 'watermark': None})
                    continue
                source_waiting = False
                if not entry.get('_disposed'): await queue_critical(queue,payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if entry.get('_disposed'): return
            chart.invalidate()
            entry['_disposed'] = True
            await queue_critical(queue,build_ws_error_payload(
                getattr(exc,'code','INDICATOR_CALCULATION_RECOVERY_REQUIRED'), str(exc),client_id=client_id))
            # Disposal cancels/drains the pump. Let this task return before
            # waiting on disposal, so it cannot await its own cancellation.
            task = asyncio.create_task(unsubscribe_client(client_id), name='chart-domain-resync:' + client_id)
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)

    async def on_event(event):
        if entry.get('_disposed'): return
        correction = event.event_type in {DataEventType.BAR_AMENDED,DataEventType.BACKFILL_COMPLETED}
        through = 0
        if correction:
            if is_zero_bar_backfill_completion(event): return
            dirty = indicator_dirty_range_for_interval(event,meta['interval'],data_manager=dm)
            if dirty is None: return
            # Historical repair supersedes queued observations; it does not
            # certify their opaque intrabar state. Rebuild the new generation.
            pending.clear()
            chart.range_service.note_correction(series_key=chart.series, start=dirty['start'],end=dirty['end'],
                event_id=indicator_correction_event_id(event,interval=meta['interval'],dirty_range=dirty))
            if event.event_type == DataEventType.BACKFILL_COMPLETED:
                barrier = str((event.detail or {}).get('request_id') or '')
                chart.require_barrier(coordinator,barrier)
        elif event.bar is not None:
            through = int(event.bar.time)
            if event.event_type == DataEventType.BAR_CLOSED:
                chart.range_service.note_closed(series_key=chart.series,closed_through=through)
        if len(pending) >= MAX_PENDING_CHART_INPUTS:
            raise ConsumerRecoveryRequired('chart_input_capacity_exhausted')
        pending.append({'through':through, 'bar':None if correction else deepcopy(event.bar),
            'watermark':event.detail.get('stream_version')})
        task = custom_tasks.get(client_id)
        if task is None or task.done():
            custom_tasks[client_id] = asyncio.create_task(pump(),name='chart-domain-stream:' + client_id)

    # No await between capturing the boundary and subscribing. Inputs emitted
    # during the subsequent snapshot are owned by the new subscription.
    chart.begin_delivery(stream_consumer_id)
    custom_handles[client_id] = dm.subscribe(callback=on_event,on_recovery=require_resync,
        symbol=meta['symbol'], interval=meta['interval'], exchange=meta['exchange'], market_type=meta['market_type'],
        preserve_updates=True,
        event_types={DataEventType.BAR_UPDATED,DataEventType.BAR_CLOSED})
    register_script_correction(dm=dm,script_correction_state=correction_state, client_id=client_id,
        meta=entry,exchange=meta['exchange'],market_type=meta['market_type'],symbol=meta['symbol'],
        _on_data_event=on_event,_require_resync=require_resync)
    # Subscriptions are registered before the closed-prefix catchup. Initial
    # catchup never observes a forming bar twice across the subscribe boundary.
    latest = await run_storage(dm.query_latest,meta['symbol'],meta['interval'],limit=2,
        exchange=meta['exchange'],market_type=meta['market_type'],auto_backfill=False)
    closed = max((bar.time for bar in latest.bars if bar.is_closed), default=0)
    await chart.wait_corrections()
    async with registry.borrow(reference.domainId) as current:
        await current.live(writer_id=stream_consumer_id,client_id=client_id,
            through=closed if closed > current.owner.cursor.closed_through else 0)
        payload = await current.view(reference_for(current.owner),
            client_id=client_id,start=current.owner.plan.start,end=current.owner.cursor.observed_through,complete=True)
    payload['type'] = 'indicator.snapshot'
    await send_json({'type':'indicator.subscribed','ok':True,'clientId':client_id,
        'indicatorId':meta['indicatorId'],'kind':'script','language':'pine','seeded':True,'seedBars':0,
        'calculation':payload['calculation'],'dataRevision':payload['dataRevision'],
        'subscriptionStatus':'accepted','realtimeStatus':'live',
        **{key:meta[key] for key in ('exchange','market_type','symbol','interval')}})
    await send_json(payload)
    ready.set()
