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
    os.environ["DATABASE_PATH"] = tmp.name
    from backend.config import settings
    settings.DATABASE_PATH = tmp.name  # os.environ alone doesn't retroactively update the already-imported settings singleton
    from backend.database.db import init_db
    init_db()
    yield tmp.name
    os.remove(tmp.name)


def test_small_period_fetch_does_not_starve_later_large_period_fetch(isolated_db):
    """The exact bug found via manual testing: the Dashboard's 5-day
    quote lookup for SPY populated the cache with only ~5 rows, and a
    later 1-year request (needed by the Market regime calculation) was
    incorrectly served from that same tiny cache instead of triggering
    a real re-fetch — because cache freshness only checked *when* data
    was cached, never *how much* of it there was."""
    import backend.data.market_data_service as mds_module
    from backend.data.base import DataResult, MarketDataProvider

    today = business_day_anchor()

    class RealisticProvider(MarketDataProvider):
        name = "fake_yfinance"
        PERIOD_DAYS = {"5d": 5, "1y": 252, "5y": 1260, "max": 2000}

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            n = self.PERIOD_DAYS.get(period, 100)
            dates = pd.date_range(end=today, periods=n, freq="B")
            n_actual = len(dates)
            rng = np.random.default_rng(1)
            df = pd.DataFrame({
                "date": dates.strftime("%Y-%m-%d"), "open": rng.random(n_actual) + 400,
                "high": rng.random(n_actual) + 401, "low": rng.random(n_actual) + 399,
                "close": rng.random(n_actual) + 400, "adj_close": rng.random(n_actual) + 400,
                "volume": rng.integers(1_000_000, 5_000_000, n_actual),
            })
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [RealisticProvider()]

    # Simulates the Dashboard's quote lookup happening first.
    mds_module.market_data_service.get_quote("SPY")

    # Simulates the Market page's regime calculation needing a full year.
    result = mds_module.market_data_service.get_historical("SPY", period="1y")

    assert result.data is not None
    assert len(result.data) >= 60, (
        f"Only got {len(result.data)} rows for a 1-year request after a prior "
        f"5-day fetch — the cache-starvation bug has regressed."
    )


def test_max_period_request_is_not_capped_at_five_years(isolated_db):
    """The cache-depth fix always fetches at least 5 years for daily
    data — but an explicit 'max' request must still get the true
    maximum, not be silently capped at 5y."""
    import backend.data.market_data_service as mds_module
    from backend.data.base import DataResult, MarketDataProvider

    today = business_day_anchor()

    class LongHistoryProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            n = 2000 if period == "max" else 1260  # "max" should request more than 5y's ~1260
            dates = pd.date_range(end=today, periods=n, freq="B")
            n_actual = len(dates)
            rng = np.random.default_rng(1)
            df = pd.DataFrame({
                "date": dates.strftime("%Y-%m-%d"), "open": rng.random(n_actual) + 100,
                "high": rng.random(n_actual) + 101, "low": rng.random(n_actual) + 99,
                "close": rng.random(n_actual) + 100, "adj_close": rng.random(n_actual) + 100,
                "volume": rng.integers(1_000_000, 5_000_000, n_actual),
            })
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [LongHistoryProvider()]
    result = mds_module.market_data_service.get_historical("AAPL", period="max")
    assert len(result.data) > 1260, "A 'max' request was capped at ~5 years instead of getting the true maximum"


def test_vix_is_rounded_even_when_regime_is_unknown():
    """Found via manual testing: the VIX value in the 'UNKNOWN' regime
    branch skipped rounding entirely, showing raw floating-point noise
    like 15.130000114440918 in the UI instead of 15.13."""
    import backend.market.regime as regime_module

    regime_module._benchmark_signal = lambda ticker: None  # force the UNKNOWN branch
    regime_module._vix_level = lambda: 15.130000114440918

    result = regime_module.classify_market_regime()
    assert result["regime"] == "UNKNOWN"
    assert result["vix"] == 15.13
