from unittest.mock import MagicMock, patch

from backend.data.news_provider import NamedOutletRSSProvider, SeekingAlphaProvider


class FakeEntry(dict):
    def __init__(self, title, link, published_parsed=None):
        super().__init__(title=title, link=link)
        self.published_parsed = published_parsed or (2026, 8, 22, 10, 0, 0, 0, 0, 0)


class FakeParsedFeed:
    def __init__(self, entries, bozo=False):
        self.entries = entries
        self.bozo = bozo


def _mock_response(status=200, content=b"<rss></rss>"):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    return resp


# ------------------------------------------------------------- Seeking Alpha

def test_seeking_alpha_builds_ticker_specific_url():
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _mock_response()

    with patch("backend.data.news_provider.requests.get", side_effect=fake_get), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed([])):
        SeekingAlphaProvider().get_news("NVDA")

    assert "NVDA" in captured["url"]
    assert "seekingalpha.com" in captured["url"]


def test_seeking_alpha_success_returns_articles():
    entries = [FakeEntry("Why NVDA Is Still A Buy Heading Into Earnings", "http://a")]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = SeekingAlphaProvider().get_news("NVDA")

    assert result.success
    assert result.data[0]["source"] == "Seeking Alpha"
    assert diag.status == "SUCCESS"
    assert diag.valid_articles == 1


def test_seeking_alpha_404_reported_as_empty_not_crash():
    with patch("backend.data.news_provider.requests.get", return_value=_mock_response(status=404)):
        result, diag = SeekingAlphaProvider().get_news("ZZZZ")
    assert not result.success
    assert diag.status == "EMPTY"
    assert diag.http_status == 404


def test_seeking_alpha_does_not_apply_relevance_filter():
    """Seeking Alpha's feed is already scoped by ticker via the URL —
    headlines like 'Why This Semiconductor Giant Is Still A Buy' won't
    literally contain the ticker, and that's fine; it shouldn't be
    dropped the way a general-topic feed's entries would be."""
    entries = [FakeEntry("Why This Semiconductor Giant Is Still A Buy", "http://a")]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = SeekingAlphaProvider().get_news("NVDA")
    assert result.success
    assert len(result.data) == 1


# ---------------------------------------------------------- Named outlet RSS

def test_named_outlet_filters_to_relevant_headlines_only():
    entries = [
        FakeEntry("NVDA shares surge on AI demand", "http://a"),
        FakeEntry("Unrelated story about housing prices", "http://b"),
        FakeEntry("Fed holds interest rates steady", "http://c"),
    ]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = NamedOutletRSSProvider("CNBC", "http://fake-feed").get_news("NVDA")

    assert result.success
    assert len(result.data) == 1
    assert result.data[0]["source"] == "CNBC"
    assert diag.entries_found == 3
    assert diag.valid_articles == 1


def test_named_outlet_reports_empty_when_nothing_relevant():
    entries = [FakeEntry("Completely unrelated market commentary", "http://a")]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = NamedOutletRSSProvider("MarketWatch", "http://fake-feed").get_news("NVDA")

    assert not result.success
    assert diag.status == "EMPTY"
    assert diag.entries_found == 1


def test_named_outlet_reports_403_explicitly():
    with patch("backend.data.news_provider.requests.get", return_value=_mock_response(status=403)):
        result, diag = NamedOutletRSSProvider("CNBC", "http://fake-feed").get_news("NVDA")
    assert not result.success
    assert diag.status == "FORBIDDEN"


def test_named_outlet_uses_correct_display_name_as_source():
    entries = [FakeEntry("NVDA earnings beat expectations", "http://a")]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = NamedOutletRSSProvider("MarketWatch", "http://fake-feed").get_news("NVDA")
    assert result.data[0]["source"] == "MarketWatch"
    assert diag.name == "MarketWatch"
