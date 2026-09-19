import random

import pytest

from app.replay import canonical
from app.replay.training.multitrack import (
    GLOBAL_ORDERING_VERSION, PreparedGlobalEventHashes, StableMarketEvent,
    global_ordering_hash, _single_event_middle,
)
from app.replay.training.tape_interval import PreparedIntervalRecord


@pytest.mark.parametrize("native", [False, True])
def test_single_event_hash_matches_reference_bytes(native, monkeypatch):
    if not native:
        monkeypatch.setattr(canonical, "orjson", None)
    _single_event_middle.cache_clear()
    rng = random.Random(761)
    for i in range(150):
        event = StableMarketEvent(
            rng.randrange(1000000000), rng.randrange(100),
            ['track-1', 'track:a', 'track.b'][i % 3] + str(i),
            2 ** (i % 52) + i + 1,
        )
        expected = canonical.canonical_sha256(dict(
            schema_version=GLOBAL_ORDERING_VERSION, events=[event.to_dict()],
        ))
        assert global_ordering_hash((event,)) == expected
        assert global_ordering_hash(iter((event,))) == expected
    assert _single_event_middle.cache_info().currsize <= 64


def test_prepared_global_hashes_reject_different_event_basis():
    events = (StableMarketEvent(1, 20, "track-1", 1),)
    prepared = PreparedGlobalEventHashes.prepare(events)
    prepared.validate(events)
    with pytest.raises(ValueError, match="event basis"):
        prepared.validate((StableMarketEvent(2, 20, "track-1", 1),))
    assert prepared.values == (global_ordering_hash(events),)


def test_prepared_interval_encoding_is_exact_and_command_bound():
    interval = dict(summary={"last": "100"}, basis={"events": [[1, "中"]]},
                    curves=[{"basis": {"times": [1], "prices": ["1.20"]}}])
    prepared = PreparedIntervalRecord.prepare(interval, "run", "command")
    prepared.validate(interval, "run", "command")
    assert prepared.summary_json == canonical.canonical_json(interval["summary"])
    assert prepared.basis_json == canonical.canonical_json(interval["basis"])
    assert prepared.curves == ((canonical.canonical_sha256(dict(
        run_id="run", command_id="command", data=interval["curves"][0]["basis"],
    )), canonical.canonical_json(interval["curves"][0]["basis"])),)
    for value, run, command in ((dict(interval), "run", "command"),
                                (interval, "other", "command"),
                                (interval, "run", "other")):
        with pytest.raises(ValueError, match="lost its basis"):
            prepared.validate(value, run, command)
