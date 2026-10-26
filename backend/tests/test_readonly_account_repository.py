import sqlite3
import pytest
from app.readonly_accounts.normalization import AccountDataError
from app.readonly_accounts.repository import AccountRepository


def row(key="10", at=100, amount="0.001"):
    return key, {"billId":key,"fillSz":amount,"ts":str(at)}, {"fillId":key,"eventTimeMs":at,"contracts":amount}


def test_rest_overlap_restart_and_ws_duplicates_do_not_duplicate_facts(tmp_path):
    repo=AccountRepository(tmp_path);repo.bind("123","a"*32,0)
    repo.start_scan("fills",0,200)
    repo.page("fills",None,[row()],next_cursor="10",complete=False)
    repo=AccountRepository(tmp_path)
    assert repo.scans()[0]["cursor"]=="10" and not repo.coverage()
    repo.page("fills","10",[row(),row("9",90)],next_cursor=None,complete=True)
    repo.observe("orders",[{"ordId":"1","tradeId":"2","accFillSz":"99"}],received_ms=210)
    repo.observe("orders",[{"ordId":"1","tradeId":"2","accFillSz":"99"}],received_ms=211)
    repo.start_scan("fills",0,300);repo.page("fills",None,[row()],next_cursor=None,complete=True)
    assert len(repo.facts("fills"))==2
    assert repo.coverage()[-1]["end_ms"]==300
    with repo.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM raw_fact WHERE kind='ws:orders'").fetchone()[0]==1


def test_conflicting_duplicate_preserves_evidence_without_advancing_cursor(tmp_path):
    repo=AccountRepository(tmp_path);repo.start_scan("fills",0,200)
    repo.page("fills",None,[row()],next_cursor="10",complete=False)
    with pytest.raises(AccountDataError,match="EXCHANGE_FACT_CONFLICT"):
        repo.page("fills","10",[row(amount="9")],next_cursor=None,complete=True)
    assert repo.facts("fills")[0]["contracts"]=="0.001"
    assert repo.scans()[0]["cursor"]=="10" and not repo.coverage()
    with repo.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM raw_fact").fetchone()[0]==2


def test_failure_between_records_rolls_back_all_facts_and_checkpoint(tmp_path):
    repo=AccountRepository(tmp_path);repo.start_scan("fills",0,200)
    with repo.connection() as db:
        db.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON fact WHEN NEW.external_key='9' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.page("fills",None,[row(),row("9",90)],next_cursor=None,complete=True)
    repo=AccountRepository(tmp_path)
    assert repo.facts("fills")==[] and repo.scans()[0]["cursor"] is None and not repo.coverage()
    with repo.connection() as db:db.execute("DROP TRIGGER injected_failure")
    repo.page("fills",None,[row(),row("9",90)],next_cursor=None,complete=True)
    assert len(repo.facts("fills"))==2 and len(repo.coverage())==1


def test_repeated_cursor_and_stale_page_cannot_claim_complete_coverage(tmp_path):
    repo=AccountRepository(tmp_path);repo.start_scan("fills",0,200)
    repo.page("fills",None,[row()],next_cursor="10",complete=False)
    with pytest.raises(AccountDataError,match="STALLED"):
        repo.page("fills","10",[row()],next_cursor="10",complete=False)
    with pytest.raises(AccountDataError,match="CONFLICT"):
        repo.page("fills",None,[row("9",90)],next_cursor=None,complete=True)
    assert len(repo.facts("fills"))==1 and not repo.coverage()


def test_account_rotation_never_rebinds_another_account_to_existing_facts(tmp_path):
    repo=AccountRepository(tmp_path);repo.bind("123","a"*32,0)
    repo.bind("123","b"*32,100)
    assert repo.account(credential_reference=True)["credential_id"]=="b"*32
    assert repo.account()["requested_from_ms"]==0 and "credential_id" not in repo.account()
    with pytest.raises(AccountDataError):repo.bind("456","c"*32,0)
    assert repo.account()["venue_uid"]=="123"


def test_secret_fields_are_never_written_in_observations_or_notes(tmp_path):
    repo=AccountRepository(tmp_path)
    with pytest.raises(AccountDataError,match="SECRET"):
        repo.observe("orders",[{"ordId":"1","nested":{"apiKey":"SENTINEL"}}],received_ms=1)
    with pytest.raises(AccountDataError,match="SECRET"):
        repo.save_note("note",0,{"secret":"SENTINEL"},event_ms=1)
    assert b'SENTINEL' not in repo.path.read_bytes()


def test_journal_versions_survive_restart_and_reject_stale_autosave(tmp_path):
    repo=AccountRepository(tmp_path)
    first=repo.save_note("plan",0,{"text":"first plan"},event_ms=1)
    repo.save_note("plan",1,{"text":"revised plan"},event_ms=2)
    with pytest.raises(AccountDataError,match="VERSION_CONFLICT"):
        repo.save_note("plan",1,{"text":"stale update"},event_ms=3)
    notes=AccountRepository(tmp_path).notes()
    assert {x['version'] for x in notes}=={1,2}
    assert first['recordedMs']>first['eventMs']
    with pytest.raises(AccountDataError,match="FILL_NOT_FOUND"):
        repo.save_note("linked",0,{"text":"missing"},event_ms=4,fill_id="missing")
