"""Observe real retained output/IPC counts; no chart or Native qualification."""
import argparse
import asyncio
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'packages/candlescope-plugin-sdk/src'))
sys.path.insert(0, str(ROOT/'backend'))

from app.indicator.pine_calculation import PineCalculationRuntime
from app.indicator.runtime_routes import IndicatorRuntimeRoutes, IndicatorRuntimeRoute
from app.indicator.runtime_service import IndicatorRuntimeService
from app.plugin_runtime.registry import RuntimeRegistry
from app.plugin_runtime.service import RuntimeHostService
from tests.test_runtime_owned_output import owner, bars, request, counter
from tests.test_pine_calculation_runtime import raw, SERIES


async def observe(output):
    output.mkdir(parents=True, exist_ok=False)
    spec = owner(output/'owned.sqlite').spec
    host = RuntimeHostService(RuntimeRegistry(plugins=(spec,)), host_name='CandleScope', host_version='0.3.0')
    service = IndicatorRuntimeService(IndicatorRuntimeRoutes((IndicatorRuntimeRoute('pine', 'sidecar', spec.runtime_id),)), host=host)
    historical = owner(output/'standalone.sqlite')
    calculation = None
    processes = []
    receipt = {'scope':'Internal real SDK/core/runtime/service calculation owner; HTTP/WS/frontend and Native remain unbound/unqualified',
        'productCommit':'bfcb36b7bc056da5ab4d47b38e4163f11b44f5ce', 'phases':[]}
    try:
        calculation = await PineCalculationRuntime.open(service, raw(bars(500)), owner_id='qa-owned-chart', series_reference=SERIES, start=bars(1)[0].time)
        receipt['descriptor'] = (await host.descriptor(spec.runtime_id)).to_wire()
        cursor = None
        for name, rows, rebuild in [('seed',bars(500),False), ('forming',bars(501,forming=True),False),
            ('next-forming',(*bars(501,forming=True)[:-1],replace(bars(501,forming=True)[-1],close=103)),False),
            ('explicit-rebuild',bars(501,forming=True),True)]:
            cursor = await calculation.advance(raw(rows), series_reference=SERIES, input_revision='source:1',
                expected=cursor, rebuild=rebuild, is_current=lambda:True)
            before = host.diagnostics()['runtimes'][0]['requests']
            for _ in range(10): snapshot = await calculation.read(expected=cursor)
            after = host.diagnostics()['runtimes'][0]['requests']
            assert before == after
            receipt['phases'].append({'phase':name,'counter':counter(snapshot.output),'cursor':asdict(cursor),
                'requestsBeforeTenReads':before,'requestsAfterTenReads':after,
                'oldOffsetPoints':[p.to_wire() for p in snapshot.output.series[1].points[-4:]]})
        finite = await historical.execute_batch(replace(request(bars(501,forming=True)[-201:]), options={},output_stream=None,bars_stream=None))
        assert finite.ok
        receipt['standalone201BarCounter'] = counter(finite.output)
        assert [p['counter'] for p in receipt['phases']] == [500,501,502,501]
        assert receipt['standalone201BarCounter'] == 201
        receipt['passed'] = True
    finally:
        processes = [s._process for s in host._supervisors.values() if s._process is not None]
        if historical._process is not None: processes.append(historical._process)
        if calculation is not None: await calculation.close()
        await service.stop(); await host.stop(); await historical.stop()
        receipt['processes'] = []
        for process in processes:
            try: os.kill(process.pid,0); absent=False
            except ProcessLookupError: absent=True
            receipt['processes'].append({'pid':process.pid,'returncode':process.returncode,'absent':absent})
        assert all(p['returncode']==0 and p['absent'] for p in receipt['processes'])
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')


if __name__=='__main__':
    args=argparse.ArgumentParser();args.add_argument('--output',type=Path,required=True)
    asyncio.run(observe(args.parse_args().output))
