"""Versioned, data-only identity for an external strategy or model."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.backtest.strategy.protocol import (
    ProviderCapabilities,
    StrategyProviderError,
    canonical_hash,
)

MANIFEST_SCHEMA = "candlescope.external-provider/1"
CONNECTION_PROTOCOL = "candlescope.external-provider-connection/1"
EXTERNAL_REVISION = "external-decision-provider-v1"
MAX_MANIFEST_BYTES = 16_384

OutputMode = Literal["SIGNAL", "TARGET_POSITION", "ORDER_INTENT"]
FeatureName = Literal["open", "high", "low", "close", "volume"]


class ExternalProviderManifest(BaseModel):
    """No executable source, endpoint, file path or account authority."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[MANIFEST_SCHEMA]
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    provider_revision: str = Field(min_length=1, max_length=128)
    provider_kind: Literal["STRATEGY", "MODEL"]
    artifact_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    runtime_lock: str = Field(min_length=1, max_length=1024)
    input_modes: tuple[Literal["BAR_CLOSE"], ...] = Field(min_length=1, max_length=1)
    output_modes: tuple[OutputMode, ...] = Field(min_length=1, max_length=3)
    required_features: tuple[FeatureName, ...] = Field(min_length=1, max_length=5)
    warmup_bars: int = Field(ge=0, le=5000)
    snapshot_restore: Literal[True]
    reproducibility: Literal["RECORDED_OUTPUT_ONLY"]

    @field_validator("snapshot_restore", mode="before")
    @classmethod
    def require_restore(cls, value: object) -> object:
        if type(value) is not bool or value is not True:
            raise ValueError("this protocol requires explicit snapshot/restore support")
        return value

    @model_validator(mode="after")
    def validate_capabilities(self) -> ExternalProviderManifest:
        for name in ("input_modes", "output_modes", "required_features"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        if self.provider_kind == "MODEL" and "ORDER_INTENT" in self.output_modes:
            raise ValueError("models emit signals or targets; order intents require a strategy")
        return self

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            input_modes=tuple(self.input_modes),
            output_modes=tuple(self.output_modes),
            required_features=tuple(self.required_features),
            signal_clock="BAR_CLOSE",
            reproducibility=(self.reproducibility,),
            snapshot_restore=True,
            warmup_requirement={"kind": "FIXED_BARS", "bars": self.warmup_bars},
        )

    def identity(self) -> dict[str, object]:
        manifest = self.model_dump(mode="json")
        return {
            "protocol": CONNECTION_PROTOCOL,
            "manifest_hash": canonical_hash(manifest),
            "provider_id": self.provider_id,
            "provider_revision": self.provider_revision,
            "provider_kind": self.provider_kind,
            "artifact_sha256": self.artifact_sha256,
            "runtime_lock": self.runtime_lock,
            "reproducibility": self.reproducibility,
        }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON values are not allowed")


def parse_manifest(source: str) -> ExternalProviderManifest:
    try:
        if len(source.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ValueError("external provider manifest exceeds its byte limit")
        # Preserve strict JSON semantics before Pydantic converts arrays to the
        # immutable tuples used by the frozen identity.
        json.loads(source, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        return ExternalProviderManifest.model_validate_json(source)
    except ValidationError as exc:
        # A misplaced credential must not be echoed in an error or support log.
        details = exc.errors(include_input=False, include_context=False, include_url=False)
        for detail in details:
            # Unknown JSON field names can themselves contain pasted private
            # text. Keep known schema locations, never echo arbitrary keys.
            if any(isinstance(part, str) and part not in ExternalProviderManifest.model_fields for part in detail["loc"]):
                detail["loc"] = ("<unknown>",)
        raise StrategyProviderError(
            "PROVIDER_PROTOCOL_VIOLATION", f"invalid external provider manifest: {details}"
        ) from None
    except (TypeError, ValueError) as exc:
        raise StrategyProviderError(
            "PROVIDER_PROTOCOL_VIOLATION", f"invalid external provider manifest: {exc}"
        ) from exc
