"""Overlay the complete backend; retain the byte-identical qualified frontend/runtime."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

repo=Path(__file__).resolve().parents[3]
base=Path(sys.argv[1]).resolve()
out=Path(sys.argv[2]).resolve()
assert not out.exists()
previous=json.loads((base/'package-source-manifest.json').read_text())
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
for paths in [('frontend',),('packages','backend/native','backend/requirements.txt',
        'backend/requirements-parquet.txt','backend/ccxt-fork.lock.json')]:
    assert not subprocess.check_output(['git','diff','--name-only',previous['product_head'],head,'--',*paths],cwd=repo)
assert not subprocess.check_output(['git','diff','--name-only','HEAD','--','backend/app'],cwd=repo)
subprocess.run(['codesign','--verify','--deep','--strict',str(base/'CandleScope.app')],check=True)
out.mkdir(parents=True)
subprocess.run(['cp','-cR',str(base/'CandleScope.app'),str(out/'CandleScope.app')],check=True)
resources=out/'CandleScope.app/Contents/Resources'
assert hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest()==previous['app_asar_sha256']
shutil.rmtree(resources/'backend/app')
hashes={}
for name in subprocess.check_output(['git','ls-files','backend/app'],cwd=repo,text=True).splitlines():
    target=resources/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(repo/name,target)
    hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
manifest=dict(product_head=head,product_tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=repo,text=True).strip(),
    base_product=previous['product_head'],frontend_source_head=head,
    frontend_source_tree=subprocess.check_output(['git','rev-parse',head+':frontend'],cwd=repo,text=True).strip(),
    app_asar_sha256=previous['app_asar_sha256'],frontend_files=previous['frontend_files'],files=hashes,
    scope='Current complete backend with unchanged verified frontend/desktop ASAR and retained Python runtime/plugins; not a fresh release/runtime build')
(out/'package-source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
for name,args in [('sign',['codesign','--force','--deep','--sign','-',str(out/'CandleScope.app')]),
                  ('verify',['codesign','--verify','--deep','--strict',str(out/'CandleScope.app')])]:
    result=subprocess.run(args,capture_output=True,text=True)
    (out/(name+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode==0
print(json.dumps({'product_head':head,'backend_files':len(hashes),'frontend_files':len(previous['frontend_files'])}))
