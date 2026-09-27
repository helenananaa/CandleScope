import copy

import pytest

from app.replay.canonical import canonical_sha256
from app.replay.training.errors import TrainingRunError
from app.replay.training.review import validate_drawing_document


def drawing(run_id="workspace"):
    return {
        "documentSchemaVersion": 1, "scopeKey": f"replay-run:{run_id}",
        "documentRevision": 1, "updatedAt": 100,
        "entities": [{
            "id": "same-local-id", "kind": "line", "geometryRevision": 1,
            "styleRevision": 1,
            "geometry": {"kind": "line", "lineType": "line-segment",
                         "dataPoints": [{"time": 100, "price": 10}, {"time": 200, "price": 20}]},
            "style": {"kind": "line", "color": "#ffffff", "lineWidth": 2},
            "bounds": {"kind": "deferred"},
        }],
    }


def test_workspace_drawing_keeps_independent_ids_and_validates_total_count():
    document = {"documentSchemaVersion": 2, "scopeKey": "replay-run:workspace",
                "charts": {"btc": drawing(), "eth": drawing()}}
    _, digest = validate_drawing_document(document, run_id="workspace", entity_count=2)
    assert digest == canonical_sha256(document)
    assert document["charts"]["btc"]["entities"][0]["id"] == "same-local-id"
    with pytest.raises(TrainingRunError):
        validate_drawing_document(document, run_id="workspace", entity_count=1)
    invalid = copy.deepcopy(document)
    invalid["charts"]["eth"]["scopeKey"] = "replay-run:another-run"
    with pytest.raises(TrainingRunError):
        validate_drawing_document(invalid, run_id="workspace", entity_count=2)


def test_workspace_drawing_rejects_recursive_envelopes_and_unbounded_charts():
    document = {"documentSchemaVersion": 2, "scopeKey": "replay-run:workspace", "charts": {}}
    document["charts"]["recursive"] = document
    with pytest.raises(TrainingRunError):
        validate_drawing_document(document, run_id="workspace", entity_count=0)
    document["charts"] = {str(index): drawing() for index in range(257)}
    with pytest.raises(TrainingRunError):
        validate_drawing_document(document, run_id="workspace", entity_count=257)


def test_legacy_drawing_contract_remains_compatible():
    document = drawing()
    assert validate_drawing_document(document, run_id="workspace", entity_count=1)[1] == canonical_sha256(document)
