import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from backend.forecasting.validation import (
    WalkForwardResult,
    compute_conformal_radius,
    compute_naive_baseline_comparison,
    run_walk_forward,
)


def _run_with_real_signal(n=1000, seed=42, min_train=200, step=50):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({"feat1": rng.normal(0, 1, n), "feat2": rng.normal(0, 1, n)})
    true_signal = 0.02 * X["feat1"] - 0.01 * X["feat2"]
    y_return = pd.Series(true_signal + rng.normal(0, 0.005, n))
    y_direction = pd.Series(np.sign(y_return).astype(int))
    return run_walk_forward(lambda: LinearRegression(), X, y_return, y_direction,
                             model_name="test", min_train_size=min_train, step_size=step)


def test_conformal_radius_achieves_target_coverage():
    result = _run_with_real_signal()
    radius = compute_conformal_radius(result, confidence=0.80)
    assert radius is not None and radius > 0

    residuals = np.abs(np.array(result.predicted_returns) - np.array(result.actual_returns))
    coverage = (residuals <= radius).mean()
    assert 0.72 < coverage < 0.88


def test_conformal_radius_generalizes_to_genuinely_unseen_data():
    """The real test of a conformal interval: calibrate on one slice
    of out-of-sample residuals, then check coverage on a DIFFERENT,
    later slice that was never used to compute the radius. If it only
    worked on the data used to build it, that would be circular, not
    a genuine generalization guarantee."""
    result = _run_with_real_signal(n=1500, seed=7, step=30)
    half = len(result.predicted_returns) // 2

    calib = WalkForwardResult(model_name="calib", n_splits=0, direction_accuracy=None, mae=None,
                               predicted_returns=result.predicted_returns[:half],
                               actual_returns=result.actual_returns[:half])
    radius = compute_conformal_radius(calib, confidence=0.80)

    holdout_pred = np.array(result.predicted_returns[half:])
    holdout_actual = np.array(result.actual_returns[half:])
    holdout_residuals = np.abs(holdout_pred - holdout_actual)
    genuine_oos_coverage = (holdout_residuals <= radius).mean()

    assert 0.65 < genuine_oos_coverage < 0.92


def test_conformal_radius_refuses_with_insufficient_data():
    sparse = WalkForwardResult(model_name="sparse", n_splits=0, direction_accuracy=None, mae=None,
                                predicted_returns=[0.01] * 5, actual_returns=[0.012] * 5)
    assert compute_conformal_radius(sparse) is None


def test_naive_baseline_correctly_identifies_real_skill():
    result = _run_with_real_signal()
    comparison = compute_naive_baseline_comparison(result)
    assert comparison["beats_naive_baseline"] is True
    assert comparison["model_mae"] < comparison["naive_mae"]


def test_naive_baseline_correctly_identifies_no_skill():
    """A model given pure noise (no real relationship between features
    and target) should NOT beat the naive 'predict zero' baseline —
    proving this check isn't just always returning True."""
    rng = np.random.default_rng(3)
    n = 800
    X = pd.DataFrame({"feat1": rng.normal(0, 1, n), "feat2": rng.normal(0, 1, n)})
    y_return = pd.Series(rng.normal(0, 0.02, n))  # no relationship to X at all
    y_direction = pd.Series(np.sign(y_return).astype(int))

    result = run_walk_forward(lambda: LinearRegression(), X, y_return, y_direction,
                               model_name="noise", min_train_size=200, step_size=50)
    comparison = compute_naive_baseline_comparison(result)
    assert comparison["beats_naive_baseline"] is False


def test_naive_baseline_handles_empty_result_gracefully():
    empty = WalkForwardResult(model_name="empty", n_splits=0, direction_accuracy=None, mae=None,
                               predicted_returns=[], actual_returns=[])
    comparison = compute_naive_baseline_comparison(empty)
    assert comparison["beats_naive_baseline"] is None
