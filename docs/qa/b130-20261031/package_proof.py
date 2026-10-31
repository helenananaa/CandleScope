"""Verify a candidate package against an immutable product checkout."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
repo=Path(sys.argv[1]).resolve()
app=repo/'frontend/desktop-dist/mac-arm64/CandleScope.app'
resources=app/'Contents/Resources'
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
files=subprocess.check_output(['git','ls-files','backend/app','backend/requirements.txt','backend/ccxt-fork.lock.json'],cwd=repo,text=True).splitlines()
errors=[f for f in files if not (resources/f).exists() or (resources/f).read_bytes()!=(repo/f).read_bytes()]
assert not errors, errors
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
deps=subprocess.check_output(['git','diff','--name-only','8e0766126496fd899b45c536e9f7d0e9944b4e19',sha,'--','backend/requirements*.txt','backend/ccxt-fork.lock.json','packages/candlescope-plugin-sdk','packages/candlescope-backtest-sdk'],cwd=repo,text=True).splitlines()
assert not deps,deps
print(json.dumps(dict(source=sha,tracked_backend_files=len(files),tracked_python_files=sum(f.endswith('.py') for f in files),backend_files_byte_identical=True,asar_sha256=digest(resources/'app.asar'),runtime_manifest_sha256=digest(resources/'python-runtime/manifest.json'),installed_app_symlink=os.readlink('/Applications/CandleScope.app'),codesign_deep_strict=True,app_installed=False,runtime_dependency_diff=deps),indent=2))
