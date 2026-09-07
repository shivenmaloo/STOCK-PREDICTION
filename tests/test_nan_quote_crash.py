import json
import os
import tempfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from tests.conftest import business_day_anchor


@pytest.fixture()
def isolated_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from backend.config import settings
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()
    yield tmp.name
    os.remove(tmp.name)


def _install_nan_provider():
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    today = business_day_anchor()

    class NaNProvider(MarketDataProvider):
        """Simulates a market-holiday data gap — the exact scenario found
        via manual testing (a real 500 crash on Labor Day 2026)."""
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            n = 5
            dates = pd.date_range(end=today, periods=n, freq="B")
            close = [400.0, 401.0, 402.0, 403.0, np.nan]  # latest bar has no valid close
            df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close, "high": close,
                                "low": close, "close": close, "adj_close": close, "volume": [1_000_000] * n})
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [NaNProvider()]


def test_get_quote_falls_back_to_last_valid_price_when_latest_bar_is_nan(isolated_db):
    """A market-holiday data gap leaves the latest bar's close as NaN
    — get_historical() now strips that trailing NaN row at the source
    (see test_global_nan_safety_net.py), so get_quote() correctly
    reports the last VALID price instead of either crashing or
    refusing outright. This is better than a blanket 'unavailable':
    the market didn't break, it's just closed, and the last real price
    is still genuinely useful information."""
    _install_nan_provider()
    from backend.data.market_data_service import market_data_service

    result = market_data_service.get_quote("SPY")
    assert result.success is True
    assert result.data["price"] == 403.0  # the last VALID close, not the NaN one
    assert not (result.data["price"] != result.data["price"])  # not NaN (NaN != NaN is the classic check)


def test_dashboard_does_not_crash_on_nan_quote(isolated_db):
    """End-to-end reproduction of the actual crash: /api/dashboard must
    return 200 with a clean, JSON-serializable body — and now correctly
    shows the last valid price rather than either crashing or refusing."""
    _install_nan_provider()
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        body = r.json()
        json.dumps(body)  # must round-trip cleanly, proving no NaN leaked into the response
        spy = next((b for b in body["benchmarks"] if b["ticker"] == "SPY"), None)
        assert spy is not None
        assert spy["quote"]["price"] == 403.0  # last valid price, not None and not NaN


def test_quote_endpoint_does_not_crash_on_nan_price(isolated_db):
    _install_nan_provider()
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        r = client.get("/api/stock/SPY/quote")
        assert r.status_code == 200
        body = r.json()
        json.dumps(body)
        assert body["quote"]["price"] == 403.0


def test_quote_genuinely_unavailable_when_every_row_is_nan(isolated_db):
    """The real 'nothing to fall back to' edge case — every row NaN,
    not just the trailing one — must still fail honestly rather than
    fabricating a price."""
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    today = business_day_anchor()

    class AllNaNProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            n = 5
            dates = pd.date_range(end=today, periods=n, freq="B")
            close = [np.nan] * n
            df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close, "high": close,
                                "low": close, "close": close, "adj_close": close, "volume": [1_000_000] * n})
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [AllNaNProvider()]
    from backend.data.market_data_service import market_data_service

    result = market_data_service.get_quote("SPY")
    assert result.success is False


def test_quote_with_partial_nan_fields_still_succeeds(isolated_db):
    """A NaN in a secondary field (day_high) while the core price is
    valid should NOT fail the whole quote — just null out that one
    field, since the price itself is still genuinely usable."""
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    today = business_day_anchor()

    class PartialNaNProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            n = 5
            dates = pd.date_range(end=today, periods=n, freq="B")
            close = [400.0, 401.0, 402.0, 403.0, 404.0]
            high = [401.0, 402.0, 403.0, 404.0, np.nan]  # only the high is missing
            df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close, "high": high,
                                "low": close, "close": close, "adj_close": close, "volume": [1_000_000] * n})
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [PartialNaNProvider()]
    from backend.data.market_data_service import market_data_service

    result = market_data_service.get_quote("SPY")
    assert result.success is True
    assert result.data["price"] == 404.0
    assert result.data["day_high"] is None  # nulled out, not NaN
