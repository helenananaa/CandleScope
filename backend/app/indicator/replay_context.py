"""Bind local indicator execution to its captured, durable replay observation."""

from pydantic import BaseModel, ConfigDict, Field

from app.replay.training.errors import TrainingRunError


class IndicatorReplayContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: str = Field(..., strict=True, min_length=1, max_length=256)
    trackId: str = Field(..., strict=True, min_length=1, max_length=256)
    dataEpoch: str = Field(..., strict=True, pattern=r"^sha256:[0-9a-f]{64}$")
    revealedBoundaryMs: int = Field(..., strict=True, ge=0, le=9_007_199_254_740_991)
    sourceSequence: int | None = Field(None, strict=True, ge=0, le=9_007_199_254_740_991)


async def replay_execution_options(context, training, *, exchange, market_type, symbol):
    """One metadata-only read per batch; never materialize history or mutate actors.

    Older captured observations remain valid as playback advances. Execution
    always uses the captured clock, never the newer durable tail or wall time.
    """
    if context is None:
        return {}
    if training is None:
        raise TrainingRunError(
            "REPLAY_TRAINING_UNAVAILABLE", "Replay indicator context is unavailable.", status_code=503
        )
    binding = await training.store.history_binding(session_id=context.sessionId, track_id=context.trackId)
    if binding.get("degraded_reason") is not None:
        raise TrainingRunError("HISTORY_SNAPSHOT_UNAVAILABLE", "Replay source is unavailable.", status_code=503)
    epochs = {binding["track_dataset_epoch"], binding["session_data_epoch"]}
    if binding["session_id"] == binding["primary_adapter_session_id"]:
        epochs.add(binding["run_dataset_epoch"])
    if epochs != {context.dataEpoch}:
        raise TrainingRunError("HISTORY_DATA_EPOCH_MISMATCH", "Replay indicator data epoch does not match.")
    if any(binding[field] != value for field, value in (
        ("exchange", exchange), ("market_type", market_type), ("symbol", symbol),
    )):
        raise TrainingRunError("HISTORY_SOURCE_IDENTITY_DRIFT", "Replay indicator market does not match.")
    if binding["subscription_tier"] not in {"WARM", "FULL"}:
        raise TrainingRunError("HISTORY_SOURCE_UNAVAILABLE", "Replay track has no indicator subscription.")
    if context.revealedBoundaryMs > binding["virtual_time_ms"]:
        raise TrainingRunError("HISTORY_BOUNDARY_AHEAD", "Indicator boundary is ahead of the durable replay cursor.")
    if context.sourceSequence is not None and context.sourceSequence > binding["source_sequence"]:
        raise TrainingRunError("HISTORY_SOURCE_SEQUENCE_AHEAD", "Indicator sequence is ahead of the durable replay cursor.")
    return {
        "pineExecutionTimeMs": context.revealedBoundaryMs,
        "pineRevealedBoundaryMs": context.revealedBoundaryMs,
    }
