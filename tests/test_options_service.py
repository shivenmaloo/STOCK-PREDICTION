import os
import tempfile
from datetime import date, datetime, timezone

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


S = 150.0
R = 0.045
TODAY = date(2026, 9, 5)


def _known_smile_iv(moneyness, tenor_days):
    base = 0.30 - 0.02 * (tenor_days / 90)
    skew = -0.25 * (moneyness - 1.0)
    smile = 0.15 * (moneyness - 1.0) ** 2
    return max(0.05, base + skew + smile)


def _build_calls_df(tenor_days):
    from backend.options.pricing import black_scholes_call_price
    strikes = np.arange(0.7 * S, 1.31 * S, S * 0.025)
    rows = []
    T = tenor_days / 365.25
    for K in strikes:
        moneyness = K / S
        true_iv = _known_smile_iv(moneyness, tenor_days)
        fair_price = black_scholes_call_price(S, K, T, R, true_iv)
        spread = max(0.05, fair_price * 0.02)
        rows.append({"strike": K, "bid": fair_price - spread / 2, "ask": fair_price + spread / 2,
                     "volume": 50, "openInterest": 100})
    return pd.DataFrame(rows)


class _FakeOptionChain:
    def __init__(self, calls_df):
        self.calls = calls_df


class _FakeYFTicker:
    def __init__(self, ticker, tenors=(30, 60, 90, 180), has_options=True):
        self.ticker = ticker
        self.options = [(TODAY + pd.Timedelta(days=t)).strftime("%Y-%m-%d") for t in tenors] if has_options else []

    def option_chain(self, expiry_str):
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        tenor_days = (expiry_date - TODAY).days
        return _FakeOptionChain(_build_calls_df(tenor_days))


def _install_price_provider():
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            anchor = business_day_anchor()
            dates = pd.date_range(end=anchor, periods=5, freq="B")
            close = [S] * 5
            df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close, "high": close,
                                "low": close, "close": close, "adj_close": close, "volume": [1_000_000] * 5})
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [FakeProvider()]


def test_full_orchestration_recovers_known_smile_end_to_end(isolated_db):
    from backend.options.service import fetch_and_build_surface
    _install_price_provider()

    result = fetch_and_build_surface("TESTCO", yf_ticker_factory=_FakeYFTicker, today=TODAY)

    assert result["success"] is True
    assert result["spot_price"] == S
    expected_atm = _known_smile_iv(1.0, 30)
    assert abs(result["atm_iv_30d"] - expected_atm) < 0.02


def test_visualization_grid_has_correct_dimensions(isolated_db):
    from backend.options.service import fetch_and_build_surface
    _install_price_provider()

    result = fetch_and_build_surface("TESTCO", yf_ticker_factory=_FakeYFTicker, today=TODAY)
    viz = result["visualization"]
    assert len(viz["iv_surface"]) == 30
    assert len(viz["iv_surface"][0]) == 30
    assert len(viz["moneyness_grid"]) == 30
    assert len(viz["tenor_grid_days"]) == 30


def test_first_reading_logs_to_iv_history_with_no_rank_yet(isolated_db):
    from backend.options.service import fetch_and_build_surface
    _install_price_provider()

    result = fetch_and_build_surface("TESTCO", yf_ticker_factory=_FakeYFTicker, today=TODAY)
    assert result["iv_rank"]["available"] is False
    assert result["iv_rank"]["n_readings"] == 1


def test_ticker_with_no_listed_options_fails_honestly(isolated_db):
    from backend.options.service import fetch_and_build_surface
    _install_price_provider()

    def no_options_factory(ticker):
        return _FakeYFTicker(ticker, has_options=False)

    result = fetch_and_build_surface("TESTCO", yf_ticker_factory=no_options_factory, today=TODAY)
    assert result["success"] is False
    assert "listed options" in result["error"]


def test_missing_spot_price_fails_honestly(isolated_db):
    """If we can't even get a current price, this must fail cleanly
    rather than attempt to proceed with a fabricated spot price."""
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module
    from backend.options.service import fetch_and_build_surface

    class FailingProvider(MarketDataProvider):
        name = "failing"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=None, source=self.name, fetched_at=datetime.now(timezone.utc),
                               timeliness="end_of_day", success=False, error="no data")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [FailingProvider()]
    result = fetch_and_build_surface("TESTCO", yf_ticker_factory=_FakeYFTicker, today=TODAY)
    assert result["success"] is False


def test_expiry_fetch_failure_for_one_expiry_does_not_fail_the_whole_request(isolated_db):
    """One bad expiry (a real, common yfinance flakiness scenario)
    must not take down the entire surface computation if other
    expiries succeed."""
    from backend.options.service import fetch_and_build_surface
    _install_price_provider()

    class FlakyYFTicker(_FakeYFTicker):
        def option_chain(self, expiry_str):
            if expiry_str == self.options[0]:
                raise ConnectionError("simulated flaky expiry fetch")
            return super().option_chain(expiry_str)

    result = fetch_and_build_surface("TESTCO", yf_ticker_factory=FlakyYFTicker, today=TODAY)
    assert result["success"] is True
    assert len(result["expiries_processed"]) == 3  # 4 total, 1 failed
