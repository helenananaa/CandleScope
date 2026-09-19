from app.api.v1.stream_indicator_payloads import _script_runtime_request


def test_pine_session_identity_is_subscription_local_and_excludes_http_ranges():
    first = dict(language="pine", script="plot(close)", exchange="binance",
                 market_type="spot", symbol="BTCUSDT", interval="1m")
    second = dict(first)
    a = _script_runtime_request(first, [], transport="websocket.snapshot")
    again = _script_runtime_request(first, [], transport="websocket.snapshot")
    b = _script_runtime_request(second, [], transport="websocket.snapshot")
    assert a.options["pineSessionId"] == again.options["pineSessionId"]
    assert a.options["pineSessionId"] != b.options["pineSessionId"]
    assert "pineSessionId" not in _script_runtime_request(
        first, [], transport="http.range"
    ).options
    assert "pineSessionId" not in _script_runtime_request(
        {**first, "language": "pyne"}, [], transport="websocket.snapshot"
    ).options
