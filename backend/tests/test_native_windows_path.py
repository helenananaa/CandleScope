"""Managed installs must retain their venv identity beyond Windows MAX_PATH."""
import os
import threading
import venv

import pytest

from app.backtest.native import invoke
from app.backtest.native_session import SessionWorker


@pytest.fixture
def long_python(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows CreateProcess application-name boundary')
    directory = tmp_path
    while len(str(directory / 'Scripts/python.exe')) <= 270:
        directory /= 'managed-plugin-installation-long-path'
    venv.EnvBuilder(with_pip=False, symlinks=False).create(directory)
    return directory / 'Scripts/python.exe'


def assert_identity(result, python):
    assert os.path.normcase(result['executable']) == os.path.normcase(str(python))
    assert os.path.normcase(result['prefix']) == os.path.normcase(str(python.parent.parent))


def test_batch_launch_preserves_long_managed_interpreter(long_python):
    script = 'import json,sys;json.load(sys.stdin);print(json.dumps(dict(ok=True,executable=sys.executable,prefix=sys.prefix)))'
    result = invoke({'command':[str(long_python),'-I','-c',script]}, {'probe':'batch'}, timeout=10)
    assert_identity(result, long_python)


def test_persistent_launch_preserves_long_managed_interpreter_and_reaps(long_python):
    script = '''import json,sys
for line in sys.stdin:
    request=json.loads(line)
    print(json.dumps(dict(ok=True,identity=request['identity'],executable=sys.executable,prefix=sys.prefix)),flush=True)
'''
    worker = SessionWorker({'command':[str(long_python),'-I','-c',script]},
        {'identity':{}}, threading.Event(), evaluator=True)
    try:
        for ordinal in range(2):
            result = worker.request({'operation':'execute','ordinal':ordinal},threading.Event(),timeout=10)
            assert_identity(result,long_python)
    finally:
        worker.close()
    assert worker.process.poll() is not None
    assert worker.process.stdout.closed and worker.process.stdin.closed
