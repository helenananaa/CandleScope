"""Download bounded public USD-M archives and verify their official checksums."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

output = Path(sys.argv[1]).resolve()
archives = output / 'archives'
archives.mkdir(parents=True, exist_ok=True)
pins = {'1m': 'da3ed73cd4316854f48567321752ddc53f976cc37c9ef1fa57c1230eb0e17fec',
        '5m': '31dcc9c67516101f495ef9e290d271dd87b592d323dcb9aba50a5535c50d1d8d',
        '15m': '4c146566bbff66b73f4058120be7d2188d7cef4d2fd7c0deab8308233de80b85',
        '1h': 'da0ec480b8857600067635308423022972e994d9dffe8b0251f0b7813018e2c8',
        '4h': 'dd6994c74a39f5b76158f133bb9e6005019ef8b9652e6149f2238afd2a5ee671',
        '1d': 'd5741a859c443e2f549f15b5f9608c0ce9b9ac44c707f299eb3ccf9aa276aadc'}

def fetch(interval):
    name = f'BTCUSDT-{interval}-2026-10.zip'
    url = f'https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/{interval}/{name}'
    for suffix in ('.CHECKSUM', ''):
        target = archives / (name + suffix)
        if target.exists():
            continue
        with urllib.request.urlopen(url + suffix, timeout=45) as response:
            payload = response.read(3 * 1024 * 1024 + 1)
        assert len(payload) <= 3 * 1024 * 1024, 'bounded public input exceeded'
        target.write_bytes(payload)
    expected = (archives / (name + '.CHECKSUM')).read_text().split()[0]
    actual = hashlib.sha256((archives / name).read_bytes()).hexdigest()
    assert actual == expected and (pins[interval] is None or pins[interval] == actual)
    return dict(interval=interval, url=url, sha256=actual, bytes=(archives / name).stat().st_size,
                provenance='official USD-M monthly archive and its matching SHA256 CHECKSUM')

with ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(fetch, pins))
(output / 'inputs.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results))
