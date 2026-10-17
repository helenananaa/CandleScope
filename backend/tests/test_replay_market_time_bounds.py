"""Indexed time boundaries must not decode rows already fixed by the directory."""

from bisect import bisect_left, bisect_right
from hashlib import sha256

import pytest
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.shared_market_index import BLOCK, build, open_object


@pytest.mark.parametrize("count", [1, BLOCK + 1, 3 * BLOCK + 31])
def test_directory_boundaries_and_gaps_match_scalar_without_row_reads(
    tmp_path, monkeypatch, count
):
    # Include intra-block and cross-block gaps. Directory endpoints locate
    # either side exactly; an interior query must still consult actual rows.
    opens = [
        (index + 5 + 3 * (index >= 17) + 9 * (index >= BLOCK)) * 60_000
        for index in range(count)
    ]
    rows = [
        {
            "open_time": at,
            "close_time": at + 59_999,
            "open": "100", "high": "101", "low": "99", "close": "100",
            "volume": "1", "source": "fixture",
        }
        for at in opens
    ]
    source = tmp_path / "source.parquet"
    source.write_bytes(b"immutable-directory-bound-fixture")
    digest = "sha256:" + sha256(source.read_bytes()).hexdigest()
    build(source, digest, "1m", ReplaySeriesIdentity("fixture", "spot", "BOUND"), rows)
    obj = open_object(source, digest)
    original, reads = obj.block, []

    def read(number):
        reads.append(number)
        return original(number)

    monkeypatch.setattr(obj, "block", read)
    probes = {opens[0] - 1, opens[-1] + 1, *obj.firsts, *obj.lasts}
    for left, right in zip(obj.lasts, obj.firsts[1:]):
        probes.update({left + 1, right - 1})
    for at in probes:
        for inclusive in (False, True):
            reads.clear()
            expected = (bisect_right if inclusive else bisect_left)(opens, at)
            assert obj.bound(at, right=inclusive) == expected
            assert reads == [], "directory-known boundary decoded source rows"
    for index in (16, 17, 29, BLOCK + 17):
        if index >= count:
            continue
        for shift in (-1, 0, 1):
            at = opens[index] + shift
            for inclusive in (False, True):
                reads.clear()
                assert obj.bound(at, right=inclusive) == (
                    bisect_right if inclusive else bisect_left
                )(opens, at)
                assert len(reads) <= 1
