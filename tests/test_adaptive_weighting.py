import json
from datetime import datetime, timedelta, timezone

import pytest
from tests.conftest import business_day_anchor


@pytest.fixture()
def isolated_db():
    import tempfile
    from backend.config import settings
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    # Directly mutate the settings singleton, not just os.environ — by
    # the time this fixture runs, `settings.DATABASE_PATH` was already
    # computed once at import time and won't re-read the environment
    # variable on its own. This is what actually gives each test its
    # own isolated database file rather than accidentally sharing
    # whichever one the first test in the session happened to create.
    original = settings.DATABASE_PATH
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()
    yield tmp.name
    settings.DATABASE_PATH = original
    import os
    os.remove(tmp.name)


def _seed_track_record(ticker: str, model_correctness: dict, n: int):
    """Seeds `n` matured, evaluated predictions where each named model
    in `model_correctness` is either always right (1) or always wrong (0)
    — an unambiguous synthetic track record to test the blending math."""
    from backend.database.db import db_cursor
    for i in range(n):
        created = (datetime.now(timezone.utc) - timedelta(days=30 + i)).isoformat()
        votes = [
            {"model": name, "direction": "bullish" if correct else "bearish",
             "predicted_return_pct": 1.0, "validated_accuracy": 0.5, "weight": 0.5}
            for name, correct in model_correctness.items()
        ]
        with db_cursor() as cur:
            cur.execute(
                """INSERT INTO predictions (ticker, created_at, horizon_days, expected_return, confidence, signal, model_breakdown_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ticker, created, 5, 1.0, 0.6, "BULLISH_WATCH", json.dumps(votes)),
            )
            pred_id = cur.lastrowid
            per_model = {name: correct for name, correct in model_correctness.items()}
            cur.execute(
                """INSERT INTO prediction_results (prediction_id, evaluated_at, actual_return, was_correct, per_model_correct_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (pred_id, datetime.now(timezone.utc).isoformat(), 2.0, 1, json.dumps(per_model)),
            )


def test_model_with_better_live_track_record_gets_higher_blended_weight(isolated_db):
    """The core claim: a model that's actually been more accurate in
    real, tracked predictions ends up weighted higher in future
    ensembles than one with an identical backtest score but a worse
    real track record."""
    from backend.forecasting.adaptive import get_live_model_accuracy, blend_accuracy

    _seed_track_record("TESTCO", {"xgboost": 1, "random_forest": 0}, n=10)

    xgb_live = get_live_model_accuracy("xgboost", ticker="TESTCO")
    rf_live = get_live_model_accuracy("random_forest", ticker="TESTCO")
    assert xgb_live["accuracy"] == 1.0
    assert rf_live["accuracy"] == 0.0

    xgb_blended = blend_accuracy(0.50, xgb_live)
    rf_blended = blend_accuracy(0.50, rf_live)
    assert xgb_blended["blended_accuracy"] > rf_blended["blended_accuracy"]


def test_small_live_sample_does_not_overwhelm_backtest(isolated_db):
    """A single lucky/unlucky live prediction shouldn't swing a model's
    weight dramatically — the shrinkage must be real."""
    from backend.forecasting.adaptive import get_live_model_accuracy, blend_accuracy

    _seed_track_record("TESTCO", {"xgboost": 0}, n=3)  # bare minimum sample, all wrong
    live = get_live_model_accuracy("xgboost", ticker="TESTCO")
    result = blend_accuracy(0.70, live)  # strong backtest history
    # Should be pulled down from 0.70, but not anywhere near 0 — the
    # backtest still carries most of the weight with only 3 live samples.
    assert 0.50 < result["blended_accuracy"] < 0.70


def test_falls_back_to_global_scope_when_ticker_specific_data_is_thin(isolated_db):
    from backend.forecasting.adaptive import get_live_model_accuracy

    _seed_track_record("OTHERCO", {"xgboost": 1}, n=10)  # plenty of global data, none for TESTCO
    result = get_live_model_accuracy("xgboost", ticker="TESTCO")
    assert result["scope"] == "global"
    assert result["accuracy"] == 1.0


def test_no_live_data_at_all_returns_none(isolated_db):
    from backend.forecasting.adaptive import get_live_model_accuracy
    result = get_live_model_accuracy("xgboost", ticker="NEVERUSEDCO")
    assert result["accuracy"] is None
    assert result["scope"] == "none"


def test_evaluate_matured_predictions_records_per_model_correctness(isolated_db):
    """Full pipeline check: evaluate_matured_predictions must actually
    populate per_model_correct_json, not just the ensemble-level
    was_correct — otherwise the adaptive weighting has nothing to read."""
    import pandas as pd
    import numpy as np
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module
    from backend.database.db import db_cursor

    today = business_day_anchor()
    n = 300
    dates = pd.date_range(end=today, periods=n, freq="B")
    n_actual = len(dates)
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, n_actual))
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": close, "high": close + 1,
        "low": close - 1, "close": close, "adj_close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n_actual),
    })

    class FakeProvider(MarketDataProvider):
        name = "fake"
        def get_quote(self, ticker): raise NotImplementedError
        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=df.copy(), source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")
        def search(self, query): raise NotImplementedError

    mds_module.market_data_service.providers = [FakeProvider()]

    backdated = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    votes = [{"model": "xgboost", "direction": "bullish", "predicted_return_pct": 1.0,
              "validated_accuracy": 0.5, "weight": 1.0}]
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO predictions (ticker, created_at, horizon_days, expected_return, confidence, signal, model_breakdown_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("REALCO", backdated, 5, 2.5, 0.6, "BULLISH_WATCH", json.dumps(votes)),
        )

    from backend.forecasting.service import PredictionService
    service = PredictionService()
    result = service.evaluate_matured_predictions("REALCO")
    assert result["evaluated"] == 1

    with db_cursor() as cur:
        cur.execute("SELECT per_model_correct_json FROM prediction_results")
        row = cur.fetchone()
    per_model = json.loads(row["per_model_correct_json"])
    assert "xgboost" in per_model
    assert per_model["xgboost"] in (0, 1)
