"""Install a frozen wheel set and optionally activate native-only plugins.

Does not alter the indicator runtime registry or either independent engine repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "CandleScope/plugins")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--runtime", choices=("all", "pyne"), default="all",
                        help="Select Pyne alone when the Pine release lacks required strategy APIs.")
    args = parser.parse_args()
    wheels = sorted(args.wheelhouse.resolve().glob("*.whl"))
    required = ("candlescope_plugin_sdk-", "candlescope_plugin_pyne-", "candlescope_plugin_pine_compat-", "pyne_runtime-", "pine_compat_runtime-", "numpy-", "tzdata-")
    if args.runtime == "pyne":
        required = tuple(prefix for prefix in required if "pine_compat" not in prefix)
        wheels = [path for path in wheels if any(path.name.startswith(prefix) for prefix in required)]
    if len(wheels) != len(required) or any(sum(p.name.startswith(prefix) for p in wheels) != 1 for prefix in required):
        parser.error("wheelhouse must contain exactly one wheel for each selected plugin, SDK, engine, numpy and tzdata")
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in wheels}
    bundle = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    installation = args.root.resolve() / "native-installs" / bundle
    executable = installation / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.exists():
        subprocess.run([sys.executable, "-m", "venv", str(installation / "venv")], check=True)
    subprocess.run([str(executable), "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--force-reinstall",
                    "--find-links", str(args.wheelhouse.resolve()), *map(str, wheels)], check=True)
    subprocess.run([str(executable), "-m", "pip", "check"], check=True)
    plugins, identities = [], {}
    for suffix, runtime_id, package in (("pine_compat", "candlescope.pine-compat", "candlescope-plugin-pine-compat"),
                                        ("pyne", "candlescope.pyne", "candlescope-plugin-pyne")):
        if args.runtime == "pyne" and suffix != "pyne":
            continue
        command = [str(executable), "-I", "-m", f"candlescope_plugin_{suffix}.native_strategy"]
        probe = subprocess.run(command, input='{"operation":"describe"}', text=True, encoding="utf-8", capture_output=True, check=True, timeout=30)
        result = json.loads(probe.stdout)
        if result.get("ok") is not True:
            raise RuntimeError(result)
        identities[runtime_id] = result["identity"]
        external_command = [*command[:-1], f"candlescope_plugin_{suffix}.external_strategy"]
        external_probe = subprocess.run(external_command, input='{"operation":"describe"}', text=True, encoding="utf-8", capture_output=True, check=True, timeout=30)
        external_result = json.loads(external_probe.stdout)
        if external_result.get("ok") is not True:
            raise RuntimeError(external_result)
        identities[runtime_id + ".external"] = external_result["identity"]
        plugins.append({"id": runtime_id, "package": package, "version": result["identity"]["plugin"]["version"],
                        "enabled": True, "autoStart": False, "required": False,
                        "launch": {"executable": str(executable), "args": command[1:]},
                        "managed": {"installationId": bundle, "activationId": uuid.uuid4().hex, "bundleSha256": "sha256:" + bundle}})
    installation.mkdir(parents=True, exist_ok=True)
    receipt = {"wheels": manifest, "identities": identities, "installation": str(installation)}
    (installation / "native-installation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    if args.activate:
        registry = args.root.resolve() / "native-strategy-registry.json"
        if registry.exists():
            (installation / "previous-native-registry.json").write_bytes(registry.read_bytes())
            existing = json.loads(registry.read_text(encoding="utf-8"))
            if existing.get("schemaVersion") != 1 or not isinstance(existing.get("plugins"), list):
                raise ValueError("existing native registry is invalid")
            replaced = {plugin["id"] for plugin in plugins}
            plugins = [plugin for plugin in existing["plugins"] if plugin["id"] not in replaced] + plugins
        temporary = registry.with_suffix(".tmp-" + uuid.uuid4().hex)
        temporary.write_text(json.dumps({"schemaVersion": 1, "plugins": plugins}, indent=2), encoding="utf-8")
        os.replace(temporary, registry)
        receipt["registry"] = str(registry)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
