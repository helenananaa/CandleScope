"""Non-credential desktop endpoint discovery for an explicitly enabled client."""

import os
import uuid
from pathlib import Path

from .wire import encode

ENDPOINT_SCHEMA = "candlescope.external-provider-endpoint/1"


def instance_id() -> str:
    return os.environ.setdefault("CANDLESCOPE_EXTERNAL_PROVIDER_INSTANCE_ID", uuid.uuid4().hex)


def publish(path: Path, *, host: str, port: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encode({"schema_version": ENDPOINT_SCHEMA, "host": host, "port": port, "instance_id": instance_id()}))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
