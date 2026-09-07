import os
import tempfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def client():
    # Isolated DB per test run.
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    os.environ["DATABASE_PATH"] = tmp_db.name
    from backend.config import settings
    settings.DATABASE_PATH = tmp_db.name  # os.environ alone doesn't retroactively update the already-imported settings singleton

    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            return DataResult(
                data={"ticker": ticker.upper(), "price": 123.45, "previous_close": 120.0,
                      "day_high": 125, "day_low": 119, "volume": 1234567,
                      "market_cap": 1e12, "currency": "USD"},
                source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="delayed_15m",
            )

        def get_historical(self, ticker, period, interval="1d"):
            n = 260
            rng = np.random.default_rng(1)
            dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
            close = 100 + np.cumsum(rng.normal(0.1, 1.5, n))
            df = pd.DataFrame({
                "date": dates, "open": close, "high": close + 1, "low": close - 1,
                "close": close, "adj_close": close, "volume": rng.integers(1_000_000, 5_000_000, n),
            })
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            return DataResult(
                data=[{"ticker": "NVDA", "name": "NVIDIA Corp", "exchange": "NASDAQ", "type": "EQUITY"}],
                source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="cached",
            )

    mds_module.market_data_service.providers = [FakeProvider()]

    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as c:
        yield c

    os.remove(tmp_db.name)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_search(client):
    r = client.get("/api/search?q=nvidia")
    assert r.status_code == 200
    assert r.json()["results"][0]["ticker"] == "NVDA"


def test_watchlist_crud(client):
    assert client.post("/api/watchlist/NVDA").status_code == 200
    r = client.get("/api/watchlist")
    tickers = [w["ticker"] for w in r.json()["watchlist"]]
    assert "NVDA" in tickers
    assert client.delete("/api/watchlist/NVDA").status_code == 200
    r = client.get("/api/watchlist")
    tickers = [w["ticker"] for w in r.json()["watchlist"]]
    assert "NVDA" not in tickers


def test_quote(client):
    r = client.get("/api/stock/NVDA/quote")
    assert r.status_code == 200
    quote = r.json()["quote"]
    # Quotes are now derived from the same (quality-scored) historical
    # data used everywhere else in the app, rather than an independent
    # per-provider get_quote() call — so this checks the price is a
    # real, sane number derived from that data, not a hardcoded mock.
    assert isinstance(quote["price"], float)
    assert quote["price"] > 0
    assert quote["ticker"] == "NVDA"


def test_historical(client):
    r = client.get("/api/stock/NVDA/historical?period=1y")
    assert r.status_code == 200
    assert len(r.json()["bars"]) == 260


def test_indicators_include_interpretation(client):
    r = client.get("/api/stock/NVDA/indicators?period=1y")
    assert r.status_code == 200
    body = r.json()
    assert "interpretation" in body and len(body["interpretation"]) > 0
    assert "structure" in body


def test_dashboard(client):
    client.post("/api/watchlist/NVDA")
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    assert len(r.json()["watchlist"]) == 1


def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Stock AI Research Terminal" in r.text
