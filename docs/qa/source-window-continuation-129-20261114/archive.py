"""Archive finite text test evidence; leave original apps/data/output intact."""
import gzip
import hashlib
import json
from pathlib import Path


def main():
    destination = Path(__file__).resolve().parent
    root = destination.parents[2]
    output = root / 'output' / destination.name
    evidence = destination / 'evidence'
    evidence.mkdir(exist_ok=True)
    paths = sorted([*output.glob('*.log'), *output.glob('*.xml'),
                    *output.glob('baseline-permission/permission-baseline.*')])
    index = []
    for source in paths:
        relative = source.relative_to(output).as_posix()
        target = evidence / (relative.replace('/', '--') + '.gz')
        content = source.read_bytes()
        target.write_bytes(gzip.compress(content, mtime=0))
        assert gzip.decompress(target.read_bytes()) == content
        index.append(dict(source=relative, archive=target.relative_to(destination).as_posix(),
                          bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
    (destination / 'evidence-index.json').write_text(json.dumps(index, indent=2) + '\n')
    source_paths = [
        'backend/app/data_engine/bar_aggregator/bar_state.py',
        'backend/app/data_engine/data_manager/aggregator_bridge.py',
        'backend/app/data_engine/storage/kline_sources.py',
        'backend/tests/test_deferred_component_preview_continuation.py',
        'packages/candlescope-plugin-pine-compat/scripts/qualify_host_contracts.py',
    ]
    hashes = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in source_paths}
    (destination / 'source-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(f'Verified {len(index)} archived text records and {len(hashes)} source hashes')


if __name__ == '__main__':
    main()
