"""Monthly transport through real ZIP/checksum/parser/import/day bindings."""

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache

import pytest
from app.data_engine.storage.raw_trade_archive import RawAggTradeSelectionWindow
from app.exchanges.archive import (
    ArchiveDataError,
    ArchiveHttpResponse,
    ArchiveHttpStatusError,
    ArchiveTransportError,
)
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.history_archive import ReplayHistoryArchiveWriter
from app.replay.official_trade_history import (
    DAY,
    MINUTE,
    OfficialTradeHistoryRepository,
)

from tests.fixtures.replay.fakes import make_bar
from tests.test_replay_projection_native_seam import _batch

START = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
IDENTITY = ReplaySeriesIdentity("binance", "futures", "BTCUSDT")


class Availability:
    def list_verified_identities(self):
        return [IDENTITY.to_dict()]

    def selection_snapshot(self, **_):
        return "sha256:" + "b" * 64, (
            RawAggTradeSelectionWindow(START, START + 31 * DAY - 1, 31),
        )


@lru_cache(maxsize=8)
def payload(url, partial=False, month_shape=None):
    name = url.rsplit("/", 1)[-1]
    if "/monthly/" in url:
        start, stop = START, START + 31 * DAY
    else:
        date = name.removeprefix("BTCUSDT-1m-").removesuffix(".zip")
        start = int(
            datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp() * 1000
        )
        stop = start + DAY
    if partial and start == START:
        start += 489 * MINUTE
    if "/monthly/" in url and month_shape in {"tail", "partial"}:
        stop = START + 25 * DAY + (730 * MINUTE if month_shape == "partial" else 0)
    rows = "".join(
        f"{at},100,102,99,101,2,{at + MINUTE - 1},202,2,1,101,0\n"
        for at in range(start, stop, MINUTE)
        if not (
            "/monthly/" in url
            and month_shape == "gap"
            and START + 25 * DAY <= at < START + 26 * DAY
        )
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name.removesuffix(".zip") + ".csv", rows)
    return out.getvalue()


class Http:
    def __init__(self, *, partial=False):
        self.calls = []
        self.month_status = 200
        self.corrupt = False
        self.timeout = False
        self.partial = partial
        self.month_shape = None

    async def get_bytes(self, url, **_):
        self.calls.append(("checksum", url))
        if self.timeout:
            raise TimeoutError("upstream archive timeout")
        if "/monthly/" in url and self.month_status != 200:
            return ArchiveHttpResponse(self.month_status, {})
        archive = url.removesuffix(".CHECKSUM")
        digest = (
            "0" * 64
            if self.corrupt
            else hashlib.sha256(
                payload(archive, self.partial, self.month_shape)
            ).hexdigest()
        )
        return ArchiveHttpResponse(
            200, {}, f"{digest}  {archive.rsplit('/', 1)[-1]}\n".encode()
        )

    async def download(self, url, destination, **_):
        self.calls.append(("body", url))
        destination.write_bytes(payload(url, self.partial, self.month_shape))
        return ArchiveHttpResponse(200, {})


def source(tmp_path, monkeypatch, *, partial=False):
    import app.replay.official_chart_archive as module

    http = Http(partial=partial)
    monkeypatch.setattr(module, "AiohttpArchiveHttpClient", lambda **_: http)
    repo = OfficialTradeHistoryRepository(tmp_path, Availability())
    revision = repo.list_all_series()[0]["source_revision"]
    return repo, revision, http


def query(repo, revision, day, *, limit=3):
    return repo.query_bars_at_revision(
        revision,
        "BTCUSDT",
        "1m",
        exchange="binance",
        market_type="futures",
        start_ms=day,
        end_ms=day + (limit - 1) * MINUTE,
        limit=limit,
    )


def test_monthly_close_seed_defers_range_tree_until_a_range_query(tmp_path, monkeypatch):
    from threading import Event

    repo, revision, http = source(tmp_path, monkeypatch)
    selected = repo.tape_indicator_closes_at_revision(
        revision, "BTCUSDT", "1m", start_ms=START + DAY, end_ms=START + 2 * DAY,
        close_times=[START + DAY + 4 * MINUTE, START + 2 * DAY - MINUTE],
        exchange="binance", market_type="futures", cancelled=Event(),
    )
    assert list(map(float, selected)) == [101.0, 101.0]
    assert len(http.calls) == 2  # One real ZIP and its checksum.
    assert not list(tmp_path.rglob("*.shared-market.v1.sqlite"))
    market = repo.tape_context_market_at_revision(
        revision, "BTCUSDT", "1m", start_ms=START + DAY, end_ms=START + 2 * DAY,
        exchange="binance", market_type="futures", cancelled=Event(),
    )
    fields = market.display_summary(0, market.count)
    assert fields[:5] == (100, 102, 99, 101, 2880)
    assert market.count == 1440
    assert list(tmp_path.rglob("*.shared-market.v1.sqlite"))
    assert len(http.calls) == 2


def test_month_is_downloaded_once_and_old_daily_binding_keeps_its_prices(
    tmp_path, monkeypatch
):
    repo, revision, http = source(tmp_path, monkeypatch, partial=True)
    # An existing daily source is intentionally different from the new month.
    root = tmp_path / "days/binance/futures/BTCUSDT/2025-01-02"
    legacy = [
        make_bar(at, price="77") for at in range(START + DAY, START + 2 * DAY, MINUTE)
    ]
    ReplayHistoryArchiveWriter(root).import_batches(
        IDENTITY, "1m", [_batch(legacy, source_key="legacy", digest_character="7")]
    )
    old = query(repo, revision, START + DAY)
    binding = tmp_path / "bindings" / revision[7:] / "2025-01-02.json"
    original_binding = binding.read_bytes()
    assert not http.calls
    bounds = repo.get_history_bounds_at_revision(
        revision, "BTCUSDT", "1m", exchange="binance", market_type="futures"
    )
    assert bounds["listing_boundary_ms"] == START + 489 * MINUTE
    for day in (2, 10, 30):
        rows = query(repo, revision, START + day * DAY)
        assert (
            len(rows) == 3 and rows[-1]["open_time"] == START + day * DAY + 2 * MINUTE
        )
        assert rows[0]["close"] == 101.0
    assert len(http.calls) == 4
    assert sum("/monthly/" in url for _, url in http.calls) == 2
    assert sum("BTCUSDT-1m-2025-01-01.zip" in url for _, url in http.calls) == 2
    assert len(list((tmp_path / "bindings" / revision[7:]).glob("*.json"))) == 5
    rows[0]["close"] = "mutated"
    # A later monthly correction must not retarget a day already selected by
    # this frozen catalog. Exercise a fresh repository, not the row cache.
    month_root = tmp_path / "months/binance/futures/BTCUSDT/2025-01"
    changed = [
        make_bar(at, price="999")
        for at in range(START + 489 * MINUTE, START + 31 * DAY, MINUTE)
    ]
    ReplayHistoryArchiveWriter(month_root).import_batches(
        IDENTITY,
        "1m",
        [_batch(changed, source_key="revised-month", digest_character="8")],
    )
    restored = OfficialTradeHistoryRepository(
        tmp_path, Availability(), day_loader=lambda *_: pytest.fail("network on reopen")
    )
    assert query(restored, revision, START + DAY) == old
    assert binding.read_bytes() == original_binding
    assert query(restored, revision, START + 30 * DAY)[0]["close"] == 101.0
    assert len(http.calls) == 4


def test_concurrent_days_share_month_download_and_release_owner_locks(
    tmp_path, monkeypatch
):
    repo, revision, http = source(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda day: query(repo, revision, START + day * DAY), (0, 5, 10, 15)
            )
        )
    assert all(len(rows) == 3 for rows in results)
    assert len(http.calls) == 2
    assert not repo._archives._owners


@pytest.mark.parametrize("status", [404, 410])
def test_missing_month_falls_back_to_days_and_can_be_published_later(
    tmp_path, monkeypatch, status
):
    import app.replay.official_chart_archive as module

    repo, revision, http = source(tmp_path, monkeypatch)
    clock = [10.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    http.month_status = status
    query(repo, revision, START)
    query(repo, revision, START + DAY)
    assert len([url for _, url in http.calls if "/monthly/" in url]) == 1
    assert len([url for kind, url in http.calls if kind == "body"]) == 2
    binding = json.loads(
        (tmp_path / "bindings" / revision[7:] / "2025-01-01.json").read_text()
    )
    assert "month" not in binding
    http.month_status = 200
    clock[0] += 301
    query(repo, revision, START + 2 * DAY)
    assert len([url for _, url in http.calls if "/monthly/" in url]) == 3
    assert (
        json.loads(
            (tmp_path / "bindings" / revision[7:] / "2025-01-03.json").read_text()
        )["month"]
        == "2025-01"
    )


@pytest.mark.parametrize("status", [503, "checksum", "timeout"])
def test_transport_or_corruption_never_publishes_a_fake_day(
    tmp_path, monkeypatch, status
):
    repo, revision, http = source(tmp_path, monkeypatch)
    http.month_status = 503 if status == 503 else 200
    http.corrupt = status == "checksum"
    http.timeout = status == "timeout"
    with pytest.raises(ArchiveDataError) as failure:
        query(repo, revision, START)
    if status == 503:
        assert (
            isinstance(failure.value, ArchiveHttpStatusError)
            and failure.value.retryable
        )
    if status == "timeout":
        assert isinstance(failure.value, ArchiveTransportError)
        assert failure.value.retryable
        assert isinstance(failure.value.__cause__, TimeoutError)
    assert not list((tmp_path / "bindings").glob("**/*.json"))
    assert all("/monthly/" in url for _, url in http.calls)
    http.month_status = 200
    http.corrupt = False
    http.timeout = False
    assert len(query(repo, revision, START)) == 3


def test_open_month_uses_daily_transport(tmp_path, monkeypatch):
    original = BinanceKlineArchiveProvider.plan_objects
    monkeypatch.setattr(
        BinanceKlineArchiveProvider,
        "plan_objects",
        lambda self, **kwargs: original(self, **{**kwargs, "now_ms": START + 15 * DAY}),
    )
    repo, revision, http = source(tmp_path, monkeypatch)
    assert len(query(repo, revision, START + DAY)) == 3
    assert len(http.calls) == 2 and all("/daily/" in url for _, url in http.calls)


@pytest.mark.parametrize("month_shape", ["tail", "gap", "partial"])
def test_verified_incomplete_month_uses_complete_daily_source_for_unbound_day(
    tmp_path, monkeypatch, month_shape
):
    repo, revision, http = source(tmp_path, monkeypatch)
    http.month_shape = month_shape
    first = query(repo, revision, START)
    monthly_binding = tmp_path / "bindings" / revision[7:] / "2025-01-01.json"
    assert json.loads(monthly_binding.read_text())["month"] == "2025-01"
    before = monthly_binding.read_bytes()
    day = START + 25 * DAY
    # Month metadata is validated but has no complete coverage of this day.
    # A daily file can supply that day without changing any prior source pin.
    rows = query(repo, revision, day, limit=1440)
    assert len(rows) == 1440
    assert rows[-1]["open_time"] == day + DAY - MINUTE
    assert len(http.calls) == 4
    assert sum("/monthly/" in url for _, url in http.calls) == 2
    assert sum("BTCUSDT-1m-2025-01-26.zip" in url for _, url in http.calls) == 2
    daily_binding = tmp_path / "bindings" / revision[7:] / "2025-01-26.json"
    assert "month" not in json.loads(daily_binding.read_text())
    restored = OfficialTradeHistoryRepository(
        tmp_path, Availability(), day_loader=lambda *_: pytest.fail("network on reopen")
    )
    assert query(restored, revision, day, limit=1440) == rows
    assert query(restored, revision, START) == first
    assert monthly_binding.read_bytes() == before
