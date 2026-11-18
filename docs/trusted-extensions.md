# Trusted extensions

CandleScope loads trusted extensions from unified `.cspkg` packages. Install packages from the desktop plugin center and approve the exact archive digest and trust setting. The Trusted extensions panel selects a theme and workspace layout from the enabled packages.

Two examples are available in [examples/unified-plugins](../examples/unified-plugins/). Build them from the repository root.

```sh
python backend/scripts/unified_plugin.py build examples/unified-plugins/paper /tmp/paper.cspkg
python backend/scripts/unified_plugin.py build examples/unified-plugins/terminal /tmp/terminal.cspkg
```

Paper provides a theme through a restricted `data` entry. Terminal uses full trust for its workspace layout and its frontend, backend and desktop entries. Full-trust code has the host process's access. The review shows the exact trust level and available entry points.

## Appearance data

A `data` entry with ID `theme` references a JSON object of schema `candlescope.theme/1`. It declares a `base` of `dark` or `light` and a bounded map of supported color, size and typography tokens. The application validates the values before approving the archive.

A `data` entry with ID `layout` references a JSON object of schema `candlescope.layout/1`. It declares the `page` and `workspace` slot order, with each host slot present exactly once. The package requires full trust. Selection is shared by windows and persists across app restarts. Disabling or uninstalling the provider clears the selection.

## Updating a previous installation

Original `.csext` archives and `trusted-extensions-v1/state.json` remain in the profile. The Trusted extensions panel lists those records for review.

- For a package containing only appearance data, choose **Review appearance migration**. CandleScope verifies the original archive digest and prepares a new data-only package. Approve it and select its theme or layout.
- For a package containing code, install its updated unified release. Authors should declare each execution entry and every startup factory it replaces. Use `ctx.track` to release owned resources. Current hooks and context contracts are described in the [unified host guide](../backend/app/plugin_lifecycle/README_zh.md).

For recovery, launch the desktop app with `--extensions-safe-mode` or use `--disable-unified-plugin=<package-id>` to persistently disable a specific package and its dependents. Start normally to apply the remaining selections.
