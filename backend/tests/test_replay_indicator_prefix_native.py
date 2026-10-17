from __future__ import annotations

import pytest
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.canonical import canonical_sha256
from app.replay.history_archive import (
    SOURCE_BUCKET_ALIGNMENT_CANONICAL,
    SOURCE_BUCKET_ALIGNMENT_CATALOG_FIXED,
)
from app.replay.training.history import build_history_page
from app.replay.training.indicator_checkpoint import IndicatorCheckpointStore
from app.replay.training.indicator_history import PinnedIndicatorHistory
from app.replay.training.indicator_prefix import CanonicalReplayIndicators

from tests import test_replay_projection_native_seam as native
from tests.test_replay_indicator_prefix import lines, ready, reference


@pytest.mark.parametrize("interval", ["3d", "1w", "1M"])
def test_native_phase_calendar_and_blind_month_keep_canonical_seed(
    tmp_path, monkeypatch, interval
):
    # Reuse the actual Parquet/native seam fixtures, including their source-grid
    # assertions; capture inputs only, never replace the production projection.
    calls = []
    projections = []
    original = native.build_display_projection

    def capture(**kwargs):
        calls.append(kwargs)
        result = original(**kwargs)
        projections.append(result)
        return result

    monkeypatch.setattr(native, "build_display_projection", capture)
    if interval == "1M":
        native.test_calendar_month_seam_is_causal_native_exact_and_history_contiguous(
            tmp_path
        )
    else:
        native.test_fixed_native_grids_fill_seam_and_keep_limit_has_more(
            tmp_path,
            interval,
            "1d",
            native.DAY_MS,
            native.DAY_MS if interval == "3d" else -3 * native.DAY_MS,
            SOURCE_BUCKET_ALIGNMENT_CATALOG_FIXED
            if interval == "3d"
            else SOURCE_BUCKET_ALIGNMENT_CANONICAL,
        )
    args = {key: value for key, value in calls[-1].items() if key != "limit"}
    binding = dict(args["binding"])
    if "history_policy" not in binding:
        import json

        snapshot = json.loads(args["persisted"]["snapshot_blob"])
        start = args["persisted"]["actual_replay_start_ms"]
        earliest = snapshot["provenance"]["source_earliest_open_ms"]
        binding["history_policy"] = {
            "schema_version": "replay.data-policy.v1",
            "indicator_warmup_bars": 1,
            "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
            "visible_history_rows": 20,
            "actual_visible_history_start_ms": earliest,
            "actual_replay_start_ms": start,
            "effective_warmup_bars": 1,
            "forward_cache_ms": 10 * native.DAY_MS,
            "interval_ms": native.DAY_MS,
            "policy_hash": "sha256:" + "8" * 64,
        }
        # The projection-only fixture originally pins just the seam and next
        # bucket. Indicator history also needs its preceding native bucket.
        from tests.fixtures.replay.fakes import make_bar

        display_ms = (3 if interval == "3d" else 7) * native.DAY_MS
        anchor = native.DAY_MS if interval == "3d" else -3 * native.DAY_MS
        first = binding["display_source_range_start_ms"]
        writer = native.ReplayHistoryArchiveWriter(
            tmp_path / "archive", now_ms=lambda: first + 3 * display_ms
        )
        manifest = writer.import_batches(
            native.IDENTITY,
            interval,
            [
                native._batch(
                    [
                        {
                            **make_bar(
                                first + offset * display_ms,
                                interval_ms=display_ms,
                                price=str(200 + offset),
                                source="binance_archive_verified",
                            ),
                            "interval": interval,
                        }
                        for offset in (-1, 0, 1)
                    ],
                    source_key="canonical-native-prefix",
                    digest_character="6",
                    source_bucket_anchor_ms=anchor,
                    alignment_policy=binding["display_alignment_policy"],
                )
            ],
        )
        binding["display_source_revision"] = manifest.catalog_epoch
        binding["display_source_range_start_ms"] = manifest.earliest_open_ms
        binding["display_source_range_end_ms"] = manifest.latest_open_ms
        binding["display_grid_commitment"] = canonical_sha256(
            {
                "schema_version": "replay.display-source-grid.v1",
                "source_revision": manifest.catalog_epoch,
                "display_interval": interval,
                "source_bucket_anchor_ms": anchor,
                "alignment_policy": binding["display_alignment_policy"],
            }
        )
    args["binding"] = binding
    tail = projections[-1]["bars"][-1]
    cursor = tail["open_time_ms"]
    collected = [tail]
    while True:
        page = build_history_page(
            **args, before_ms=cursor, limit=100, expected_history_epoch=None
        )
        collected = [*page["bars"], *collected]
        if not page["has_more"]:
            break
        assert page["next_before_ms"] < cursor
        cursor = page["next_before_ms"]
    assert len(collected) >= 3
    history = PinnedIndicatorHistory(**args)
    rows = [ReplayDisplayBar.from_dict(row) for row in collected]
    engine = CanonicalReplayIndicators(IndicatorCheckpointStore(tmp_path / "prefix.db"))
    result, _ = ready(engine, history, "EMA", {"period": 2}, rows[-1:])
    expected = reference("EMA", {"period": 2}, rows)
    assert lines(result["payload"]) == [
        (name, points[-1:]) for name, points in lines(expected)
    ]
    assert result["prefix_rows_read"] == len(rows) - 1
    assert history.origin_ms == rows[0].open_time_ms
