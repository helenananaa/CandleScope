from datetime import datetime, timezone

import pytest

from app.data_engine.interval_policy import parse_interval_spec
from app.data_preparation.dependency_plan import strategy_warmup, warmup_start
from app.data_preparation.models import PreparationError
from tests.test_backtest_chart_context import _runtime
from tests.test_backtest_strategy_workspace_m9 import _revision


def test_warmup_uses_frozen_parameters_and_registered_legacy_declaration(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        compiled = _revision(runtime.service)
        assert strategy_warmup(runtime, compiled["revision_id"], {"length": 30}) == 31
        assert strategy_warmup(runtime, compiled["revision_id"], {}) == 25
        with pytest.raises(PreparationError, match="whole-number"):
            strategy_warmup(runtime, compiled["revision_id"], {"length": True})
    finally:
        runtime.shutdown()


def test_monthly_warmup_uses_calendar_grid_in_leap_year():
    march = int(datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
    february = int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert warmup_start(parse_interval_spec("1M"), march, 1) == february
    assert march - february == 29 * 86_400_000
