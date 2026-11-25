# Releasing the desktop app

Pushing a version tag runs **Actions → Desktop release**. It builds every desktop
package, checks it, and opens a **draft** GitHub Release. Nothing becomes public
until a maintainer reviews the draft and publishes it.

| Package | Built on | File |
|---|---|---|
| macOS, Apple silicon | `macos-15` | `CandleScope-<version>-macos-arm64.dmg` and `.zip` |
| macOS, Intel | `macos-15-intel` | `CandleScope-<version>-macos-x64.dmg` and `.zip` |
| Windows 10/11, x64 | `windows-latest` | `CandleScope-<version>-windows-x64-setup.exe` |

The release also carries `SHA256SUMS` and `build-manifests.json`, which records the
commit and CI run that produced each package.

## Steps

1. In one PR, set the new version in all three places, and merge it:
   - `"version"` in `frontend/package.json`;
   - the two `"version"` fields at the top of `frontend/package-lock.json`;
   - `APP_VERSION` in `backend/app/core/version.py`.

   In the same PR, rename `## Unreleased` in `RELEASE_NOTES.md` to the version,
   for example `## 1.0.0 (2026-11-30)`, and start a new empty `## Unreleased` above it.
2. Tag the merge commit on `main` and push the tag:

   ```sh
   git fetch origin
   git tag v1.0.0 origin/main
   git push origin v1.0.0
   ```

   The tag must be `v` plus the version from step 1. A version with a suffix,
   such as `1.1.0-rc.1`, becomes a prerelease.
3. Wait for the run to finish, then open the draft from the run summary or
   **Releases**. Check the file list and notes, download a package and try it.
4. Choose **Publish release** and leave **Set as the latest release** ticked.
   The README's Download link and release badge follow the latest `v*` release.

Rerunning a failed tag run refreshes its own draft. Once a release is published,
the workflow refuses to replace it: fix the problem and tag a new version.

## What the run checks

- **Before building:** the tag, both version files and the release notes
  section all name the same version.
- **On each macOS build:**
  - It runs the desktop host tests.
  - It packages the app with the bundled Python.
  - It runs the backend regression list on that Python.
  - It unpacks the ZIP into a new folder, then launches and restarts the app from there.
- **On the Windows build:**
  - It runs the desktop host tests, packages the installer, and checks the sidecar
    and retired-Pyne rejection on the bundled Python.
  - It uses the qualified CCXT fork wheel, checked against the SHA-256 in
    `backend/ccxt-fork.lock.json`. The macOS jobs rebuild that pure-Python wheel
    from the pinned source and must match the same hash.
  - It installs silently into a folder with a space in its name, then launches and
    restarts the installed app.
  - It uninstalls silently and confirms that user data in `%APPDATA%\CandleScope Replay` is kept.
- **When assembling:**
  - Every package must come from the tagged commit and match the checksum that its
    build recorded.
  - Exactly the files in the table above must be present.

Pull requests that change the release workflow, and manual runs from
**Run workflow**, do all of this as a dry run. They upload the assembled release
as a workflow artifact and publish nothing.

## Signing

The packages are not signed with a paid certificate:

- **macOS:** builds are ad-hoc signed, without an Apple Developer ID or
  notarization. Users allow the first launch in
  **System Settings → Privacy & Security → Open Anyway**.
- **Windows:** the installer is unsigned. Users choose
  **More info → Run anyway** in the SmartScreen prompt.

The release notes and both READMEs give these steps. Signing later needs:

- **macOS:** an Apple Developer Program membership, a Developer ID certificate and
  notarization credentials stored as repository secrets.
- **Windows:** a code signing certificate or signing service.

An in-app updater on macOS also needs a Developer ID signature. Until then, users
update by downloading the new release.
