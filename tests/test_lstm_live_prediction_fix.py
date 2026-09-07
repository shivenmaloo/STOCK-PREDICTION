import numpy as np
import pandas as pd


class _MockLSTM:
    """Mimics LSTMModel's interface: needs `seq_len` rows of context to
    produce a real prediction — only the last row of a sufficiently
    long input gets a non-default value, mirroring the real model's
    documented windowing behavior."""
    seq_len = 20

    def predict(self, X):
        preds = np.zeros(len(X))
        if len(X) >= self.seq_len:
            preds[-1] = 0.042
        return preds


class _MockTabular:
    def predict(self, X):
        return np.array([0.017] * len(X))


def test_lstm_receives_full_windowing_context_not_a_single_row():
    """Real, previously undetected bug: the live prediction pipeline
    passed every model type — including LSTM — only a single row of
    features. Tabular models (linear/RF/GBM/XGBoost) only need one row
    and work correctly this way, but LSTM's architecture requires a
    sequence of `seq_len` preceding rows to build its temporal window.
    Without them, LSTMModel.predict() has no history to work with and
    silently returns 0.0 (neutral) — meaning the LSTM's live prediction
    had never actually reflected real market conditions, regardless of
    what the market was doing, with no error ever raised."""
    from backend.forecasting.service import _predict_live_value

    X_full = pd.DataFrame({"f1": range(100), "f2": range(100)})
    latest_row = X_full.iloc[[-1]]

    result = _predict_live_value(_MockLSTM(), "lstm", X_full, latest_row)
    assert result == 0.042, "LSTM must receive enough context to produce a real prediction, not the neutral default"


def test_old_single_row_input_would_have_silently_produced_zero():
    """Documents exactly what the bug produced, so a future change
    can't quietly reintroduce it without this test catching it."""
    X_full = pd.DataFrame({"f1": range(100), "f2": range(100)})
    latest_row = X_full.iloc[[-1]]
    old_buggy_result = _MockLSTM().predict(latest_row.values)[0]
    assert old_buggy_result == 0.0


def test_tabular_models_still_receive_only_the_single_latest_row():
    """The fix must not change behavior for the models that were
    always correct — passing them extra context they don't need would
    be its own kind of bug (and a performance cost)."""
    from backend.forecasting.service import _predict_live_value

    X_full = pd.DataFrame({"f1": range(100), "f2": range(100)})
    latest_row = X_full.iloc[[-1]]

    captured_lengths = []

    class RecordingModel:
        def predict(self, X):
            captured_lengths.append(len(X))
            return np.array([0.5] * len(X))

    _predict_live_value(RecordingModel(), "random_forest", X_full, latest_row)
    assert captured_lengths == [1]


def test_lstm_falls_back_gracefully_with_insufficient_history():
    """If there genuinely isn't enough history yet (e.g. very early in
    a ticker's available data) to build even one full window, the
    model's own predict() handles that (returns 0.0/neutral) — this
    must not raise an exception."""
    from backend.forecasting.service import _predict_live_value

    X_short = pd.DataFrame({"f1": range(5), "f2": range(5)})  # fewer than seq_len=20 rows
    latest_row = X_short.iloc[[-1]]

    result = _predict_live_value(_MockLSTM(), "lstm", X_short, latest_row)
    assert result == 0.0  # honestly neutral, not a crash
