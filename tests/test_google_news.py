from unittest.mock import MagicMock, patch

from backend.data.news_provider import GoogleNewsSearchProvider


class FakeEntry(dict):
    def __init__(self, title, link, published_parsed=None, source=None):
        super().__init__(title=title, link=link)
        self.published_parsed = published_parsed
        if source:
            self["source"] = source


class FakeParsedFeed:
    def __init__(self, entries, bozo=False):
        self.entries = entries
        self.bozo = bozo


def _mock_requests_response(status=200, content=b"<rss></rss>"):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    return resp


def test_google_news_splits_title_suffix_when_no_source_tag():
    entries = [FakeEntry("NVDA beats earnings estimates - Reuters", "http://a", (2026, 8, 16, 10, 0, 0, 0, 0, 0))]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")
    assert result.success
    assert result.data[0]["source"] == "Reuters"
    assert result.data[0]["headline"] == "NVDA beats earnings estimates"
    assert diag.status == "SUCCESS"
    assert diag.valid_articles == 1
    assert diag.publisher_breakdown == {"Reuters": 1}


def test_google_news_prefers_structured_source_tag():
    entries = [FakeEntry("NVDA stock rallies", "http://a", (2026, 8, 16, 10, 0, 0, 0, 0, 0), source={"title": "Barron's"})]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")
    assert result.success
    assert result.data[0]["source"] == "Barron's"


def test_google_news_never_fabricates_unknown_publisher():
    """An entry with no source tag and no ' - Publisher' suffix should
    be labeled as unspecified, never guessed."""
    entries = [FakeEntry("NVDA headline with no attribution", "http://a", (2026, 8, 16, 10, 0, 0, 0, 0, 0))]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")
    assert result.data[0]["source"] == "Google News (source unspecified)"


def test_google_news_uses_company_name_in_query_when_provided():
    captured_url = {}

    def fake_get(url, headers=None, timeout=None):
        captured_url["url"] = url
        return _mock_requests_response()

    with patch("backend.data.news_provider.requests.get", side_effect=fake_get), \
         patch("backend.data.news_provider.feedparser.parse",
               return_value=FakeParsedFeed([FakeEntry("CoreWeave headline - Source", "http://a")])):
        GoogleNewsSearchProvider().get_news("CRWV", company_name="CoreWeave Inc")

    assert "CoreWeave" in captured_url["url"]


def test_google_news_reports_failure_on_empty_results():
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed([])):
        result, diag = GoogleNewsSearchProvider().get_news("ZZZZ")
    assert not result.success
    assert diag.status == "EMPTY"
    assert diag.http_status == 200
    assert diag.entries_found == 0


def test_google_news_reports_429_as_rate_limited():
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response(status=429)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")
    assert not result.success
    assert diag.status == "RATE_LIMITED"
    assert diag.http_status == 429


def test_google_news_reports_403_as_forbidden():
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response(status=403)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")
    assert not result.success
    assert diag.status == "FORBIDDEN"


def test_google_news_reports_other_http_errors():
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response(status=500)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")
    assert not result.success
    assert diag.status == "HTTP_ERROR"
    assert diag.http_status == 500


def test_google_news_reports_timeout_distinctly():
    import requests as requests_module
    with patch("backend.data.news_provider.requests.get", side_effect=requests_module.exceptions.Timeout()):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")
    assert not result.success
    assert diag.status == "NETWORK_ERROR"
    assert "timed out" in diag.error


def test_google_news_captures_response_size_and_entry_count():
    entries = [FakeEntry(f"NVDA headline {i} - Source{i}", f"http://{i}") for i in range(5)]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response(content=b"x" * 4096)), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA", limit=20)
    assert diag.response_size_bytes == 4096
    assert diag.entries_found == 5
    assert diag.valid_articles == 5


def test_google_news_fetches_with_browser_user_agent():
    """Regression test: feedparser's default fetch uses a non-browser
    User-Agent that some servers quietly rate-limit. We fetch via
    `requests` with a browser-like header instead of letting feedparser
    fetch the URL itself."""
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()) as mock_get, \
         patch("backend.data.news_provider.feedparser.parse",
               return_value=FakeParsedFeed([FakeEntry("h - S", "http://a")])):
        GoogleNewsSearchProvider().get_news("NVDA")

    assert mock_get.called
    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs.get("headers", {})
    assert "Mozilla" in kwargs["headers"]["User-Agent"]


def test_google_news_filters_out_irrelevant_results():
    """Real bug found in testing: Google's own search relevance is loose
    and returns topically-adjacent stories that never mention the
    company at all (e.g. an AAPL search surfacing a Lakers tax-shelter
    story). Anything not actually mentioning the ticker or company name
    must be dropped."""
    entries = [
        FakeEntry("Apple downgraded by analyst on weak iPhone demand - Reuters", "http://a"),
        FakeEntry("Anthropic market debut could break SpaceX IPO record: media - AFP", "http://b"),
        FakeEntry("The Lakers as a $12.5 Billion Tax Shelter - Barrons.com", "http://c"),
        FakeEntry("AAPL stock rises after earnings beat - CNBC", "http://d"),
    ]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("AAPL", company_name="Apple Inc.")

    headlines = [item["headline"] for item in result.data]
    assert len(result.data) == 2
    assert any("Apple downgraded" in h for h in headlines)
    assert any("AAPL stock rises" in h for h in headlines)
    assert not any("Lakers" in h for h in headlines)
    assert not any("Anthropic" in h for h in headlines)


def test_google_news_relevance_filter_matches_ticker_without_company_name():
    entries = [
        FakeEntry("NVDA shares climb on AI chip demand - Reuters", "http://a"),
        FakeEntry("Unrelated story about the housing market - AP", "http://b"),
    ]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("NVDA")

    assert len(result.data) == 1
    assert "NVDA shares climb" in result.data[0]["headline"]


def test_google_news_reports_empty_when_all_results_are_irrelevant():
    entries = [FakeEntry("Completely unrelated story about weather - AP", "http://a")]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("AAPL", company_name="Apple Inc.")

    assert not result.success
    assert diag.status == "EMPTY"
    assert diag.entries_found == 1  # got results, but none were actually relevant


def test_google_news_short_ticker_uses_case_sensitive_match():
    """Single/double-letter tickers (e.g. 'T' for AT&T) would match
    almost any lowercase word if matched case-insensitively — must be
    case-sensitive to avoid massive false positives."""
    entries = [
        FakeEntry("T reports quarterly earnings beat - Reuters", "http://a"),
        FakeEntry("I think this is a good time to invest - Motley Fool", "http://b"),  # contains lowercase "t"
    ]
    with patch("backend.data.news_provider.requests.get", return_value=_mock_requests_response()), \
         patch("backend.data.news_provider.feedparser.parse", return_value=FakeParsedFeed(entries)):
        result, diag = GoogleNewsSearchProvider().get_news("T")

    assert len(result.data) == 1
    assert "T reports quarterly earnings" in result.data[0]["headline"]
