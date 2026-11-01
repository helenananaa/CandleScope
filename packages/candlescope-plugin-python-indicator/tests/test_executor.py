from pathlib import Path
import sys
import os
import time
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from candlescope_plugin_python_indicator.author import AuthorError
from candlescope_plugin_python_indicator.executor import execute

BAR = dict(time=1, open=1, high=2, low=1, close=2, volume=3)


def test_batch_function_runs_in_fresh_process_without_global_leakage():
    source = "counter=0\ndef compute(bars, params):\n global counter\n counter+=1\n return {'lines':{'main':[counter for _ in bars['time']]}}"
    assert execute(source,[BAR],{})[1] == {'main':[1]}
    assert execute(source,[BAR],{})[1] == {'main':[1]}


def test_author_print_does_not_pollute_output_protocol():
    source = "print('top-level log')\ndef compute(bars, params):\n print('compute log')\n return {'lines':{'main':list(bars['close'])}}"
    assert execute(source,[BAR],{})[1] == {'main':[2]}


def test_user_exception_has_author_line_and_does_not_crash_parent():
    with pytest.raises(AuthorError) as error:
        execute("def compute(bars, params):\n raise RuntimeError('example')",[BAR],{})
    assert error.value.line == 2 and 'example' in str(error.value)


def test_hung_batch_is_physically_terminated():
    with pytest.raises(AuthorError, match='deadline'):
        execute("def compute(bars, params):\n while True: pass",[BAR],{},timeout=.2)


def test_author_cannot_mutate_input_columns():
    with pytest.raises(AuthorError, match='TypeError'):
        execute("def compute(bars, params):\n bars['close'][0]=99",[BAR],{})
    assert BAR['close'] == 2


def test_worker_exit_is_recoverable_failure():
    with pytest.raises(AuthorError, match='code 23'):
        execute("import os\ndef compute(bars, params):\n os._exit(23)",[BAR],{})


def test_declared_window_is_never_silently_shortened():
    with pytest.raises(AuthorError, match='window'):
        execute("INDICATOR={'window':1}\ndef compute(bars, params): pass",[BAR,{**BAR,'time':2}],{})


@pytest.mark.skipif(os.name != 'posix', reason='POSIX process group cleanup; Windows native qualification is separate')
def test_successful_batch_does_not_leave_a_running_descendant(tmp_path):
    marker=tmp_path/'orphan'
    child=f"import time;time.sleep(1);open({str(marker)!r},'w').write('orphan')"
    source=f"import subprocess,sys\ndef compute(bars, params):\n subprocess.Popen([sys.executable,'-c',{child!r}])\n return {{'lines':{{'main':[1]}}}}"
    assert execute(source,[BAR],{})[1] == {'main':[1]}
    time.sleep(1.2)
    assert not marker.exists()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX parent death; Windows native process lifecycle qualification remains separate')
def test_worker_stops_when_its_runtime_parent_is_terminated(tmp_path):
    marker=tmp_path/'worker-pid'
    source=f"import os,time\ndef compute(bars, params):\n open({str(marker)!r},'w').write(str(os.getpid()))\n time.sleep(20)"
    controller="from candlescope_plugin_python_indicator.executor import execute\nexecute("+repr(source)+","+repr([BAR])+",{},timeout=30)"
    root=Path(__file__).resolve().parents[1]/'src'
    process=subprocess.Popen([sys.executable,'-c',controller],env={**os.environ,'PYTHONPATH':str(root)},
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+5
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
        assert marker.exists()
        worker=int(marker.read_text())
        process.terminate();process.wait(timeout=3)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            status=subprocess.run(['ps','-o','stat=','-p',str(worker)],capture_output=True,text=True).stdout.strip()
            if not status or status.startswith('Z'):break
            time.sleep(.05)
        else:pytest.fail('Fresh worker survived termination of its runtime parent')
    finally:
        if process.poll() is None:process.kill();process.wait()
