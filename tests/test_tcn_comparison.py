import numpy as np
import pytest

from backend.backtesting.tcn_comparison import run_five_way_comparison, simulate_buy_and_hold, simulate_positions
from backend.forecasting.risk_map import RiskMapConfig


def _synthetic_series(n=500, seed=3):
    rng = np.random.default_rng(seed)
    actual_returns = rng.normal(0.0005, 0.015, n)
    probabilities = np.clip(0.5 + 0.15 * np.sign(actual_returns) + rng.normal(0, 0.1, n), 0.01, 0.99)
    volatilities = np.abs(rng.normal(0.02, 0.005, n))
    return probabilities, actual_returns, volatilities


def test_buy_and_hold_matches_manual_cumulative_calculation():
    _, actual_returns, _ = _synthetic_series()
    result = simulate_buy_and_hold(actual_returns)
    manual = (np.cumprod(1 + actual_returns)[-1] - 1) * 100
    assert abs(result["total_return_pct"] - manual) < 0.01


def test_dead_zone_reduces_or_maintains_trade_count_versus_raw_signal():
    probs, returns, vols = _synthetic_series()
    results = run_five_way_comparison(probs, returns, vols, RiskMapConfig())
    assert results["model_plus_dead_zone"]["n_trades"] <= results["raw_model_signal"]["n_trades"]


def test_exposure_cap_is_genuinely_respected():
    probs, returns, vols = _synthetic_series()
    results = run_five_way_comparison(probs, returns, vols, RiskMapConfig(max_position_pct=0.20))
    assert results["model_plus_vol_scaling_and_cap"]["max_abs_exposure_pct"] <= 20.0 + 0.01


def test_uncapped_variant_can_exceed_the_cap_that_the_final_variant_respects():
    """Proves the cap is actually doing something — if every variant
    happened to stay under the cap anyway, the cap test above would be
    vacuously true."""
    probs, returns, vols = _synthetic_series()
    results = run_five_way_comparison(probs, returns, vols, RiskMapConfig(max_position_pct=0.20))
    assert results["raw_model_signal"]["max_abs_exposure_pct"] > 20.0


def test_all_five_variants_are_present():
    probs, returns, vols = _synthetic_series()
    results = run_five_way_comparison(probs, returns, vols, RiskMapConfig())
    assert set(results.keys()) == {
        "buy_and_hold", "raw_model_signal", "model_plus_dead_zone",
        "model_plus_vol_scaling", "model_plus_vol_scaling_and_cap",
    }


def test_zero_signal_throughout_produces_zero_trades_and_flat_equity():
    n = 100
    probabilities = np.full(n, 0.5)  # perfectly uninformative -> signal always 0
    actual_returns = np.random.default_rng(1).normal(0, 0.01, n)
    volatilities = np.full(n, 0.02)
    result = simulate_positions(probabilities, actual_returns, volatilities, RiskMapConfig(), stages=None)
    assert result["n_trades"] == 0
    assert result["total_return_pct"] == 0.0


def test_transaction_costs_are_applied_to_every_trade():
    """A position taken with zero actual return should still show a
    negative net trade return once costs are subtracted — otherwise
    costs aren't actually being applied per trade."""
    probabilities = np.array([0.9])  # strong bullish signal
    actual_returns = np.array([0.0])  # but the stock didn't move at all
    volatilities = np.array([0.02])
    result = simulate_positions(probabilities, actual_returns, volatilities,
                                 RiskMapConfig(dead_zone_threshold=0.0), stages=None)
    assert result["n_trades"] == 1
    assert result["avg_trade_return_pct"] < 0  # pure cost drag, no price movement to offset it


def test_buy_and_hold_with_precomputed_value_avoids_the_overlapping_return_explosion():
    """Real bug found via a real user report: y_return (used as
    actual_returns here) is an OVERLAPPING multi-day forward return —
    row i covers days [i, i+horizon), row i+1 covers [i+1, i+horizon+1),
    heavily overlapping with row i. The original code compounded these
    day-by-day as if they were sequential, non-overlapping daily
    returns, multi-counting the same underlying price moves hundreds of
    times over. At realistic NVDA-like drift (~1.5% average 5-day
    return), this reproduces an explosion in the same order of
    magnitude as the reported bug (+4,032,923%) — confirming the exact
    mechanism. Passing a properly pre-computed start-to-end price ratio
    directly must avoid this entirely."""
    rng = np.random.default_rng(1)
    n = 851
    actual_returns = rng.normal(0.015, 0.03, n)  # realistic NVDA-like overlapping 5-day forward returns
    probabilities = np.full(n, 0.5)
    volatilities = np.full(n, 0.02)

    # The old, buggy path (no precomputed value given) must still
    # reproduce the explosion — this documents the mechanism so a
    # future change can't silently reintroduce it elsewhere.
    old_result = run_five_way_comparison(probabilities, actual_returns, volatilities, RiskMapConfig())
    assert old_result["buy_and_hold"]["total_return_pct"] > 100_000

    # The fixed path must produce exactly the pre-computed value, with
    # no compounding artifact at all.
    correct_bh = 850.0
    new_result = run_five_way_comparison(probabilities, actual_returns, volatilities,
                                          RiskMapConfig(), buy_and_hold_return_pct=correct_bh)
    assert new_result["buy_and_hold"]["total_return_pct"] == correct_bh


def test_buy_and_hold_precomputed_value_has_no_drawdown_or_sharpe_fabricated():
    """With only a start/end price ratio (no full daily equity curve),
    max_drawdown/sharpe/win_rate/n_trades must be honestly None, not a
    fabricated number that implies more precision than is actually available."""
    result = run_five_way_comparison(np.full(10, 0.5), np.zeros(10), np.full(10, 0.02),
                                      RiskMapConfig(), buy_and_hold_return_pct=42.0)
    bh = result["buy_and_hold"]
    assert bh["total_return_pct"] == 42.0
    assert bh["max_drawdown_pct"] is None
    assert bh["sharpe_ratio"] is None
    assert bh["n_trades"] is None
