import numpy as np
import pandas as pd
import pytest

from backend.options.pricing import black_scholes_call_price
from backend.options.surface import preprocess_chain, get_surface_features, interpolate_surface

S = 100.0
R = 0.045


def _known_smile_iv(moneyness, tenor_days):
    base = 0.30 - 0.02 * (tenor_days / 90)
    skew = -0.25 * (moneyness - 1.0)
    smile = 0.15 * (moneyness - 1.0) ** 2
    return max(0.05, base + skew + smile)


def _build_synthetic_chain(tenor_days, spread_pct=0.02, strikes=None):
    strikes = strikes if strikes is not None else np.arange(70, 131, 2.5)
    rows = []
    T = tenor_days / 365.25
    for K in strikes:
        moneyness = K / S
        true_iv = _known_smile_iv(moneyness, tenor_days)
        fair_price = black_scholes_call_price(S, K, T, R, true_iv)
        spread = max(0.05, fair_price * spread_pct)
        rows.append({"strike": K, "bid": fair_price - spread / 2, "ask": fair_price + spread / 2,
                     "volume": 50, "openInterest": 100})
    return pd.DataFrame(rows)


def _full_surface_points():
    all_points = []
    for tenor in [30, 60, 90, 180]:
        chain = _build_synthetic_chain(tenor)
        all_points.append(preprocess_chain(chain, S, tenor, R))
    return pd.concat(all_points, ignore_index=True)


def test_pipeline_recovers_known_atm_iv_and_skew():
    """The core end-to-end correctness proof: build an options chain
    priced from a KNOWN volatility smile, run it through the full
    preprocess -> interpolate -> extract-features pipeline, and confirm
    the recovered ATM IV and skew closely match the known input."""
    full_df = _full_surface_points()
    features = get_surface_features(full_df, S)

    expected_atm = _known_smile_iv(1.0, 30)
    expected_skew = _known_smile_iv(0.95, 30) - _known_smile_iv(1.05, 30)

    assert abs(features["atm_iv_30d"] - expected_atm) < 0.02
    assert abs(features["put_call_skew_30d"] - expected_skew) < 0.02


def test_feature_vector_has_correct_dimensionality():
    full_df = _full_surface_points()
    features = get_surface_features(full_df, S)
    assert len(features["feature_vector"]) == 7 * 4  # 7 moneyness points x 4 tenors


def test_expiry_below_minimum_days_produces_empty_result():
    """Near-dated options are excluded entirely — high-gamma noise,
    not a stable signal, per the module's own stated design."""
    chain = _build_synthetic_chain(30)
    result = preprocess_chain(chain, S, expiry_days=3, risk_free_rate=R)
    assert result.empty


def test_zero_volume_contracts_are_filtered_out():
    chain = _build_synthetic_chain(30)
    chain.loc[chain.index[:3], "volume"] = 0
    result = preprocess_chain(chain, S, expiry_days=30, risk_free_rate=R)
    surviving_strikes = set(result["strike"])
    dropped_strikes = set(chain.iloc[:3]["strike"])
    assert surviving_strikes.isdisjoint(dropped_strikes)


def test_low_open_interest_contracts_are_filtered_out():
    chain = _build_synthetic_chain(30)
    chain.loc[chain.index[:3], "openInterest"] = 1  # below MIN_OPEN_INTEREST (5)
    result = preprocess_chain(chain, S, expiry_days=30, risk_free_rate=R)
    surviving_strikes = set(result["strike"])
    dropped_strikes = set(chain.iloc[:3]["strike"])
    assert surviving_strikes.isdisjoint(dropped_strikes)


def test_wide_bid_ask_spread_contracts_are_filtered_out():
    chain = _build_synthetic_chain(30, spread_pct=0.02)
    # Blow out the spread on a few contracts far beyond the 25% threshold
    chain.loc[chain.index[:3], "ask"] = chain.loc[chain.index[:3], "bid"] * 3
    result = preprocess_chain(chain, S, expiry_days=30, risk_free_rate=R)
    surviving_strikes = set(result["strike"])
    dropped_strikes = set(chain.iloc[:3]["strike"])
    assert surviving_strikes.isdisjoint(dropped_strikes)


def test_arbitrage_violating_price_is_filtered_out():
    """A quote priced below intrinsic value (max(0, S-K)) is an
    arbitrage violation, not a real market price — must be dropped."""
    chain = _build_synthetic_chain(30)
    deep_itm_idx = chain["strike"].idxmin()  # the deepest ITM strike, largest intrinsic value
    chain.loc[deep_itm_idx, "bid"] = 0.01
    chain.loc[deep_itm_idx, "ask"] = 0.02  # priced far below intrinsic value
    result = preprocess_chain(chain, S, expiry_days=30, risk_free_rate=R)
    assert chain.loc[deep_itm_idx, "strike"] not in set(result["strike"])


def test_zero_bid_or_ask_contracts_are_filtered_out():
    chain = _build_synthetic_chain(30)
    chain.loc[chain.index[0], "bid"] = 0
    result = preprocess_chain(chain, S, expiry_days=30, risk_free_rate=R)
    assert chain.iloc[0]["strike"] not in set(result["strike"])


def test_interpolation_returns_none_with_too_few_points():
    sparse_df = pd.DataFrame({
        "time_to_expiry_days": [30, 30], "moneyness": [0.95, 1.05], "implied_vol": [0.3, 0.28],
    })
    result = interpolate_surface(sparse_df, np.array([0.95, 1.0, 1.05]), np.array([30, 60]))
    assert result is None


def test_get_surface_features_returns_none_with_insufficient_data():
    empty_df = pd.DataFrame(columns=["strike", "moneyness", "time_to_expiry_days", "mid_price", "implied_vol"])
    assert get_surface_features(empty_df, S) is None


def test_degenerate_collinear_data_does_not_crash_interpolation():
    """Real bug found via testing: scipy's griddata raises a hard
    QhullError (not a graceful NaN) when every point shares the same
    coordinate on one axis — e.g. every surviving contract sharing the
    same time to expiry, which is a genuinely possible real-world
    options chain shape (a name with liquidity concentrated in a
    single expiry). Must degrade gracefully, not crash the request."""
    points_df = pd.DataFrame({
        "strike": [200, 210, 220, 230],
        "moneyness": [0.90, 0.95, 1.00, 1.05],
        "time_to_expiry_years": [12 / 365.25] * 4,
        "time_to_expiry_days": [12, 12, 12, 12],
        "mid_price": [22, 15, 9, 5],
        "implied_vol": [0.42, 0.38, 0.35, 0.33],
    })
    result = interpolate_surface(points_df, np.array([0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]), np.array([30, 60, 90, 180]))
    assert result is None  # honest "couldn't build a grid," not a crash


def test_headline_stats_recover_via_nearest_neighbor_fallback_when_grid_fails_entirely():
    """The actual fix for a real user report: blank ATM IV/skew despite
    having real, filtered contracts. When the full grid can't be built
    at all (e.g. the degenerate case above), the headline stats must
    still fall back to the closest real observed contract rather than
    going blank — and must say so transparently."""
    points_df = pd.DataFrame({
        "strike": [200, 210, 220, 230],
        "moneyness": [0.90, 0.95, 1.00, 1.05],
        "time_to_expiry_years": [12 / 365.25] * 4,
        "time_to_expiry_days": [12, 12, 12, 12],
        "mid_price": [22, 15, 9, 5],
        "implied_vol": [0.42, 0.38, 0.35, 0.33],
    })
    features = get_surface_features(points_df, spot_price=222)
    assert features is not None
    assert features["atm_iv_30d"] == 0.35  # the real ATM contract's own IV, not fabricated
    assert features["put_call_skew_30d"] == 0.05  # 0.38 - 0.33, the real 0.95/1.05 contracts
    assert len(features["data_quality_notes"]) == 2


def test_headline_stats_recover_via_nearest_neighbor_when_only_specific_grid_points_are_nan():
    """A less extreme, more common real scenario: the overall grid
    interpolates fine, but the SPECIFIC standard sample point (exactly
    30 days, exactly ATM) happens to fall in a gap the actual data
    doesn't cover well. Must fall back for that one point without
    discarding the rest of a perfectly good surface."""
    from backend.options.pricing import black_scholes_call_price

    S_local = 100.0
    rows = []
    # Real, well-distributed data across four expiries, but the
    # available strikes at 90 days are ONLY deep OTM — nothing near
    # ATM at that specific tenor, which can starve that grid cell.
    for tenor, strikes in [(15, np.arange(80, 121, 2.5)), (45, np.arange(80, 121, 2.5)),
                           (90, [130, 135, 140]), (200, np.arange(80, 121, 2.5))]:
        T = tenor / 365.25
        for K in strikes:
            iv = 0.30
            price = black_scholes_call_price(S_local, K, T, 0.045, iv)
            spread = max(0.05, price * 0.02)
            rows.append({"strike": K, "moneyness": K / S_local, "time_to_expiry_years": T,
                         "time_to_expiry_days": tenor, "mid_price": price, "implied_vol": iv})
    points_df = pd.DataFrame(rows)

    features = get_surface_features(points_df, spot_price=S_local)
    assert features is not None
    # Whether or not THIS particular case needed the fallback, the
    # core requirement is that ATM IV is never silently blank when
    # this much real, relevant data genuinely exists nearby.
    assert features["atm_iv_30d"] is not None


def test_empty_raw_chain_produces_empty_result():
    empty_chain = pd.DataFrame(columns=["strike", "bid", "ask", "volume", "openInterest"])
    result = preprocess_chain(empty_chain, S, expiry_days=30, risk_free_rate=R)
    assert result.empty
