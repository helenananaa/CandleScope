"""Actual evaluator/session children bind references after a full exchange."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

CURRENT = {"session_identity": "candlescope.session-identity/1", "engine": "frozen", "feature": False}
PROTOCOL = "candlescope.native-strategy/1"


def test_cached_identity_keeps_each_decoded_request_detached():
    from copy import deepcopy
    from candlescope_plugin_sdk.native_strategy import _SessionIdentity
    current = {**CURRENT, "nested": {"values": [False, 0, "开仓"]}}
    frozen = deepcopy(current)
    binding = _SessionIdentity(current)
    binding.decode({"protocol": PROTOCOL, "identity": frozen})
    current["nested"]["values"].append("outside mutation")
    request = {"protocol": PROTOCOL, "identity_ref": reference(frozen)}
    decoded, referenced = binding.decode(request)
    assert referenced and decoded["identity"] == frozen
    decoded["identity"]["nested"]["values"].append("adapter mutation")
    assert binding.decode(request)[0]["identity"] == frozen
    assert binding.encode({}, False)["identity"] == frozen


def reference(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def child(mode, requests, current=CURRENT):
    source = Path(__file__).resolve().parents[1] / "src"
    script = f'''import sys
sys.path.insert(0,{str(source)!r})
from candlescope_plugin_sdk import native_strategy as transport
current={current!r}
class Session:
    def advance(self,target):return {{"target":target}}
def execute(request):
    assert "identity_ref" not in request
    assert request["identity"]==current
    return {{"source":request["source"]}}
if {mode!r}=="serve_session":
    raise SystemExit(transport.serve_session(lambda:current,lambda request:Session()))
else:
    raise SystemExit(getattr(transport,{mode!r})(lambda:current,execute))
'''
    data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests).encode()
    result = subprocess.run([sys.executable, "-I", "-c", script], input=data,
                            capture_output=True, timeout=15)
    return result, [json.loads(row) for row in result.stdout.decode().splitlines()]


@pytest.mark.parametrize("mode", ["serve_evaluator", "serve_session"])
def test_reference_resolves_to_full_identity_and_compacts_both_wire_directions(mode):
    first = {"protocol": PROTOCOL, "identity": CURRENT, "operation": "open", "source": "开仓 café"}
    second = {"protocol": PROTOCOL, "identity_ref": reference(CURRENT),
              "operation": "advance", "target": 2, "source": "止损 🎯"}
    result, rows = child(mode, [first, second])
    assert result.returncode == 0, result.stderr
    assert all(row["ok"] for row in rows)
    assert rows[0]["identity"] == CURRENT and "identity_ref" not in rows[0]
    assert rows[1]["identity_ref"] == reference(CURRENT) and "identity" not in rows[1]
    assert rows[1]["target" if mode == "serve_session" else "source"] == (2 if mode == "serve_session" else "止损 🎯")


@pytest.mark.parametrize("mode", ["serve_evaluator", "serve_session"])
@pytest.mark.parametrize("failure", ["unbound", "changed", "mixed", "legacy", "protocol", "full-change", "full-type"])
def test_invalid_reference_or_changed_full_identity_terminates_the_actual_worker(mode, failure):
    current = {"engine": "legacy"} if failure == "legacy" else CURRENT
    first = {"protocol": PROTOCOL, "identity": current, "operation": "open", "source": "first"}
    second = {"protocol": PROTOCOL, "identity_ref": reference(current),
              "operation": "advance", "target": 1, "source": "second"}
    if failure == "changed":
        second["identity_ref"] = reference({**current, "feature": 0})
    elif failure == "mixed":
        second["identity"] = current
    elif failure == "protocol":
        second["protocol"] = "wrong"
    elif failure in {"full-change", "full-type"}:
        second.pop("identity_ref")
        second["identity"] = {**current, **({"engine": "changed"} if failure == "full-change" else {"feature": 0})}
    result, rows = child(mode, [second] if failure == "unbound" else [first, second], current)
    assert rows[-1]["ok"] is False
    assert "NATIVE_IDENTITY_MISMATCH" in rows[-1]["diagnostics"][0]["message"]
    assert result.returncode == 1


def test_stateless_execution_cannot_use_a_reference_even_with_a_full_identity():
    request = {"protocol": PROTOCOL, "identity": CURRENT, "identity_ref": reference(CURRENT), "source": "bad"}
    _, rows = child("serve", [request])
    assert rows[0]["ok"] is False


def test_legacy_worker_keeps_full_identity_exchanges():
    current = {"engine": "legacy"}
    requests = [{"protocol": PROTOCOL, "identity": current, "source": str(i)} for i in range(2)]
    result, rows = child("serve_evaluator", requests, current)
    assert result.returncode == 0
    assert all(row["identity"] == current and "identity_ref" not in row for row in rows)
