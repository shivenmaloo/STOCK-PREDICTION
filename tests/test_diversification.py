import pandas as pd
import pytest

from backend.forecasting.diversification import select_diversified_picks


def _known_corr_matrix():
    return pd.DataFrame(
        [[1.00, 0.95, 0.05],
         [0.95, 1.00, 0.03],
         [0.05, 0.03, 1.00]],
        index=["A", "B", "C"], columns=["A", "B", "C"],
    )


def test_prefers_weaker_uncorrelated_pick_over_stronger_redundant_one():
    """The core point of the whole feature: a slightly-lower-scoring
    but genuinely uncorrelated pick should beat a higher-scoring but
    redundant one, once correlation is actually penalized."""
    candidates = [
        {"ticker": "A", "score": 3.0, "signal": "STRONG_BULLISH_SETUP"},
        {"ticker": "B", "score": 2.9, "signal": "STRONG_BULLISH_SETUP"},
        {"ticker": "C", "score": 2.0, "signal": "BULLISH_WATCH"},
    ]
    result = select_diversified_picks(candidates, limit=2, correlation_penalty=0.5, corr_matrix=_known_corr_matrix())
    picked = [p["ticker"] for p in result["picks"]]
    assert picked == ["A", "C"]


def test_zero_penalty_reduces_to_plain_top_n_ranking():
    candidates = [
        {"ticker": "A", "score": 3.0, "signal": "STRONG_BULLISH_SETUP"},
        {"ticker": "B", "score": 2.9, "signal": "STRONG_BULLISH_SETUP"},
        {"ticker": "C", "score": 2.0, "signal": "BULLISH_WATCH"},
    ]
    result = select_diversified_picks(candidates, limit=2, correlation_penalty=0.0, corr_matrix=_known_corr_matrix())
    picked = [p["ticker"] for p in result["picks"]]
    assert picked == ["A", "B"]


def test_always_takes_the_single_best_scoring_pick_first():
    candidates = [
        {"ticker": "A", "score": 3.0, "signal": "STRONG_BULLISH_SETUP"},
        {"ticker": "B", "score": 1.0, "signal": "BULLISH_WATCH"},
    ]
    result = select_diversified_picks(candidates, limit=2, correlation_penalty=0.5, corr_matrix=_known_corr_matrix())
    assert result["picks"][0]["ticker"] == "A"
    assert result["picks"][0]["avg_correlation_with_selected"] is None  # nothing to compare the first pick against


def test_empty_candidates_returns_empty_result():
    result = select_diversified_picks([], limit=5)
    assert result["picks"] == []
    assert result["correlation_data_available"] is False


def test_missing_correlation_data_degrades_to_neutral_zero_correlation():
    """If correlation data can't be fetched for a candidate (or at
    all), it should be treated as neutral (0 correlation) rather than
    crashing or silently dropping the candidate."""
    candidates = [
        {"ticker": "A", "score": 3.0, "signal": "STRONG_BULLISH_SETUP"},
        {"ticker": "UNKNOWN_TICKER", "score": 2.9, "signal": "STRONG_BULLISH_SETUP"},
    ]
    empty_corr = pd.DataFrame()
    result = select_diversified_picks(candidates, limit=2, correlation_penalty=0.5, corr_matrix=empty_corr)
    assert len(result["picks"]) == 2
    assert result["correlation_data_available"] is False


def test_fewer_candidates_than_limit_returns_all_of_them():
    candidates = [{"ticker": "A", "score": 3.0, "signal": "STRONG_BULLISH_SETUP"}]
    result = select_diversified_picks(candidates, limit=5, corr_matrix=_known_corr_matrix())
    assert len(result["picks"]) == 1


def test_negative_scores_handled_via_absolute_value_ranking():
    """Scores can be negative (risk-flag style candidates) — ranking
    must be by magnitude of conviction, not raw sign, so a strong
    bearish call isn't treated as 'weaker' than a weak bullish one."""
    candidates = [
        {"ticker": "A", "score": -3.0, "signal": "HIGH_RISK_POSSIBLE_EXIT"},
        {"ticker": "B", "score": 1.0, "signal": "BULLISH_WATCH"},
    ]
    result = select_diversified_picks(candidates, limit=2, correlation_penalty=0.0, corr_matrix=pd.DataFrame())
    assert result["picks"][0]["ticker"] == "A"  # -3.0 has greater magnitude than 1.0
