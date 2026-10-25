"""Self-contained, lossless storage for large replay checkpoints.

The 64 MiB limit applies to the actual stored representation. Decoding has a
separate finite limit; neither IPC limits nor execution deadlines change.
Legacy JSON checkpoints remain readable. Financial checksums cover the complete
decoded value, independently of the storage envelope checksum.
"""
import base64
import hashlib
import json
import math
import zlib

from .native import MAX_BYTES, encoded

SCHEMA = "candlescope.replay-checkpoint-zlib/1"
MAX_DECODED_BYTES = 256 * 1024 * 1024
COMPRESS_FROM_BYTES = 1024 * 1024


def detached_json(value, *, preserve_aliases=True):
    """Normalize owned checkpoint data without expanding shared JSON graphs.

    Mutable containers are detached from the caller. By default repeated references
    share one detached copy; public views can request independent containers for
    every occurrence instead. Serialized values stay identical to
    the previous JSON round trip. Non-JSON values retain that round trip's
    default=str and key-conversion semantics.
    """
    memo, active = {}, set()

    def clone(item):
        kind = type(item)
        if kind in (str, int, bool, type(None)):
            return item
        if kind is float:
            if not math.isfinite(item):
                raise ValueError("Out of range float values are not JSON compliant")
            return item
        if kind not in (dict, list, tuple) or (kind is dict and any(type(key) is not str for key in item)):
            return json.loads(json.dumps(item, default=str, allow_nan=False))
        key = id(item)
        if key in active:
            raise ValueError("Circular reference detected")
        if preserve_aliases and key in memo:
            return memo[key]
        active.add(key)
        result = {} if kind is dict else []
        if preserve_aliases:
            memo[key] = result
        try:
            if kind is dict:
                result.update((name, clone(child)) for name, child in item.items())
            else:
                result.extend(clone(child) for child in item)
        finally:
            active.remove(key)
        return result

    return clone(value)


def canonical_fragments(value):
    """Yield the existing canonical JSON bytes, chunking large history arrays.

    Short lists are traversed so delta-operation and plot wrappers do not hide
    large arrays. History rows are encoded in C in groups of 512, retaining the
    standard encoder's numeric, escaping and key-order rules.
    """
    active = set()

    def fragments(item):
        kind = type(item)
        if kind is dict and all(type(key) is str for key in item):
            if id(item) in active:
                raise ValueError("Circular reference detected")
            active.add(id(item))
            try:
                yield b"{"
                for index, key in enumerate(sorted(item)):
                    if index:
                        yield b","
                    yield (encoded(key) + ":").encode("utf-8")
                    yield from fragments(item[key])
                yield b"}"
            finally:
                active.remove(id(item))
        elif kind in (list, tuple):
            if id(item) in active:
                raise ValueError("Circular reference detected")
            active.add(id(item))
            try:
                yield b"["
                if len(item) <= 16:
                    for index, child in enumerate(item):
                        if index:
                            yield b","
                        yield from fragments(child)
                else:
                    for start in range(0, len(item), 512):
                        if start:
                            yield b","
                        yield encoded(item[start:start+512])[1:-1].encode("utf-8")
                yield b"]"
            finally:
                active.remove(id(item))
        else:
            yield encoded(item).encode("utf-8")

    yield from fragments(value)


def checkpoint_measure(value):
    """Hash complete canonical JSON and count its bytes in the same pass."""
    checksum, size = hashlib.sha256(), 0
    for fragment in canonical_fragments(value):
        checksum.update(fragment)
        size += len(fragment)
    return "sha256:" + checksum.hexdigest(), size


def checkpoint_digest(value):
    return checkpoint_measure(value)[0]


def _pack_fragments(fragments, fallback):
    size, checksum = 0, hashlib.sha256()
    raw, compressed = [], []
    compressor = None
    for fragment in fragments:
        size += len(fragment)
        if size > MAX_DECODED_BYTES:
            raise ValueError("replay checkpoint decoded size exceeds 256 MiB")
        checksum.update(fragment)
        if compressor is None:
            raw.append(fragment)
            if size < COMPRESS_FROM_BYTES:
                continue
            compressor = zlib.compressobj(level=1)
            for part in raw:
                compressed.append(compressor.compress(part))
            raw.clear()
            del part
        else:
            compressed.append(compressor.compress(fragment))
    if compressor is None:
        return b"".join(raw).decode("utf-8")
    compressed.append(compressor.flush())
    compressed_bytes = b"".join(compressed)
    del compressed, compressor
    payload_bytes = base64.b64encode(compressed_bytes)
    del compressed_bytes
    payload = payload_bytes.decode("ascii")
    del payload_bytes
    # Base64 only contains JSON-safe ASCII; keep the same canonical key order
    # without creating a second escaped copy of the complete payload.
    envelope = "".join((
        encoded({"decoded_bytes": size, "decoded_sha256": checksum.hexdigest()})[:-1],
        ',"payload":"', payload, '","storage_schema":', encoded(SCHEMA), "}",
    ))
    del payload
    # Incompressible values retain the legacy raw representation. Normal large
    # histories avoid allocating their complete raw string and byte copy.
    stored_size = len(envelope) if envelope.isascii() else len(envelope.encode("utf-8"))
    return envelope if stored_size < size else fallback()


def pack(value):
    return _pack_fragments(canonical_fragments(value), lambda: encoded(value))


def pack_with_checksum(value):
    """Seal and store a checkpoint in one complete content-encoding pass.

    The financial checksum covers the unchanged canonical content. Its field
    is appended last in the stored JSON, so compression can consume the body
    before that checksum is known. The existing envelope hashes every stored
    decoded byte; existing readers recover the same complete sealed value.
    Generic pack() keeps its original canonical stored representation.
    """
    if type(value) is not dict or "checksum" in value:
        raise ValueError("unsealed checkpoint dictionary required")
    sealed = []

    def fragments():
        content = hashlib.sha256()
        previous = None
        for fragment in canonical_fragments(value):
            content.update(fragment)
            if previous is not None:
                yield previous
            previous = fragment
        if previous != b"}":
            raise ValueError("checkpoint dictionary terminator differs")
        checksum = "sha256:" + content.hexdigest()
        sealed.append(checksum)
        yield (("," if value else "") + '"checksum":' + encoded(checksum) + "}").encode("utf-8")

    stored = _pack_fragments(fragments(), lambda: encoded({**value, "checksum": sealed[0]}))
    return stored, sealed[0]


def unpack(raw):
    # Large legacy checkpoints can exceed the new stored-size ceiling; they
    # remain readable under the same finite decoded limit.
    if len(raw.encode("utf-8")) > MAX_DECODED_BYTES:
        raise ValueError("replay checkpoint decoded size exceeds 256 MiB")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("storage_schema") != SCHEMA:
        return value
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("stored replay checkpoint exceeds 64 MiB")
    size = value.get("decoded_bytes")
    if type(size) is not int or not 0 <= size <= MAX_DECODED_BYTES:
        raise ValueError("invalid replay checkpoint decoded size")
    try:
        compressed = base64.b64decode(value["payload"], validate=True)
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed, size + 1)
    except (KeyError, TypeError, ValueError, zlib.error) as exc:
        raise ValueError("invalid compressed replay checkpoint") from exc
    if (len(decoded) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or hashlib.sha256(decoded).hexdigest() != value.get("decoded_sha256")):
        raise ValueError("replay checkpoint size or checksum mismatch")
    # Avoid retaining both the decompressed bytes and json.loads' implicit
    # Unicode copy while constructing a large parsed checkpoint graph.
    text = decoded.decode("utf-8")
    del decoded, compressed, value, decoder
    return json.loads(text)
