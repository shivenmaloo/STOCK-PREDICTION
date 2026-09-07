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


def _install_trailing_nan_provider():
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    today = business_day_anchor()

    class NaNProvider(MarketDataProvider):
        """Simulates a market-holiday data gap across ALL benchmark
        tickers at once — the exact scenario that crashed Market
        regime and Sector rankings (a bug that slipped past the
        earlier get_quote()-only fix, since those endpoints read
        historical data through a different path)."""
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            n = 300
            rng = np.random.default_rng(1)
            dates = pd.date_range(end=today, periods=n, freq="B")
            close = list(400 + np.cumsum(rng.normal(0, 1, n - 1))) + [np.nan]
            df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close, "high": close,
                                "low": close, "close": close, "adj_close": close, "volume": [1_000_000] * n})
            return DataResult(data=df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [NaNProvider()]


def test_get_historical_strips_trailing_nan_row_at_source(isolated_db):
    """The root-cause fix: get_historical() must never return a
    trailing row with a NaN close, regardless of which consumer calls
    it — fixing this once here protects every downstream consumer
    (quotes, regime, sectors, scanner, predictions, alerts...) instead
    of requiring each one to individually guard against it."""
    _install_trailing_nan_provider()
    from backend.data.market_data_service import market_data_service

    result = market_data_service.get_historical("SPY", period="1y")
    assert result.success
    assert not pd.isna(result.data["close"].iloc[-1])


def test_market_regime_endpoint_survives_nan_benchmark_data(isolated_db):
    _install_trailing_nan_provider()
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        r = client.get("/api/market/regime")
        assert r.status_code == 200
        json.dumps(r.json())  # must round-trip cleanly — no NaN leaked through


def test_market_sectors_endpoint_survives_nan_benchmark_data(isolated_db):
    _install_trailing_nan_provider()
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        r = client.get("/api/market/sectors")
        assert r.status_code == 200
        json.dumps(r.json())


def test_global_json_sanitizer_strips_nan_and_inf():
    """Unit test for the global safety-net response class directly —
    this is what protects every endpoint, including ones that don't
    yet exist, from ever crashing on a stray NaN/Infinity again."""
    from backend.main import _sanitize_nan

    dirty = {
        "a": float("nan"),
        "b": float("inf"),
        "c": float("-inf"),
        "d": 42.5,
        "e": [1.0, float("nan"), {"nested": float("inf")}],
        "f": "a normal string",
        "g": None,
    }
    clean = _sanitize_nan(dirty)
    assert clean["a"] is None
    assert clean["b"] is None
    assert clean["c"] is None
    assert clean["d"] == 42.5
    assert clean["e"] == [1.0, None, {"nested": None}]
    assert clean["f"] == "a normal string"
    assert clean["g"] is None

    # Must actually be JSON-serializable now.
    json.dumps(clean)
