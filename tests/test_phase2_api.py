import os
import tempfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def client():
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    os.environ["DATABASE_PATH"] = tmp_db.name
    from backend.config import settings
    settings.DATABASE_PATH = tmp_db.name  # os.environ alone doesn't retroactively update the already-imported settings singleton

    from backend.data.base import DataResult, MarketDataProvider
    from backend.data.news_provider import SourceDiagnostics
    import backend.data.market_data_service as mds_module
    import backend.fundamentals.service as fs_module
    import backend.news.service as ns_module

    def synth_ohlcv(n=300, seed=1, start=100, drift=0.1):
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2024-06-01", periods=n, freq="B").strftime("%Y-%m-%d")
        close = start + np.cumsum(rng.normal(drift, 1.5, n))
        return pd.DataFrame({
            "date": dates, "open": close, "high": close + 1, "low": close - 1,
            "close": close, "adj_close": close, "volume": rng.integers(1_000_000, 5_000_000, n),
        })

    class FakeMarket(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            return DataResult(
                data={"ticker": ticker, "price": 123.45, "previous_close": 120.0,
                      "day_high": 125, "day_low": 119, "volume": 1_000_000,
                      "market_cap": 1e12, "currency": "USD"},
                source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="delayed_15m",
            )

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(
                data=synth_ohlcv(seed=42, start=400, drift=0.2),
                source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day",
            )

        def search(self, query):
            return DataResult(
                data=[{"ticker": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "type": "EQUITY"}],
                source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="cached",
            )

    mds_module.market_data_service.providers = [FakeMarket()]

    class FakeFundamentals:
        name = "fake"

        def get_fundamentals(self, ticker):
            return DataResult(
                data={"revenue_growth": 0.15, "earnings_growth": 0.2, "net_margin": 0.22,
                      "return_on_equity": 0.3, "trailing_pe": 22, "price_to_sales": 5,
                      "debt_to_equity": 0.5, "current_ratio": 1.5, "market_cap": 1e12,
                      "sector": "Technology", "short_name": "Fake Corp"},
                source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day",
            )

    fs_module.fundamentals_service.provider = FakeFundamentals()

    class FakeNews:
        name = "fake"

        def get_news(self, ticker, limit=15, company_name=None):
            diag = SourceDiagnostics("Fake News Source")
            diag.status = "SUCCESS"
            diag.entries_found = 2
            diag.valid_articles = 2
            return DataResult(
                data=[
                    {"headline": "Company beats earnings estimates, raises full-year guidance",
                     "link": "http://x", "source": "Reuters",
                     "published_at": datetime.now(timezone.utc).isoformat()},
                    {"headline": "Company revenue increased but guidance was reduced",
                     "link": "http://y", "source": "Bloomberg",
                     "published_at": datetime.now(timezone.utc).isoformat()},
                ],
                source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="delayed_15m",
            ), diag

    ns_module.news_service.google_provider = FakeNews()
    ns_module.news_service.yahoo_providers = []
    ns_module.news_service.direct_outlet_providers = []  # prevent real network calls to Seeking Alpha/CNBC/MarketWatch in tests

    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as c:
        yield c

    os.remove(tmp_db.name)


def test_fundamentals_endpoint(client):
    r = client.get("/api/stock/NVDA/fundamentals")
    assert r.status_code == 200
    body = r.json()
    assert body["score"]["score"] is not None
    assert body["score"]["score"] > 50  # our fake data is strong fundamentals


def test_news_endpoint_includes_sentiment_and_category(client):
    r = client.get("/api/stock/NVDA/news")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    for item in items:
        assert "sentiment" in item and "category" in item and "impact_score" in item
    # the contrast-conjunction headline must come out negative
    contrast_item = next(i for i in items if "but guidance" in i["headline"])
    assert contrast_item["sentiment"]["score"] < 0


def test_market_regime_endpoint(client):
    r = client.get("/api/market/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["regime"] in ("STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "STRONG_BEAR", "UNKNOWN")
    assert "explanation" in body


def test_sector_rankings_endpoint(client):
    r = client.get("/api/market/sectors")
    assert r.status_code == 200
    body = r.json()
    assert "top_sectors" in body and "weakest_sectors" in body


def test_scanner_endpoint_does_not_crash_without_network(client):
    # In this sandboxed test environment yfinance can't reach the network,
    # so this just verifies the endpoint degrades gracefully rather than
    # throwing a 500.
    r = client.get("/api/scanner?min_rsi=0&max_rsi=100")
    assert r.status_code == 200
    body = r.json()
    assert "scanned" in body and "matched" in body
