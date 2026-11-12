from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib,urllib.request,json,sys
root=Path(sys.argv[1]).resolve()/'archives'
root.mkdir(parents=True,exist_ok=True)
pins={'1m': 'da3ed73cd4316854f48567321752ddc53f976cc37c9ef1fa57c1230eb0e17fec', '5m': '31dcc9c67516101f495ef9e290d271dd87b592d323dcb9aba50a5535c50d1d8d', '15m': '4c146566bbff66b73f4058120be7d2188d7cef4d2fd7c0deab8308233de80b85', '1h': 'da0ec480b8857600067635308423022972e994d9dffe8b0251f0b7813018e2c8'}
def get(interval):
    name=f'BTCUSDT-{interval}-2026-10.zip'
    url=f'https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/{interval}/{name}'
    p=root/name
    for suffix in ['.CHECKSUM','']:
        target=root/(name+suffix)
        if not target.exists():
            with urllib.request.urlopen(url+suffix,timeout=45) as r: target.write_bytes(r.read())
    expected=(root/(name+'.CHECKSUM')).read_text().split()[0]
    actual=hashlib.sha256(p.read_bytes()).hexdigest()
    assert actual==expected==pins[interval]
    return {'interval':interval,'url':url,'sha256':actual,'bytes':p.stat().st_size}
with ThreadPoolExecutor(max_workers=4) as ex: result=list(ex.map(get,['1m','5m','15m','1h']))
(root.parent/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
