"""Base64, share-link and provider subscriptions, and redirects (#575 PL-11c)."""
import base64
import datetime
import ipaddress
import json
import ssl

import pytest
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.proxy_subscriptions import source
from app.proxy_subscriptions.formats import share_link
from app.proxy_subscriptions.source import SubscriptionError, parse_nodes

SOURCE = "https://sub.test/subscription?token=private-test-token"
VMESS = {"v": "2", "ps": "Tokyo ws", "add": "jp.example.invalid", "port": "443", "id": "a3482e88-686a-4a58-8126-99c9df64b7bf",
         "aid": "0", "scy": "auto", "net": "ws", "type": "none", "host": "cdn.example.invalid", "path": "/ray",
         "tls": "tls", "sni": "cdn.example.invalid", "alpn": "h2,http/1.1", "fp": "chrome"}


def b64(text, *, urlsafe=False, pad=True):
    encoded = (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(text.encode()).decode()
    return encoded if pad else encoded.rstrip("=")


def test_share_links_become_allowlisted_nodes():
    cases = {
        "ss://" + b64("aes-128-gcm:test-password", urlsafe=True, pad=False) + "@ss.example.invalid:8388#HK%20ss": {
            "name": "HK ss", "type": "ss", "server": "ss.example.invalid", "port": 8388,
            "cipher": "aes-128-gcm", "password": "test-password"},
        "ss://" + b64("chacha20-ietf-poly1305:p@ss:word@legacy.example.invalid:443") + "#legacy": {
            "name": "legacy", "type": "ss", "server": "legacy.example.invalid", "port": 443,
            "cipher": "chacha20-ietf-poly1305", "password": "p@ss:word"},
        "ss://2022-blake3-aes-128-gcm:YctPZ6U7xPPcU%2Bgp3u%2B0tx%2FtRizJN9K8y%2BuKlW2qjlI%3D@[2001:db8::1]:443#v6": {
            "name": "v6", "type": "ss", "server": "2001:db8::1", "port": 443,
            "cipher": "2022-blake3-aes-128-gcm", "password": "YctPZ6U7xPPcU+gp3u+0tx/tRizJN9K8y+uKlW2qjlI="},
        "vmess://" + b64(json.dumps(VMESS)): {
            "name": "Tokyo ws", "type": "vmess", "server": "jp.example.invalid", "port": 443,
            "uuid": VMESS["id"], "alterId": 0, "cipher": "auto", "tls": True, "servername": "cdn.example.invalid",
            "alpn": ["h2", "http/1.1"], "client-fingerprint": "chrome", "network": "ws",
            "ws-opts": {"path": "/ray", "headers": {"Host": "cdn.example.invalid"}}},
        "vless://a3482e88-686a-4a58-8126-99c9df64b7bf@vl.example.invalid:443?encryption=none&security=reality"
        "&sni=www.example.invalid&fp=chrome&pbk=test-public-key&sid=6ba85179&type=tcp&flow=xtls-rprx-vision#reality": {
            "name": "reality", "type": "vless", "server": "vl.example.invalid", "port": 443,
            "uuid": "a3482e88-686a-4a58-8126-99c9df64b7bf", "tls": True, "servername": "www.example.invalid",
            "client-fingerprint": "chrome", "reality-opts": {"public-key": "test-public-key", "short-id": "6ba85179"},
            "flow": "xtls-rprx-vision"},
        "trojan://pass%3Aword@tj.example.invalid:443?sni=tj-sni.example.invalid&type=grpc&serviceName=svc"
        "&allowInsecure=1#gRPC": {
            "name": "gRPC", "type": "trojan", "server": "tj.example.invalid", "port": 443, "password": "pass:word",
            "sni": "tj-sni.example.invalid", "skip-cert-verify": True, "network": "grpc",
            "grpc-opts": {"grpc-service-name": "svc"}},
        "hy2://test-auth@hy.example.invalid:8443/?sni=hy.example.invalid&obfs=salamander&obfs-password=test-obfs#hy": {
            "name": "hy", "type": "hysteria2", "server": "hy.example.invalid", "port": 8443, "password": "test-auth",
            "sni": "hy.example.invalid", "obfs": "salamander", "obfs-password": "test-obfs"},
        "anytls://test-password@any.example.invalid:443/?sni=any.example.invalid": {
            "name": "anytls any.example.invalid:443", "type": "anytls", "server": "any.example.invalid", "port": 443,
            "password": "test-password", "sni": "any.example.invalid"},
        "socks://" + b64("user:test-password") + "@socks.example.invalid:1080#socks": {
            "name": "socks", "type": "socks5", "server": "socks.example.invalid", "port": 1080,
            "username": "user", "password": "test-password"},
    }
    for link, expected in cases.items():
        assert share_link(link) == expected, link
    nodes, skipped = parse_nodes("\n".join(cases).encode(), SOURCE)
    assert skipped == 0 and [n["name"] for n in nodes.values()] == [n["name"] for n in cases.values()]


@pytest.mark.parametrize("link", [
    "ssr://" + b64("ssr.example.invalid:443:origin:aes-256-cfb:plain:cGFzcw/"),
    "ss://" + b64("aes-128-gcm:test-password") + "@ss.example.invalid:8388/?plugin=obfs-local%3Bobfs%3Dhttp#plugin",
    "vmess://" + b64(json.dumps({**VMESS, "net": "h2"})),
    "vmess://" + b64(json.dumps({**VMESS, "net": "tcp", "type": "http"})),
    "vmess://not-base64!",
    "vless://uuid@vl.example.invalid:443?encryption=mlkem768x25519plus#post-quantum",
    "vless://uuid@vl.example.invalid:443?security=reality#no-public-key",
    "trojan://secret@tj.example.invalid:not-a-port#bad-port",
    "hysteria2://secret@hy.example.invalid:1000-2000#port-range",
    "https://other.example.invalid/nested-subscription",
])
def test_links_that_cannot_be_converted_are_skipped_not_guessed(link):
    good = "trojan://secret@tj.example.invalid:443#kept"
    nodes, skipped = parse_nodes(f"{good}\n{link}\n".encode(), SOURCE)
    assert skipped == 1 and [n["name"] for n in nodes.values()] == ["kept"]


def test_base64_bodies_in_either_alphabet_with_or_without_padding_or_line_breaks():
    links = "trojan://secret@tj.example.invalid:443#first\nss://" + b64("aes-128-gcm:x") + "@ss.example.invalid:1#second\n"
    expected = parse_nodes(links.encode(), SOURCE)
    for body in (b64(links), b64(links, urlsafe=True, pad=False), "\n".join(b64(links)[i:i + 76] for i in range(0, len(b64(links)), 76))):
        assert parse_nodes(body.encode(), SOURCE) == expected
    yaml = "proxies:\n  - {name: first, type: trojan, server: tj.example.invalid, port: 443, password: secret}\n"
    assert list(parse_nodes(b64(yaml).encode(), SOURCE)[0]) == list(expected[0])[:1]
    for body in (b"subscriptionunavailable", b64("not a subscription").encode(), b"\xff\xfe"):
        with pytest.raises(SubscriptionError):
            parse_nodes(body, SOURCE)


def test_node_ids_follow_the_name_so_a_format_change_keeps_selections():
    yaml = b"proxies:\n  - {name: kept, type: trojan, server: tj.example.invalid, port: 443, password: secret}\n"
    link = b"trojan://secret@tj.example.invalid:443?sni=tj.example.invalid#kept"
    assert list(parse_nodes(yaml, SOURCE)[0]) == list(parse_nodes(link, SOURCE)[0])
    assert list(parse_nodes(yaml, SOURCE)[0]) != list(parse_nodes(yaml, SOURCE + "&other")[0])


def test_inline_providers_are_read_and_file_providers_ignored():
    body = b"""
proxies:
  - {name: direct-list, type: trojan, server: a.example.invalid, port: 443, password: secret}
proxy-providers:
  inline:
    type: inline
    override: {additional-prefix: "[in] "}
    payload:
      - {name: one, type: trojan, server: b.example.invalid, port: 443, password: secret}
      - {name: two, type: direct}
  disk:
    type: file
    path: /etc/passwd
"""
    nodes, skipped = parse_nodes(body, SOURCE)
    assert [n["name"] for n in nodes.values()] == ["direct-list", "[in] one"] and skipped == 1
    with pytest.raises(SubscriptionError, match="must be downloaded"):
        parse_nodes(b"proxy-providers: {remote: {type: http, url: 'https://sub.test/p'}}", SOURCE)
    many = "proxy-providers:\n" + "".join(f"  p{i}: {{type: http, url: 'https://sub.test/{i}'}}\n" for i in range(9))
    with pytest.raises(SubscriptionError, match="more than 8 providers"):
        parse_nodes(many.encode(), SOURCE)


def test_identical_duplicates_collapse_and_conflicting_ones_fail():
    node = "{name: same, type: trojan, server: a.example.invalid, port: 443, password: secret}"
    assert len(parse_nodes(f"proxies: [{node}, {node}]".encode(), SOURCE)[0]) == 1
    with pytest.raises(SubscriptionError, match="Duplicate"):
        parse_nodes(f"proxies: [{node}, {node.replace('a.example', 'b.example')}]".encode(), SOURCE)


def _certificates(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key, key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CandleScope test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
          .not_valid_after(now + datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    names = [x509.DNSName(h) for h in ("sub.test", "hop.test", "provider.test", "lan.test")]
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sub.test")]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(names + [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    (tmp_path / "leaf.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "leaf.key").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server.load_cert_chain(tmp_path / "leaf.pem", tmp_path / "leaf.key")
    client = ssl.create_default_context(cadata=ca.public_bytes(serialization.Encoding.PEM).decode())
    return server, client


@pytest.fixture
async def provider(tmp_path, monkeypatch):
    """An HTTPS provider on 127.0.0.1 that answers for every *.test name.

    Hosts map to 127.0.0.1, which the private-address check treats as public here,
    except lan.test, which maps to a private address the check refuses.
    """
    server_tls, client_tls = _certificates(tmp_path)
    pages, seen = {}, []

    async def handle(request):
        seen.append(f"{request.host.split(':')[0]}{request.path_qs}")
        status, headers, body = pages.get(request.path_qs, (404, {}, b""))
        return web.Response(status=status, headers=headers, body=body)

    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    monkeypatch.setattr(source, "_TLS", client_tls)
    monkeypatch.setattr(source, "_addresses", lambda host, *_: ["10.1.2.3" if host == "lan.test" else "127.0.0.1"])
    monkeypatch.setattr(source, "_public", lambda address: address == "127.0.0.1")
    try:
        yield pages, seen, lambda host, path: f"https://{host}:{port}{path}"
    finally:
        await runner.cleanup()


LINKS = b"trojan://secret@tj.example.invalid:443#first\ntrojan://secret@tj.example.invalid:444#second\n"


@pytest.mark.anyio
async def test_redirects_are_followed_over_https_only(provider):
    pages, seen, url = provider
    pages["/start?token=private-test-token"] = (302, {"Location": url("hop.test", "/moved")}, b"")
    pages["/moved"] = (301, {"Location": "/final#fragment-dropped"}, b"")
    pages["/final"] = (200, {}, base64.b64encode(LINKS))
    start = url("sub.test", "/start?token=private-test-token")
    nodes, skipped = await source.download(start)
    assert [n["name"] for n in nodes.values()] == ["first", "second"] and skipped == 0
    assert seen == ["sub.test/start?token=private-test-token", "hop.test/moved", "hop.test/final"]
    assert list(nodes) == list(parse_nodes(LINKS, start)[0])  # Identity follows the URL the user entered.

    pages["/moved"] = (302, {"Location": url("hop.test", "/final").replace("https:", "http:")}, b"")
    with pytest.raises(SubscriptionError, match="not an HTTPS URL") as failure:
        await source.download(start)
    assert "private-test-token" not in str(failure.value)
    for hop in range(6):
        pages[f"/loop{hop}"] = (307, {"Location": f"/loop{hop + 1}"}, b"")
    pages["/start?token=private-test-token"] = (302, {"Location": "/loop0"}, b"")
    with pytest.raises(SubscriptionError, match="more than 5 times"):
        await source.download(start)
    pages["/start?token=private-test-token"] = (302, {}, b"")
    with pytest.raises(SubscriptionError, match="without a location"):
        await source.download(start)


@pytest.mark.anyio
async def test_provider_supplied_hops_may_not_reach_the_local_network(provider, monkeypatch):
    pages, seen, url = provider
    pages["/start"] = (302, {"Location": url("lan.test", "/router")}, b"")
    with pytest.raises(SubscriptionError, match="private address"):
        await source.download(url("sub.test", "/start"))
    pages["/start"] = (302, {"Location": "https://192.168.1.1/admin"}, b"")
    with pytest.raises(SubscriptionError, match="private address"):
        await source.download(url("sub.test", "/start"))
    pages["/start"] = (200, {}, f"proxy-providers: {{lan: {{type: http, url: '{url('lan.test', '/p')}'}}}}".encode())
    with pytest.raises(SubscriptionError, match="private address"):
        await source.download(url("sub.test", "/start"))
    assert not any(item.startswith(("lan.test", "192.168")) for item in seen)
    # The host the user typed is theirs to choose, even on the local network; a hop is not.
    monkeypatch.setattr(source, "_public", lambda address: False)
    pages["/router"] = (200, {}, LINKS)
    pages["/start"] = (302, {"Location": "/router"}, b"")
    assert len((await source.download(url("sub.test", "/start")))[0]) == 2
    pages["/start"] = (302, {"Location": url("hop.test", "/router")}, b"")
    with pytest.raises(SubscriptionError, match="private address"):
        await source.download(url("sub.test", "/start"))


@pytest.mark.anyio
async def test_http_providers_are_fetched_once_with_their_prefix(provider):
    pages, seen, url = provider
    pages["/start"] = (200, {}, f"""
proxies:
  - {{name: own, type: trojan, server: a.example.invalid, port: 443, password: secret}}
proxy-providers:
  links:
    type: http
    url: "{url('provider.test', '/links#ignored')}"
    override: {{additional-prefix: "P1 "}}
  yaml:
    type: http
    url: "{url('provider.test', '/yaml')}"
""".encode())
    pages["/links"] = (200, {}, base64.b64encode(LINKS + b"ssr://unsupported\n"))
    pages["/yaml"] = (200, {}, f"""
proxies:
  - {{name: from-yaml, type: trojan, server: b.example.invalid, port: 443, password: secret}}
proxy-providers:
  deeper: {{type: http, url: "{url('provider.test', '/deeper')}"}}
""".encode())
    nodes, skipped = await source.download(url("sub.test", "/start"))
    assert [n["name"] for n in nodes.values()] == ["own", "P1 first", "P1 second", "from-yaml"]
    assert skipped == 1 and "provider.test/deeper" not in seen
    pages["/yaml"] = (404, {}, b"")
    with pytest.raises(SubscriptionError, match="provider returned HTTP 404"):
        await source.download(url("sub.test", "/start"))
    pages["/start"] = (200, {}, b"proxy-providers: {p: {type: http, url: 'http://provider.test/links'}}")
    with pytest.raises(SubscriptionError, match="not an HTTPS URL"):
        await source.download(url("sub.test", "/start"))
