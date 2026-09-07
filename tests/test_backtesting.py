import os
import tempfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from tests.conftest import business_day_anchor


def _make_ohlcv(n, seed=1, drift=0.0006):
    today = business_day_anchor()
    dates = pd.date_range(end=today, periods=n, freq="B")
    n_actual = len(dates)
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(drift, 0.013, n_actual))
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": close, "high": close * 1.005,
        "low": close * 0.995, "close": close, "adj_close": close,
        "volume": rng.integers(1_000_000, 10_000_000, n_actual),
    })


@pytest.fixture()
def isolated_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from backend.config import settings
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()

    import backend.backtesting.service as bt_module
    monkeypatch.setattr(bt_module, "BACKTEST_STEP", 90)  # faster for tests

    yield tmp.name
    os.remove(tmp.name)


def _install_provider(df):
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=df.copy(), source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [FakeProvider()]


def test_backtest_produces_valid_result_structure(isolated_db):
    from backend.backtesting.service import run_backtest
    _install_provider(_make_ohlcv(1300))

    result = run_backtest("TESTCO", horizon_days=5)
    assert result["success"]
    assert len(result["equity_curve"]) > 0
    assert "total_return_pct" in result["stats"]
    assert "buy_and_hold_return_pct" in result["stats"]
    assert "max_drawdown_pct" in result["stats"]
    assert result["stats"]["max_drawdown_pct"] <= 0  # drawdown is always <= 0 by definition
    assert result["stats"]["final_equity"] > 0


def test_backtest_fails_gracefully_with_insufficient_data(isolated_db):
    from backend.backtesting.service import run_backtest
    _install_provider(_make_ohlcv(50))

    result = run_backtest("TOOSHORTCO", horizon_days=5)
    assert not result["success"]
    assert "error" in result


def test_buy_and_hold_matches_actual_tested_date_range(isolated_db):
    """Real bug found and fixed during development: buy-and-hold was
    computed over the ENTIRE feature history (including the initial
    training warm-up period never actually traded), while the
    strategy's own return was only computed over the period actually
    tested — an apples-to-oranges comparison. They must now cover the
    exact same date range."""
    from backend.backtesting.service import run_backtest
    df = _make_ohlcv(1300)
    _install_provider(df)

    result = run_backtest("TESTCO", horizon_days=5)
    assert result["success"]

    first_date = result["equity_curve"][0]["date"]
    last_date = result["equity_curve"][-1]["date"]
    mask = (df["date"] >= first_date) & (df["date"] <= last_date)
    subset = df[mask]
    expected_bh = (subset["close"].iloc[-1] / subset["close"].iloc[0] - 1) * 100

    assert abs(expected_bh - result["stats"]["buy_and_hold_return_pct"]) < 0.5


def test_early_trading_decisions_are_not_affected_by_future_data(isolated_db):
    """The core causality/no-leakage guarantee, tested the same way
    walk-forward validation itself was: two backtests that are
    IDENTICAL up through some early point, but diverge completely
    afterward, must produce IDENTICAL trade decisions and equity
    values up through that point. If a later change could alter an
    earlier decision, that would mean the simulation is peeking at
    future data — exactly what this whole app has been built to avoid."""
    from backend.backtesting.service import run_backtest
    import backend.backtesting.service as bt_module

    base_df = _make_ohlcv(1300, seed=1)

    # Version A: the real, unmodified series.
    _install_provider(base_df)
    result_a = run_backtest("TESTCO", horizon_days=5)
    assert result_a["success"]

    # Version B: identical for the first 900 rows, then replaced with
    # completely different random data for everything after.
    diverged_df = base_df.copy()
    rng = np.random.default_rng(999)
    tail_len = len(diverged_df) - 900
    new_tail_close = 100 * np.cumprod(1 + rng.normal(-0.002, 0.03, tail_len))  # wildly different regime
    diverged_df.loc[900:, "close"] = new_tail_close
    diverged_df.loc[900:, "open"] = new_tail_close
    diverged_df.loc[900:, "high"] = new_tail_close * 1.01
    diverged_df.loc[900:, "low"] = new_tail_close * 0.99

    _install_provider(diverged_df)
    result_b = run_backtest("TESTCO", horizon_days=5)
    assert result_b["success"]

    # Compare equity curve entries that fall before the divergence point.
    divergence_date = base_df["date"].iloc[900]
    early_a = [p for p in result_a["equity_curve"] if p["date"] < divergence_date]
    early_b = [p for p in result_b["equity_curve"] if p["date"] < divergence_date]

    assert len(early_a) == len(early_b) and len(early_a) > 0
    for pa, pb in zip(early_a, early_b):
        assert pa["date"] == pb["date"]
        assert abs(pa["equity"] - pb["equity"]) < 0.01, (
            f"Equity at {pa['date']} differs between the two runs ({pa['equity']} vs {pb['equity']}) "
            f"despite identical data up to that point — this means a later change is somehow "
            f"affecting an earlier trading decision, which would be a real leakage bug."
        )


def test_position_sizing_starts_conservative_before_enough_trade_history(isolated_db):
    """Before MIN_TRADES_FOR_KELLY real trades have closed, the backtest
    must use a small, fixed conservative stake rather than a
    statistically unjustified Kelly-derived size."""
    from backend.backtesting.service import run_backtest
    _install_provider(_make_ohlcv(1300))

    result = run_backtest("TESTCO", horizon_days=5)
    assert result["success"]
    early_trades = result["trade_log"][:5]
    for t in early_trades:
        assert t["position_pct"] <= 5.0  # conservative default stake, not an aggressive Kelly size


def test_backtest_is_stored_in_database(isolated_db):
    from backend.backtesting.service import run_backtest
    from backend.database.db import db_cursor
    _install_provider(_make_ohlcv(1300))

    run_backtest("TESTCO", horizon_days=5)
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as c FROM backtests WHERE ticker = 'TESTCO'")
        count = cur.fetchone()["c"]
    assert count == 1


def test_transaction_costs_genuinely_reduce_reported_performance(isolated_db, monkeypatch):
    """Real gap found via audit: the backtest computed every trade's
    P&L from the raw price move with zero deduction for transaction
    costs — a well-known, textbook way a backtest can overstate real
    performance. It was disclosed in the UI's disclaimer text, but a
    disclaimer isn't the same as actually modeling it. This proves the
    modeled cost genuinely drags down reported returns, not just gets
    mentioned in a caption."""
    import backend.backtesting.service as bt_module
    monkeypatch.setattr(bt_module, "BACKTEST_STEP", 60)
    df = _make_ohlcv(1300, seed=5)
    _install_provider(df)

    result_with_cost = bt_module.run_backtest("TESTCO", horizon_days=5)

    monkeypatch.setattr(bt_module, "ROUND_TRIP_TRANSACTION_COST_PCT", 0.0)
    result_no_cost = bt_module.run_backtest("TESTCO", horizon_days=5)

    assert result_with_cost["stats"]["total_return_pct"] < result_no_cost["stats"]["total_return_pct"]
