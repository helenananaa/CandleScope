"""Observe real shared owners and durable release; no HTTP/WS/Native claim."""
import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'packages/candlescope-plugin-sdk/src'))
sys.path.insert(0, str(ROOT/'backend'))

from app.indicator.pine_calculation import PineCalculationRuntime
from app.indicator.runtime_routes import IndicatorRuntimeRoutes, IndicatorRuntimeRoute
from app.indicator.runtime_service import IndicatorRuntimeService
from app.plugin_runtime.registry import RuntimeRegistry
from app.plugin_runtime.service import RuntimeHostService
from tests.test_runtime_owned_output import owner, bars, counter
from tests.test_pine_calculation_runtime import raw, SERIES


def journal(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        return {'ids':[row[0] for row in db.execute('SELECT id FROM journal_sessions ORDER BY id')],
            'budget':list(db.execute('SELECT sessions, bytes FROM journal_budget').fetchone()),
            'operations':db.execute('SELECT COUNT(*) FROM journal_operations').fetchone()[0]}


async def observe(output, source):
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip() == source
    output.mkdir(parents=True, exist_ok=False)
    path = output/'owned.sqlite'
    spec = owner(path).spec
    host = RuntimeHostService(RuntimeRegistry(plugins=(spec,)), host_name='CandleScope', host_version='0.3.0')
    service = IndicatorRuntimeService(IndicatorRuntimeRoutes((IndicatorRuntimeRoute('pine','sidecar',spec.runtime_id),)), host=host)
    receipt = {'source':source, 'scope':'Real calculation registry/service/SDK/core/sidecar only; chart HTTP/WS/frontend and Native still unbound/unqualified',
        'coreVersion':importlib.metadata.version('pine-compat-runtime'), 'phases':[], 'retiredRounds':[]}
    processes = []
    async def create(owner_id):
        return await PineCalculationRuntime.open(service,raw(bars(500)),owner_id=owner_id,
            series_reference=SERIES,start=bars(1)[0].time)
    async def advance(owner_id, rows, expected=None):
        async with service.calculations.borrow(owner_id) as shared:
            cursor = await shared.advance(raw(rows),series_reference=SERIES,input_revision='source:1',
                expected=expected,rebuild=False,is_current=lambda:True)
            before = host.diagnostics()['runtimes'][0]['requests']
            for _ in range(10): snapshot = await shared.read(expected=cursor)
            after = host.diagnostics()['runtimes'][0]['requests']
            assert before == after
            receipt['phases'].append({'owner':owner_id,'counter':counter(snapshot.output),
                'generation':cursor.generation,'sequence':cursor.sequence,
                'requestsBeforeTenReads':before,'requestsAfterTenReads':after})
            return cursor
    try:
        first_id = await service.calculations.open(create)
        first = await advance(first_id,bars(500))
        second_id = await service.calculations.open(create)
        await advance(second_id,bars(50))
        second = await advance(first_id,bars(501,forming=True),first)
        assert [phase['counter'] for phase in receipt['phases']] == [500,50,501]
        receipt['beforeRetire'] = journal(path)
        assert receipt['beforeRetire']['budget'][0] == 2
        await service.calculations.retire(first_id)
        receipt['afterRetireFirst'] = journal(path)
        assert receipt['afterRetireFirst']['ids'] == [second_id]
        assert await host.read_output(spec.runtime_id,first_id) is None
        await host.release_stream(spec.runtime_id,first_id)
        assert journal(path) == receipt['afterRetireFirst']
        async with service.calculations.borrow(second_id) as remaining:
            assert counter((await remaining.read(expected=remaining.owner.cursor)).output) == 50
        for count in range(20,26):
            next_id = await service.calculations.open(create)
            await advance(next_id,bars(count))
            await service.calculations.retire(next_id)
            state = journal(path)
            assert state == receipt['afterRetireFirst']
            receipt['retiredRounds'].append({'owner':next_id,'afterRelease':state})
        receipt['registryBeforeStop'] = service.calculations.snapshot()
        receipt['descriptor'] = (await host.descriptor(spec.runtime_id)).to_wire()
        receipt['passed'] = True
    finally:
        processes = [item._process for item in host._supervisors.values() if item._process is not None]
        await service.stop()
        receipt['afterStop'] = journal(path)
        assert receipt['afterStop'] == {'ids':[], 'budget':[0,0], 'operations':0}
        receipt['registryAfterStop'] = service.calculations.snapshot()
        await host.stop()
        receipt['processes'] = []
        for process in processes:
            try: os.kill(process.pid,0); absent=False
            except ProcessLookupError: absent=True
            receipt['processes'].append({'pid':process.pid,'returncode':process.returncode,'absent':absent})
        assert all(item['returncode'] == 0 and item['absent'] for item in receipt['processes'])
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    asyncio.run(observe(args.output,args.source))
