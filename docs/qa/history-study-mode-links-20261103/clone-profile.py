"""Clone a stopped, qualified QA profile without migrating derived owners."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
source, output = args.source.resolve(), args.output.resolve()
assert output.is_relative_to(ROOT / "output")
assert source.name == "history-study-cursor-recovery-native-20261103"
assert source != output and not (output / "profile").exists()
receipt = json.loads((source / "acceptance.json").read_text())
assert receipt["passed"] and receipt["steps"][-1]["name"] == "full-owned-exit"
assert not receipt.get("exitFailure")
commands = subprocess.check_output(["ps", "-axo", "command="], text=True).splitlines()
for base in (source, output):
    assert not any(command.strip().startswith(str(base / "Installed App/CandleScope.app") + "/")
                   or command.strip().startswith(str(base / "profile") + "/")
                   for command in commands)

destination = output / "profile"
destination.mkdir(parents=True)


def clone(before, after):
    subprocess.run(["/bin/cp", "-cR", str(before), str(after)], check=True)


root_exclusions = {"data", "plugins", "logs", "control", "SingletonLock", "SingletonSocket", "SingletonCookie"}
for entry in (source / "profile").iterdir():
    if entry.name not in root_exclusions:
        clone(entry, destination / entry.name)
(destination / "data").mkdir()
data_exclusions = {"prepared-inputs", "data-preparation.sqlite3", "data-preparation.sqlite3-shm",
                   "data-preparation.sqlite3-wal", "data-preparation.lock", "plugins", "readonly-accounts"}
for entry in (source / "profile/data").iterdir():
    if entry.name not in data_exclusions:
        clone(entry, destination / "data" / entry.name)
shutil.copy2(source / "fixture.json", output / "fixture.json")
shutil.copy2(source / "basic-acceptance.json", output / "cursor-base-acceptance.json")
(output / "profile-source.json").write_text(json.dumps({
    "source": str(source), "sourceApplicationCommit": receipt["applicationSourceCommit"],
    "sourceNativePassed": True,
    "copy": "APFS clone of fully stopped owned public-history/manual-note QA profile; original retained",
    "excludedRoot": sorted(root_exclusions), "excludedData": sorted(data_exclusions),
    "reason": "New derived preparation cache/database, plugin registry/venvs and control connection are created by their normal owners. Never rewrite ownership markers or execute an inherited plugin venv in the source profile.",
    "scope": "Three independent saved studies and one live linked sibling in two windows. Only controlled manual accounts and public data; not a fresh user profile or cold online qualification.",
}, indent=2) + "\n")
print(json.dumps({"profile": str(destination), "source": str(source)}))
