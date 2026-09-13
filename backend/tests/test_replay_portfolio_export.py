import json
from hashlib import sha256
from decimal import Decimal, localcontext
from itertools import groupby

import pytest

from app.replay.training.portfolio_history import capture, curve, export_chunks
from app.replay.training.models import ReplayV2CommandType as C
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market


@pytest.mark.anyio
async def test_portfolio_review_and_export_are_versioned_and_self_contained(
    tmp_path, monkeypatch
):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=100)
    try:
        await service.training.prepare_indexed_run(run)
        at = (await service.get_session_state(session))["cursor"]["virtual_time_ms"]
        await send(
            "advance",
            C.ADVANCE_TO,
            {"virtual_time_ms": at + 90 * 60000, "stop_on_event": False},
        )
        snapshot = await capture(service.training, run)
        await send(
            "later",
            C.ADVANCE_TO,
            {"virtual_time_ms": at + 95 * 60000, "stop_on_event": False},
        )
        assert snapshot["end"] == at + 90 * 60000
        response = await service.store.run_worker(
            "curve",
            curve,
            snapshot,
            input_root=service.training.hedge_inputs.root,
            limit=20,
            bucket_ms=60000,
        )
        assert response["available"] and len(response["samples"]) <= 20
        assert response["complete_training_history"] is False
        payload = await service.store.run_worker(
            "export",
            lambda: b"".join(
                export_chunks(snapshot, input_root=service.training.hedge_inputs.root)
            ),
        )
        lines = payload.splitlines(keepends=True)
        records = [json.loads(line) for line in lines]
        assert records[-1]["kind"] == "complete"
        assert records[-1]["sha256"] == sha256(b"".join(lines[:-1])).hexdigest()
        assert records[-1]["records"] == len(records) - 1
        assert b"public_path" not in payload and b"actual_delta" not in payload
        assert records[0]["span_ms"] <= snapshot["end"] - min(
            row[1] for row in snapshot["rows"]
        )
        for interval in (r for r in records if r.get("kind") == "interval"):
            marks = sorted(
                (
                    r
                    for r in records
                    if r.get("kind") == "mark" and r["interval"] == interval["index"]
                ),
                key=lambda r: (
                    r["offset_ms"],
                    r["event_phase"],
                    r["track_id"],
                    r["sequence"],
                ),
            )
            prices = {k: Decimal(v) for k, v in interval["initial_prices"].items()}

            def equity():
                return Decimal(interval["cash"]) + sum(
                    (
                        (prices[leg["track_id"]] - Decimal(leg["entry"]))
                        * Decimal(leg["quantity"])
                        * Decimal(leg["contract_size"])
                        * (1 if leg["side"] == "LONG" else -1)
                        for leg in interval["legs"]
                    ),
                    Decimal(0),
                )

            with localcontext() as context:
                context.prec = 60
                values = [equity()]
                for _, cohort in groupby(marks, key=lambda r: r["offset_ms"]):
                    for mark in cohort:
                        assert (
                            interval["start_ms"]
                            < mark["offset_ms"]
                            <= interval["end_ms"]
                        )
                        prices[mark["track_id"]] = Decimal(mark["price"])
                    values.append(equity())
                assert values[-1] == Decimal(interval["summary"]["last"])
                assert min(values) == Decimal(interval["summary"]["trough"])
                assert max(values) == Decimal(interval["summary"]["peak"])
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from app.api.v1.replay import router

        app = FastAPI()
        app.state.replay_service = service
        app.include_router(router, prefix="/api/v1")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            plotted = await client.get(f"/api/v1/replay/runs/{run}/portfolio-equity")
            assert plotted.status_code == 200, plotted.text
            assert plotted.json()["scope"] == "RECORDED_PORTFOLIO_INTERVALS"
            exported = await client.get(
                f"/api/v1/replay/runs/{run}/portfolio-equity/export"
            )
            assert exported.status_code == 200, exported.text
            assert "attachment" in exported.headers["content-disposition"]
            assert json.loads(exported.content.splitlines()[-1])["kind"] == "complete"
    finally:
        await service.shutdown(step_timeout=5)
