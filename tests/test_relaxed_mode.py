import os
import tempfile

import numpy as np
import pandas as pd
import pytest
from tests.conftest import business_day_anchor


def _make_ohlcv(n, seed=1):
    today = business_day_anchor()
    dates = pd.date_range(end=today, periods=n, freq="B")
    n_actual = len(dates)
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, n_actual))
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": close, "high": close * 1.005,
        "low": close * 0.995, "close": close, "adj_close": close,
        "volume": rng.integers(1_000_000, 10_000_000, n_actual),
    })


@pytest.fixture()
def ml_service_with_data(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from backend.config import settings
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()

    import backend.forecasting.service as service_module
    monkeypatch.setattr(service_module, "WALK_FORWARD_STEP", 21)

    def _configure(n_rows, seed=1):
        from backend.data.base import DataResult, MarketDataProvider
        import backend.data.market_data_service as mds_module
        from datetime import datetime, timezone

        df = _make_ohlcv(n_rows, seed=seed)

        class FakeProvider(MarketDataProvider):
            name = "fake"

            def get_quote(self, ticker):
                raise NotImplementedError

            def get_historical(self, ticker, period, interval="1d"):
                return DataResult(data=df.copy(), source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

            def search(self, query):
                raise NotImplementedError

        mds_module.market_data_service.providers = [FakeProvider()]
        from backend.forecasting.service import PredictionService
        return PredictionService()

    yield _configure
    os.remove(tmp.name)


def test_short_history_ticker_gets_relaxed_mode_not_refusal(ml_service_with_data):
    """The exact real-world bug found via manual testing: a ticker like
    SNDK/CRWV with only ~380 raw trading days (recent IPO/spinoff) was
    being silently given zero walk-forward splits instead of either a
    real relaxed-mode result or an honest refusal."""
    service = ml_service_with_data(n_rows=382)
    result = service.train_and_predict("SHORTCO", horizon_days=5)

    assert result["success"]
    assert result["relaxed_mode"] is True
    assert any(perf.get("n_splits", 0) > 0 for perf in result["model_performance"].values()), \
        "Relaxed mode must produce at least one real walk-forward split, not silently zero"
    assert any("RELAXED MODE" in note for note in result["notes"])


def test_long_history_ticker_uses_standard_mode(ml_service_with_data):
    service = ml_service_with_data(n_rows=1300)
    result = service.train_and_predict("LONGCO", horizon_days=5)

    assert result["success"]
    assert result["relaxed_mode"] is False
    assert not any("RELAXED MODE" in note for note in result["notes"])


def test_extremely_short_history_still_refused(ml_service_with_data):
    """Below the absolute floor, there's genuinely nothing meaningful
    to validate — this must still refuse rather than fabricate."""
    service = ml_service_with_data(n_rows=50)
    result = service.train_and_predict("TOOSHORTCO", horizon_days=5)

    assert not result["success"]
    assert "error" in result
