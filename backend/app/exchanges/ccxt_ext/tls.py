"""Process-wide TLS contexts for CandleScope's CCXT async clients.

CCXT 4.5.60 ``async_support.Exchange.open()`` builds
``ssl.create_default_context(cafile=certifi.where())`` for every client.  With
OpenSSL 3 that CA-bundle parse costs 0.5-1.8 s, and ``open()`` runs on the event
loop, so every pooled REST rail, ccxt.pro session and reconnect stalled the
loop for that long.  The contexts here are built once per process and shared:
aiohttp only reads a caller-supplied context (it shares its own defaults the
same way).
"""

from __future__ import annotations

import logging
import ssl
import threading

import certifi

logger = logging.getLogger(__name__)

_contexts: dict[tuple[str | None, bool], ssl.SSLContext] = {}
_contexts_lock = threading.Lock()


def shared_ssl_context(
    cafile: str | None,
    *,
    include_os_certificates: bool = False,
) -> ssl.SSLContext:
    """Return the verifying context CCXT ``open()`` would build for ``cafile``.

    The context is shared by every client in the process: do not mutate it.
    """

    key = (cafile, include_os_certificates)
    context = _contexts.get(key)
    if context is not None:
        return context
    with _contexts_lock:
        context = _contexts.get(key)
        if context is None:
            context = ssl.create_default_context(cafile=cafile)
            if include_os_certificates:
                os_cafile = ssl.get_default_verify_paths().cafile
                if os_cafile and os_cafile != cafile:
                    context.load_verify_locations(cafile=os_cafile)
            _contexts[key] = context
    return context


def start_shared_ssl_context_warmup() -> threading.Thread:
    """Build the default CCXT context on a thread before the first client opens.

    OpenSSL releases the GIL while it parses the CA file, so the event loop
    keeps running.  A client that opens meanwhile waits for this build instead
    of starting a second one.
    """

    def build() -> None:
        try:
            shared_ssl_context(certifi.where())
        except Exception:
            # The first client's open() retries and reports the failure.
            logger.warning("CCXT TLS context warm-up failed", exc_info=True)

    thread = threading.Thread(target=build, name="ccxt-tls-warmup", daemon=True)
    thread.start()
    return thread


class SharedSslContextMixin:
    """Hand a CCXT async client the shared context before ``Exchange.open()``.

    Follows CCXT's own rules: a falsy ``verify`` keeps ``ssl=False``, a context
    already set on the client wins, and ``cafile`` plus the
    ``include_OS_certificates`` option select which shared context is used.
    """

    def open(self) -> None:
        if self.ssl_context is None and self.verify:
            self.ssl_context = shared_ssl_context(
                self.cafile,
                include_os_certificates=bool(
                    self.safe_bool(self.options, "include_OS_certificates", False)
                ),
            )
        super().open()  # type: ignore[misc]
