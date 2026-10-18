"""Explicit control and SDK delivery contracts; no credential body field."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.backtest.request_contracts import SnapshotPreviewRequest

from .contracts import CONNECTION_PROTOCOL


class ConnectionCreateRequest(SnapshotPreviewRequest):
    strategy_revision_id: str = Field(min_length=1, max_length=128)
    snapshot_hash: str = Field(min_length=8, max_length=80)


class ConnectionSmokeRequest(ConnectionCreateRequest):
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_mode: Literal["SIGNAL", "TARGET_POSITION", "ORDER_INTENT"] = "TARGET_POSITION"


class ClientConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[CONNECTION_PROTOCOL]
    client_id: str = Field(min_length=1, max_length=128)
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ClientPollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_id: str = Field(min_length=1, max_length=128)
    client_generation: int = Field(ge=1)


class ClientReplyRequest(ClientPollRequest):
    run_id: str = Field(min_length=1, max_length=128)
    host_generation: int = Field(ge=1)
    cursor: int = Field(ge=1)
    call_id: str = Field(pattern=r"^epcall_[0-9a-f]{32}$")
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result: dict[str, Any]
