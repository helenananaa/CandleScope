"""Training reports, review navigation and user annotations.

Account audit and the live global clock remain owned by the run coordinator.
Reads and annotation writes reuse its store and public-time disclosure policy.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal

from app.replay.broker.models import decimal_to_string

from . import service_validation as service_validation_ops
from .errors import TrainingRunError
from .models import REPLAY_V2_PROTOCOL, validate_v2_counter
from .storage import TrainingRunStore


class TrainingReviewService:
    """Own reports, revealed time projection, annotations and ReviewMode."""

    def __init__(
        self,
        *,
        store: TrainingRunStore,
        replay_service,
        audit_account: Callable[[str], Awaitable[dict[str, object]]],
        get_market_tracks: Callable[[str], Awaitable[dict[str, object]]],
    ) -> None:
        self.store = store
        self.replay_service = replay_service
        self._audit_account = audit_account
        self._get_market_tracks = get_market_tracks

    async def integrity(self, run_id: str) -> dict[str, object]:
        return await self.store.integrity(service_validation_ops.identifier(run_id, field_name="run_id"))

    async def rules(self, run_id: str) -> dict[str, object]:
        return await self.store.run_rules(service_validation_ops.identifier(run_id, field_name="run_id"))

    async def current_drawing_document(self, run_id: str) -> dict[str, object]:
        return await self.store.current_drawing_document(
            service_validation_ops.identifier(run_id, field_name="run_id")
        )

    async def record_drawing_document(
        self,
        run_id: str,
        *,
        command_id: str,
        document_hash: str,
        document: Mapping[str, object],
        entity_count: int,
    ) -> dict[str, object]:
        return await self.store.record_drawing_document(
            run_id=service_validation_ops.identifier(run_id, field_name="run_id"),
            command_id=service_validation_ops.identifier(command_id, field_name="command_id"),
            document_hash=service_validation_ops.digest(
                document_hash,
                field_name="document_hash",
            ),
            document=document,
            entity_count=validate_v2_counter(
                entity_count,
                field_name="entity_count",
            ),
        )

    async def record_review_marker(
        self,
        run_id: str,
        *,
        command_id: str,
        text: str,
    ) -> dict[str, object]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        return await self.store.record_review_marker(
            run_id=service_validation_ops.identifier(run_id, field_name="run_id"),
            command_id=service_validation_ops.identifier(command_id, field_name="command_id"),
            text=text,
        )

    async def public_times(
        self,
        run_id: str,
        *,
        timeline_ms: tuple[int, ...],
    ) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        if not isinstance(timeline_ms, tuple):
            raise TypeError("timeline_ms must be a tuple")
        if not 1 <= len(timeline_ms) <= 2_000:
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                "public time batch must contain between 1 and 2000 values",
                status_code=422,
            )
        return await self.store.public_times(
            normalized,
            timeline_ms=timeline_ms,
            max_items=2_000,
        )

    async def equity(
        self,
        run_id: str,
        *,
        resolution: str = "AUTO",
        limit: int = 1_000,
    ) -> dict[str, object]:
        return await self.store.equity(
            service_validation_ops.identifier(run_id, field_name="run_id"),
            resolution=resolution,
            limit=limit,
        )

    async def journal(self, run_id: str) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        binding = await self.store.run_binding(normalized)
        journal = await self.replay_service.journal(str(binding["adapter_session_id"]))
        return {
            "protocol": "replay.v3",
            "run_id": normalized,
            "entries": journal["entries"],
            "integrity": await self.store.integrity(normalized),
        }

    async def report(self, run_id: str) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        binding = await self.store.run_binding(normalized)
        report = await self.replay_service.report(str(binding["adapter_session_id"]))
        timeline_ms: set[int] = set()

        def collect(value: object, *, key: str | None = None) -> None:
            if isinstance(value, Mapping):
                for child_key, child in value.items():
                    collect(child, key=str(child_key))
            elif isinstance(value, (list, tuple)):
                for child in value:
                    collect(child, key=key)
            elif (
                key is not None
                and key.endswith("_time_ms")
                and not isinstance(value, bool)
                and isinstance(value, int)
            ):
                if value not in timeline_ms and len(timeline_ms) >= 20_000:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "training report exceeds the public-time projection bound",
                        status_code=503,
                    )
                timeline_ms.add(value)

        collect(report["report"])
        integrity = await self.store.integrity(normalized)
        if timeline_ms:
            public_time_index = await self.store.public_times(
                normalized,
                timeline_ms=tuple(sorted(timeline_ms)),
                max_items=20_000,
            )
        else:
            public_time_index = {
                "protocol": REPLAY_V2_PROTOCOL,
                "run_id": normalized,
                "policy": integrity["effective_time_disclosure_policy"],
                "items": [],
            }
        market_projection = await self.store.get_market_tracks(normalized)
        portfolio = market_projection.get("portfolio")
        account_audit = None
        if isinstance(portfolio, Mapping) and (
            portfolio.get("position_mode") == "HEDGE"
            or (
                isinstance(portfolio.get("account_history"), Mapping)
                and portfolio["account_history"].get("mode")  # type: ignore[union-attr]
                == "HISTORICAL_EXACT"
            )
        ):
            account_audit = await self._audit_account(normalized)
            market_projection = await self.store.get_market_tracks(normalized)
            portfolio = market_projection.get("portfolio")
        return {
            "protocol": "replay.v3",
            "run_id": normalized,
            "data_fidelity": report["data_fidelity"],
            "execution_fidelity": report["execution_fidelity"],
            "revealed": report["revealed"],
            "report": report["report"],
            "integrity": integrity,
            "public_time_index": public_time_index,
            "modelled_account": portfolio,
            "account_audit": account_audit,
            "liquidation_channel_contract": {
                "simulated_account": "MODELLED_ACCOUNT_NOT_MARKET_LIQUIDATION_FEED",
                "historical_market": "INDEPENDENT_FEED_OR_UNSUPPORTED",
            },
            **(
                {"actual_history": report["actual_history"]}
                if report.get("revealed") and "actual_history" in report
                else {}
            ),
        }

    async def training_results(self, run_id: str, *, limit: int) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        projection = await self.store.training_results(normalized, limit=limit)
        binding = await self.store.run_binding(normalized)
        broker_report = await self.replay_service.report(
            str(binding["adapter_session_id"])
        )
        report = service_validation_ops._stored_mapping(
            broker_report.get("report"),
            field_name="broker report",
        )
        summary = service_validation_ops._stored_mapping(
            projection.get("summary"),
            field_name="training-results summary",
        )
        realized_pnl = Decimal(str(report.get("realized_pnl", "0")))
        fees_paid = Decimal(str(report.get("fees_paid", "0")))
        return {
            **projection,
            "summary": {
                **dict(summary),
                "max_drawdown": report.get("max_drawdown", "0"),
                "profit_factor": report.get("profit_factor"),
                "fees_paid": decimal_to_string(
                    fees_paid,
                    field_name="training results fees paid",
                ),
                "net_realized_pnl": decimal_to_string(
                    realized_pnl - fees_paid,
                    field_name="training results net realized pnl",
                ),
            },
            "data_fidelity": broker_report.get("data_fidelity"),
            "execution_fidelity": broker_report.get("execution_fidelity"),
        }

    async def _assert_review_original_quiescent(self, run_id: str) -> None:
        market_tracks = await self._get_market_tracks(run_id)
        global_clock = service_validation_ops._stored_mapping(
            market_tracks.get("global_clock"),
            field_name="review global clock",
        )
        state = str(global_clock.get("state"))
        if state not in {"PAUSED", "ENDED"}:
            raise TrainingRunError(
                "REVIEW_REQUIRES_PAUSED_RUN",
                "pause the training run before entering ReviewMode",
                status_code=409,
                details={"state": state},
            )

    async def start_review(
        self,
        run_id: str,
        *,
        event_id: str | None,
    ) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        await self._assert_review_original_quiescent(normalized)
        normalized_event = (
            None
            if event_id is None
            else service_validation_ops.identifier(event_id, field_name="event_id")
        )
        return await self.store.start_review(
            run_id=normalized,
            review_id=service_validation_ops.identifier(
                f"review-{uuid.uuid4().hex}",
                field_name="review_id",
            ),
            event_id=normalized_event,
        )

    async def control_review(
        self,
        run_id: str,
        review_id: str,
        *,
        action: str,
        event_id: str | None,
        expected_cursor_revision: int,
        playback_rate: str | None,
    ) -> dict[str, object]:
        normalized_run_id = service_validation_ops.identifier(run_id, field_name="run_id")
        await self._assert_review_original_quiescent(normalized_run_id)
        normalized_event = (
            None
            if event_id is None
            else service_validation_ops.identifier(event_id, field_name="event_id")
        )
        return await self.store.control_review(
            run_id=normalized_run_id,
            review_id=service_validation_ops.identifier(review_id, field_name="review_id"),
            action=action,
            event_id=normalized_event,
            expected_cursor_revision=validate_v2_counter(
                expected_cursor_revision,
                field_name="expected_cursor_revision",
            ),
            playback_rate=playback_rate,
        )
