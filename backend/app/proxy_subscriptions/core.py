"""One isolated Mihomo process with a fixed, authenticated listener per node."""
from __future__ import annotations

import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from contextlib import ExitStack

import requests

from .source import SubscriptionError


def _reserve(stack):
    sock = stack.enter_context(socket.socket())
    sock.bind(("127.0.0.1", 0))
    return sock.getsockname()[1]


class Core:
    def __init__(self, nodes):
        self.nodes = {}
        self.endpoints = {}
        self.listeners = {}
        self.process = None
        self.session = requests.Session()
        self.session.trust_env = False
        self.secret = secrets.token_hex(32)
        self.session.headers["Authorization"] = "Bearer " + self.secret
        try:
            with ExitStack() as stack:
                self.controller = f"http://127.0.0.1:{_reserve(stack)}"
                listeners = self._listeners(nodes, stack)
            self._launch(self._config(nodes, listeners))
            self._ready(nodes, listeners)
            self._publish(nodes, listeners)
        except BaseException:
            self.close()
            raise

    def _listeners(self, nodes, stack):
        listeners = {}
        for key, node in nodes.items():
            if self.nodes.get(key) == node:
                listeners[key] = self.listeners[key]
            else:
                listeners[key] = {"name": "in-" + key, "type": "http", "listen": "127.0.0.1",
                                  "port": _reserve(stack), "proxy": key,
                                  "users": [{"username": "candlescope", "password": secrets.token_hex(24)}]}
        return listeners

    def _publish(self, nodes, listeners):
        self.endpoints = {
            k: f"http://candlescope:{v['users'][0]['password']}@127.0.0.1:{v['port']}"
            for k, v in listeners.items()
        }
        self.listeners = listeners
        self.nodes = nodes

    def _config(self, nodes, listeners):
        return {
            "external-controller": self.controller.removeprefix("http://"), "secret": self.secret,
            "listeners": list(listeners.values()), "allow-lan": False, "tun": {"enable": False},
            "proxies": [dict(n, name=k) for k, n in nodes.items()],
            "mode": "rule", "rules": ["MATCH,REJECT"], "log-level": "silent",
            "find-process-mode": "off", "profile": {"store-selected": False},
        }

    def _launch(self, config):
        binary = os.environ.get("CANDLESCOPE_MIHOMO") or shutil.which("mihomo")
        if not binary:
            raise SubscriptionError("Mihomo executable unavailable")
        env = {key: value for key, value in os.environ.items() if key.upper() in {
            "HOME", "TEMP", "TMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "USERPROFILE",
            "LOCALAPPDATA", "APPDATA", "PATH", "LANG",
        }}
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name("guard.py")), binary],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
            )
            self.process.stdin.write(json.dumps(config).encode() + b"\n")
            self.process.stdin.flush()
        except OSError:
            raise SubscriptionError("Could not launch Mihomo") from None

    @staticmethod
    def _owns_listener(listener):
        # An origin-form request has no upstream destination. Mihomo checks
        # proxy authentication first, then rejects the missing absolute URL.
        # A port occupied by another local proxy must never become a pool route.
        password = listener["users"][0]["password"]
        token = base64.b64encode(("candlescope:" + password).encode()).decode()
        for headers, expected in [({}, 407), ({"Proxy-Authorization": "Basic " + token}, 400)]:
            conn = http.client.HTTPConnection("127.0.0.1", listener["port"], timeout=0.4)
            try:
                conn.request("GET", "/", headers=headers)
                if conn.getresponse().status != expected:
                    return False
            finally:
                conn.close()
        return True

    def _ready(self, nodes, listeners):
        deadline = time.monotonic() + 8
        while self.alive and time.monotonic() < deadline:
            try:
                r = self.session.get(self.controller + "/proxies", timeout=0.4)
                if r.ok and nodes.keys() <= r.json()["proxies"].keys():
                    if all(self._owns_listener(listener) for listener in listeners.values()):
                        return
            except (OSError, http.client.HTTPException, requests.RequestException, ValueError, KeyError):
                pass
            time.sleep(0.05)
        raise SubscriptionError("Mihomo could not start all selected listeners")

    def _reload(self, nodes, listeners):
        try:
            r = self.session.put(self.controller + "/configs",
                                 json={"payload": json.dumps(self._config(nodes, listeners))}, timeout=8)
            r.raise_for_status()
            self._ready(nodes, listeners)
        except requests.RequestException:
            raise SubscriptionError("Mihomo rejected the selected configuration") from None

    def reconfigure(self, nodes):
        with ExitStack() as stack:
            listeners = self._listeners(nodes, stack)
        try:
            self._reload(nodes, listeners)
        except SubscriptionError:
            try:
                self._reload(self.nodes, self.listeners)
            except SubscriptionError:
                self.close()
            raise
        self._publish(nodes, listeners)

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    def close(self):
        if self.process:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.session.close()
