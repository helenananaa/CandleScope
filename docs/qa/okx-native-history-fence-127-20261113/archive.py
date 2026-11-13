"""Archive source/native QA without changing the original profiles or apps."""
import gzip
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[3]
qa = Path(__file__).resolve().parent
out = root/'output/okx-native-history-fence-127-20261113'
ev = qa/'evidence'
ev.mkdir(exist_ok=True)

def archive_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(source.read_bytes(), mtime=0))

for p in sorted(out.iterdir()):
    if p.is_file() and p.suffix in {'.log', '.xml', '.json'}:
        archive_file(p, ev/(p.name+'.gz'))

redactions = {}
for name, location in [('initial-c67', out), ('final-ef030', out/'final-native'),
                       ('legacy-0bba', out/'legacy-native')]:
    app = location/'CandleScope.app'
    resources = app/'Contents/Resources'
    manifest = json.loads((location/'package-source-manifest.json').read_text())
    hashes = {f: hashlib.sha256((resources/f).read_bytes()).hexdigest() for f in manifest['files']}
    assert hashes == manifest['files']
    asar = hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest()
    assert asar == manifest['app_asar_sha256']
    result = subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], capture_output=True, text=True)
    (location/'sign-after.log').write_text(result.stdout+result.stderr)
    assert result.returncode == 0
    (location/'package-after.json').write_text(json.dumps({'product_head': manifest['product_head'],
        'app_files': len(hashes), 'backend_matches': True, 'app_asar_sha256': asar,
        'asar_matches': True, 'signature_status': result.returncode}, indent=2)+'\n')
    target = ev/name
    target.mkdir(exist_ok=True)
    for f in ['package-source-manifest.json', 'package-after.json', 'sign.log', 'sign-before.log', 'sign-after.log',
              'native-cold1.log', 'native-cold1/traffic.json', 'native-cold1/process.log',
              'native-cold1/profile/logs/backend-sidecar.log']:
        source = location/f
        if source.exists():
            archive_file(source, target/(f.replace('/', '_')+'.gz'))
    receipt = json.loads((location/'native-cold1/acceptance.json').read_text())
    paths = []
    def redact(value, path=''):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'contextToken' and isinstance(item, str):
                    value[key] = '[REDACTED]'
                    paths.append(path+'/'+key)
                else:
                    redact(item, path+'/'+key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                redact(item, path+'/'+str(i))
    redact(receipt)
    (target/'acceptance.json.gz').write_bytes(gzip.compress((json.dumps(receipt, indent=2)+'\n').encode(), mtime=0))
    redactions[name] = paths
    for filename in ['initial.png', 'recreated.png', 'restored.png', 'failure.png']:
        source = location/'native-cold1'/filename
        if source.exists():
            shutil.copyfile(source, qa/(name+'-'+filename))
    db = location/'native-cold1/profile/data/candlescope.db'
    with sqlite3.connect('file:'+str(db)+'?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        summary = {'canonical': [dict(r) for r in conn.execute(
            "SELECT interval,count(*) rows,min(open_time) first,max(open_time) last FROM klines WHERE exchange='okx' AND symbol='BTC-USDT' GROUP BY interval")],
            'pending_history': [dict(r) for r in conn.execute(
            "SELECT h.series,count(*) rows FROM kline_source_heads h JOIN kline_source_observations o ON o.id=h.observation_id WHERE h.delivered_revision<h.revision AND json_extract(o.envelope_json,'$._source_delivery_owner')='history' GROUP BY h.series")],
            'ledger': [dict(r) for r in conn.execute(
            'SELECT interval,status,count(*) rows FROM kline_gap_ledger GROUP BY interval,status')]}
    (qa/(name+'-database-summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
(qa/'redactions.json').write_text(json.dumps({'policy': 'only ephemeral control context strings; numeric active_read_tokens remain intact',
    'paths': redactions}, indent=2)+'\n')
files = subprocess.check_output(['git', 'diff', '--name-only', 'dd5002d38eb3e1b6c1ddbe3713b90f5ae665d750', 'HEAD', '--', 'backend'], cwd=root, text=True).splitlines()
(qa/'source-hashes.json').write_text(json.dumps({'base': 'dd5002d38eb3e1b6c1ddbe3713b90f5ae665d750',
    'measurement_head': 'c67d2a2d5ce9978b4937a9aa5225f8bb2ec8769d',
    'product_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    'files': {f: hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files}}, indent=2)+'\n')
(qa/'evidence-index.json').write_text(json.dumps({str(p.relative_to(qa)): {
    'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
    for p in sorted(ev.rglob('*')) if p.is_file()}, indent=2)+'\n')
print('archived source and two native revisions; originals retained')
