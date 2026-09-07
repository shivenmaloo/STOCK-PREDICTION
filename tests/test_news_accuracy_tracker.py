import os
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from tests.conftest import business_day_anchor


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


def _seed_log(ticker, impact_score, direction, reference_price, horizon_days=5, days_ago=10):
    from backend.database.db import db_cursor
    logged_time = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO news_sentiment_log (ticker, logged_at, impact_score, news_direction, reference_price, horizon_days) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker, logged_time, impact_score, direction, reference_price, horizon_days),
        )


def _install_provider(close_prices):
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    today = business_day_anchor()
    dates = pd.date_range(end=today, periods=len(close_prices), freq="B")
    df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close_prices, "high": close_prices,
                        "low": close_prices, "close": close_prices, "adj_close": close_prices,
                        "volume": [1_000_000] * len(close_prices)})

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=df.copy(), source=self.name, fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    mds_module.market_data_service.providers = [FakeProvider()]


def test_log_news_sentiment_writes_a_row(isolated_db):
    from backend.news.accuracy_tracker import log_news_sentiment
    from backend.database.db import db_cursor

    log_news_sentiment("TESTCO", 25.0, "bullish", 100.0, 5)
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as c FROM news_sentiment_log WHERE ticker = 'TESTCO'")
        assert cur.fetchone()["c"] == 1


def test_log_news_sentiment_never_raises_on_db_failure(isolated_db, monkeypatch):
    """A logging failure must never break the prediction that triggered it."""
    from backend.news import accuracy_tracker

    def broken_cursor():
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(accuracy_tracker, "db_cursor", broken_cursor)
    accuracy_tracker.log_news_sentiment("TESTCO", 25.0, "bullish", 100.0, 5)  # must not raise


def test_correctly_identifies_right_and_wrong_directional_calls(isolated_db):
    from backend.news.accuracy_tracker import evaluate_matured_news_sentiment, get_news_sentiment_accuracy

    _seed_log("TESTCO", 25.0, "bullish", 100.0)   # will be validated (price rises)
    _seed_log("TESTCO", -30.0, "bearish", 100.0)  # will be invalidated (price rises)
    _install_provider(np.linspace(100, 110, 30))  # steadily rising

    result = evaluate_matured_news_sentiment()
    assert result["evaluated"] == 2

    accuracy = get_news_sentiment_accuracy()
    assert accuracy["n_evaluated"] == 2
    assert accuracy["accuracy"] == 0.5


def test_neutral_reads_are_never_scored_right_or_wrong(isolated_db):
    """A neutral read isn't a directional call — it can't be marked
    correct or incorrect against a directional outcome, and must not
    be silently counted as either."""
    from backend.news.accuracy_tracker import evaluate_matured_news_sentiment, get_news_sentiment_accuracy
    from backend.database.db import db_cursor

    _seed_log("TESTCO", 2.0, "neutral", 100.0)
    _install_provider(np.linspace(100, 110, 30))

    result = evaluate_matured_news_sentiment()
    assert result["evaluated"] == 1

    with db_cursor() as cur:
        cur.execute("SELECT was_correct FROM news_sentiment_results")
        row = cur.fetchone()
        assert row["was_correct"] is None

    accuracy = get_news_sentiment_accuracy()
    assert accuracy["n_evaluated"] == 0  # neutral reads excluded from the accuracy stat entirely


def test_not_yet_matured_reads_are_skipped(isolated_db):
    from backend.news.accuracy_tracker import evaluate_matured_news_sentiment

    _seed_log("TESTCO", 25.0, "bullish", 100.0, horizon_days=20, days_ago=1)  # nowhere near matured
    _install_provider(np.linspace(100, 110, 30))

    result = evaluate_matured_news_sentiment()
    assert result["evaluated"] == 0
    assert result["skipped_not_yet_matured_or_no_data"] == 1


def test_no_evaluated_reads_returns_honest_empty_state(isolated_db):
    from backend.news.accuracy_tracker import get_news_sentiment_accuracy

    accuracy = get_news_sentiment_accuracy()
    assert accuracy["n_evaluated"] == 0
    assert accuracy["accuracy"] is None
    assert accuracy["note"] is not None


def test_accuracy_can_be_filtered_by_ticker(isolated_db):
    from backend.news.accuracy_tracker import evaluate_matured_news_sentiment, get_news_sentiment_accuracy

    _seed_log("AAA", 25.0, "bullish", 100.0)
    _seed_log("BBB", -30.0, "bearish", 100.0)
    _install_provider(np.linspace(100, 110, 30))  # rising — validates AAA, invalidates BBB

    evaluate_matured_news_sentiment()

    aaa_accuracy = get_news_sentiment_accuracy(ticker="AAA")
    assert aaa_accuracy["n_evaluated"] == 1
    assert aaa_accuracy["accuracy"] == 1.0

    bbb_accuracy = get_news_sentiment_accuracy(ticker="BBB")
    assert bbb_accuracy["n_evaluated"] == 1
    assert bbb_accuracy["accuracy"] == 0.0
