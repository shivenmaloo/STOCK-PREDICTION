import os
import tempfile

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


def _install_fake_provider(prices: dict):
    from datetime import datetime, timezone
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    today = business_day_anchor()

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            price = prices.get(ticker)
            if price is None:
                return DataResult(data=None, source=self.name, fetched_at=datetime.now(timezone.utc),
                                   timeliness="end_of_day", success=False, error=f"No data for {ticker}", quality="ERROR")
            dates = pd.date_range(end=today, periods=5, freq="B")
            df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": [price] * 5, "high": [price] * 5,
                                "low": [price] * 5, "close": [price] * 5, "adj_close": [price] * 5, "volume": [1_000_000] * 5})
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [FakeProvider()]


# ------------------------------------------------------------ portfolio

def test_portfolio_computes_gain_and_loss_correctly(isolated_db):
    _install_fake_provider({"NVDA": 220.0, "AAPL": 175.0})
    import backend.portfolio.service as portfolio_service

    portfolio_service.add_holding("NVDA", shares=10, entry_price=200.0)
    portfolio_service.add_holding("AAPL", shares=5, entry_price=180.0)

    summary = portfolio_service.get_portfolio_summary()
    nvda = next(h for h in summary["holdings"] if h["ticker"] == "NVDA")
    aapl = next(h for h in summary["holdings"] if h["ticker"] == "AAPL")

    assert nvda["unrealized_pl"] == 200.0
    assert aapl["unrealized_pl"] == -25.0
    assert summary["total_value"] == 3075.0


def test_portfolio_refuses_to_fabricate_total_when_price_missing(isolated_db):
    _install_fake_provider({"NVDA": 220.0})  # AAPL deliberately not in the fake price map
    import backend.portfolio.service as portfolio_service

    portfolio_service.add_holding("NVDA", shares=10, entry_price=200.0)
    portfolio_service.add_holding("AAPL", shares=5, entry_price=180.0)

    summary = portfolio_service.get_portfolio_summary()
    aapl = next(h for h in summary["holdings"] if h["ticker"] == "AAPL")
    assert aapl["price_available"] is False
    assert summary["total_value"] is None  # never a silently-wrong partial total


def test_remove_holding(isolated_db):
    _install_fake_provider({"NVDA": 220.0})
    import backend.portfolio.service as portfolio_service

    holding_id = portfolio_service.add_holding("NVDA", shares=10, entry_price=200.0)
    assert portfolio_service.remove_holding(holding_id) is True
    assert portfolio_service.list_holdings_raw() == []


def test_empty_portfolio_returns_zeroed_summary(isolated_db):
    import backend.portfolio.service as portfolio_service
    summary = portfolio_service.get_portfolio_summary()
    assert summary["holdings"] == []
    assert summary["total_value"] == 0.0


# ------------------------------------------------------------- exit risk

def test_exit_risk_low_for_healthy_position():
    from backend.alerts.exit_risk import assess_exit_risk
    healthy = {"close": 220, "sma_50": 200, "sma_200": 180, "rsi_14": 60, "macd_hist": 1.5,
               "relative_volume": 1.1, "daily_return_pct": 1.2, "atr_pct_14": 2.0, "hist_vol_20": 20}
    result = assess_exit_risk(healthy, {"breakdown": False})
    assert result["risk_level"] == "LOW"
    assert result["action"] == "No action indicated"


def test_exit_risk_escalates_with_compounding_factors():
    from backend.alerts.exit_risk import assess_exit_risk
    deteriorating = {"close": 190, "sma_50": 200, "sma_200": 195, "rsi_14": 35, "macd_hist": -0.8,
                      "relative_volume": 1.2, "daily_return_pct": -0.5, "atr_pct_14": 2.5, "hist_vol_20": 22}
    result = assess_exit_risk(deteriorating, {"breakdown": False})
    assert result["risk_level"] == "HIGH"
    assert result["action"] == "Review position"


def test_exit_risk_medium_tier_reachable():
    from backend.alerts.exit_risk import assess_exit_risk
    medium = {"close": 190, "sma_50": 210, "sma_200": 180, "rsi_14": 38, "macd_hist": 0.5,
              "relative_volume": 1.0, "daily_return_pct": 0.1, "atr_pct_14": 2.0, "hist_vol_20": 20}
    result = assess_exit_risk(medium, {"breakdown": False})
    assert result["risk_level"] == "MEDIUM"


def test_exit_risk_never_recommends_selling():
    """Spec's own explicit requirement: the strongest output must be
    'Review position', never an instruction to sell."""
    from backend.alerts.exit_risk import assess_exit_risk
    severe = {"close": 190, "sma_50": 200, "sma_200": 195, "rsi_14": 32, "macd_hist": -1.2,
              "relative_volume": 2.4, "daily_return_pct": -3.5, "atr_pct_14": 6.5, "hist_vol_20": 35}
    negative_news = [{"sentiment": {"label": "strong_negative"}}, {"sentiment": {"label": "moderate_negative"}}]
    result = assess_exit_risk(severe, {"breakdown": True}, recent_news_items=negative_news)
    assert result["risk_level"] == "HIGH"
    assert "sell" not in result["action"].lower()
    assert "review" in result["action"].lower()


def test_exit_risk_handles_missing_indicator_data_gracefully():
    from backend.alerts.exit_risk import assess_exit_risk
    sparse = {"close": 190, "sma_50": None, "sma_200": None, "rsi_14": None,
              "macd_hist": None, "relative_volume": None, "daily_return_pct": None,
              "atr_pct_14": None, "hist_vol_20": None}
    result = assess_exit_risk(sparse, {"breakdown": False})
    assert result["risk_level"] == "LOW"  # no data to flag anything
    assert "No significant deterioration signals detected." in result["reasons"]
