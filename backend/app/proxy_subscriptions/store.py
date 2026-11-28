"""Encrypted, immutable subscription snapshots referenced by ordinary pool settings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from cryptography.fernet import Fernet

from .source import SubscriptionError

REFERENCE = re.compile(r"mihomo://([0-9a-f]{64})/([0-9a-f]{32})\Z")


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = root

    def _cipher(self, create):
        try:
            if sys.platform == "darwin":
                from keyring.backends.macOS import Keyring
            elif sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring as Keyring
            else:
                raise SubscriptionError("Subscription storage requires macOS or Windows")
            vault = Keyring()
            # The namespace follows the data folder when it moves (see secret_namespace_origin).
            from app.core.profile_relocation import secret_namespace_origin
            profile = hashlib.sha256(secret_namespace_origin(self.root).encode()).hexdigest()
            service = "CandleScope.proxy-subscriptions"
            key = vault.get_password(service, profile)
            if key is None and create:
                from app.plugin_security_v2.storage import security_lock
                with security_lock(self.root / ".key.lock"):
                    key = vault.get_password(service, profile)
                    if key is None:
                        key = Fernet.generate_key().decode()
                        vault.set_password(service, profile, key)
            return Fernet(key)
        except SubscriptionError:
            raise
        except Exception:
            raise SubscriptionError("Subscription credential store unavailable") from None

    def save(self, url, nodes):
        payload = json.dumps({"url": url, "nodes": nodes}, sort_keys=True).encode()
        revision = hashlib.sha256(payload).hexdigest()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        cipher = self._cipher(create=True)
        descriptor, name = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as out:
                out.write(cipher.encrypt(payload))
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.root / revision)
        finally:
            Path(name).unlink(missing_ok=True)
        return [{"id": "sub_" + key, "name": node["name"], "url": f"mihomo://{revision}/{key}",
                 "egress_group": "shared", "enabled": True} for key, node in nodes.items()]

    def read(self, revision):
        if not re.fullmatch("[0-9a-f]{64}", revision):
            raise SubscriptionError("Invalid subscription reference")
        try:
            raw = self._cipher(create=False).decrypt((self.root / revision).read_bytes())
            if hashlib.sha256(raw).hexdigest() != revision:
                raise SubscriptionError("Incorrect subscription snapshot")
            return json.loads(raw)
        except Exception:
            raise SubscriptionError("Saved subscription unavailable") from None
