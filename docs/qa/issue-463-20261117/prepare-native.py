"""Retain verified runtime; rebuild current ASAR and complete backend at one HEAD."""
from pathlib import Path
import hashlib,json,plistlib,shutil,subprocess,sys
repo=Path(__file__).resolve().parents[3]
base=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
assert not out.exists()
prior=json.loads((base/'package-source-manifest.json').read_text())
assert not subprocess.check_output(['git','diff','--name-only',prior['product_head'],'HEAD','--','packages','backend/native','backend/requirements.txt','backend/requirements-parquet.txt','backend/ccxt-fork.lock.json'],cwd=repo)
assert not subprocess.check_output(['git','diff','--name-only','HEAD','--','backend/app','frontend/desktop','frontend/src'],cwd=repo)
subprocess.run(['codesign','--verify','--deep','--strict',str(base/'CandleScope.app')],check=True)
out.mkdir(parents=True)
subprocess.run(['cp','-cR',str(base/'CandleScope.app'),str(out/'CandleScope.app')],check=True)
resources=out/'CandleScope.app/Contents/Resources'
shutil.rmtree(resources/'backend/app')
files=subprocess.check_output(['git','ls-files','backend/app'],cwd=repo,text=True).splitlines()
hashes={}
for name in files:
 target=resources/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/name,target)
 hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
initial=dict(prior,product_head=head,product_tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=repo,text=True).strip(),files=hashes)
(out/'package-source-manifest.json').write_text(json.dumps(initial,indent=2)+'\n')
payload=out/'app-payload';payload.mkdir()
for name in ('dist','desktop'):shutil.copytree(repo/'frontend'/name,payload/name)
shutil.copyfile(repo/'frontend/package.json',payload/'package.json')
asar=out/'CandleScope.app/Contents/Resources/app.asar'
subprocess.run(['node',str(repo/'frontend/node_modules/@electron/asar/bin/asar.js'),'pack',str(payload),str(asar)],check=True)
header=subprocess.check_output(['node','-e',
 'const a=require(process.argv[1]),c=require("node:crypto");process.stdout.write(c.createHash("sha256").update(a.getRawHeader(process.argv[2]).headerString).digest("hex"));',
 str(repo/'frontend/node_modules/@electron/asar'),str(asar)],text=True)
p=out/'CandleScope.app/Contents/Info.plist';info=plistlib.loads(p.read_bytes());info['ElectronAsarIntegrity']={'Resources/app.asar':{'algorithm':'SHA256','hash':header}};p.write_bytes(plistlib.dumps(info))
m=json.loads((out/'package-source-manifest.json').read_text())
m.update(frontend_source_head=m['product_head'],app_asar_sha256=hashlib.sha256(asar.read_bytes()).hexdigest(),
 frontend_files={str(p.relative_to(payload)):hashlib.sha256(p.read_bytes()).hexdigest() for p in payload.rglob('*') if p.is_file()},
 scope='macOS arm64 retained verified Python runtime/plugins; freshly rebuilt current frontend and desktop ASAR plus all current backend; not a fresh runtime/release build')
(out/'package-source-manifest.json').write_text(json.dumps(m,indent=2)+'\n')
for name,command in [('sign',['codesign','--force','--deep','--sign','-',str(out/'CandleScope.app')]),('verify',['codesign','--verify','--deep','--strict',str(out/'CandleScope.app')])]:
 r=subprocess.run(command,capture_output=True,text=True);(out/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0
print(json.dumps({'head':m['product_head'],'backend_files':len(m['files']),'fresh_frontend_files':len(m['frontend_files'])}))
