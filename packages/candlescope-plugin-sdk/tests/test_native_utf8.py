"""Native JSON IPC must not inherit the user's terminal encoding."""
import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("mode", ["serve", "serve_evaluator", "serve_session"])
def test_native_json_overrides_legacy_stdio_code_pages_in_a_real_child(mode):
    source = Path(__file__).resolve().parents[1] / "src"
    script = f'''import sys
sys.path.insert(0,{str(source)!r})
from candlescope_plugin_sdk import native_strategy as transport
sys.stdin.reconfigure(encoding="latin-1")
sys.stdout.reconfigure(encoding="latin-1")
describe=lambda: {{"fixed":"identity"}}
if {mode!r}=="serve_session":
    transport.serve_session(describe,lambda request: None)
else:
    getattr(transport,{mode!r})(describe,lambda request: {{"echo":request["source"]}})
'''
    request={"protocol":"candlescope.native-strategy/1","identity":{"fixed":"identity"},
             "operation":"open" if mode=="serve_session" else "execute","source":"开仓 止损 café 🎯"}
    raw=(json.dumps(request,ensure_ascii=False)+"\n").encode("utf-8")
    child=subprocess.run([sys.executable,"-I","-c",script],input=raw,capture_output=True,timeout=10)
    assert child.returncode==0,child.stderr.decode("utf-8",errors="replace")
    result=json.loads(child.stdout.decode("utf-8"))
    assert result["ok"] is True,result
    if mode!="serve_session":
        assert result["echo"]==request["source"]
