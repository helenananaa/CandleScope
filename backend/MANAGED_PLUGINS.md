# Managed plugin installation

CandleScope has one fail-closed setup path for downloadable plugins. The layer
is deliberately separate from runtime or exchange plugin APIs: it answers only
how a checked-in, pinned artifact becomes available in the selected backend
environment.

## Composition

- `CANDLESCOPE_PLUGINS.json` is the host registry. Setup installs entries with
  `autoInstall: true`; the CLI can explicitly select or exclude an entry.
- Each `CANDLESCOPE_PLUGIN.json` is the immutable install lock: plugin identity,
  driver, distribution/module/version, source and Release identity, manifest
  digest, and verification probe.
- `scripts/managed_plugin_installer.py` owns registry/lock validation, bounded
  HTTPS downloads, SHA-256 checks, atomic cache writes, platform selection,
  installation, stamps, and fresh-process verification.
- `scripts/managed_plugin_probes.py` owns host-specific semantic checks. The
  built-in `python-import` probe needs no plugin-specific code; Pine uses
  `pine-runtime-v1` for its schema/SMA smoke.

The only current install driver is `python-wheel`. It installs one verified
wheel with `pip --no-index --no-deps --force-reinstall`. Dependencies must be
part of the backend's pinned requirements or represented by separately managed
artifacts. Unsupported drivers, platforms, ABIs, probes, or lock schemas stop
setup; there is no source-build or unpinned-package fallback.

## Commands

```powershell
# List declarations without importing or installing anything.
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py --list

# Read-only readiness check for all auto-install entries.
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py --check

# Ensure one registered plugin, using only the verified cache.
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py `
  --plugin pine-compat --offline
```

`CANDLESCOPE_PLUGIN_CACHE_DIR` overrides the per-user artifact cache. The old
`CANDLESCOPE_RUNTIME_CACHE_DIR` name and existing `runtime-cache` directory are
accepted for migration. Canonical stamps live under
`<venv>/.candlescope/plugins/<plugin-id>.json`. Pine's old
`pine-runtime-install.json` stamp is accepted and migrated on a normal setup;
`--check` remains read-only.

## Adding a verified Python wheel plugin

A minimal import-only lock has this shape (all placeholder identities and
digests must be replaced with values from the published Release):

```json
{
  "schemaVersion": 1,
  "pluginId": "example-plugin",
  "displayName": "Example plugin",
  "installer": {
    "kind": "python-wheel",
    "package": "example-plugin",
    "pythonModule": "example_plugin",
    "version": "1.2.3",
    "pythonRequires": ">=3.10",
    "pythonTag": "cp310",
    "abiTag": "abi3"
  },
  "source": {"url": "https://github.com/org/repo", "commit": "<40 hex>"},
  "release": {
    "tag": "v1.2.3",
    "commit": "<40 hex>",
    "manifestUrl": "https://host/release/v1.2.3/manifest.json",
    "manifestSha256": "<64 hex>",
    "assetBaseUrl": "https://host/release/v1.2.3"
  },
  "verification": {"probe": "python-import"},
  "legacyStampFiles": []
}
```

The registry entry is intentionally small:

```json
{"id": "example-plugin", "lockFile": "../packages/example/CANDLESCOPE_PLUGIN.json", "autoInstall": true}
```

1. Publish a stable Release with `manifest.json` and platform wheels. The
   manifest must pin distribution, module, version, tag, commit, Python floor,
   wheel tags, byte sizes, and SHA-256 digests.
2. Add a checked-in `CANDLESCOPE_PLUGIN.json`. Use `installer.kind` =
   `python-wheel`; pin the manifest digest and Release identity. Use
   `verification.probe` = `python-import` unless CandleScope needs a stronger
   semantic contract.
3. Add its id, relative lock path, and explicit `autoInstall` policy to
   `backend/CANDLESCOPE_PLUGINS.json`.
4. If a semantic probe is required, add a named implementation and config
   validation in `scripts/managed_plugin_probes.py`. Do not put network or
   installation behavior in a probe.
5. Add installer tests for lock/manifest identity, target selection, offline
   cache behavior, stamp identity, and the probe. Then run `--list`, `--check`,
   a cold install in a disposable venv, and a repeat install.

Non-wheel artifacts should add a new installer driver behind the same registry,
cache, digest, stamp, and probe lifecycle. They must not be disguised as wheel
entries or extracted by ad-hoc setup-script code.
