"""Share links and Base64 bodies, turned into the node fields a Clash YAML list carries.

Every node made here still passes source._supported, so a link can never set a field
that a YAML subscription could not. A link that cannot be converted is counted as
skipped, never guessed at.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from urllib.parse import parse_qsl, unquote, urlsplit

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_BASE64 = re.compile(r"[A-Za-z0-9+/_-]+={0,2}")
_TRUE = {"1", "true"}


def _base64_text(value: str) -> str:
    value = "".join(value.split()).replace("-", "+").replace("_", "/")
    value += "=" * (-len(value) % 4)
    return base64.b64decode(value, validate=True).decode("utf-8")


def unwrap_base64(text: str) -> str | None:
    """The text a Base64 subscription body encodes, or None if it is not one."""
    compact = "".join(text.split())
    if len(compact) < 8 or not _BASE64.fullmatch(compact):
        return None
    try:
        return _base64_text(compact).removeprefix("﻿")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def _entries(text):
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


def is_link_list(text: str) -> bool:
    """Share-link lists start with a scheme; Clash YAML never does."""
    first = next(_entries(text), "")
    return bool(_SCHEME.match(first))


def parse_links(text: str) -> tuple[list[dict], int]:
    nodes, skipped = [], 0
    for line in _entries(text):
        node = share_link(line)
        if node is None:
            skipped += 1
        else:
            nodes.append(node)
    return nodes, skipped


def share_link(link: str) -> dict | None:
    scheme = link.partition("://")[0].lower()
    convert = _CONVERTERS.get(scheme)
    if convert is None:
        return None
    try:
        return convert(link)
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error, UnicodeError):
        return None


def _query(parts):
    return {key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)}


def _address(parts):
    if not parts.hostname or parts.port is None:
        raise ValueError("missing server or port")
    return parts.hostname, parts.port


def _userinfo(parts):
    """The raw secret before '@'; urlsplit would split a ':' inside it into two fields."""
    if "@" not in parts.netloc:
        raise ValueError("missing secret")
    return unquote(parts.netloc.rpartition("@")[0])


def _named(node, fragment):
    node["name"] = unquote(fragment).strip() or f"{node['type']} {node['server']}:{node['port']}"
    return node


def _tls(node, query, *, sni="sni"):
    if query.get("sni") or query.get("peer"):
        node[sni] = query.get("sni") or query["peer"]
    if query.get("alpn"):
        node["alpn"] = [item for item in query["alpn"].split(",") if item]
    if query.get("fp"):
        node["client-fingerprint"] = query["fp"]
    if (query.get("allowInsecure") or query.get("insecure") or "").lower() in _TRUE:
        node["skip-cert-verify"] = True


def _transport(node, network, *, path=None, host=None, service=None, header=None):
    """Only plain TCP, WebSocket and gRPC; other transports have no allowlisted options."""
    if network in (None, "", "tcp"):
        return header in (None, "", "none")  # TCP with HTTP header obfuscation has no fields here.
    if network == "ws":
        node["network"] = "ws"
        options = {}
        if path:
            options["path"] = path
        if host:
            options["headers"] = {"Host": host}
        if options:
            node["ws-opts"] = options
        return True
    if network == "grpc":
        node["network"] = "grpc"
        if service:
            node["grpc-opts"] = {"grpc-service-name": service}
        return True
    return False


def _ss(link):
    rest, _, fragment = link[len("ss://"):].partition("#")
    if "@" not in rest:  # Legacy form: Base64 of method:password@host:port.
        encoded, _, tail = rest.partition("?")
        rest = _base64_text(encoded.rstrip("/")) + ("?" + tail if tail else "")
    secret, _, address = rest.rpartition("@")
    plain = unquote(secret)
    method, _, password = (plain if ":" in plain else _base64_text(secret)).partition(":")
    parts = urlsplit("//" + address)
    if _query(parts).get("plugin") or not method or not password:
        return None  # Plugins (obfs, v2ray-plugin) have no allowlisted fields.
    server, port = _address(parts)
    return _named({"type": "ss", "server": server, "port": port, "cipher": method, "password": password}, fragment)


def _vmess(link):
    data = json.loads(_base64_text(link[len("vmess://"):].partition("#")[0]))
    if not isinstance(data, dict):
        return None
    node = {"type": "vmess", "server": str(data["add"]), "port": int(str(data["port"])),
            "uuid": str(data["id"]), "alterId": int(str(data.get("aid") or 0)),
            "cipher": str(data.get("scy") or "auto")}
    if str(data.get("tls") or "") == "tls":
        node["tls"] = True
        query = {key: str(data[name]) for key, name in (("sni", "sni"), ("alpn", "alpn"), ("fp", "fp")) if data.get(name)}
        _tls(node, query, sni="servername")
    network = str(data.get("net") or "tcp")
    path = str(data.get("path") or "") or None
    if not _transport(node, network, path=path, host=str(data.get("host") or "") or None,
                      service=path, header=str(data.get("type") or "") or None):
        return None
    if not node["server"]:
        return None
    node["name"] = str(data.get("ps") or "").strip() or f"vmess {node['server']}:{node['port']}"
    return node


def _vless(link):
    parts = urlsplit(link)
    query = _query(parts)
    if query.get("encryption", "none") not in ("", "none"):
        return None
    server, port = _address(parts)
    node = {"type": "vless", "server": server, "port": port, "uuid": _userinfo(parts)}
    security = query.get("security", "")
    if security in ("tls", "reality"):
        node["tls"] = True
        _tls(node, query, sni="servername")
    elif security not in ("", "none"):
        return None
    if security == "reality":
        if not query.get("pbk"):
            return None
        node["reality-opts"] = {"public-key": query["pbk"], **({"short-id": query["sid"]} if query.get("sid") else {})}
    if query.get("flow"):
        node["flow"] = query["flow"]
    if not _transport(node, query.get("type"), path=query.get("path"), host=query.get("host"),
                      service=query.get("serviceName"), header=query.get("headerType")):
        return None
    return _named(node, parts.fragment)


def _trojan(link):
    parts = urlsplit(link)
    query = _query(parts)
    if query.get("security", "tls") not in ("", "tls"):
        return None
    server, port = _address(parts)
    node = {"type": "trojan", "server": server, "port": port, "password": _userinfo(parts)}
    _tls(node, query)
    if not _transport(node, query.get("type"), path=query.get("path"), host=query.get("host"),
                      service=query.get("serviceName"), header=query.get("headerType")):
        return None
    return _named(node, parts.fragment)


def _hysteria2(link):
    parts = urlsplit(link)
    query = _query(parts)
    server, port = _address(parts)
    node = {"type": "hysteria2", "server": server, "port": port, "password": _userinfo(parts)}
    _tls(node, query)
    if query.get("obfs"):
        node["obfs"] = query["obfs"]
        if query.get("obfs-password"):
            node["obfs-password"] = query["obfs-password"]
    if query.get("mport"):
        node["ports"] = query["mport"]
    return _named(node, parts.fragment)


def _anytls(link):
    parts = urlsplit(link)
    server, port = _address(parts)
    node = {"type": "anytls", "server": server, "port": port, "password": _userinfo(parts)}
    _tls(node, _query(parts))
    return _named(node, parts.fragment)


def _socks(link):
    parts = urlsplit(link)
    server, port = _address(parts)
    node = {"type": "socks5", "server": server, "port": port}
    if "@" in parts.netloc:
        secret = parts.netloc.rpartition("@")[0]
        plain = unquote(secret)
        username, _, password = (plain if ":" in plain else _base64_text(secret)).partition(":")
        node.update(username=username, password=password)
    return _named(node, parts.fragment)


_CONVERTERS = {
    "ss": _ss, "vmess": _vmess, "vless": _vless, "trojan": _trojan,
    "hysteria2": _hysteria2, "hy2": _hysteria2, "anytls": _anytls,
    "socks": _socks, "socks5": _socks,
}
