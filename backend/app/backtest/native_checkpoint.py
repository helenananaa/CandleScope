"""Self-contained, lossless storage for large replay checkpoints.

The 64 MiB limit applies to the actual stored representation. Decoding has a
separate finite limit; neither IPC limits nor execution deadlines change.
Legacy JSON checkpoints remain readable. Financial checksums cover the complete
decoded value, independently of the storage envelope checksum.
"""
import base64
import hashlib
import json
import zlib

from .native import MAX_BYTES, encoded

SCHEMA = "candlescope.replay-checkpoint-zlib/1"
MAX_DECODED_BYTES = 256 * 1024 * 1024
COMPRESS_FROM_BYTES = 1024 * 1024


def pack(value):
    raw = encoded(value).encode("utf-8")
    if len(raw) > MAX_DECODED_BYTES:
        raise ValueError("replay checkpoint decoded size exceeds 256 MiB")
    if len(raw) < COMPRESS_FROM_BYTES:
        return raw.decode("utf-8")
    compressed = zlib.compress(raw, level=1)
    envelope = encoded({"storage_schema": SCHEMA, "decoded_bytes": len(raw),
        "decoded_sha256": hashlib.sha256(raw).hexdigest(),
        "payload": base64.b64encode(compressed).decode("ascii")})
    return envelope if len(envelope.encode("utf-8")) < len(raw) else raw.decode("utf-8")


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
    return json.loads(decoded)
