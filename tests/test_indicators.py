import numpy as np
import pandas as pd

from backend.indicators.technical import (
    compute_all_indicators,
    detect_price_structure,
    interpret_technicals,
    rsi,
    sma,
)


def _synthetic_ohlcv(n=300, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    close = 100 + np.cumsum(rng.normal(0.1, 1.5, n))
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.5, n))
    volume = rng.integers(1_000_000, 5_000_000, n)
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "adj_close": close, "volume": volume,
    })


def test_sma_matches_manual_mean():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = sma(s, 3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == 2.0
    assert result.iloc[4] == 4.0


def test_rsi_bounds():
    df = _synthetic_ohlcv()
    r = rsi(df["close"])
    assert r.dropna().between(0, 100).all()


def test_compute_all_indicators_preserves_row_count():
    df = _synthetic_ohlcv(n=250)
    enriched = compute_all_indicators(df)
    assert len(enriched) == len(df)
    for col in ["sma_50", "sma_200", "rsi_14", "macd", "atr_14", "bb_upper", "obv"]:
        assert col in enriched.columns


def test_detect_price_structure_has_required_keys():
    df = _synthetic_ohlcv(n=100)
    enriched = compute_all_indicators(df)
    structure = detect_price_structure(enriched)
    for key in ("support", "resistance", "breakout", "breakdown", "structure"):
        assert key in structure


def test_interpret_technicals_returns_nonempty_sentence():
    df = _synthetic_ohlcv(n=250)
    enriched = compute_all_indicators(df)
    structure = detect_price_structure(enriched)
    text = interpret_technicals(enriched.iloc[-1], structure)
    assert isinstance(text, str)
    assert len(text) > 20


def test_interpret_technicals_handles_short_history_gracefully():
    df = _synthetic_ohlcv(n=3)
    enriched = compute_all_indicators(df)
    structure = detect_price_structure(enriched)
    text = interpret_technicals(enriched.iloc[-1], structure)
    assert isinstance(text, str)
