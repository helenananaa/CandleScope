"""Harmless packaged-desktop acceptance probes; never installs or executes packages."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "packages" / "candlescope-plugin-sdk" / "src"))
from app.trusted_extensions.store import unpack


def package(root, name, manifest, files):
    target = root / f"{name}.csext"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extension.json", json.dumps({
            "schema": "candlescope.extension/1", "apiVersion": 1, "internalApiVersion": 1,
            "trust": "full-trust", **manifest,
        }))
        for path, text in files.items():
            archive.writestr(path, text)
    unpack(target.read_bytes())


def build(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    for version in ("1.0.0", "1.1.0"):
        package(root, f"probe-{version}", {
            "id": "qualification.lifecycle", "name": "Lifecycle qualification", "version": version,
            "entries": {"frontend": "frontend.mjs", "backend": "backend.py", "desktop": "desktop.mjs"},
        }, {
            "frontend.mjs": f"""
export function activate(ctx) {{
  const previous = window.__extensionQualification;
  window.__extensionQualification = {{ version: '{version}', count: (previous?.count ?? 0) + 1 }};
  ctx.track(() => {{ delete window.__extensionQualification; }});
}}
""",
            "backend.py": f"""
import json, os
from pathlib import Path

def record(event):
    with (Path(os.environ['CANDLESCOPE_EXTENSION_PROBE_OUT']) / 'backend.jsonl').open('a') as output:
        output.write(json.dumps({{'event': event, 'version': '{version}', 'pid': os.getpid()}}) + '\\n')
def prepare(ctx):
    record('prepare')
    ctx.track(lambda: record('cleanup'))
def activate(ctx):
    ctx.replace_service('extension_qualification', '{version}')
    record('activate')
def deactivate(ctx):
    record('deactivate')
""",
            "desktop.mjs": f"""
import {{ appendFileSync }} from 'node:fs';
import path from 'node:path';
const record = event => appendFileSync(path.join(process.env.CANDLESCOPE_EXTENSION_PROBE_OUT, 'desktop.jsonl'), JSON.stringify({{event,version:'{version}',pid:process.pid}})+'\\n');
export function activate(ctx) {{
  if (!ctx.electron.app.isPackaged || !ctx.host.manager) throw Error('Real packaged host required');
  record('activate');
  ctx.track(() => record('cleanup'));
}}
export function deactivate() {{ record('deactivate'); }}
""",
        })
    package(root, "broken", {"id": "qualification.broken", "name": "Failure qualification", "version": "1.0.0",
        "entries": {"frontend": "frontend.mjs", "backend": "backend.py", "desktop": "desktop.mjs"}}, {
        "frontend.mjs": "export function activate(ctx) { ctx.ui.stylesheet('body { --qualification-broken: 1; }'); throw Error('Qualification frontend failure'); }",
        "backend.py": "def activate(ctx):\n    ctx.replace_service('broken_qualification', 1)\n    raise RuntimeError('Qualification backend failure')\n",
        "desktop.mjs": "export function activate() { throw Error('Qualification desktop failure'); }",
    })
    package(root, "crash", {"id": "qualification.crash", "name": "Interrupted startup qualification", "version": "1.0.0",
        "entries": {"desktop": "desktop.mjs"}}, {"desktop.mjs": "export function activate() { process.crash(); }"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
