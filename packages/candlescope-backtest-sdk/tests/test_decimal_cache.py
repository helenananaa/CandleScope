from decimal import localcontext
import pytest

from candlescope_backtest_sdk.models import (
    _decimal_string, _normalize_decimal_text, _short_decimal_string,
)


@pytest.mark.parametrize("precision", [1, 28, 80])
def test_cached_values_preserve_reference_format_and_decimal_context(precision):
    _short_decimal_string.cache_clear()
    with localcontext() as context:
        context.prec = precision
        for value in ("1", "-0", "001.00", "10000", "1e6", "0.000001", "12345678901234567890", "١٢٣"):
            before = dict(context.flags)
            for _ in range(3):
                assert _decimal_string(value, "quantity") == _normalize_decimal_text(value, "quantity")
            assert dict(context.flags) == before
    assert _short_decimal_string.cache_info().hits > 0


@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity", "bad", "1__2bad"])
def test_invalid_values_keep_error_class_and_message(value):
    with pytest.raises(Exception) as original:
        _normalize_decimal_text(str(value).strip(), "quantity")
    with pytest.raises(type(original.value)) as cached:
        _decimal_string(value, "quantity")
    assert str(cached.value) == str(original.value)


def test_large_exponents_are_not_cached_or_truncated():
    _short_decimal_string.cache_clear()
    assert _decimal_string("1e1000", "quantity") == "1" + "0" * 1000
    assert _short_decimal_string.cache_info().currsize == 0
