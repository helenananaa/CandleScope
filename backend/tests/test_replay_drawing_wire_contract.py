"""The replay drawing allowlist accepts every drawing the chart can create.

Replay training saves the chart's drawing document in the run record. The
frontend contract lives in frontend/src/features/drawings/core/drawingWireContract.ts;
its JSON copy frontend/contracts/drawing-wire.json lists every kind and key, plus one replay save encoded
by the frontend with every key set. A frontend tool the backend does not accept
fails these tests instead of failing every later replay drawing save with
REVIEW_DRAWING_INVALID.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.replay.canonical import canonical_sha256
from app.replay.training import review
from app.replay.training.errors import TrainingRunError
from app.replay.training.review import validate_drawing_document

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend/contracts/drawing-wire.json"
)


@pytest.fixture(scope="module")
def contract() -> dict:
    data = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert data["contract"] == "candlescope.drawing-wire.v1"
    return data


def _sample(contract: dict) -> tuple[dict, str, int]:
    sample = contract["replaySample"]
    return copy.deepcopy(sample["document"]), sample["runId"], sample["entityCount"]


def _sample_entities(document: dict) -> list[dict]:
    return [entity for chart in document["charts"].values() for entity in chart["entities"]]


def test_every_frontend_drawing_kind_is_allowed(contract):
    missing = sorted(set(contract["kinds"]) - set(review._DRAWING_GEOMETRY_KEYS))
    assert not missing, f"replay review allowlist lacks drawing kinds: {missing}"
    assert set(review._DRAWING_GEOMETRY_KEYS) == set(review._DRAWING_STYLE_KEYS)


def test_every_frontend_geometry_and_style_key_is_allowed(contract):
    common = set(contract["commonStyleKeys"])
    gaps: list[str] = []
    for kind, keys in sorted(contract["kinds"].items()):
        allowed_geometry = review._DRAWING_GEOMETRY_KEYS.get(kind, frozenset())
        allowed_style = review._DRAWING_STYLE_KEYS.get(kind, frozenset())
        gaps += [f"{kind}.geometry.{key}" for key in sorted(set(keys["geometry"]) - allowed_geometry)]
        gaps += [f"{kind}.style.{key}" for key in sorted((set(keys["style"]) | common) - allowed_style)]
    assert not gaps, f"replay review allowlist lacks drawing keys: {gaps}"


def test_frontend_replay_save_with_every_key_is_accepted(contract):
    document, run_id, entity_count = _sample(contract)
    kinds = {entity["kind"] for entity in _sample_entities(document)}
    assert kinds == set(contract["kinds"]), "the sample must cover every frontend kind"
    _, digest = validate_drawing_document(document, run_id=run_id, entity_count=entity_count)
    assert digest == canonical_sha256(document)


@pytest.mark.parametrize("kind", ["path", "channel", "range-measure"])
def test_shipped_tools_save_on_their_own(contract, kind):
    """Path, arrow path, parallel channel and the price/time range tools (1.0.1)."""
    document, run_id, _ = _sample(contract)
    for chart in document["charts"].values():
        chart["entities"] = [entity for entity in chart["entities"] if entity["kind"] == kind]
    count = len(_sample_entities(document))
    assert count == 1
    validate_drawing_document(document, run_id=run_id, entity_count=count)


@pytest.mark.parametrize(
    ("part", "key"),
    [("geometry", "unexpected"), ("style", "unexpected"), ("style", "_private")],
)
def test_keys_outside_the_contract_are_still_rejected(contract, part, key):
    document, run_id, entity_count = _sample(contract)
    _sample_entities(document)[0][part][key] = 1
    with pytest.raises(TrainingRunError) as rejected:
        validate_drawing_document(document, run_id=run_id, entity_count=entity_count)
    assert rejected.value.code == "REVIEW_DRAWING_INVALID"


def test_unknown_kinds_are_still_rejected(contract):
    document, run_id, entity_count = _sample(contract)
    entity = _sample_entities(document)[0]
    for part in (entity, entity["geometry"], entity["style"]):
        part["kind"] = "future-kind"
    with pytest.raises(TrainingRunError) as rejected:
        validate_drawing_document(document, run_id=run_id, entity_count=entity_count)
    assert rejected.value.code == "REVIEW_DRAWING_INVALID"
