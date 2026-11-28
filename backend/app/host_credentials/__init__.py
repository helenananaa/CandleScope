"""Secrets CandleScope keeps for the user, in the OS secret store (see vault.py)."""
from .vault import (
    CredentialStore,
    CredentialVaultError,
    MAX_SECRET_CHARS,
    open_host_vault,
    vault_supported,
)

__all__ = [
    "CredentialStore",
    "CredentialVaultError",
    "MAX_SECRET_CHARS",
    "open_host_vault",
    "vault_supported",
]
