"""TrainingOrderService with explicit runtime dependencies and shared per-service state."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import cast

from app.replay.errors import ReplayDomainError

from . import control_rules as control_rules_ops
from . import order_rules as order_rules_ops
from . import service_validation as service_validation_ops
from .errors import TrainingRunError
from .models import (
    REPLAY_V2_PROTOCOL,
    BookMode,
    TrainingCursor,
)
from .multitrack import (
    TrainingRunActor,
)


class TrainingOrderService:
    """Own order operations outside command orchestration."""

    def __init__(self, *, store, replay_service, historical_books, run_actors) -> None:
        self.store = store
        self.replay_service = replay_service
        self.historical_books = historical_books
        self._run_actors = run_actors

    async def preview_order(
        self,
        run_id: str,
        *,
        expected_revision: int,
        expected_cursor: TrainingCursor,
        position_intent: str,
        order: Mapping[str, object],
        trade_plan: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Return a non-mutating order preview bound to one authoritative cursor."""

        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        if expected_revision != expected_cursor.revision:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "preview revision must match expected cursor revision",
                status_code=422,
            )
        actor = self._run_actors.setdefault(normalized, TrainingRunActor(normalized))
        async with actor.serialized():
            binding = await self.store.run_binding(normalized)
            projection = await self.store.get_market_tracks(normalized)
            tracks = projection.get("tracks")
            if not isinstance(tracks, list):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market tracks projection is invalid",
                    status_code=503,
                )
            selected_track_id = str(binding["selected_track_id"])
            selected = next(
                (
                    track
                    for track in tracks
                    if isinstance(track, Mapping)
                    and track.get("track_id") == selected_track_id
                ),
                None,
            )
            if (
                selected is None
                or selected.get("subscription_tier") != "FULL"
                or selected.get("state") != "READY"
            ):
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_READY",
                    "order preview requires the selected market track to be READY and FULL",
                    status_code=409,
                )
            session_id = str(binding["adapter_session_id"])
            session = await self.replay_service.get_session(session_id)
            snapshot = service_validation_ops.adapter_snapshot(session)
            cursor = snapshot.get("cursor")
            if not isinstance(cursor, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "adapter cursor is invalid",
                    status_code=503,
                )
            actual = {
                "virtual_time_ms": cursor.get("virtual_time_ms"),
                "source_sequence": cursor.get("source_sequence"),
                "revision": snapshot.get("revision"),
            }
            if actual != expected_cursor.to_dict():
                raise TrainingRunError(
                    "REVISION_CONFLICT",
                    "preview cursor does not match the authoritative run cursor",
                    status_code=409,
                    details={"expected": expected_cursor.to_dict(), "actual": actual},
                )
            await self._guard_historical_book_current(
                run_id=normalized,
                binding=binding,
                snapshot=snapshot,
            )
            payload = dict(
                order_rules_ops.order_payload_with_optional_leverage(
                    order,
                    {
                        "client_order_id",
                        "side",
                        "order_type",
                        "quantity",
                        "reduce_only",
                        "limit_price",
                        "stop_price",
                    },
                )
            )
            if position_intent not in {"NET", "OPEN"}:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "order preview position intent is unsupported",
                    status_code=422,
                )
            if binding.get("position_mode") == "HEDGE" and payload.get(
                "position_side"
            ) not in {"LONG", "SHORT"}:
                raise TrainingRunError(
                    "ORDER_REJECTED",
                    "HEDGE order preview requires position_side",
                    status_code=409,
                )
            if position_intent == "OPEN" and binding.get("position_mode") != "HEDGE":
                if (
                    payload.get("order_type") != "MARKET"
                    or payload.get("reduce_only") is not False
                ):
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "OPEN preview is only available for non-reduce-only market orders",
                        status_code=422,
                    )
                position = selected.get("position")
                if not isinstance(position, Mapping):
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "selected position projection is invalid",
                        status_code=503,
                    )
                try:
                    position_quantity = Decimal(str(position.get("quantity")))
                except InvalidOperation as exc:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "selected position quantity is invalid",
                        status_code=503,
                    ) from exc
                if position_quantity != 0 and (position_quantity > 0) != (
                    payload.get("side") == "BUY"
                ):
                    raise TrainingRunError(
                        "ORDER_REJECTED",
                        "OPEN cannot reduce or reverse the current position",
                        status_code=409,
                    )
            normalized_plan: dict[str, object] | None = None
            if trade_plan is not None:
                if position_intent != "OPEN":
                    raise TrainingRunError(
                        "TRADE_PLAN_INVALID",
                        "trade plans are only available for opening orders",
                        status_code=422,
                    )
                provisional_entry = order_rules_ops.planned_entry_reference(
                    payload=payload,
                    selected_track=selected,
                )
                normalized_plan = order_rules_ops.build_trade_plan_snapshot(
                    draft=trade_plan,
                    payload=payload,
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                    entry_price=provisional_entry,
                )
                payload["quantity"] = normalized_plan["quantity"]
            order_rules_ops.assert_exact_account_order_filters(
                payload=payload,
                selected_track=selected,
                portfolio=projection.get("portfolio"),
            )
            order_rules_ops.assert_shared_settlement_reservation(
                payload=payload,
                selected_track=selected,
                portfolio=projection.get("portfolio"),
                binding=binding,
            )
            try:
                adapter_preview = await self.replay_service.preview_order(
                    session_id,
                    payload,
                )
            except ReplayDomainError as exc:
                raise TrainingRunError(
                    exc.code.value,
                    exc.message,
                    status_code=exc.http_status,
                    details=exc.details,
                ) from exc
            preview_cursor = adapter_preview.get("cursor")
            if not isinstance(preview_cursor, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "adapter preview cursor is invalid",
                    status_code=503,
                )
            preview_actual = {
                "virtual_time_ms": preview_cursor.get("virtual_time_ms"),
                "source_sequence": preview_cursor.get("source_sequence"),
                "revision": adapter_preview.get("revision"),
            }
            if preview_actual != expected_cursor.to_dict():
                raise TrainingRunError(
                    "REVISION_CONFLICT",
                    "market advanced while the order preview was built",
                    status_code=409,
                    details={
                        "expected": expected_cursor.to_dict(),
                        "actual": preview_actual,
                    },
                )
            preview = adapter_preview.get("preview")
            if not isinstance(preview, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "adapter order preview is invalid",
                    status_code=503,
                )
            if normalized_plan is not None:
                normalized_plan = order_rules_ops.build_trade_plan_snapshot(
                    draft=trade_plan,
                    payload=payload,
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                    entry_price=preview.get("estimated_fill_price"),
                )
                if payload["quantity"] != normalized_plan["quantity"]:
                    payload["quantity"] = normalized_plan["quantity"]
                    order_rules_ops.assert_exact_account_order_filters(
                        payload=payload,
                        selected_track=selected,
                        portfolio=projection.get("portfolio"),
                    )
                    order_rules_ops.assert_shared_settlement_reservation(
                        payload=payload,
                        selected_track=selected,
                        portfolio=projection.get("portfolio"),
                        binding=binding,
                    )
                    try:
                        adapter_preview = await self.replay_service.preview_order(
                            session_id,
                            payload,
                        )
                    except ReplayDomainError as exc:
                        raise TrainingRunError(
                            exc.code.value,
                            exc.message,
                            status_code=exc.http_status,
                            details=exc.details,
                        ) from exc
                    preview = service_validation_ops._stored_mapping(
                        adapter_preview.get("preview"),
                        field_name="adapter order preview",
                    )
                    revised_cursor = service_validation_ops._stored_mapping(
                        adapter_preview.get("cursor"),
                        field_name="adapter order preview cursor",
                    )
                    revised_actual = {
                        "virtual_time_ms": revised_cursor.get("virtual_time_ms"),
                        "source_sequence": revised_cursor.get("source_sequence"),
                        "revision": adapter_preview.get("revision"),
                    }
                    if revised_actual != expected_cursor.to_dict():
                        raise TrainingRunError(
                            "REVISION_CONFLICT",
                            "market advanced while the planned quantity was recalculated",
                            status_code=409,
                            details={
                                "expected": expected_cursor.to_dict(),
                                "actual": revised_actual,
                            },
                        )
            preview = {
                **dict(preview),
                "max_quantity": order_rules_ops.shared_order_capacity_quantity(
                    adapter_max_quantity=preview.get("max_quantity"),
                    reference_price=preview.get("reference_price"),
                    payload=payload,
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                    binding=binding,
                ),
            }
            response = {
                **dict(preview),
                "protocol": REPLAY_V2_PROTOCOL,
                "schema_version": (
                    "replay.order-preview.v2"
                    if normalized_plan is not None
                    else "replay.order-preview.v1"
                ),
                "run_id": normalized,
                "track_id": selected_track_id,
                "accepted": True,
                "position_intent": position_intent,
                "revision": expected_revision,
                "cursor": expected_cursor.to_dict(),
                "state_hash": adapter_preview["state_hash"],
                "execution_fidelity": adapter_preview["execution_fidelity"],
            }
            if normalized_plan is not None:
                response["trade_plan"] = normalized_plan
            return response

    async def order_capacity(
        self,
        run_id: str,
        *,
        expected_revision: int,
        expected_cursor: TrainingCursor,
        position_intent: str,
        context: Mapping[str, object],
    ) -> dict[str, object]:
        """Return a cursor-bound maximum without validating a draft quantity."""

        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        if expected_revision != expected_cursor.revision:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "capacity revision must match expected cursor revision",
                status_code=422,
            )
        actor = self._run_actors.setdefault(normalized, TrainingRunActor(normalized))
        async with actor.serialized():
            binding = await self.store.run_binding(normalized)
            projection = await self.store.get_market_tracks(normalized)
            tracks = projection.get("tracks")
            if not isinstance(tracks, list):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market tracks projection is invalid",
                    status_code=503,
                )
            selected_track_id = str(binding["selected_track_id"])
            selected = next(
                (
                    track
                    for track in tracks
                    if isinstance(track, Mapping)
                    and track.get("track_id") == selected_track_id
                ),
                None,
            )
            if (
                selected is None
                or selected.get("subscription_tier") != "FULL"
                or selected.get("state") != "READY"
            ):
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_READY",
                    "order capacity requires the selected market track to be READY and FULL",
                    status_code=409,
                )
            session_id = str(binding["adapter_session_id"])
            session = await self.replay_service.get_session(session_id)
            snapshot = service_validation_ops.adapter_snapshot(session)
            cursor = snapshot.get("cursor")
            if not isinstance(cursor, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "adapter cursor is invalid",
                    status_code=503,
                )
            actual = {
                "virtual_time_ms": cursor.get("virtual_time_ms"),
                "source_sequence": cursor.get("source_sequence"),
                "revision": snapshot.get("revision"),
            }
            if actual != expected_cursor.to_dict():
                raise TrainingRunError(
                    "REVISION_CONFLICT",
                    "capacity cursor does not match the authoritative run cursor",
                    status_code=409,
                    details={"expected": expected_cursor.to_dict(), "actual": actual},
                )
            await self._guard_historical_book_current(
                run_id=normalized,
                binding=binding,
                snapshot=snapshot,
            )
            payload = dict(
                order_rules_ops.order_payload_with_optional_leverage(
                    context,
                    {
                        "side",
                        "order_type",
                        "reduce_only",
                        "limit_price",
                        "stop_price",
                    },
                )
            )
            if position_intent not in {"NET", "OPEN"}:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "order capacity position intent is unsupported",
                    status_code=422,
                )
            if binding.get("position_mode") == "HEDGE" and payload.get(
                "position_side"
            ) not in {"LONG", "SHORT"}:
                raise TrainingRunError(
                    "ORDER_REJECTED",
                    "HEDGE order capacity requires position_side",
                    status_code=409,
                )
            if position_intent == "OPEN" and binding.get("position_mode") != "HEDGE":
                if (
                    payload.get("order_type") != "MARKET"
                    or payload.get("reduce_only") is not False
                ):
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "OPEN capacity is only available for non-reduce-only market orders",
                        status_code=422,
                    )
                position = selected.get("position")
                if not isinstance(position, Mapping):
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "selected position projection is invalid",
                        status_code=503,
                    )
                try:
                    position_quantity = Decimal(str(position.get("quantity")))
                except InvalidOperation as exc:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "selected position quantity is invalid",
                        status_code=503,
                    ) from exc
                if position_quantity != 0 and (position_quantity > 0) != (
                    payload.get("side") == "BUY"
                ):
                    raise TrainingRunError(
                        "ORDER_REJECTED",
                        "OPEN cannot reduce or reverse the current position",
                        status_code=409,
                    )
            order_rules_ops.assert_exact_account_capacity_context(
                payload=payload,
                selected_track=selected,
                portfolio=projection.get("portfolio"),
            )
            try:
                adapter_capacity = await self.replay_service.order_capacity(
                    session_id,
                    payload,
                )
            except ReplayDomainError as exc:
                raise TrainingRunError(
                    exc.code.value,
                    exc.message,
                    status_code=exc.http_status,
                    details=exc.details,
                ) from exc
            capacity_cursor = adapter_capacity.get("cursor")
            if not isinstance(capacity_cursor, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "adapter capacity cursor is invalid",
                    status_code=503,
                )
            capacity_actual = {
                "virtual_time_ms": capacity_cursor.get("virtual_time_ms"),
                "source_sequence": capacity_cursor.get("source_sequence"),
                "revision": adapter_capacity.get("revision"),
            }
            if capacity_actual != expected_cursor.to_dict():
                raise TrainingRunError(
                    "REVISION_CONFLICT",
                    "market advanced while order capacity was calculated",
                    status_code=409,
                    details={
                        "expected": expected_cursor.to_dict(),
                        "actual": capacity_actual,
                    },
                )
            raw_capacity = adapter_capacity.get("capacity")
            if not isinstance(raw_capacity, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "adapter order capacity is invalid",
                    status_code=503,
                )
            maximum = order_rules_ops.shared_order_capacity_quantity(
                adapter_max_quantity=raw_capacity.get("max_quantity"),
                reference_price=raw_capacity.get("reference_price"),
                payload=payload,
                selected_track=selected,
                portfolio=projection.get("portfolio"),
                binding=binding,
            )
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "schema_version": "replay.order-capacity.v1",
                "run_id": normalized,
                "track_id": selected_track_id,
                "position_intent": position_intent,
                "revision": expected_revision,
                "cursor": expected_cursor.to_dict(),
                "state_hash": adapter_capacity["state_hash"],
                "execution_fidelity": adapter_capacity["execution_fidelity"],
                "context": dict(raw_capacity["context"]),
                "reference_price": raw_capacity["reference_price"],
                "max_quantity": maximum,
                "quote_asset": raw_capacity["quote_asset"],
                "max_leverage": raw_capacity["max_leverage"],
            }

    async def _guard_historical_book_current(
        self,
        *,
        run_id: str,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        tracks: list[Mapping[str, object]] | None = None,
    ) -> None:
        if (
            str(binding.get("book_mode", "OFF"))
            != BookMode.BOOK_ASSISTED_REQUIRED.value
        ):
            return
        cursor = service_validation_ops._stored_mapping(
            snapshot.get("cursor"), field_name="adapter cursor"
        )
        virtual_time_ms = service_validation_ops._stored_counter(
            cursor.get("virtual_time_ms"), field_name="virtual_time_ms"
        )
        if tracks is None:
            values = await self.store.get_market_track_heads(run_id)
            tracks = [
                cast(Mapping[str, object], track)
                for track in values
                if isinstance(track, Mapping)
                and track.get("subscription_tier") == "FULL"
            ]
        prepared = await self.historical_books.prepare_run_projection(
            run_id=run_id,
            tracks=tracks,
            actual_time_ms=control_rules_ops.actual_event_time_ms(
                binding, virtual_time_ms
            ),
            virtual_time_ms=virtual_time_ms,
        )
        await self.historical_books.commit_run_projection(
            run_id=run_id,
            prepared=prepared,
        )
