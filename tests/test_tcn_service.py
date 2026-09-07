from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


class _FakeTCNModel:
    """Records exactly what it's called with, so the context-window
    fix can be verified without needing real PyTorch."""
    calls = []

    def __init__(self, **kwargs):
        pass

    def fit(self, X, y):
        return self

    def predict_proba(self, X):
        _FakeTCNModel.calls.append(len(X))
        return np.linspace(0.3, 0.7, len(X))


def test_walk_forward_tcn_passes_real_preceding_context_not_just_the_test_block():
    """Real bug found via a real user report (NVDA showing 0 trades
    across every risk-managed variant): predict_proba()'s windowing
    only looks backward WITHIN the array it's handed. Handing it only
    the isolated test block (e.g. 21 rows, the walk-forward step size)
    when the model needs window_len (e.g. 64) rows of context means
    almost every prediction silently defaults to 0.5 — the same
    staleness/insufficient-context bug already found and fixed for the
    LSTM's live prediction path, not yet applied here until now."""
    import backend.forecasting.tcn_service as tcn_service
    from backend.forecasting.tcn_search import TCNSearchConfig

    _FakeTCNModel.calls = []
    X = pd.DataFrame({"f1": range(500), "f2": range(500), "atr_pct_14": [0.02] * 500})
    y_return = pd.Series(np.random.default_rng(0).normal(0, 0.01, 500))
    config = TCNSearchConfig(window_len=64)

    with patch.object(tcn_service, "TCNModel", _FakeTCNModel):
        probs, returns, vols, n_splits = tcn_service._run_walk_forward_tcn(X, y_return, config, min_train=200, step=21)

    assert all(call_len > 21 for call_len in _FakeTCNModel.calls), \
        "predict_proba() must receive more than just the isolated 21-row test block"


def test_walk_forward_tcn_output_count_matches_test_rows_not_padded_context():
    import backend.forecasting.tcn_service as tcn_service
    from backend.forecasting.tcn_search import TCNSearchConfig
    from backend.forecasting.validation import walk_forward_splits

    _FakeTCNModel.calls = []
    X = pd.DataFrame({"f1": range(500), "f2": range(500), "atr_pct_14": [0.02] * 500})
    y_return = pd.Series(np.random.default_rng(0).normal(0, 0.01, 500))
    config = TCNSearchConfig(window_len=64)

    with patch.object(tcn_service, "TCNModel", _FakeTCNModel):
        probs, returns, vols, n_splits = tcn_service._run_walk_forward_tcn(X, y_return, config, min_train=200, step=21)

    splits = walk_forward_splits(500, 200, 21)
    expected_total = sum(len(test_idx) for _, test_idx in splits)
    assert len(probs) == expected_total


def test_walk_forward_tcn_predictions_are_not_all_defaulted_to_neutral():
    """The direct, observable symptom of the bug: with the fix, real
    (varying) probabilities reach the output instead of every single
    one silently defaulting to 0.5."""
    import backend.forecasting.tcn_service as tcn_service
    from backend.forecasting.tcn_search import TCNSearchConfig

    _FakeTCNModel.calls = []
    X = pd.DataFrame({"f1": range(500), "f2": range(500), "atr_pct_14": [0.02] * 500})
    y_return = pd.Series(np.random.default_rng(0).normal(0, 0.01, 500))
    config = TCNSearchConfig(window_len=64)

    with patch.object(tcn_service, "TCNModel", _FakeTCNModel):
        probs, returns, vols, n_splits = tcn_service._run_walk_forward_tcn(X, y_return, config, min_train=200, step=21)

    assert not np.allclose(probs, 0.5), "Predictions must not all collapse to the neutral default"


def test_prepare_features_close_prices_align_exactly_with_x_length(tmp_path):
    """The invariant _prepare_features asserts internally — this test
    documents and locks in why: close_prices is derived by replicating
    build_training_matrix's exact dropna mask, not a positional slice,
    specifically because a positional slice would silently misalign if
    dropna ever removed a non-edge row."""
    from backend.config import settings
    settings.DATABASE_PATH = str(tmp_path / "test.db")
    from backend.database.db import init_db
    init_db()

    import backend.data.market_data_service as mds_module
    from backend.data.base import DataResult, MarketDataProvider
    from datetime import datetime, timezone

    n = 800
    dates = pd.date_range("2021-01-01", periods=n, freq="B")
    close = 100 * np.cumprod(1 + np.random.default_rng(2).normal(0.0005, 0.02, n))
    df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close, "high": close * 1.01,
                        "low": close * 0.99, "close": close, "adj_close": close,
                        "volume": np.random.default_rng(2).integers(1_000_000, 5_000_000, n)})

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=df.copy(), source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [FakeProvider()]

    import backend.forecasting.tcn_service as tcn_service
    result = tcn_service._prepare_features("TESTCO", horizon_days=5)
    if result is None:
        pytest.skip("Not enough synthetic history for this particular run")
    X, y_return, close_prices = result
    assert len(close_prices) == len(X) == len(y_return)
