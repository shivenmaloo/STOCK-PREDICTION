import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def isolated_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from backend.config import settings
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()
    yield tmp.name
    os.remove(tmp.name)


def _add_watchlist(*tickers):
    from backend.database.db import db_cursor
    with db_cursor() as cur:
        for t in tickers:
            cur.execute("INSERT INTO watchlist (ticker, added_at, notes) VALUES (?, ?, '')",
                        (t, datetime.now(timezone.utc).isoformat()))


def _seed_prediction(ticker, signal, confidence, hours_ago=1, horizon=5):
    from backend.database.db import db_cursor
    created = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO predictions (ticker, created_at, horizon_days, expected_return, confidence, signal, model_breakdown_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, created, horizon, 2.0, confidence, signal, "[]"),
        )


def test_empty_watchlist_and_portfolio_returns_honest_note(isolated_db):
    from backend.forecasting.suggestions import get_stock_suggestions
    result = get_stock_suggestions()
    assert result["bullish"] == []
    assert result["risk_flags"] == []
    assert result["note"] is not None


def test_bullish_ranked_by_signal_strength_and_confidence(isolated_db):
    from backend.forecasting.suggestions import get_stock_suggestions
    _add_watchlist("NVDA", "AAPL")
    _seed_prediction("NVDA", "STRONG_BULLISH_SETUP", 0.85)
    _seed_prediction("AAPL", "BULLISH_WATCH", 0.6)

    result = get_stock_suggestions()
    assert [s["ticker"] for s in result["bullish"]] == ["NVDA", "AAPL"]


def test_risk_flags_ranked_separately_from_bullish(isolated_db):
    from backend.forecasting.suggestions import get_stock_suggestions
    _add_watchlist("XOM")
    _seed_prediction("XOM", "HIGH_RISK_POSSIBLE_EXIT", 0.7)

    result = get_stock_suggestions()
    assert result["bullish"] == []
    assert result["risk_flags"][0]["ticker"] == "XOM"


def test_neutral_signal_appears_in_neither_list(isolated_db):
    from backend.forecasting.suggestions import get_stock_suggestions
    _add_watchlist("BORING")
    _seed_prediction("BORING", "NEUTRAL", 0.5)

    result = get_stock_suggestions()
    assert result["bullish"] == []
    assert result["risk_flags"] == []


def test_stale_prediction_is_excluded_and_reported():
    """Real bug found and fixed during development: a stale prediction
    was being marked 'seen' (preventing it from being flagged as
    missing) while simultaneously being excluded from the staleness
    list itself — meaning it silently disappeared from the report
    entirely instead of being flagged either way."""
    import tempfile as _tf
    from backend.config import settings
    tmp = _tf.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()

    _add_watchlist("STALE")
    _seed_prediction("STALE", "STRONG_BULLISH_SETUP", 0.9, hours_ago=72)

    from backend.forecasting.suggestions import get_stock_suggestions
    result = get_stock_suggestions()
    assert result["bullish"] == []  # too stale to count as a live suggestion
    assert "STALE" in result["stale_or_missing"]  # but must not silently vanish
    os.remove(tmp.name)


def test_never_predicted_ticker_appears_in_missing_list(isolated_db):
    from backend.forecasting.suggestions import get_stock_suggestions
    _add_watchlist("NEVERPREDICTED")
    result = get_stock_suggestions()
    assert "NEVERPREDICTED" in result["stale_or_missing"]


def test_only_tracked_tickers_are_considered(isolated_db):
    """A prediction exists for a ticker that's neither watchlisted nor
    held — it must not appear in suggestions at all."""
    from backend.forecasting.suggestions import get_stock_suggestions
    _add_watchlist("TRACKED")
    _seed_prediction("TRACKED", "BULLISH_WATCH", 0.6)
    _seed_prediction("UNTRACKED", "STRONG_BULLISH_SETUP", 0.95)

    result = get_stock_suggestions()
    all_tickers = [s["ticker"] for s in result["bullish"] + result["risk_flags"]]
    assert "UNTRACKED" not in all_tickers
    assert "TRACKED" in all_tickers


def test_portfolio_holdings_are_also_considered(isolated_db):
    from backend.database.db import db_cursor
    with db_cursor() as cur:
        cur.execute("INSERT INTO portfolio (ticker, shares, entry_price, entry_date, notes) VALUES (?, ?, ?, ?, ?)",
                    ("HELD", 10, 100.0, "2026-01-01", ""))
    _seed_prediction("HELD", "HIGH_RISK_POSSIBLE_EXIT", 0.75)

    from backend.forecasting.suggestions import get_stock_suggestions
    result = get_stock_suggestions()
    assert result["risk_flags"][0]["ticker"] == "HELD"


def test_limit_is_respected(isolated_db):
    from backend.forecasting.suggestions import get_stock_suggestions
    tickers = [f"T{i}" for i in range(10)]
    _add_watchlist(*tickers)
    for t in tickers:
        _seed_prediction(t, "STRONG_BULLISH_SETUP", 0.8)

    result = get_stock_suggestions(limit=3)
    assert len(result["bullish"]) == 3


def test_discovery_excludes_already_tracked_tickers(isolated_db):
    """The core point of discovery: a ticker already in your
    watchlist/portfolio must not also show up in discovery — that
    would just be the tracked suggestion duplicated, not something new."""
    from backend.forecasting.suggestions import get_discovery_suggestions, SCANNER_UNIVERSE
    tracked_ticker = SCANNER_UNIVERSE[0]
    _add_watchlist(tracked_ticker)
    _seed_prediction(tracked_ticker, "STRONG_BULLISH_SETUP", 0.9)

    result = get_discovery_suggestions()
    all_tickers = [s["ticker"] for s in result["bullish"] + result["risk_flags"]]
    assert tracked_ticker not in all_tickers


def test_discovery_surfaces_untracked_universe_tickers(isolated_db):
    """The actual point of this whole feature: a ticker the user never
    added anywhere should still be able to show up as a genuine
    discovery, as long as it's in the scanner universe and has a fresh
    prediction."""
    from backend.forecasting.suggestions import get_discovery_suggestions, SCANNER_UNIVERSE
    untracked = SCANNER_UNIVERSE[5]
    _seed_prediction(untracked, "STRONG_BULLISH_SETUP", 0.85)

    result = get_discovery_suggestions()
    assert untracked in [s["ticker"] for s in result["bullish"]]


def test_discovery_never_includes_tickers_outside_the_universe(isolated_db):
    """A random ticker that happens to have a prediction but isn't
    part of the curated scanner universe must not appear in discovery
    — discovery is scoped to that specific, known-liquid pool."""
    from backend.forecasting.suggestions import get_discovery_suggestions
    _seed_prediction("ZZZZNOTINUNIVERSE", "STRONG_BULLISH_SETUP", 0.9)

    result = get_discovery_suggestions()
    all_tickers = [s["ticker"] for s in result["bullish"] + result["risk_flags"]]
    assert "ZZZZNOTINUNIVERSE" not in all_tickers


def test_discovery_coverage_reflects_real_fresh_predictions(isolated_db):
    from backend.forecasting.suggestions import get_discovery_coverage, SCANNER_UNIVERSE
    _seed_prediction(SCANNER_UNIVERSE[0], "NEUTRAL", 0.5)
    _seed_prediction(SCANNER_UNIVERSE[1], "NEUTRAL", 0.5)

    coverage = get_discovery_coverage()
    assert coverage["covered"] == 2
    assert coverage["total"] == len(SCANNER_UNIVERSE)
    assert coverage["pct"] == round(2 / len(SCANNER_UNIVERSE) * 100, 1)


def test_discovery_coverage_excludes_stale_predictions(isolated_db):
    from backend.forecasting.suggestions import get_discovery_coverage, SCANNER_UNIVERSE
    _seed_prediction(SCANNER_UNIVERSE[0], "NEUTRAL", 0.5, hours_ago=100)  # well past the freshness window

    coverage = get_discovery_coverage()
    assert coverage["covered"] == 0


def test_discovery_coverage_excludes_tracked_tickers_from_the_denominator(isolated_db):
    """A tracked ticker shouldn't count toward (or against) discovery
    coverage — it's not part of what discovery is trying to cover."""
    from backend.forecasting.suggestions import get_discovery_coverage, SCANNER_UNIVERSE
    _add_watchlist(SCANNER_UNIVERSE[0])

    coverage = get_discovery_coverage()
    assert coverage["total"] == len(SCANNER_UNIVERSE) - 1


def test_discovery_sweep_prioritizes_never_predicted_tickers(isolated_db, monkeypatch):
    """The sweep must make real progress toward covering the universe
    — prioritizing tickers with NO existing prediction over ones that
    already have a recent one, so coverage actually grows each run."""
    from backend.forecasting import suggestions as suggestions_module
    from backend.forecasting.suggestions import SCANNER_UNIVERSE

    # Give the very first universe ticker a fresh prediction already —
    # it should NOT be selected for retraining ahead of never-trained ones.
    _seed_prediction(SCANNER_UNIVERSE[0], "NEUTRAL", 0.5, hours_ago=1)

    trained_tickers = []

    class FakePredictionService:
        def get_or_train(self, ticker, horizon_days):
            trained_tickers.append(ticker)
            return {"success": True}

    monkeypatch.setattr(
        "backend.forecasting.service.prediction_service", FakePredictionService()
    )

    result = suggestions_module.run_discovery_sweep(batch_size=3)
    assert len(result["refreshed"]) == 3
    assert SCANNER_UNIVERSE[0] not in trained_tickers


def test_discovery_sweep_handles_training_failures_gracefully(isolated_db, monkeypatch):
    class FailingPredictionService:
        def get_or_train(self, ticker, horizon_days):
            raise RuntimeError("simulated training failure")

    monkeypatch.setattr(
        "backend.forecasting.service.prediction_service", FailingPredictionService()
    )

    from backend.forecasting.suggestions import run_discovery_sweep
    result = run_discovery_sweep(batch_size=2)
    assert len(result["failed"]) == 2
    assert result["refreshed"] == []
