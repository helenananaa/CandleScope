"""Two owned backend processes, one existing QA SQLite profile; loopback only.

Run with the same bundled Python/PYTHONPATH as http_server.py. This verifies
backend process restoration, not installed desktop or browser-profile restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

root = Path(os.environ["CANDLESCOPE_NOTE_QA_ROOT"]).resolve()
port = int(os.environ["CANDLESCOPE_NOTE_QA_PORT"])
base = f"http://127.0.0.1:{port}"
server = Path(__file__).with_name("http_server.py")
root.mkdir(parents=True, exist_ok=True)


def get(path):
    with urlopen(base + path, timeout=10) as response:
        return json.load(response)


def generation(index):
    log = (root / f"restart-server-{index}.log").open("wb")
    process = subprocess.Popen([sys.executable, "-B", str(server)], stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Owned backend exited early: {process.returncode}")
            try:
                state = get("/fixture/state")
                if state["pid"] != process.pid:
                    raise RuntimeError("Port belongs to a different process")
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.1)
        context = state["context"]
        notes = get(f'/api/v1/replay/runs/{context["runId"]}/tracks/{context["trackId"]}/notes')
        images = {}
        for note in notes["notes"]:
            cursor = note["revisionCount"] + 1
            while cursor is not None:
                page = get(f'/api/v1/replay/runs/{context["runId"]}/tracks/{context["trackId"]}/notes/{note["id"]}/versions?before_revision={cursor}&limit=20')
                for version in page["versions"]:
                    for capture in version.get("screenshots", []):
                        identity = f'{note["id"]}/{version["revisionCount"]}/{capture["id"]}'
                        images[identity] = get(f'/api/v1/replay/runs/{context["runId"]}/tracks/{context["trackId"]}/notes/{note["id"]}/versions/{version["revisionCount"]}/screenshots/{capture["id"]}')
                cursor = page["nextBeforeRevision"]
        (root / f"restart-images-{index}.json").write_text(json.dumps(images, indent=2))
        assert state["network"]["blocked_attempts"] == 0
        (root / f"restart-state-{index}.json").write_text(json.dumps(state, indent=2))
        (root / f"restart-notes-{index}.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2))
        return state, notes, images, process.pid
    finally:
        if process.poll() is None:
            process.terminate()  # uvicorn handles SIGTERM and awaits both manager/service shutdowns.
            process.wait(timeout=20)
        log.close()
        receipt = json.loads((root / f"exit-{process.pid}.json").read_text())
        assert receipt["network"]["blocked_attempts"] == 0
        assert receipt["manager"]["closed"] and receipt["manager"]["streams"] == 0


before, notes, images, first = generation(1)
after, restored, restored_images, second = generation(2)
assert first != second
assert notes == restored
assert images == restored_images
assert before["snapshot"] == after["snapshot"]
assert before["context"] == after["context"]
result = {"passed": True, "scope": "Real backend process restart, explicit fixture candles; not native desktop qualification",
          "pids": [first, second], "notes": len(notes["notes"]), "versionImages": len(images), "blockedExternalAttempts": 0,
          "checks": ["all visible note versions equal", "version PNG bytes and metadata equal", "review/source cursors and financial snapshot equal", "both owned exits closed manager without streams"]}
(root / "restart-checks-current.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
