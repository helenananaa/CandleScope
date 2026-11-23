"""Verify local plugin archives and reject the retired script bundle format."""

import zipfile
from pathlib import Path

from app.plugin_installer_v2.bundle import verify_platform_bundle

from .errors import core_error


def verify_local_platform_bundle(path: Path, **kwargs):
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        names = set()
    if "manifest.json" in names and "bundle.json" not in names:
        raise core_error(
            "PLUGIN_SCRIPT_RUNTIME_UPDATE_REQUIRED",
            "This script runtime package uses a retired format. Obtain an updated unified plugin package.",
        )
    return verify_platform_bundle(path, **kwargs)
