"""A replay drawing save that fails only on some drawings names each of them.

The client leaves just those drawings out of the run record and saves the
rest, instead of every later save failing on the same drawing.
"""
from __future__ import annotations

import copy

import pytest

from app.replay.canonical import canonical_sha256
from app.replay.training.errors import TrainingRunError
from app.replay.training.review import (
    REVIEW_DRAWING_REJECTION_LIMIT,
    validate_drawing_document,
)

RUN_ID = "rejections"


def line(entity_id: str, **style: object) -> dict:
    return {
        "id": entity_id, "kind": "line", "geometryRevision": 1, "styleRevision": 1,
        "geometry": {"kind": "line", "lineType": "line-segment",
                     "dataPoints": [{"time": 100, "price": 10}, {"time": 200, "price": 20}]},
        "style": {"kind": "line", "color": "#ffffff", "lineWidth": 2, **style},
        "bounds": {"kind": "deferred"},
    }


def chart(*entities: dict) -> dict:
    return {
        "documentSchemaVersion": 1, "scopeKey": f"replay-run:{RUN_ID}",
        "documentRevision": 3, "updatedAt": 100, "entities": list(entities),
    }


def workspace(**charts: dict) -> dict:
    return {"documentSchemaVersion": 2, "scopeKey": f"replay-run:{RUN_ID}", "charts": charts}


def rejected(document: dict, entity_count: int) -> dict:
    with pytest.raises(TrainingRunError) as error:
        validate_drawing_document(document, run_id=RUN_ID, entity_count=entity_count)
    assert error.value.code == "REVIEW_DRAWING_INVALID"
    assert error.value.status_code == 422
    return dict(error.value.details)


def test_each_rejected_drawing_is_named_with_its_chart_and_reason():
    future = line("future")
    for part in (future, future["geometry"], future["style"]):
        part["kind"] = "future-kind"
    floats = line("float", lineWidth=2.5)
    document = workspace(
        btc=chart(line("btc-ok"), future),
        eth=chart(line("unknown-field", unexpected=True, _private=1), floats, line("eth-ok")),
    )
    assert rejected(document, 5) == {
        "rejected": [
            {"chart": "btc", "id": "future", "kind": "future-kind",
             "reason": "UNSUPPORTED_KIND", "fields": []},
            {"chart": "eth", "id": "unknown-field", "kind": "line",
             "reason": "UNSUPPORTED_FIELD", "fields": ["style._private", "style.unexpected"]},
            {"chart": "eth", "id": "float", "kind": "line", "reason": "INVALID", "fields": []},
        ],
        "rejected_count": 3,
    }


def test_the_document_without_the_rejected_drawings_saves():
    document = workspace(
        btc=chart(line("btc-ok"), line("bad", unexpected=True)),
        eth=chart(line("eth-ok")),
    )
    rejected(document, 3)
    kept = copy.deepcopy(document)
    kept["charts"]["btc"]["entities"] = [
        entity for entity in kept["charts"]["btc"]["entities"] if entity["id"] != "bad"
    ]
    _, digest = validate_drawing_document(kept, run_id=RUN_ID, entity_count=2)
    assert digest == canonical_sha256(kept)


def test_a_legacy_single_chart_record_names_drawings_without_a_chart():
    details = rejected(chart(line("ok"), line("bad", arrowHead="open")), 2)
    assert details["rejected"] == [
        {"chart": None, "id": "bad", "kind": "line", "reason": "UNSUPPORTED_FIELD",
         "fields": ["style.arrowHead"]},
    ]


@pytest.mark.parametrize(
    "document, count",
    [
        (workspace(btc={**chart(line("a")), "scopeKey": "replay-run:another"}), 1),
        (workspace(btc=chart(line("same"), line("same"))), 2),
        (workspace(btc=chart(line("a"))), 2),
        (workspace(btc=chart({"kind": "line"})), 1),
    ],
    ids=["scope", "duplicate-id", "count", "no-id"],
)
def test_document_level_failures_name_no_drawings(document, count):
    assert rejected(document, count) == {}


def test_the_rejection_list_is_bounded():
    bad = [line(f"bad-{index}", unexpected=True) for index in range(REVIEW_DRAWING_REJECTION_LIMIT + 8)]
    details = rejected(workspace(btc=chart(*bad)), len(bad))
    assert len(details["rejected"]) == REVIEW_DRAWING_REJECTION_LIMIT
    assert details["rejected_count"] == len(bad)
