import json
import sqlite3
from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from app.backtest.report_storage import encode_storage, rollback_reports
from app.backtest.reports import seal_report, build_report, verify_report_hash
from app.backtest.service import BacktestService
from app.backtest.strategy.protocol import DeterministicFakeProvider
from tests.test_backtest_control_plane import _settings, _payload
from tests.test_backtest_colocated import bars


@pytest.mark.parametrize("case", ["FEEDBACK", "ORDERS"])
@pytest.mark.parametrize("bound", [False, True])
def test_spawned_feedback_and_owned_report_equivalence(tmp_path, monkeypatch, case, bound):
    import shutil
    from app.backtest.strategy.python_provider import PythonHostProvider
    from scripts.generic_strategy_sources import SOURCES
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    bundle = tmp_path / "script"
    bundle.mkdir()
    (bundle / "strategy.py").write_text(SOURCES[case], encoding="utf-8")
    settings = _settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="31",
                         BACKTEST_TRADE_EXPLANATION_ENABLED="1")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(execution_model_revision="EXECUTION_REALISM_V2"),
                          idempotency_key="same", now_ms=2)
    seed.shutdown()
    outputs = []
    for enabled in (False, True):
        for name in ("BACKTEST_DIRECT_FEEDBACK_ENABLED", "BACKTEST_OWNED_REPORT_ENABLED"):
            monkeypatch.setenv(name, str(int(enabled)))
        db = tmp_path / f"mode-{enabled}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        try:
            provider = PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True,
                                          bound_transcript=bound)
            outputs.append(service.execute_bar_run(run["run_id"], events=bars(350),
                                                    provider=provider, now_ms=3))
        finally:
            service.shutdown()
    assert outputs[0]["result"] == outputs[1]["result"]
    assert outputs[0]["report"] == outputs[1]["report"]


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("kind", ["normal", "unicode", "mutation", "error", "float", "large", "decimal"])
def test_feedback_receipts_and_aliases_match(monkeypatch, bound, kind):
    from types import SimpleNamespace
    from app.backtest.strategy.local_python import LocalPythonRunner
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    outputs = []
    for enabled in (False, True):
        monkeypatch.setenv("BACKTEST_DIRECT_FEEDBACK_ENABLED", str(int(enabled)))
        runner = LocalPythonRunner(bound_transcript=bound)
        runner.start()
        runner._strategy = SimpleNamespace(close=lambda: None)
        report = {"generation": 1, "accepted": True, "order": {"qty": "1", "values": ["x"]}}
        if kind == "unicode": report["text"] = "中文\x7f"
        if kind == "float": report["number"] = 1.25
        if kind == "large": report["text"] = "x" * 2000
        if kind == "decimal":
            from decimal import Decimal
            report["order"]["qty"] = Decimal("1.000")
        original = deepcopy(report)
        seen = []
        def receive(value):
            seen.append(deepcopy(value))
            if kind == "mutation": value["order"]["values"].append("changed")
            if kind == "error": raise ValueError('中文 error "')
        runner._strategy.on_execution_report = receive
        try:
            error = None
            try: runner.on_execution_report(report)
            except Exception as exc: error = (type(exc).__name__, str(exc))
            assert report == original
            outputs.append((seen, error, runner.close()))
        finally:
            runner.close()
    assert outputs[0] == outputs[1]


def test_real_kernel_decimal_fill_qualifies_without_losing_scale():
    from decimal import Decimal
    from app.backtest.strategy.direct_feedback import prepare_feedback
    from app.simulation.kernel import SimulatedFill, _flat_record
    fill = SimulatedFill("o1", 3, 180000, "BUY", Decimal("100.00"), Decimal("1.000"), Decimal(".10"), "fill")
    request = {"id": 1, "method": "on_execution_report", "params": {
        "report": {"accepted": True, "generation": 1, "fill": _flat_record(fill)}}}
    prepared = prepare_feedback(request)
    assert prepared is not None
    detached, wire = prepared
    assert detached == json.loads(json.dumps(request, default=str))
    assert wire == canonical_json(detached).encode()


def fake_report():
    rows = [{"index": i, "text": "中文" * 16, "nested": {"x": [i]}} for i in range(800)]
    return seal_report({"runId": "r", "schemaVersion": "candlescope.backtest-report/2", "hashes": {},
                        "fills": rows, "orders": rows, "trades": [], "ledger": {"order_events": rows}, "order_events": rows})


def publish(repo, report, *, generation=1):
    raw, parts = encode_storage(report, part_limit=16384, total_limit=2000000)
    repo.finalize_run(run_id="r", expected_generation=generation, report_schema=report["schemaVersion"],
                      report_json=raw, report_chunks=parts, report_hash=report["hashes"]["report"],
                      generated_at_ms=1, updated_at_ms=1, audit_action="complete", audit_actor="host", audit_details_json="{}")


def ready_repo(tmp_path):
    from app.backtest.repository import BacktestRepository
    repo = BacktestRepository(tmp_path / "state.db")
    repo.open(now_ms=1)
    columns = repo.connection.execute("PRAGMA table_info(backtest_runs)").fetchall()
    values = {col[1]: (1 if col[2] == "INTEGER" else "x") for col in columns if col[3]}
    values.update(run_id="r", state="COMPLETING", generation=1)
    repo.connection.execute("INSERT INTO backtest_runs (" + ",".join(values) + ") VALUES (" +
                            ",".join("?" for _ in values) + ")", tuple(values.values()))
    repo.connection.commit()
    return repo


def test_report_parts_reopen_pages_compare_and_offline_rollback(tmp_path):
    repo = ready_repo(tmp_path)
    report = fake_report()
    publish(repo, report)
    assert repo.connection.execute("SELECT COUNT(*) FROM backtest_report_parts").fetchone()[0] > 0
    repo.close()
    repo.open(now_ms=2)
    stored = repo.get_report("r")
    assert json.loads(stored["report_json"]) == report
    assert repo.get_reports_for_compare("r", "r") == (report, report)
    for offset in (0, 250, 790, 800, 900):
        page = repo.get_report_view("r", view="page", section="fills", offset=offset, limit=30)
        assert page["rows"] == report["fills"][offset:offset+30] and page["total"] == 800
    summary = repo.get_report_view("r")
    assert summary["detailCounts"]["fills"] == 800 and summary["summary"]["fills"] == []
    repo.close()
    assert rollback_reports(tmp_path / "state.db")["schemaVersion"] == 8
    db = sqlite3.connect(tmp_path / "state.db")
    assert json.loads(db.execute("SELECT report_json FROM backtest_reports").fetchone()[0]) == report
    db.close()


@pytest.mark.parametrize("damage", ["missing", "part", "manifest"])
def test_report_corruption_and_downgrade_fail_closed(tmp_path, damage):
    repo = ready_repo(tmp_path)
    publish(repo, fake_report())
    if damage == "missing": repo.connection.execute("DELETE FROM backtest_report_parts")
    elif damage == "part": repo.connection.execute("UPDATE backtest_report_parts SET payload_json='[]'")
    else:
        value = json.loads(repo.connection.execute("SELECT report_json FROM backtest_reports").fetchone()[0])
        value["report"]["fills"] = ["changed"]
        repo.connection.execute("UPDATE backtest_reports SET report_json=?", (canonical_json(value),))
    repo.connection.commit()
    with pytest.raises(BacktestError, match="REPORT_CORRUPT"): repo.get_report("r")
    with pytest.raises(BacktestError, match="REPORT_CORRUPT"):
        repo.get_report_view("r", view="page", section="fills", offset=0, limit=10)
    repo.close()
    with pytest.raises(BacktestError): rollback_reports(tmp_path / "state.db")
    db = sqlite3.connect(tmp_path / "state.db")
    assert db.execute("SELECT schema_version FROM backtest_schema_meta").fetchone()[0] == 9
    db.close()


def test_report_publication_generation_and_budget(tmp_path):
    repo = ready_repo(tmp_path)
    with pytest.raises(RuntimeError): publish(repo, fake_report(), generation=2)
    assert repo.connection.execute("SELECT COUNT(*) FROM backtest_report_parts").fetchone()[0] == 0
    assert repo.get_report("r") is None
    with pytest.raises(BacktestError, match="storage byte limit"):
        encode_storage(fake_report(), part_limit=16384, total_limit=20000)
    repo.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_owned_report_stays_detached_and_hash_identical(enabled):
    record = {"run_id": "r", "config_json": "{}"}
    payload = {"ledger": {"account": {"nested": [1]}, "order_events": [{"nested": [2]}]},
               "data_quality": {"nested": [3]}, "equity_curve": [{"equity": "10", "nested": [4]}],
               "contract_coverage": {"nested": [5]}, "fill_model": {"nested": [6]}}
    report = build_report(record, payload, _owned_seal=enabled)
    assert report == build_report(record, payload)
    before = deepcopy(payload)
    report["ledger"]["account"]["nested"].append(99)
    report["data_quality"]["nested"].append(99)
    report["equity_curve"][0]["nested"].append(99)
    assert payload == before


@pytest.mark.parametrize("policy,expected", [("INTERVAL", [0, 10, 20, 25]), ("FINAL_ONLY", [25]), ("NONE", [])])
def test_checkpoint_policy_publication_and_result(tmp_path, policy, expected):
    service = BacktestService.start(_settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="100000"), now_ms=1)
    publications = []
    original = service.repository.save_checkpoint
    def save(payload):
        publications.append(payload["sequence"])
        return original(payload)
    service.repository.save_checkpoint = save
    try:
        request = _payload(checkpoint_policy=policy)
        if policy == "INTERVAL": request["checkpoint_interval"] = 10
        record = service.create_run(request, idempotency_key="p", now_ms=2)
        config = json.loads(record["config_json"])
        assert config["checkpoint_policy"] == policy
        result = service.execute_bar_run(record["run_id"], events=bars(25), provider=DeterministicFakeProvider(), now_ms=3)
        assert result["state"] == "COMPLETED" and verify_report_hash(result["report"])
        assert publications == expected
    finally:
        service.shutdown()


def test_chunked_report_service_and_http_legacy_compatibility(tmp_path):
    service = BacktestService.start(_settings(tmp_path, BACKTEST_MAX_REPORT_BYTES="12000"), now_ms=1)
    record = service.create_run(_payload(), idempotency_key="http", now_ms=2)
    result = service.execute_bar_run(record["run_id"], events=bars(400), provider=DeterministicFakeProvider(), now_ms=3)
    assert result["state"] == "COMPLETED"
    expected = json.loads(canonical_json(result["report"]))
    assert service.get_report(record["run_id"]) == expected
    assert service.repository.connection.execute("SELECT COUNT(*) FROM backtest_report_parts").fetchone()[0] > 0
    from app.api.v1.backtests import router
    api = FastAPI()
    api.include_router(router, prefix="/api/v1")
    api.state.backtest_service = service
    client = TestClient(api)
    base = f'/api/v1/backtests/runs/{record["run_id"]}/report'
    assert client.get(base).json() == expected
    assert client.get(base + "/summary").json()["reportHash"] == result["report"]["hashes"]["report"]
    assert client.get(base + "/details?section=equity_curve&offset=2&limit=5").json()["rows"] == result["report"]["equity_curve"][2:7]
    assert client.get(base + "/details?limit=501").status_code == 422
    service.shutdown()


@pytest.mark.parametrize("policy", ["NONE", "FINAL_ONLY"])
def test_failure_without_recovery_points_cannot_claim_resume(tmp_path, policy):
    from app.backtest.strategy.protocol import StrategyProviderError
    class Fails(DeterministicFakeProvider):
        def step(self, frame):
            if frame.sequence == 7:
                raise StrategyProviderError("PROVIDER_TIMEOUT", "injected")
            return super().step(frame)
    service = BacktestService.start(_settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="2"), now_ms=1)
    record = service.create_run(_payload(checkpoint_policy=policy), idempotency_key="failure", now_ms=2)
    try:
        with pytest.raises(StrategyProviderError):
            service.execute_bar_run(record["run_id"], events=bars(25), provider=Fails(), now_ms=3)
        assert service.repository.latest_checkpoint(record["run_id"]) is None
        with pytest.raises(BacktestError, match="no durable checkpoint"):
            service.resume_failed_run(record["run_id"], now_ms=4)
    finally:
        service.shutdown()


def test_policy_is_frozen_but_financial_result_is_equivalent(tmp_path):
    service = BacktestService.start(_settings(tmp_path), now_ms=1)
    outcomes, identities = [], []
    try:
        for policy in ("INTERVAL", "FINAL_ONLY", "NONE"):
            record = service.create_run(_payload(checkpoint_policy=policy), idempotency_key=policy, now_ms=2)
            result = service.execute_bar_run(record["run_id"], events=bars(25), provider=DeterministicFakeProvider(), now_ms=3)
            outcomes.append(tuple(result["result"][key] for key in ("decision_hash", "fill_hash", "ledger_hash")))
            identities.append(record["config_hash"])
        assert outcomes[0] == outcomes[1] == outcomes[2]
        assert len(set(identities)) == 3
    finally:
        service.shutdown()


def test_explicit_interval_freezes_host_default_and_legacy_omission_stays_legacy(tmp_path):
    service = BacktestService.start(_settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="50000"), now_ms=1)
    try:
        explicit = service.create_run(_payload(checkpoint_policy="INTERVAL"), idempotency_key="explicit", now_ms=2)
        legacy = service.create_run(_payload(), idempotency_key="legacy", now_ms=2)
        assert json.loads(explicit["config_json"])["checkpoint_interval"] == 50000
        assert "checkpoint_policy" not in json.loads(legacy["config_json"])
        assert "checkpoint_interval" not in json.loads(legacy["config_json"])
    finally:
        service.shutdown()


def test_partial_report_publication_rolls_back_all_chunks(tmp_path):
    repo = ready_repo(tmp_path)
    repo.connection.execute("CREATE TRIGGER fail_report BEFORE INSERT ON backtest_reports BEGIN SELECT RAISE(ABORT, 'injected'); END")
    repo.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): publish(repo, fake_report())
    assert repo.connection.execute("SELECT COUNT(*) FROM backtest_report_parts").fetchone()[0] == 0
    assert repo.get_report("r") is None
    assert repo.connection.execute("SELECT state FROM backtest_runs").fetchone()[0] == "COMPLETING"
    repo.close()
