# Releasing Binary Wheels

GitHub Actions builds the Python extension wheels for the supported
desktop platforms:

- glibc Linux x86-64: `cp310-abi3-manylinux_2_17_x86_64`
- Windows x86-64: `cp310-abi3-win_amd64`

The `abi3-py310` PyO3 feature makes each platform wheel compatible with
ordinary GIL-enabled CPython 3.10 and newer. macOS, musllinux, ARM, and
free-threaded CPython remain outside the release matrix.

## Workflow Behavior

`.github/workflows/wheels.yml` runs for pull requests, pushes to `main`, version
tags, and manual dispatches.

- Pull requests and ordinary `main` pushes build, install, test, and retain the
  wheels as 14-day workflow artifacts.
- A `v*` tag performs the same build and then creates a durable GitHub Release.
- The release contains both wheels, `manifest.json`, and `SHA256SUMS`.

Workflow artifacts are test evidence. Applications must consume only GitHub
Release assets.

## Version Contract

Before tagging, keep these versions synchronized:

- `pyproject.toml` project version
- every workspace crate package version under `crates/*/Cargo.toml`
- workspace package versions recorded in `Cargo.lock`
- Git tag without its leading `v`

The manifest builder reads the wheel metadata and fails the release if the tag
does not match the packaged version or if the two expected wheels are missing.

## Release Checklist

1. Merge the release workflow and confirm both wheel jobs pass on `main`.
2. Run the canonical local gate:

   ```text
   scripts/verify.sh
   ```

3. Create and push the annotated tag:

   ```text
   git tag -a v0.2.0 -m "Pine Compat Runtime v0.2.0"
   git push origin v0.2.0
   ```

4. Confirm the GitHub Release contains exactly two wheels plus the manifest and
   checksums.
5. Install each wheel in a clean matching environment and run the binding smoke
   test before making an application updater follow the release.

## Application Update Contract

An application updater should query the repository's latest stable GitHub
Release, download `manifest.json`, choose a wheel using Python compatibility
tags, verify its SHA-256 digest, and install it into a versioned plugin
directory. It must keep the previous version for rollback and activate a new
native extension only on process restart.

Do not install release wheels into a global Python environment, replace a
loaded `.pyd` or `.so` in place, consume pull-request artifacts, or silently
fall back to building from source on an end-user machine.
