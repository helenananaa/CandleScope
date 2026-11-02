"""Exercise existing full-vs-patch host assertions against installed current wheels.

Only the process executable/entrypoint changes from the source test fixtures.
The sidecar imports installed wheels with -I and uses test-owned journals.
"""
from pathlib import Path
import asyncio
from dataclasses import replace
import hashlib
import json
import os
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'packages/candlescope-plugin-sdk/src')]
from app.plugin_runtime.installer import PluginInstaller
from app.plugin_runtime.supervisor import RuntimeSupervisor
from app.plugin_runtime.registry import load_runtime_registry
PRODUCT=ROOT/'output/issue-152-pine-bridge-20261102'
OUT=Path(os.environ.get('PINE_QUALIFICATION_OUT', str(PRODUCT)))
BUNDLE=PRODUCT/'plugins/candlescope-plugin-pine-compat-0.4.0-Darwin-arm64.cspkg'
PYTHON=Path('/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/Installed App/CandleScope.app/Contents/Resources/python-runtime/python/bin/python3.12')
installer=PluginInstaller(root=OUT/'controlled-install',python_executable=PYTHON)
result=installer.install(BUNDLE,expected_sha256='sha256:'+hashlib.sha256(BUNDLE.read_bytes()).hexdigest())
spec=load_runtime_registry(installer.registry_path).plugins[0]
site=spec.executable.parent.parent/'lib/python3.12/site-packages';sys.path.append(str(site))
runner=OUT/'run_installed_pine.py'
runner.write_text('import sys\nfrom candlescope_plugin_sdk import serve_runtime\nfrom candlescope_plugin_pine_compat import PineCompatRuntimePlugin\nraise SystemExit(serve_runtime(PineCompatRuntimePlugin(journal_path=sys.argv[1])))\n')
from tests import test_plugin_runtime_output_patch as outputs
from tests import test_plugin_runtime_bars_patch as inputs
import pytest
original_output,original_input=outputs._pine,inputs._pine
supervisors=[]
def installed(old,journal):
 old.spec=replace(old.spec,executable=spec.executable,arguments=('-I',str(runner),str(journal)))
 supervisors.append(old)
 return old
outputs._pine=lambda journal:installed(original_output(journal),journal)
inputs._pine=lambda journal,**kwargs:installed(original_input(journal,**kwargs),journal)
async def run():
 out=OUT/'controlled-walk';assert not out.exists(),'Preserve earlier receipts';out.mkdir()
 monkey=pytest.MonkeyPatch()
 try:
  await outputs.test_patched_stream_gives_callers_the_full_snapshot_result(out/'output',monkey)
  await inputs.test_patched_requests_give_callers_the_full_request_result(out/'input')
 finally:
  monkey.undo()
  for supervisor in supervisors:await supervisor.stop()
 snapshots=[s.snapshot() for s in supervisors]
 assert all(s['state']=='stopped' for s in snapshots)
 receipt={'passed':True,'scope':'Real RuntimeSupervisor framing, installed freshly built source SDK/bridge wheels, unchanged verified native engine. Existing16output +44input walk assertions unmodified, including journals/restarts/corrections/rolling windows/eviction. No HTTP/UI/external market.','install':result.to_wire(),'snapshots':snapshots}
 (OUT/'installed-sidecar-qualification.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps({'passed':True,'walks':[16,44],'processes':len(snapshots)}))
asyncio.run(run())
