"""Bind the shared calculation owner to the existing qualified Pine sidecar.

No transport, history cache or Pine implementation is created here. The normal
IndicatorRuntimeService still prepares inputs, executes and observes results.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import logging

from candlescope_plugin_sdk import FEATURE_RENDER_OUTPUT_PATCH_V1

from .calculation_owner import CalculationCursor, CalculationExecution, CalculationOwnerError, CalculationPlan, ScriptCalculationOwner
from .runtime_routes import ROUTE_MODE_SIDECAR
from .runtime_service import IndicatorRuntimeRequest, IndicatorRuntimeService, removed_in_process_runtime, _value

_TRANSPORT_OPTIONS = frozenset({'pineSessionId', 'pineSessionEpoch', 'pineLeaseId', 'pineLiveUpdate', 'pineLiveBarTime'})
logger = logging.getLogger(__name__)


def calculation_identity(request: IndicatorRuntimeRequest, series_reference: str) -> str:
    if request.language != 'pine' or not isinstance(series_reference, str) or not series_reference:
        raise CalculationOwnerError('INDICATOR_CALCULATION_BINDING_UNSUPPORTED')
    value = {'language': request.language, 'source': request.source, 'exchange': request.exchange,
        'marketType': request.market_type, 'symbol': request.symbol, 'interval': request.interval,
        'series': series_reference, 'parameters': request.params,
        'options': {key:value for key,value in request.options.items() if key not in _TRANSPORT_OPTIONS}}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()


class PineCalculationRuntime:
    @classmethod
    async def open(cls, service: IndicatorRuntimeService, request: IndicatorRuntimeRequest, *, owner_id: str,
                   series_reference: str, start: int, max_pending=8):
        identity = calculation_identity(request, series_reference)
        await service.start()
        route = service.route_for(request.language)
        if route.mode != ROUTE_MODE_SIDECAR or service.host is None:
            raise CalculationOwnerError('INDICATOR_CALCULATION_BINDING_UNSUPPORTED')
        descriptor = await service.host.descriptor(route.runtime_id)
        if FEATURE_RENDER_OUTPUT_PATCH_V1 not in descriptor.features or not callable(getattr(service.host, 'read_output', None)):
            raise CalculationOwnerError('INDICATOR_CALCULATION_OUTPUT_UNSUPPORTED')
        self = cls()
        self.service, self.runtime_id = service, route.runtime_id
        self.owner = ScriptCalculationOwner(CalculationPlan(owner_id, identity, start), read=self._read, max_pending=max_pending)
        return self

    async def _read(self, reference):
        return await self.service.host.read_output(self.runtime_id, reference.stream, expected=reference)

    async def advance(self, request: IndicatorRuntimeRequest, *, series_reference: str, input_revision: str,
                      expected: CalculationCursor | None, rebuild: bool, is_current):
        if not request.bars:
            raise CalculationOwnerError('INDICATOR_CALCULATION_INPUT_INVALID')
        identity = calculation_identity(request, series_reference)
        last = request.bars[-1]
        closed = last if _value(last, 'is_closed', 'isClosed', default=True) else (
            request.bars[-2] if len(request.bars) > 1 else None)
        publication = None
        async def execute(epoch):
            nonlocal publication
            receipt = None
            def capture(result):
                nonlocal receipt
                receipt = result
                return {'ok': result.ok}
            bound = replace(request, options={**request.options, 'pineSessionId': self.owner.plan.owner_id,
                'pineSessionEpoch': epoch, 'pineLeaseId': self.owner.plan.owner_id})
            await self.service.execute(bound, legacy=removed_in_process_runtime, adapt_sidecar=capture, notify_result=False)
            if receipt is None or not receipt.ok:
                raise CalculationOwnerError('INDICATOR_CALCULATION_EXECUTION_FAILED')
            snapshot = await self.service.host.read_output(self.runtime_id, self.owner.plan.owner_id)
            if snapshot is None or snapshot.output is not receipt.output:
                raise CalculationOwnerError('INDICATOR_CALCULATION_OUTPUT_LOST')
            publication = (bound, receipt)
            return CalculationExecution(snapshot.reference, receipt.meta.get('sessionRetained') is True,
                receipt.meta.get('sessionReset') is True)
        async def notify(_cursor):
            if self.service.observe_result is not None and publication is not None:
                try: await self.service.observe_result(*publication)
                except Exception:
                    logger.exception('Admitted indicator result notification failed')
        return await self.owner.advance(semantic_identity=identity,
            input_start=int(_value(request.bars[0], 'time')), observed_through=int(_value(last, 'time')),
            closed_through=int(_value(closed, 'time')) if closed is not None else 0,
            input_revision=input_revision, expected=expected, rebuild=rebuild, is_current=is_current, execute=execute,
            on_publish=notify)

    async def read(self, *, expected: CalculationCursor):
        return await self.owner.read(expected=expected)

    async def close(self, *, release=None):
        async def release_owned():
            if self.service.release_inputs is not None:
                await self.service.release_inputs(self.owner.plan.owner_id)
            if release is not None:
                await release()
        await self.owner.close(release=release_owned)
