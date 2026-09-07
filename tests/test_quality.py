import pandas as pd
import numpy as np

from backend.data.quality import score_historical_result, pick_best_historical
from tests.conftest import business_day_anchor


def _make_df(end_offset_days, n_periods, nan_slice=None, seed=1):
    today = business_day_anchor()
    dates = pd.date_range(end=today - pd.Timedelta(days=end_offset_days), periods=n_periods, freq="B")
    n = len(dates)
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": rng.random(n) + 100, "high": rng.random(n) + 101,
        "low": rng.random(n) + 99, "close": rng.random(n) + 100,
        "adj_close": rng.random(n) + 100,
        "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    })
    if nan_slice is not None:
        df.loc[nan_slice, "volume"] = np.nan
    return df


def test_fresher_source_scores_higher():
    fresh = _make_df(end_offset_days=0, n_periods=250)
    stale = _make_df(end_offset_days=10, n_periods=250)
    fresh_score = score_historical_result(fresh, "1y", "source_a")
    stale_score = score_historical_result(stale, "1y", "source_b")
    assert fresh_score["score"] > stale_score["score"]


def test_more_complete_source_scores_higher_at_equal_freshness():
    complete = _make_df(end_offset_days=0, n_periods=250)
    incomplete = _make_df(end_offset_days=0, n_periods=250, nan_slice=slice(0, 50))
    complete_score = score_historical_result(complete, "1y", "source_a")
    incomplete_score = score_historical_result(incomplete, "1y", "source_b")
    assert complete_score["score"] > incomplete_score["score"]


def test_empty_or_none_data_scores_as_unusable():
    assert score_historical_result(None, "1y", "source_a")["score"] == -1
    assert score_historical_result(pd.DataFrame(), "1y", "source_a")["score"] == -1


def test_pick_best_is_content_based_not_order_based():
    """The core requirement: selection must depend on which data is
    actually better, not which provider happens to be listed/tried
    first. Swapping which provider has the better data must swap the
    winner too."""
    good = _make_df(end_offset_days=0, n_periods=250)
    bad = _make_df(end_offset_days=15, n_periods=100, nan_slice=slice(0, 20))

    result_a = pick_best_historical([("provider_x", good), ("provider_y", bad)], "1y")
    result_b = pick_best_historical([("provider_x", bad), ("provider_y", good)], "1y")

    assert result_a["winner"] == "provider_x"
    assert result_b["winner"] == "provider_y"  # same underlying good data, different provider name


def test_pick_best_falls_back_to_only_available_candidate():
    only = _make_df(end_offset_days=0, n_periods=100)
    result = pick_best_historical([("only_source", only)], "1y")
    assert result["winner"] == "only_source"


def test_pick_best_handles_all_candidates_failing():
    result = pick_best_historical([("a", None), ("b", pd.DataFrame())], "1y")
    assert result["winner"] is None


def test_comparison_includes_human_readable_reasons():
    df = _make_df(end_offset_days=0, n_periods=250)
    result = pick_best_historical([("source_a", df)], "1y")
    assert len(result["comparison"][0]["reasons"]) >= 2
    assert all(isinstance(r, str) for r in result["comparison"][0]["reasons"])
