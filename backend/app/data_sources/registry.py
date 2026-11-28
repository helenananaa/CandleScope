"""Built-in data sources that take a user's own key (ADR-DATA-002 §8)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PRINTABLE = re.compile(r"^[\x21-\x7e]+$")


@dataclass(frozen=True)
class CredentialField:
    id: str
    # The environment variable that configured this field before the vault.
    environment: str
    min_length: int = 4
    max_length: int = 256

    def valid(self, value: object) -> bool:
        return (isinstance(value, str) and self.min_length <= len(value) <= self.max_length
                and _PRINTABLE.fullmatch(value) is not None)


@dataclass(frozen=True)
class DataSource:
    id: str
    name: str
    fields: tuple[CredentialField, ...]
    signup_url: str

    def field(self, field_id: str) -> CredentialField | None:
        return next((field for field in self.fields if field.id == field_id), None)


DATA_SOURCES: dict[str, DataSource] = {
    "twelvedata": DataSource(
        id="twelvedata",
        name="Twelve Data",
        # Real keys are 32 characters; Twelve Data's public "demo" key is 4.
        fields=(CredentialField(id="apiKey", environment="INGESTION_TWELVE_DATA_API_KEY", min_length=4),),
        signup_url="https://twelvedata.com/pricing",
    ),
}


def credential_field(source_id: str, field_id: str) -> tuple[DataSource, CredentialField] | None:
    source = DATA_SOURCES.get(source_id)
    field = source.field(field_id) if source else None
    return (source, field) if source and field else None
