"""Current source SDK/bridge + hash-verified unchanged qualified native wheel.

This is a local qualification bundle, not a new upstream engine build/release.
Published locks and the retained application remain untouched.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/issue-152-pine-bridge-20261102'
RETAINED=Path('/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/Installed App/CandleScope.app/Contents/Resources/python-runtime/plugins')
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value);return value
def sha(path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
recipe=json.loads((ROOT/'frontend/scripts/desktop-plugin-sources.json').read_text())
lock=json.loads((RETAINED/'candlescope-plugin-pine-compat.lock.json').read_text())
assert lock['engineProvenance']==recipe['engines']['pine-compat-runtime']
wheelhouse=OUT/'wheels';wheelhouse.mkdir(parents=True,exist_ok=True)
engine=lock['wheels']['pine-compat-runtime'];target=wheelhouse/engine['artifactFilename']
with zipfile.ZipFile(RETAINED/'candlescope-plugin-pine-compat-0.4.0-Darwin-arm64.cspkg') as z:
 target.write_bytes(z.read('wheels/'+target.name))
assert sha(target)==engine['sha256'] and target.stat().st_size==engine['size']
canonicalizer=module(ROOT/'packages/candlescope-plugin-pine-compat/scripts/canonicalize_wheel.py','canonicalizer')
for package in ['candlescope_plugin_sdk','candlescope_plugin_pine_compat']:
 wheel=next(wheelhouse.glob(package+'-*.whl'));canonicalizer.canonicalize(wheel)
builder=module(ROOT/'packages/candlescope-plugin-pine-compat/scripts/build_bundle.py','builder')
source=module(ROOT/'frontend/scripts/prepare-desktop-plugins.py','desktop_source')
lock['bridgeSourceSha256']=source.source_digest(ROOT/'packages/candlescope-plugin-pine-compat')
lock['sdkSourceSha256']=source.source_digest(ROOT/'packages/candlescope-plugin-sdk')
records={r.package:r for r in map(builder.inspect_wheel,wheelhouse.glob('*.whl'))}
for package in lock['wheels']:
 r=records[package];lock['wheels'][package]={'version':r.version,'artifactFilename':r.path.name,'sha256':r.sha256,'size':r.path.stat().st_size}
lock.pop('bundle',None);lock.pop('qualification',None)
bundles=OUT/'plugins';assert not bundles.exists(),'Preserve prior bundle receipts';bundles.mkdir()
lockpath=bundles/'candlescope-plugin-pine-compat.lock.json';lockpath.write_text(json.dumps(lock,indent=2)+'\n')
bundle=bundles/'candlescope-plugin-pine-compat-0.4.0-Darwin-arm64.cspkg'
verified=builder.build_locked_bundle([records[p].path for p in lock['wheels']],bundle,lock_path=lockpath)
manifest=json.loads((RETAINED/'manifest.json').read_text());entry=manifest['plugins'][0];assert len(manifest['plugins'])==1
entry.update(filename=bundle.name,sha256=verified.sha256,size=verified.size)
(bundles/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
shutil.copytree(RETAINED/'sources',bundles/'sources')
print(json.dumps({'bundle':str(bundle),'sha256':verified.sha256,'lock':str(lockpath),'engineReused':engine,'currentBridgeSource':lock['bridgeSourceSha256'],'currentSdkSource':lock['sdkSourceSha256']}))
