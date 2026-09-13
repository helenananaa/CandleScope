"""Run with -I and a fresh pip --target directory containing native+SDK wheels."""
import hashlib
import json
from pathlib import Path
import sys

site = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(site))
from app.backtest.strategy import _native_rows
import candlescope_backtest_sdk as sdk

assert Path(_native_rows.__file__).resolve().is_relative_to(site)
assert Path(sdk.__file__).resolve().is_relative_to(site)
assert _native_rows.ROW_PROTOCOL_ABI == 1

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

bar = {"open":"1.00", "high":"2.0", "low":"0.5", "close":"1.5", "volume":"10"}
market = {"symbol": 'BTC"\\\x7f'}
factory = _native_rows.RowFactory("installed", market, sdk.Bar, sdk.Observation)
observation, raw = factory.build(bar, 1, 60000, "EVALUATION")
wire = json.loads(raw)
assert observation == sdk.Observation.from_wire(wire)
assert raw == encoded(wire)
assert observation.input_hash == "sha256:" + hashlib.sha256(encoded({
    "bar":bar, "features":bar, "sequence":1, "trade":None, "watermark":60000,
})).hexdigest()
output = sdk.encode_output(1, sdk.TargetPosition("1"))
digest, output_wire = factory.output_wire(1, output["kind"], output["payload"], output["schemaVersion"])
assert digest == output["outputHash"] and output_wire == encoded(output)
def target_hash(quantity):
    return "sha256:" + hashlib.sha256(encoded({"quantity":quantity, "targetExposure":quantity})).hexdigest()
host_args, combined_wire = factory.output_parts(1, output["kind"], output["payload"], output["schemaVersion"], target_hash)
assert combined_wire == output_wire
assert host_args == (1, "TARGET_POSITION", {"quantity":"1", "targetExposure":"1"}, target_hash("1"), digest)
response = {"id":1, "ok":True, "result":output}
record = {"request":{"id":1, "method":"step", "params":{"observation":wire}}, "response":response}
hasher = hashlib.sha256(b"[")
factory.bind_transcript(hasher)
factory.record_v1(1, False, raw, encoded(response), None)
hasher.update(b"]")
assert hasher.hexdigest() == hashlib.sha256(encoded([record])).hexdigest()
combined = _native_rows.RowFactory("installed", market, sdk.Bar, sdk.Observation)
combined_hash = hashlib.sha256(b"[")
combined.bind_transcript(combined_hash)
combined.record_success(1, False, raw, output_wire, None)
combined_hash.update(b"]")
assert combined_hash.hexdigest() == hasher.hexdigest()
previous = "sha256:GENESIS"
from types import SimpleNamespace
from candlescope_backtest_sdk import models
assert models.NATIVE_OUTPUT_LAYOUT == 1
specs = tuple((kind, kind.to_payload, names, wire_names, label, kind.__name__) for kind, names, wire_names, label in (
    (sdk.Signal, ("direction", "score", "confidence", "horizon"), ("direction", "score", "confidence", "horizon"), "SIGNAL"),
    (sdk.TargetPosition, ("quantity",), ("quantity",), "TARGET_POSITION"),
    (sdk.OrderIntent, ("side", "type", "quantity", "limit_price", "stop_price", "tif", "client_tag"),
     ("side", "type", "quantity", "limitPrice", "stopPrice", "tif", "clientTag"), "ORDER_INTENT"),
))
entry = _native_rows.RowFactory("installed", market, sdk.Bar, sdk.Observation)
entry_hash = hashlib.sha256(b"[")
entry.bind_transcript(entry_hash)
entry.bind_outputs(models, models.output_kind, specs)
assert entry.object_output(1, sdk.TargetPosition("1"), target_hash) == (host_args, combined_wire)
runner = SimpleNamespace(_strategy=SimpleNamespace(step=lambda obs: sdk.TargetPosition("1")),
    _count=0, _bound=False, _native_target_hash=target_hash, _native_output_type=lambda *args: args)
session = SimpleNamespace(run_id="installed", _accept_clock=lambda *args: None)
assert entry.execute(bar, 1, 60000, "EVALUATION", runner, session, True) == (host_args,)
entry_hash.update(b"]")
assert runner._count == 1 and entry_hash.hexdigest() == hasher.hexdigest()
expected_empty = "sha256:" + hashlib.sha256(encoded({"previous":previous,
    "decision":{"intents":[], "sequence":1, "watermark_ms":60000}})).hexdigest()
assert _native_rows.empty_decision_hash(previous, 1, 60000, hashlib.sha256) == expected_empty
receipt = {"status":"PASS", "python":sys.version, "module":_native_rows.__file__,
           "module_sha256":hashlib.sha256(Path(_native_rows.__file__).read_bytes()).hexdigest(),
           "sdk":sdk.__file__, "abi":_native_rows.ROW_PROTOCOL_ABI, "output_parts":True,
           "record_success":True, "empty_decision_hash":True, "native_entry":True,
           "native_output_fields":True, "stats":factory.stats()}
print(json.dumps(receipt, indent=2))
