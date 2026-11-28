"""ADR-DATA-002 D2e: imported daily datasets on an exchange trading calendar."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.backtest.runtime import BacktestRuntime
from app.core.config import load_backtest_settings
from app.data_engine.history.calendar import CalendarRegistry, get_history_calendar_registry
from app.data_engine.history.exchange_date_calendar import (
    CN_A_SHARE_DAILY_CALENDAR_ID,
    ExchangeDateCalendar,
    build_cn_a_share_calendar,
)
from app.data_engine.history.expected_bars import calendar_by_id, follows, session_calendar
from app.local_data import LocalDatasetError, LocalDatasetService, LocalImportOptions


DAY_MS = 86_400_000
CN = CN_A_SHARE_DAILY_CALENDAR_ID


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _day(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).date().isoformat()


def _write_csv(path: Path, dates: list[str], *, start: float = 10.0) -> Path:
    rows = ["time,open,high,low,close,volume"]
    price = start
    for index, value in enumerate(dates):
        step = 0.4 if (index // 4) % 2 == 0 else -0.4
        close = price + step
        rows.append(f"{value},{price:.2f},{max(price, close) + 0.1:.2f},{min(price, close) - 0.1:.2f},{close:.2f},{100 + index}")
        price = close
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _import(service: LocalDatasetService, path: Path, **overrides) -> dict:
    options = {
        "name": "A-share fixture",
        "symbol": "SH600000",
        "interval": "1d",
        "timezone_name": "UTC",
        "timestamp_unit": "iso",
        "calendar_id": CN,
        **overrides,
    }
    return service.import_csv(path, LocalImportOptions(**options))


# --- the calendar ------------------------------------------------------------


def test_a_share_calendar_follows_shanghai_trading_dates() -> None:
    calendar = build_cn_a_share_calendar()
    assert calendar.calendar_id == CN
    assert calendar.first_session == date(1990, 12, 19)
    assert calendar.known_through >= date(2026, 12, 31)
    # 2024 had 242 sessions; the Spring Festival closed 2024-02-09..2024-02-18.
    assert calendar.count_expected(_ms("2024-01-01"), _ms("2024-12-31"), "1d") == 242
    assert _day(calendar.next_expected_open(_ms("2024-02-08"), "1d")) == "2024-02-19"
    assert _day(calendar.previous_expected_open(_ms("2024-02-19"), "1d")) == "2024-02-08"
    assert follows(calendar, "1d", _ms("2024-01-05"), _ms("2024-01-08"))
    assert not follows(calendar, "1d", _ms("2024-01-05"), _ms("2024-01-09"))
    assert calendar.first_expected_open(_ms("2024-02-10"), _ms("2024-02-18"), "1d") is None
    assert calendar.previous_expected_open(_ms("1990-12-19"), "1d") is None
    segments = calendar.open_segments(_ms("2024-01-01"), _ms("2024-01-14"), "1d")
    assert [(_day(item.start_ms), _day(item.end_ms)) for item in segments] == [
        ("2024-01-02", "2024-01-05"),
        ("2024-01-08", "2024-01-12"),
    ]
    assert calendar.bucket_end_ms(_ms("2024-01-02"), "1d") == _ms("2024-01-03")


def test_the_calendar_refuses_dates_it_does_not_know_and_intraday_bars() -> None:
    calendar = build_cn_a_share_calendar()
    beyond = calendar.known_end_ms
    last = calendar.last_expected_open(beyond - 30 * DAY_MS, beyond - 1, "1d")
    assert last is not None
    with pytest.raises(ValueError, match="known only through"):
        calendar.next_expected_open(last, "1d")
    with pytest.raises(ValueError, match="known only through"):
        calendar.count_expected(beyond - DAY_MS, beyond + 10 * DAY_MS, "1d")
    with pytest.raises(ValueError, match="known only through"):
        calendar.first_expected_open(beyond, beyond + 10 * DAY_MS, "1d")
    with pytest.raises(ValueError, match="daily"):
        calendar.first_expected_open(_ms("2024-01-02"), _ms("2024-01-03"), "1h")
    # A session inside the known schedule is still found from a range past it.
    assert calendar.first_expected_open(last, beyond + DAY_MS, "1d") == last


def test_any_process_resolves_the_calendar_from_the_default_registry() -> None:
    calendar = calendar_by_id(CN)
    assert isinstance(calendar, ExchangeDateCalendar)
    assert session_calendar(calendar) is calendar
    assert CN in get_history_calendar_registry().ids()
    assert CalendarRegistry(include_defaults=False).get(CN) is None


def test_registered_factories_are_built_once() -> None:
    built: list[int] = []
    sessions = (date(2024, 1, 2), date(2024, 1, 3))

    def factory() -> ExchangeDateCalendar:
        built.append(1)
        return ExchangeDateCalendar(calendar_id="test.dates", sessions=sessions, known_through=date(2024, 1, 31), source="test")

    registry = CalendarRegistry(include_defaults=False)
    registry.register_factory("test.dates", factory)
    assert "test.dates" in registry.ids()
    assert registry.get("test.dates") is registry.get("test.dates")
    assert built == [1]
    with pytest.raises(ValueError, match="already registered"):
        registry.register_factory("test.dates", factory)


# --- importing -----------------------------------------------------------------


def test_closures_are_not_gaps_but_a_missing_session_is(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local")
    # 02-09..02-18 is the Spring Festival; 02-20 is a session left out (a suspension).
    path = _write_csv(tmp_path / "bars.csv", ["2024-02-07", "2024-02-08", "2024-02-19", "2024-02-21", "2024-02-22"])
    manifest = _import(service, path)
    assert manifest["calendar_id"] == CN
    assert manifest["excluded_range_count"] == 1
    details = service.revision_details(manifest["dataset_id"], manifest["data_epoch"])
    assert details["quality"]["excluded_ranges"] == [
        {"start_ms": _ms("2024-02-20"), "end_ms": _ms("2024-02-21"), "reason": "source_gap", "missing_bars": 1},
    ]
    assert details["receipt"]["calendar"]["calendar_id"] == CN
    assert details["receipt"]["calendar"]["source"].startswith("exchange_calendars ")


def test_rows_off_the_calendar_are_refused(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local")
    weekend = _write_csv(tmp_path / "weekend.csv", ["2024-02-08", "2024-02-10"])
    with pytest.raises(LocalDatasetError, match="Row 3: 2024-02-10T00:00:00Z is not a trading day") as raised:
        _import(service, weekend)
    assert raised.value.code == "calendar_session_mismatch"

    # Dates read as Shanghai midnight open at 16:00 UTC the day before.
    shanghai = _write_csv(tmp_path / "shanghai.csv", ["2024-02-07", "2024-02-08"])
    with pytest.raises(LocalDatasetError) as raised:
        _import(service, shanghai, timezone_name="Asia/Shanghai")
    assert raised.value.code == "calendar_session_mismatch"

    known = build_cn_a_share_calendar().known_through
    future = _write_csv(tmp_path / "future.csv", [date.fromordinal(known.toordinal() + 5).isoformat()])
    with pytest.raises(LocalDatasetError) as raised:
        _import(service, future)
    assert raised.value.code == "calendar_range_unavailable"


def test_the_calendar_must_be_known_and_fit_the_interval(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local")
    path = _write_csv(tmp_path / "bars.csv", ["2024-02-07", "2024-02-08"])
    with pytest.raises(LocalDatasetError) as raised:
        _import(service, path, calendar_id="xnys.regular")
    assert raised.value.code == "calendar_unknown"
    with pytest.raises(LocalDatasetError) as raised:
        _import(service, path, interval="1h")
    assert raised.value.code == "calendar_interval_unsupported"


def test_datasets_without_a_calendar_keep_their_epoch(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local")
    path = tmp_path / "golden.csv"
    path.write_text(
        "time,open,high,low,close,volume\n"
        "2024-02-07,10,11,9,10.5,100\n2024-02-08,10.5,11,10,10.8,120\n"
        "2024-02-19,10.8,12,10.6,11.9,300\n2024-02-21,11.9,12.2,11.5,12,90\n",
        encoding="utf-8",
    )
    plain = _import(service, path, symbol="SH600000", name="g", calendar_id=None)
    # Epoch of this file before D2e (integration/multi-asset-data 620d3f6d7).
    assert plain["data_epoch"] == "sha256:6b4cc78443ec3db3f3f390006ce49cdadda2aab4a60578d7fbebbacfb530dd10"
    assert "calendar_id" not in plain
    assert plain["excluded_range_count"] == 2
    on_calendar = _import(service, path, symbol="SH600000", name="g")
    assert on_calendar["data_epoch"] != plain["data_epoch"]
    assert on_calendar["excluded_range_count"] == 1


def test_a_revision_keeps_the_dataset_calendar(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local")
    first = _import(service, _write_csv(tmp_path / "a.csv", ["2024-02-07", "2024-02-08"]))
    revised = _import(
        service,
        _write_csv(tmp_path / "b.csv", ["2024-02-07", "2024-02-08", "2024-02-19"]),
        dataset_id=first["dataset_id"],
        calendar_id=None,
    )
    assert revised["calendar_id"] == CN
    plain = _import(service, _write_csv(tmp_path / "c.csv", ["2024-02-07", "2024-02-08"]), calendar_id=None)
    with pytest.raises(LocalDatasetError) as raised:
        _import(service, _write_csv(tmp_path / "d.csv", ["2024-02-07"]), dataset_id=plain["dataset_id"])
    assert raised.value.code == "dataset_identity_mismatch"


def test_calendar_datasets_show_only_their_source_interval(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local")
    manifest = _import(service, _write_csv(tmp_path / "bars.csv", ["2024-02-07", "2024-02-08", "2024-02-19"]))
    rows = service.query(manifest["dataset_id"], interval="1d", limit=10)
    assert rows["count"] == 3
    with pytest.raises(LocalDatasetError) as raised:
        service.query(manifest["dataset_id"], interval="2d", limit=10)
    assert raised.value.code == "interval_not_composable"
    # Host snapshots on a session calendar keep their derived intervals.
    snapshot = {"interval": "1m", "alignment_offset_ms": 0, "calendar_id": "twelvedata.exchange-date.weekdays.utc"}
    assert service.resolve_interval(snapshot, "5m").derived


# --- strategy runs ---------------------------------------------------------------


def _trading_days(start: str, count: int) -> list[str]:
    calendar = build_cn_a_share_calendar()
    opens = list(calendar.expected_opens(_ms(start), _ms(start) + 400 * DAY_MS, "1d"))[:count]
    return [_day(value) for value in opens]


def _run_sma(tmp_path: Path, calendar_id: str | None) -> dict:
    local_root = tmp_path / "local"
    service = LocalDatasetService(local_root)
    path = _write_csv(tmp_path / "bars.csv", _trading_days("2024-01-02", 60))
    manifest = _import(service, path, calendar_id=calendar_id)
    settings = load_backtest_settings(
        {"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"},
        data_dir=tmp_path,
        klines_db_path=tmp_path / "candlescope.db",
        replay_db_path=tmp_path / "replay.db",
    )
    runtime = BacktestRuntime.start(settings, local_data_dir=local_root)
    try:
        end_ms = int(manifest["last_open_ms"]) + DAY_MS - 1
        preview = runtime.preview_snapshot(
            dataset_id=manifest["dataset_id"],
            data_epoch=manifest["data_epoch"],
            start_time_ms=int(manifest["first_open_ms"]),
            end_time_ms=end_ms,
            interval="1d",
        )
        created = runtime.service.create_run(
            {
                "strategy_revision_id": "builtin-sma-cross-v1",
                "dataset_id": manifest["dataset_id"],
                "data_epoch": manifest["data_epoch"],
                "snapshot_hash": preview["snapshot_hash"],
                "fidelity_mode": "BAR_APPROX",
                "start_time_ms": int(manifest["first_open_ms"]),
                "end_time_ms": end_ms,
                "interval": "1d",
                "parameters": {"fast": 3, "slow": 5},
            },
            idempotency_key=f"d2e-{calendar_id}",
        )
        deadline = time.monotonic() + 30
        record = created
        while time.monotonic() < deadline:
            record = runtime.service.get_run(str(created["run_id"]))
            if record["state"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.05)
        return record
    finally:
        runtime.shutdown()


def test_a_strategy_runs_across_market_closures(tmp_path: Path) -> None:
    record = _run_sma(tmp_path, CN)
    assert record["state"] == "COMPLETED", record


def test_without_a_calendar_closures_still_stop_the_run(tmp_path: Path) -> None:
    record = _run_sma(tmp_path, None)
    assert record["state"] == "FAILED"
    assert "DATA_GAP_REJECTED" in str(record.get("error_code") or record.get("error_message") or record)
