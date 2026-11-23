"""Import explicit node definitions without granting provider control over the core."""
from __future__ import annotations

import asyncio
import hashlib
from urllib.parse import urlsplit

import aiohttp

MAX_BYTES = 2 * 1024 * 1024
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


def parse_nodes(raw: bytes, source: str):
    if len(raw) > MAX_BYTES:
        raise SubscriptionError("Subscription exceeds size limit")
    yaml, loader = _node_loader()
    try:
        data = yaml.load(raw, Loader=loader)
    except (yaml.YAMLError, UnicodeError, RecursionError, ValueError):
        raise SubscriptionError("Invalid or unsupported subscription YAML") from None
    nodes = data.get("proxies") if isinstance(data, dict) else None
    if not isinstance(nodes, list) or len(nodes) > 4096:
        raise SubscriptionError("Expected a Clash YAML proxies list (maximum 4096 nodes)")
    result = {}
    prefix = source_id(source)
    for node in nodes:
        if not _supported(node):
            continue
        node_id = prefix + hashlib.sha256(node["name"].encode()).hexdigest()[:16]
        if node_id in result:
            raise SubscriptionError("Duplicate node name in subscription")
        result[node_id] = node
    if not result:
        raise SubscriptionError("No supported nodes in subscription")
    return result, len(nodes) - len(result)


async def download(url: str):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.fragment:
            raise SubscriptionError("Expected an HTTPS subscription URL")
        body = bytearray()
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20), headers={"User-Agent": "clash-verge/CandleScope"}
        ) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    raise SubscriptionError(f"Subscription returned HTTP {response.status}")
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise SubscriptionError("Subscription exceeds size limit")
        return await asyncio.to_thread(parse_nodes, bytes(body), url)
    except SubscriptionError:
        raise
    except (aiohttp.ClientError, OSError, ValueError, TimeoutError):
        raise SubscriptionError("Could not fetch subscription") from None
