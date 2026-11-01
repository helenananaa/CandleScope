"""Package the Python indicator and SDK wheels with a fixed functional probe."""
from pathlib import Path
import argparse
from email.parser import BytesParser
import json
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]/'backend'))
sys.path.insert(0, str(ROOT.parent/'candlescope-plugin-sdk/src'))
from app.plugin_runtime.bundle import build_plugin_bundle


def build(wheels, output):
    records = {}
    for path in map(Path, wheels):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(names) != 1:
                raise ValueError('Wheel must contain one distribution metadata file')
            meta = BytesParser().parsebytes(archive.read(names[0]))
        package = meta['Name'].lower().replace('_','-')
        if package in records:
            raise ValueError('Duplicate wheel distribution')
        records[package] = (path, meta['Version'])
    expected = {'candlescope-plugin-python-indicator':'0.1.0', 'candlescope-plugin-sdk':'0.2.1'}
    if {key: value[1] for key,value in records.items()} != expected:
        raise ValueError('Exactly the Python indicator0.1.0 and SDK0.2.1 wheels are required')
    manifest = dict(schemaVersion=1,
        plugin=dict(id='candlescope.python-indicator',name='Python Indicators',version='0.1.0',
                    package='candlescope-plugin-python-indicator',protocol='candlescope.script-runtime/1'),
        python=dict(requires='>=3.11,<3.14',module='candlescope_plugin_python_indicator'),
        wheels=[dict(path='wheels/'+path.name,package=name,version=version)
                for name,(path,version) in sorted(records.items())],
        probe=json.loads((ROOT/'release/probe.json').read_text()))
    with tempfile.TemporaryDirectory() as temporary:
        template=Path(temporary)/'manifest.json';template.write_text(json.dumps(manifest))
        return build_plugin_bundle(template, wheels, output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel',action='append',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    bundle=build(args.wheel,args.output)
    print(json.dumps({'output':str(args.output),'sha256':bundle.sha256}))
