"""Import explicit node definitions without granting provider control over the core.

A subscription is Clash YAML, a share-link list, or either one Base64-encoded. A Clash
document may name proxy providers: inline ones are read in place, HTTPS ones are fetched
once (they cannot name providers of their own), and local file providers are ignored.
Every node, however it arrived, passes the same field allowlist.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
from aiohttp.abc import AbstractResolver

from . import formats

MAX_BYTES = 2 * 1024 * 1024
MAX_NODES = 4096
MAX_PROVIDERS = 8
MAX_REDIRECTS = 5
_REDIRECTS = {301, 302, 303, 307, 308}
# Certificate verification for every hop; tests swap in a context that trusts a test CA.
_TLS: object = True
_COMMON = {"name", "type", "server", "port", "udp", "ip-version"}
_TLS = {"tls", "servername", "sni", "skip-cert-verify", "alpn", "client-fingerprint", "fingerprint"}
_STREAM = {"network", "ws-opts", "grpc-opts", "reality-opts", "ws-path", "ws-headers"}
_FIELDS = {
    "http": _TLS | {"username", "password"},
    "socks5": _TLS | {"username", "password"},
    "vless": _TLS | _STREAM | {"uuid", "flow", "packet-encoding"},
    "vmess": _TLS | _STREAM | {"uuid", "alterId", "cipher", "packet-encoding"},
    "hysteria2": _TLS | {"password", "up", "down", "ports", "mport", "obfs", "obfs-password"},
    "ss": {"cipher", "password", "udp-over-tcp"},
    "trojan": _TLS | _STREAM | {"password"},
    "anytls": _TLS | {"password"},
}
_NESTED = {
    "ws-opts": {"path", "headers", "max-early-data", "early-data-header-name"},
    "grpc-opts": {"grpc-service-name"},
    "reality-opts": {"public-key", "short-id"},
}


class SubscriptionError(ValueError):
    """Messages may be returned to callers and must never include input values."""


_LOADER = None


def _node_loader():
    """PyYAML loads on first parse: the browser version imports this module through the
    settings routes but has no PyYAML and never parses a subscription."""
    global _LOADER
    if _LOADER is None:
        import yaml

        class _NodeLoader(yaml.SafeLoader):
            depth = 0
            count = 0

            def compose_node(self, parent, index):
                self.count += 1
                if self.depth >= 40 or self.count > 100_000 or self.check_event(yaml.AliasEvent):
                    raise SubscriptionError("Unsupported YAML complexity or alias")
                self.depth += 1
                try:
                    return super().compose_node(parent, index)
                finally:
                    self.depth -= 1

        _LOADER = (yaml, _NodeLoader)
    return _LOADER


def _headers(value):
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )


def _supported(node):
    if not isinstance(node, dict) or not isinstance(node.get("type"), str):
        return False
    fields = _FIELDS.get(node["type"])
    if fields is None or node.keys() - (_COMMON | fields):
        return False
    if not isinstance(node.get("name"), str) or not 1 <= len(node["name"]) <= 160:
        return False
    if not isinstance(node.get("server"), str) or type(node.get("port")) is not int:
        return False
    for key, value in node.items():
        if key in _NESTED:
            if not isinstance(value, dict) or value.keys() - _NESTED[key]:
                return False
            for subkey, subvalue in value.items():
                if subkey == "headers":
                    if not _headers(subvalue):
                        return False
                elif type(subvalue) not in (str, int, bool):
                    return False
        elif key == "ws-headers":
            if not _headers(value):
                return False
        elif key == "alpn":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                return False
        elif type(value) not in (str, int, bool):
            return False
    return True


def source_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


@dataclass
class _Provider:
    url: str
    prefix: str = ""
    suffix: str = ""


@dataclass
class _Document:
    candidates: list = field(default_factory=list)
    skipped: int = 0
    providers: list = field(default_factory=list)

    def add(self, nodes, prefix="", suffix=""):
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("name"), str) and (prefix or suffix):
                node = dict(node, name=prefix + node["name"] + suffix)
            self.candidates.append(node)
        if len(self.candidates) + self.skipped > MAX_NODES:
            raise SubscriptionError(f"Subscription has more than {MAX_NODES} nodes")


def _affix(provider):
    override = provider.get("override")
    if not isinstance(override, dict):
        return "", ""
    prefix, suffix = override.get("additional-prefix", ""), override.get("additional-suffix", "")
    return (prefix if isinstance(prefix, str) else ""), (suffix if isinstance(suffix, str) else "")


def _read(raw: bytes, *, nested: bool = False) -> _Document:
    """Node candidates and HTTPS provider references in one fetched body."""
    if len(raw) > MAX_BYTES:
        raise SubscriptionError("Subscription exceeds size limit")
    try:
        text = raw.decode("utf-8").removeprefix("\ufeff")
    except UnicodeError:
        raise SubscriptionError("Invalid or unsupported subscription") from None
    text = formats.unwrap_base64(text) or text
    document = _Document()
    if formats.is_link_list(text):
        nodes, document.skipped = formats.parse_links(text)
        document.add(nodes)
        return document
    yaml, loader = _node_loader()
    try:
        data = yaml.load(text, Loader=loader)
    except (yaml.YAMLError, RecursionError, ValueError):
        raise SubscriptionError("Invalid or unsupported subscription YAML") from None
    data = data if isinstance(data, dict) else {}
    nodes = data.get("proxies")
    providers = None if nested else data.get("proxy-providers")  # A provider's providers are not followed.
    if (nodes is None and providers is None or nodes is not None and not isinstance(nodes, list)
            or providers is not None and not isinstance(providers, dict)):
        raise SubscriptionError("Expected Clash YAML proxies or proxy-providers, share links, or Base64 of either")
    document.add(nodes or [])
    for provider in (providers or {}).values():
        if not isinstance(provider, dict):
            continue
        prefix, suffix = _affix(provider)
        if provider.get("type") == "inline" and isinstance(provider.get("payload"), list):
            document.add(provider["payload"], prefix, suffix)
        elif provider.get("type") == "http" and isinstance(provider.get("url"), str):
            document.providers.append(_Provider(provider["url"], prefix, suffix))
        # File providers name paths on the provider's own disk and are ignored.
    if len(document.providers) > MAX_PROVIDERS:
        raise SubscriptionError(f"Subscription references more than {MAX_PROVIDERS} providers")
    return document


def _index(document: _Document, source: str):
    result = {}
    skipped = document.skipped
    prefix = source_id(source)
    for node in document.candidates:
        if not _supported(node):
            skipped += 1
            continue
        node_id = prefix + hashlib.sha256(node["name"].encode()).hexdigest()[:16]
        if node_id in result:
            if result[node_id] == node:
                continue  # The same node listed twice, e.g. by two providers.
            raise SubscriptionError("Duplicate node name in subscription")
        result[node_id] = node
    if not result:
        raise SubscriptionError("No supported nodes in subscription")
    return result, skipped


def parse_nodes(raw: bytes, source: str):
    """Nodes of a body that needs no further download, keyed by stable id, and the skipped count."""
    document = _read(raw)
    if document.providers:
        raise SubscriptionError("Subscription providers must be downloaded")
    return _index(document, source)


def _public(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return (getattr(value, "ipv4_mapped", None) or value).is_global


def _addresses(host, port, family):
    infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class _Resolver(AbstractResolver):
    """Only the host the user entered may resolve to a private or loopback address.

    Redirects and provider references come from the provider, so they may not point the
    backend at the local network. The check runs on the addresses the connection uses.
    """

    def __init__(self, trusted: str):
        self.trusted = trusted

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        addresses = await asyncio.to_thread(_addresses, host, port, family)
        if not addresses:
            raise OSError("no address")
        if host.rstrip(".").lower() != self.trusted and not all(map(_public, addresses)):
            raise SubscriptionError("Subscription redirect or provider points to a private address")
        return [{"hostname": host, "host": address, "port": port,
                 "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                 "proto": 0, "flags": socket.AI_NUMERICHOST | socket.AI_NUMERICSERV} for address in addresses]

    async def close(self):
        pass


def _hop(url: str, trusted: str) -> str:
    """An HTTPS URL the provider sent (redirect or provider reference), without its fragment."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or "@" in parsed.netloc:
        raise SubscriptionError("Subscription redirect or provider is not an HTTPS URL")
    parsed.port  # Raises ValueError on a malformed port.
    host = parsed.hostname.rstrip(".")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and host != trusted and not _public(host):
        raise SubscriptionError("Subscription redirect or provider points to a private address")
    return urlunsplit(parsed._replace(fragment=""))


async def _fetch(session, url, trusted, label):
    for _ in range(MAX_REDIRECTS + 1):
        async with session.get(url, allow_redirects=False) as response:
            if response.status in _REDIRECTS:
                location = response.headers.get("Location")
                if not location:
                    raise SubscriptionError(f"{label} redirected without a location")
                url = _hop(urljoin(url, location), trusted)
                continue
            if response.status != 200:
                raise SubscriptionError(f"{label} returned HTTP {response.status}")
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise SubscriptionError(f"{label} exceeds size limit")
            return bytes(body)
    raise SubscriptionError(f"{label} redirected more than {MAX_REDIRECTS} times")


async def download(url: str):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.fragment:
            raise SubscriptionError("Expected an HTTPS subscription URL")
        trusted = parsed.hostname.rstrip(".")
        async with asyncio.timeout(60):
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20), headers={"User-Agent": "clash-verge/CandleScope"},
                connector=aiohttp.TCPConnector(resolver=_Resolver(trusted), ssl=_TLS),
            ) as session:
                document = await asyncio.to_thread(_read, await _fetch(session, url, trusted, "Subscription"))
                for provider in document.providers:
                    try:
                        body = await _fetch(session, _hop(provider.url, trusted), trusted, "Subscription provider")
                    except (aiohttp.ClientError, OSError, TimeoutError):
                        raise SubscriptionError("Could not fetch a subscription provider") from None
                    nested = await asyncio.to_thread(_read, body, nested=True)
                    document.skipped += nested.skipped
                    document.add(nested.candidates, provider.prefix, provider.suffix)
        return await asyncio.to_thread(_index, document, url)
    except SubscriptionError:
        raise
    except (aiohttp.ClientError, OSError, ValueError, TimeoutError):
        raise SubscriptionError("Could not fetch subscription") from None
