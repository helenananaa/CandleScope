"""Dev preview only: the account service reports Windows Credential Manager as its key store.

Keys are still kept in this Mac's Keychain; only the store name the panel reads changes.
"""
from app.readonly_accounts import service

service.credential_store = lambda platform=None: "windows-credential-manager"

from app.main import app  # noqa: E402,F401
