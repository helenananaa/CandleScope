from pathlib import Path
import datetime, hashlib, json, shutil, subprocess, zipfile
root = Path(__file__).resolve().parent
repo = root.parent.parent
frontend = repo / 'frontend'
expected = '7ebe9e3428abd9be0d0e9e2227c2c298485b5793'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip() == expected
subprocess.run(['git','diff','--exit-code','HEAD'],cwd=repo,check=True,stdout=subprocess.DEVNULL)
assert not (root/'built-dist').exists()
shutil.copytree(frontend/'dist',root/'built-dist')
with (root/'package.log').open('w') as log:
 subprocess.run([str(frontend/'node_modules/.bin/electron-builder'),'--mac','zip','--arm64','--publish','never'],cwd=frontend,stdout=log,stderr=subprocess.STDOUT,check=True)
archive = root/'CandleScope-0.3.0-macos-arm64.zip'
assert not archive.exists()
shutil.move(frontend/'desktop-dist'/archive.name, archive)
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 assert 'CandleScope.app/Contents/Resources/app.asar' in z.namelist()
stage = frontend/'desktop-dist/mac-arm64'
assert stage.is_dir() and not stage.is_symlink()
shutil.rmtree(stage)
(root/'staging-cleanup.json').write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sourceCommit':expected,'removedReproducibleStage':str(stage),'retainedZip':str(archive),'zipSha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'reason':'CRC-verified distributable retained; remove only packaging staging before fresh ZIP extraction'},indent=2)+'\n')
subprocess.run(['ditto','-x','-k',str(archive),str(root/'Installed App')],check=True)
with (root/'signature-before.log').open('w') as log:
 subprocess.run(['codesign','--verify','--deep','--strict',str(root/'Installed App/CandleScope.app')],check=True,stdout=log,stderr=subprocess.STDOUT)
with (root/'package-verification.log').open('w') as log:
 subprocess.run(['node',str(root/'verify-package.mjs')],cwd=repo,check=True,stdout=log,stderr=subprocess.STDOUT)
print((root/'package-verification.log').read_text(),flush=True)
