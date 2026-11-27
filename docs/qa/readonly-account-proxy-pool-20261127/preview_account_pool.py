"""Dev preview only: an account session that runs on a pool route with no Keychain and no exchange calls."""
import asyncio

from app.readonly_accounts import service


class _Vault:
    def read(self, key):
        return {"apiKey": "preview", "secret": "preview", "password": "preview"}

    def delete(self, key):
        pass


class _Sync:
    def __init__(self, repository, client, *, state_changed, network_result):
        self.stream_status, self.last_ws_received_ms, self.ws_error = "live", None, None
        self.changed = asyncio.Event()

    def observe(self, message):
        pass

    async def initialize(self, uid):
        pass

    async def run(self):
        await asyncio.Event().wait()


service.ReadOnlyAccountService._vault = lambda self: _Vault()
service.AccountSynchronizer = _Sync

from app.main import app  # noqa: E402,F401
