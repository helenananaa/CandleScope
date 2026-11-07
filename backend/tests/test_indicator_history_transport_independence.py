"""Exercise the actual spawned range worker without an HTTP application."""
from pathlib import Path
import subprocess
import sys
import textwrap


def test_cold_range_worker_needs_no_http_imports(tmp_path):
    root = Path(__file__).resolve().parents[2]
    probe = tmp_path / "cold_range_worker.py"
    probe.write_text(textwrap.dedent(f"""
        import asyncio
        import importlib.abc
        import json
        import os
        import sys

        sys.path[:0] = {[
            str(root / 'backend'),
            str(root / 'packages/candlescope-plugin-sdk/src'),
            str(root / 'packages/candlescope-backtest-sdk/src'),
        ]!r}

        class NoHTTP(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == name or fullname.startswith(name + '.')
                       for name in ('app.api', 'app.main', 'fastapi', 'starlette')):
                    raise ImportError('Range worker imported HTTP composition: ' + fullname)

        # spawn re-executes this file, installing the guard in the actual child.
        sys.meta_path.insert(0, NoHTTP())
        from app.data_engine.data_manager.models import BarData
        from app.indicator.history_worker import BuiltinHistoryExecutor

        async def main():
            executor = BuiltinHistoryExecutor()
            pid = None
            try:
                bars = tuple(BarData(time=(i + 1) * 60, open=100+i, high=101+i,
                                    low=99+i, close=100+i, volume=10, is_closed=True)
                             for i in range(10))
                meta = {{'symbol': 'BTCUSDT', 'interval': '1m', 'market_type': 'spot',
                        'exchange': 'binance', 'name': 'MA', 'params': {{'period': 5}},
                        'indicatorId': 'cold-ma'}}
                request = ('range', 'cold-client', meta, 480, 720, bars, 'cold-range', 5)
                result = await executor.run(request, len(bars))
                pid = executor.snapshot()['worker']['pid']
                assert pid != os.getpid()
                assert result['type'] == 'indicator.replace_range'
                assert result['range'] == {{'start': 480, 'end': 600}}
                assert result['warmupBars'] == 4 and result['targetBars'] == 5
                assert result['lines'][0]['data'] == [
                    {{'time': 480, 'value': 105.0}},
                    {{'time': 540, 'value': 106.0}},
                    {{'time': 600, 'value': 107.0}},
                ]
                try:
                    await executor.run(('range', 'cold-client', meta, 900, 1200,
                                        bars, 'missing-range', 6), len(bars))
                except RuntimeError as error:
                    assert type(error).__name__ == 'IndicatorRangeNotReadyError'
                    assert error.request_ids == [] and error.waited_ms == 0
                else:
                    raise AssertionError('Unavailable target must remain a domain error')
                assert await executor.run(request, len(bars)) == result
                assert executor.snapshot()['worker']['pid'] == pid
                assert not any(name == 'app.api' or name.startswith('app.api.')
                               for name in sys.modules)
            finally:
                await asyncio.to_thread(executor.close)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('Owned range worker survived close')
            print(json.dumps({{'workerPid': pid, 'range': result['range'],
                              'workerExited': True, 'httpImportsBlocked': True}}))

        if __name__ == '__main__':
            asyncio.run(main())
    """))
    result = subprocess.run([sys.executable, '-I', '-B', str(probe)],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
