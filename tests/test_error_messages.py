from unittest.mock import MagicMock, patch

from backend.data.stooq_provider import StooqProvider


def test_invalid_ticker_gets_clean_error_not_raw_http_exception():
    """Found via manual testing: a typo'd ticker like 'APPL' surfaced
    the raw requests HTTPError text ('404 Client Error: Not Found for
    url: https://stooq.com/...') straight to the user. Must be a clean,
    human-readable message instead."""
    resp = MagicMock()
    resp.status_code = 404
    with patch("backend.data.stooq_provider.requests.get", return_value=resp):
        result = StooqProvider().get_historical("APPL", period="1y")

    assert not result.success
    assert "404" not in result.error
    assert "Client Error" not in result.error
    assert "APPL" in result.error


def test_stooq_network_error_gets_readable_message():
    import requests as requests_module
    with patch("backend.data.stooq_provider.requests.get",
               side_effect=requests_module.exceptions.ConnectionError("boom")):
        result = StooqProvider().get_historical("AAPL", period="1y")
    assert not result.success
    assert "Could not reach Stooq" in result.error


def test_stooq_empty_response_body_gets_clean_message():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "No data"
    with patch("backend.data.stooq_provider.requests.get", return_value=resp):
        result = StooqProvider().get_historical("ZZZZ", period="1y")
    assert not result.success
    assert "doesn't look like a valid ticker" in result.error
