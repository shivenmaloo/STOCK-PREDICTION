import os
import tempfile

import numpy as np
import pandas as pd
import pytest
from tests.conftest import business_day_anchor


def _make_synthetic_ohlcv(n=1300, seed=123):
    today = business_day_anchor()
    dates = pd.date_range(end=today, periods=n, freq="B")
    n_actual = len(dates)
    rng = np.random.default_rng(seed)
    returns = np.zeros(n_actual)
    regime = 0.0005
    for i in range(1, n_actual):
        if i % 60 == 0:
            regime = rng.choice([-0.001, 0.0008, 0.0003])
        returns[i] = regime + rng.normal(0, 0.012)
    close = 100 * np.cumprod(1 + returns)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": close, "high": close * 1.005,
        "low": close * 0.995, "close": close, "adj_close": close,
        "volume": rng.integers(1_000_000, 10_000_000, n_actual),
    })


@pytest.fixture()
def ml_service(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_PATH"] = tmp.name
    from backend.config import settings
    settings.DATABASE_PATH = tmp.name  # os.environ alone doesn't retroactively update the already-imported settings singleton
    from backend.database.db import init_db
    init_db()

    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module
    from datetime import datetime, timezone

    df = _make_synthetic_ohlcv()

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=df.copy(), source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [FakeProvider()]

    import backend.forecasting.service as service_module
    # Coarser walk-forward step for test speed (fewer splits = fewer
    # model fits) — still fully exercises every code path, just with
    # less validation granularity than production would use.
    monkeypatch.setattr(service_module, "WALK_FORWARD_STEP", 120)

    from backend.forecasting.service import PredictionService
    service = PredictionService()
    yield service
    os.remove(tmp.name)


def test_train_and_predict_produces_full_bundle(ml_service):
    result = ml_service.train_and_predict("TESTCO", horizon_days=5)
    assert result["success"]
    assert "signal" in result and "reason" in result["signal"]
    assert "ensemble" in result and "votes" in result["ensemble"]
    assert len(result["ensemble"]["votes"]) >= 1
    assert "model_performance" in result
    assert "position_sizing" in result
    assert "atr_stop" in result
    # walk-forward metrics must be present and be real numbers, not None/fabricated
    for name, perf in result["model_performance"].items():
        assert perf["n_splits"] > 0
        assert perf["direction_accuracy"] is not None
    # technical_agrees must be present — a real gap found via testing:
    # it was computed internally to feed classify_signal() but never
    # actually surfaced to the API response, so the frontend had no way
    # to honestly show whether the technical read agreed.
    assert "technical_agrees" in result


def test_model_reuse_avoids_retraining(ml_service):
    first = ml_service.train_and_predict("TESTCO", horizon_days=5)
    assert first["success"]

    second = ml_service.get_or_train("TESTCO", horizon_days=5)
    assert second["success"]
    assert second.get("from_cache") is True


def test_force_retrain_bypasses_cache(ml_service):
    ml_service.train_and_predict("TESTCO", horizon_days=5)
    result = ml_service.get_or_train("TESTCO", horizon_days=5, force_retrain=True)
    assert result["success"]
    assert not result.get("from_cache")


def test_insufficient_history_fails_gracefully(ml_service):
    import backend.data.market_data_service as mds_module
    from backend.data.base import DataResult, MarketDataProvider
    from datetime import datetime, timezone

    short_df = _make_synthetic_ohlcv(n=50)  # far below MIN_ROWS_FOR_TRAINING

    class ShortProvider(MarketDataProvider):
        name = "short"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=short_df, source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [ShortProvider()]
    result = ml_service.train_and_predict("SHORTCO", horizon_days=5)
    assert not result["success"]
    assert "error" in result


def test_matured_prediction_gets_evaluated(ml_service):
    from datetime import datetime, timezone, timedelta
    from backend.database.db import db_cursor

    backdated = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO predictions (ticker, created_at, horizon_days, expected_return, confidence, signal, model_breakdown_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("BACKDATED", backdated, 5, 2.5, 0.6, "BULLISH_WATCH", "[]"),
        )

    eval_result = ml_service.evaluate_matured_predictions("BACKDATED")
    assert eval_result["evaluated"] == 1

    acc = ml_service.get_prediction_accuracy("BACKDATED")
    assert "5" in acc
    assert acc["5"]["n_evaluated"] == 1
    assert acc["5"]["accuracy"] in (0.0, 1.0)  # deterministic given fixed seed data


def test_unmatured_prediction_is_not_evaluated(ml_service):
    from datetime import datetime, timezone
    from backend.database.db import db_cursor

    just_now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO predictions (ticker, created_at, horizon_days, expected_return, confidence, signal, model_breakdown_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("FRESHCO", just_now, 20, 1.0, 0.5, "NEUTRAL", "[]"),
        )

    eval_result = ml_service.evaluate_matured_predictions("FRESHCO")
    assert eval_result["evaluated"] == 0
