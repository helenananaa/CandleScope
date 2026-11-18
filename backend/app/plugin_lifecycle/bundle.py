"""Streaming verification of unified archives; validation never imports entries."""

from __future__ import annotations

import hashlib
import os
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import (
    JsonLimits,
    PlatformContractError,
    canonical_dumps,
    loads_strict,
)
from candlescope_plugin_sdk.unified import Manifest, ManifestError
from candlescope_plugin_sdk.unified.manifest import MAX_MANIFEST_BYTES, package_path

from .appearance import MAX_APPEARANCE_BYTES, appearance_kind, parse_appearance
from .paths import is_link

BUNDLE_SCHEMA = "candlescope.unified-bundle/1"
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_FILES = 1024
MAX_DESCRIPTOR_BYTES = 1024 * 1024
CHUNK = 1024 * 1024
MAX_DIRECTORY_BYTES = MAX_FILES * 1024


class PackageError(ValueError):
    """The archive cannot be staged or used as a unified package."""


@dataclass(frozen=True, slots=True)
class VerifiedPackage:
    manifest: Manifest
    sha256: str
    size: int

    def review(self) -> dict:
        return {
            "packageSha256": self.sha256,
            "size": self.size,
            "manifest": self.manifest.to_wire(),
            "publisherVerified": False,
        }


def _digest(stream, limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(CHUNK):
        size += len(block)
        if size > limit:
            raise PackageError("package content exceeds its byte budget")
        digest.update(block)
    return "sha256:" + digest.hexdigest(), size


def _directory_budget(stream, size: int) -> None:
    """Bound ZIP metadata before ZipFile allocates per-member Python objects.

    Our file/byte budgets never require ZIP64 or multi-volume records. Candidate
    packages also omit archive comments/trailing bytes to keep one exact layout.
    """
    if size < 22:
        raise PackageError("truncated archive")
    stream.seek(-22, os.SEEK_END)
    signature, disk, directory_disk, local_count, count, length, offset, comment = (
        struct.unpack("<4s4H2LH", stream.read(22))
    )
    if (
        signature != b"PK\x05\x06"
        or disk
        or directory_disk
        or comment
        or local_count != count
        or not 2 <= count <= MAX_FILES
        or length > MAX_DIRECTORY_BYTES
        or offset + length != size - 22
    ):
        raise PackageError(
            "unsupported or over-budget ZIP directory, comment or trailing data"
        )
    stream.seek(offset)
    directory = stream.read(length)
    cursor = 0
    actual_count = 0
    while cursor < length:
        if cursor + 46 > length or directory[cursor : cursor + 4] != b"PK\x01\x02":
            raise PackageError("invalid ZIP directory record")
        name_size, extra_size, comment_size = struct.unpack_from(
            "<3H", directory, cursor + 28
        )
        actual_count += 1
        if (
            actual_count > count
            or name_size > 180
            or extra_size > 256
            or comment_size > 256
        ):
            raise PackageError("ZIP directory metadata exceeds its budget")
        cursor += 46 + name_size + extra_size + comment_size
    if actual_count != count or cursor != length:
        raise PackageError("ZIP directory count or length mismatch")
    stream.seek(0)


def verify_package(path: Path | str) -> VerifiedPackage:
    """Verify exact archive bytes, portable names, envelope and every member.

    Limits match the existing platform bundle's conservative byte budgets.
    No extraction, dependency installation, source import or probe execution.
    """
    path = Path(path)
    if is_link(path) or not path.is_file():
        raise PackageError("package must be a regular file, not a symlink or device")
    try:
        with path.open("rb") as stream:
            details = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(details.st_mode)
                or not 0 < details.st_size <= MAX_PACKAGE_BYTES
            ):
                raise PackageError("package must be a bounded regular file")
            sha256, size = _digest(stream, MAX_PACKAGE_BYTES)
            _directory_budget(stream, size)
            with zipfile.ZipFile(stream) as archive:
                infos = archive.infolist()
                if not 2 <= len(infos) <= MAX_FILES:
                    raise PackageError("archive file count is outside its budget")
                names = {info.filename for info in infos}
                if "manifest.json" in names and "bundle.json" not in names:
                    # Preserve the retired-language diagnostic for historical manifests.
                    with archive.open("manifest.json") as source:
                        Manifest.from_json(source.read(MAX_MANIFEST_BYTES + 1))
                    raise PackageError(
                        "unified bundle.json is required; update old packages"
                    )
                files = {}
                folded = set()
                total = 0
                for info in infos:
                    name = package_path(info.orig_filename)
                    mode = stat.S_IFMT(info.external_attr >> 16)
                    if (
                        name != info.filename
                        or info.is_dir()
                        or mode not in {0, stat.S_IFREG}
                        or info.flag_bits & 1
                        or name.casefold() in folded
                    ):
                        raise PackageError(
                            "archive contains ambiguous, linked or encrypted files"
                        )
                    if info.compress_type not in {
                        zipfile.ZIP_STORED,
                        zipfile.ZIP_DEFLATED,
                    }:
                        raise PackageError("unsupported archive compression")
                    if (
                        not 0 <= info.file_size <= MAX_FILE_BYTES
                        or info.file_size > max(1, info.compress_size) * 100
                    ):
                        raise PackageError(
                            "archive member exceeds its expansion budget"
                        )
                    folded.add(name.casefold())
                    files[name] = info
                    total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise PackageError("archive expanded bytes exceed their budget")
                for name in folded:
                    parts = name.split("/")
                    if any(
                        "/".join(parts[:end]) in folded for end in range(1, len(parts))
                    ):
                        raise PackageError("archive file/directory paths collide")
                if "manifest.json" not in files:
                    raise PackageError(
                        "unified manifest.json and bundle.json are required; update old packages"
                    )
                if files["manifest.json"].file_size > MAX_MANIFEST_BYTES:
                    raise PackageError("manifest exceeds its byte budget")
                if "bundle.json" not in files:
                    raise PackageError(
                        "unified bundle.json is required; update old packages"
                    )
                manifest = Manifest.from_json(archive.read(files["manifest.json"]))
                if files["bundle.json"].file_size > MAX_DESCRIPTOR_BYTES:
                    raise PackageError("bundle descriptor exceeds its byte budget")
                envelope = loads_strict(
                    archive.read(files["bundle.json"]),
                    limits=JsonLimits(
                        max_message_bytes=MAX_DESCRIPTOR_BYTES,
                        max_depth=8,
                        max_container_items=MAX_FILES,
                        max_string_bytes=4096,
                    ),
                )
                if (
                    not isinstance(envelope, dict)
                    or set(envelope) != {"schema", "files"}
                    or envelope["schema"] != BUNDLE_SCHEMA
                    or not isinstance(envelope["files"], dict)
                ):
                    raise PackageError("unsupported unified bundle envelope")
                declared = envelope["files"]
                if set(declared) != set(files) - {"bundle.json"}:
                    raise PackageError(
                        "envelope must pin every other archive member exactly once"
                    )
                for name, expected in declared.items():
                    if (
                        not isinstance(expected, dict)
                        or set(expected) != {"sha256", "size"}
                        or type(expected["size"]) is not int
                        or expected["size"] != files[name].file_size
                    ):
                        raise PackageError("envelope member metadata is invalid")
                    with archive.open(files[name]) as content:
                        actual_sha, actual_size = _digest(content, MAX_FILE_BYTES)
                    if (
                        actual_sha != expected["sha256"]
                        or actual_size != expected["size"]
                    ):
                        raise PackageError(f"archive member digest mismatch: {name}")
                if any(entry.path not in declared for entry in manifest.entries):
                    raise PackageError(
                        "every entry must reference a pinned archive file"
                    )
                for entry in manifest.entries:
                    if kind := appearance_kind(entry):
                        with archive.open(files[entry.path]) as source:
                            parse_appearance(
                                kind,
                                source.read(MAX_APPEARANCE_BYTES + 1),
                                manifest.trust,
                            )
            return VerifiedPackage(manifest, sha256, size)
    except PackageError:
        raise
    except (
        OSError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        PlatformContractError,
        ManifestError,
    ) as exc:
        raise PackageError(f"invalid unified package: {exc}") from exc


def build_package(source: Path | str, destination: Path | str) -> VerifiedPackage:
    """Build deterministic candidate bytes outside the source tree, without executing.

    The envelope is generated from bytes actually written. Existing destinations
    are never replaced; source symlinks and pre-existing envelopes are rejected.
    """
    source, destination = Path(source), Path(destination)
    if is_link(source) or not source.is_dir():
        raise PackageError("package source must be a regular directory")
    source = source.resolve()
    destination = destination.absolute()
    if destination.resolve().is_relative_to(source):
        raise PackageError("package output must be outside its source directory")
    if destination.exists() or is_link(destination):
        raise PackageError("package output already exists")
    files = []
    for scanned, path in enumerate(source.rglob("*"), 1):
        if scanned > MAX_FILES * 2:
            raise PackageError("source tree exceeds its path budget")
        if is_link(path):
            raise PackageError("package source must not contain symlinks")
        if path.is_dir():
            continue
        name = package_path(path.relative_to(source).as_posix())
        if name == "bundle.json" or not path.is_file():
            raise PackageError("source contains a generated envelope or non-file asset")
        files.append((name, path))
        if len(files) >= MAX_FILES:
            raise PackageError("too many source files")
    files.sort(key=lambda item: item[0])
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".unified-build-", suffix=".cspkg", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        declared = {}
        total = 0
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, path in files:
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                digest, size = hashlib.sha256(), 0
                with path.open("rb") as content, archive.open(info, "w") as output:
                    while block := content.read(CHUNK):
                        size += len(block)
                        total += len(block)
                        if size > MAX_FILE_BYTES or total > MAX_PACKAGE_BYTES:
                            raise PackageError(
                                "source bytes exceed their package budget"
                            )
                        output.write(block)
                        digest.update(block)
                declared[name] = {
                    "sha256": "sha256:" + digest.hexdigest(),
                    "size": size,
                }
            info = zipfile.ZipInfo("bundle.json", date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(
                info, canonical_dumps({"schema": BUNDLE_SCHEMA, "files": declared})
            )
        verified = verify_package(temporary)
        # Windows requires a writable handle to flush file contents.
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        # Link is an atomic create-if-absent on the same filesystem. It cannot
        # overwrite an existing user artifact created during the build.
        os.link(temporary, destination)
        if os.name != "nt":
            directory = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return verified
    finally:
        temporary.unlink(missing_ok=True)
