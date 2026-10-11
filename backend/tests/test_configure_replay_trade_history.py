from pathlib import Path

import pytest
from dotenv import dotenv_values

from scripts.publish_replay_agg_trade_remote_index import configure_backend
from app.replay.remote_trade_archive import publish_remote_agg_trade_index
from app.replay.remote_history import ReplayHistoryOriginUnavailable
from tests.fixtures.replay.trade_service_fakes import verified_trade_archive


def test_enable_verified_history_preserves_other_settings(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    verified_trade_archive(origin)
    publish_remote_agg_trade_index(origin)
    env = tmp_path / ".env"
    env.write_text("KEEP_ME=unchanged\nREPLAY_AGG_TRADE_ENABLED=0\n")
    configure_backend(env, origin, tmp_path / "cache")
    configure_backend(env, origin, tmp_path / "cache")
    values = dotenv_values(env)
    assert values["KEEP_ME"] == "unchanged"
    assert values["REPLAY_AGG_TRADE_ENABLED"] == "1"
    assert values["REPLAY_AGG_TRADE_ORIGIN_URI"] == str(origin)
    assert env.read_text().count("REPLAY_AGG_TRADE_ENABLED=") == 1


def test_invalid_catalog_does_not_enable_history(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("REPLAY_AGG_TRADE_ENABLED=0\n")
    with pytest.raises(ReplayHistoryOriginUnavailable):
        configure_backend(env, tmp_path / "missing", tmp_path / "cache")
    assert env.read_text() == "REPLAY_AGG_TRADE_ENABLED=0\n"
