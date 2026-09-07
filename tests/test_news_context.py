from datetime import datetime, timezone


class _FakeNewsService:
    def __init__(self, items=None, raise_error=False):
        self.items = items or []
        self.raise_error = raise_error

    def get_analyzed_news(self, ticker, limit=10, company_name=None):
        if self.raise_error:
            raise ConnectionError("simulated network failure")
        from backend.data.base import DataResult
        return DataResult(data=self.items, source="fake", fetched_at=datetime.now(timezone.utc), timeliness="delayed_15m")


class _FakeFundamentalsService:
    """Keeps tests fast and network-independent — real company-name
    lookup is tested separately."""
    def get_fundamentals(self, ticker):
        from backend.data.base import DataResult
        return DataResult(data={"short_name": f"{ticker} Corp"}, source="fake",
                           fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")


def test_news_agrees_with_bullish_model():
    from backend.forecasting.news_context import get_news_context
    fake = _FakeNewsService([{"impact_score": 40}, {"impact_score": 25}, {"impact_score": 10}])
    result = get_news_context("NVDA", ensemble_direction="bullish", news_service=fake, fundamentals_service=_FakeFundamentalsService())
    assert result["available"] is True
    assert result["news_direction"] == "bullish"
    assert result["agrees_with_model"] is True


def test_news_contradicts_bullish_model():
    from backend.forecasting.news_context import get_news_context
    fake = _FakeNewsService([{"impact_score": -50}, {"impact_score": -30}, {"impact_score": -20}])
    result = get_news_context("NVDA", ensemble_direction="bullish", news_service=fake, fundamentals_service=_FakeFundamentalsService())
    assert result["news_direction"] == "bearish"
    assert result["agrees_with_model"] is False
    assert "counter" in result["summary"]


def test_news_fetch_failure_degrades_gracefully():
    from backend.forecasting.news_context import get_news_context
    fake = _FakeNewsService(raise_error=True)
    result = get_news_context("OBSCURETICKER", ensemble_direction="bullish", news_service=fake, fundamentals_service=_FakeFundamentalsService())
    assert result["available"] is False  # never raises, never breaks the prediction


def test_no_news_available_degrades_gracefully():
    from backend.forecasting.news_context import get_news_context
    fake = _FakeNewsService(items=[])
    result = get_news_context("OBSCURETICKER", ensemble_direction="bullish", news_service=fake, fundamentals_service=_FakeFundamentalsService())
    assert result["available"] is False


def test_neutral_comparisons_are_not_forced():
    from backend.forecasting.news_context import get_news_context
    fake = _FakeNewsService([{"impact_score": 2}, {"impact_score": -3}])
    result = get_news_context("NVDA", ensemble_direction="neutral", news_service=fake, fundamentals_service=_FakeFundamentalsService())
    assert result["news_direction"] == "neutral"
    assert result["agrees_with_model"] is None  # neither agree nor disagree — not a meaningful comparison


def test_news_context_never_appears_as_a_trained_feature():
    """The core methodological guarantee: news must never enter the
    feature matrix used for training/walk-forward validation, only the
    live, post-hoc prediction bundle."""
    from backend.forecasting.features import FEATURE_COLUMNS
    for col in FEATURE_COLUMNS:
        assert "news" not in col.lower() and "sentiment" not in col.lower()


def test_company_name_is_resolved_and_passed_to_news_search():
    """Real gap found via testing: searching news for a raw ticker like
    'NVDA' misses articles that only say 'NVIDIA' — the vast majority
    of real coverage. The company name must be looked up and passed
    through to the actual search call."""
    from backend.forecasting.news_context import get_news_context

    captured = {}

    class CapturingNewsService:
        def get_analyzed_news(self, ticker, limit=10, company_name=None):
            captured["ticker"] = ticker
            captured["company_name"] = company_name
            from backend.data.base import DataResult
            return DataResult(data=[{"impact_score": 10}], source="fake",
                               fetched_at=datetime.now(timezone.utc), timeliness="delayed_15m")

    class FakeFundamentals:
        def get_fundamentals(self, ticker):
            from backend.data.base import DataResult
            return DataResult(data={"short_name": "NVIDIA Corporation"}, source="fake",
                               fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

    get_news_context("NVDA", ensemble_direction="bullish",
                      news_service=CapturingNewsService(), fundamentals_service=FakeFundamentals())

    assert captured["ticker"] == "NVDA"
    assert captured["company_name"] == "NVIDIA Corporation"


def test_company_name_lookup_failure_falls_back_gracefully():
    """If the fundamentals lookup fails for any reason, news search
    should still proceed ticker-only rather than breaking entirely."""
    from backend.forecasting.news_context import get_news_context

    class FailingFundamentals:
        def get_fundamentals(self, ticker):
            raise ConnectionError("simulated failure")

    fake_news = _FakeNewsService([{"impact_score": 10}])
    result = get_news_context("NVDA", ensemble_direction="bullish",
                               news_service=fake_news, fundamentals_service=FailingFundamentals())
    assert result["available"] is True  # degraded gracefully, still got a result


def test_recent_article_outweighs_stale_weekend_article():
    """The core adaptation of the weekend-rollup idea for a LIVE (not
    trained) check: a stale Saturday rumor must not count equally with
    this morning's real news. Flat-mean of -60 and +40 would be -10
    (bearish-leaning); recency-weighted should let the recent +40
    dominate and land clearly positive instead."""
    from datetime import datetime, timedelta, timezone
    from backend.forecasting.news_context import get_news_context

    now = datetime.now(timezone.utc)
    items = [
        {"impact_score": -60, "published_at": (now - timedelta(days=2, hours=10)).isoformat()},
        {"impact_score": 40, "published_at": (now - timedelta(hours=2)).isoformat()},
    ]
    result = get_news_context("TESTCO", "bullish", news_service=_FakeNewsService(items),
                               fundamentals_service=_FakeFundamentalsService())
    assert result["avg_impact_score"] > 0, "Recency weighting must let the recent article dominate the stale one"


def test_weekend_spanning_window_is_flagged_transparently():
    from datetime import datetime, timedelta, timezone
    from backend.forecasting.news_context import get_news_context

    now = datetime.now(timezone.utc)
    items = [
        {"impact_score": 20, "published_at": (now - timedelta(days=2, hours=10)).isoformat()},
        {"impact_score": 25, "published_at": (now - timedelta(hours=2)).isoformat()},
    ]
    result = get_news_context("TESTCO", "bullish", news_service=_FakeNewsService(items),
                               fundamentals_service=_FakeFundamentalsService())
    assert "spans about" in result["summary"]


def test_narrow_same_day_window_is_not_flagged():
    from datetime import datetime, timedelta, timezone
    from backend.forecasting.news_context import get_news_context

    now = datetime.now(timezone.utc)
    items = [
        {"impact_score": 20, "published_at": (now - timedelta(hours=1)).isoformat()},
        {"impact_score": 25, "published_at": (now - timedelta(hours=3)).isoformat()},
    ]
    result = get_news_context("TESTCO", "bullish", news_service=_FakeNewsService(items),
                               fundamentals_service=_FakeFundamentalsService())
    assert "spans about" not in result["summary"]


def test_missing_or_malformed_published_at_degrades_gracefully():
    """An article with no timestamp, or a malformed one, must still be
    counted (at neutral weight) rather than dropped or crashing —
    losing a real, already-analyzed article over a missing date field
    would throw away genuine signal."""
    from backend.forecasting.news_context import get_news_context

    items = [
        {"impact_score": 30},  # no published_at at all
        {"impact_score": -10, "published_at": "not-a-real-date"},  # malformed
    ]
    result = get_news_context("TESTCO", "bullish", news_service=_FakeNewsService(items),
                               fundamentals_service=_FakeFundamentalsService())
    assert result["available"] is True
    assert result["article_count"] == 2


def test_weekend_span_summary_survives_downstream_truncation_in_plain_summary():
    """Real bug found and fixed during development: build_plain_summary()
    extracts a headline from news_context['summary'] by splitting on the
    FIRST em-dash. The weekend-span coverage note originally also used
    an em-dash internally, so a weekend-spanning summary got silently
    truncated mid-parenthetical the moment it reached the plain-English
    summary — cut off before ever mentioning the gap it was flagging in
    the first place. Fixed by removing the internal dash; this proves
    the fix holds through the actual downstream consumer, not just the
    news_context module in isolation."""
    from datetime import datetime, timedelta, timezone
    from backend.forecasting.news_context import get_news_context
    from backend.forecasting.summary import build_plain_summary

    now = datetime.now(timezone.utc)
    items = [
        {"impact_score": 20, "published_at": (now - timedelta(days=2, hours=10)).isoformat()},
        {"impact_score": 25, "published_at": (now - timedelta(hours=2)).isoformat()},
    ]
    news_context = get_news_context("TESTCO", "bullish", news_service=_FakeNewsService(items),
                                     fundamentals_service=_FakeFundamentalsService())
    assert "spans about" in news_context["summary"]

    plain = build_plain_summary(
        ticker="TESTCO", horizon_days=5,
        signal={"signal": "BULLISH_WATCH", "reason": "test"},
        ensemble={"direction": "bullish", "confidence": 0.6, "expected_return_pct": 1.5,
                  "model_agreement": "3/4", "low_confidence_disagreement": False},
        news_context=news_context,
        position_sizing={"suggested_position_pct": None},
        relaxed_mode=False, out_of_distribution={"is_out_of_distribution": False},
    )
    assert "weekend or holiday gap" in plain, "The gap mention must survive all the way into the plain-English summary, not get truncated"
