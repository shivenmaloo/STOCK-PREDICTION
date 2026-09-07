from unittest.mock import MagicMock, patch

from backend.sec.analysis import build_financial_trend


def _mock_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def test_get_cik_uses_ticker_map():
    from backend.data.sec_provider import SECProvider
    provider = SECProvider()
    provider.__class__._ticker_map_cache = None
    provider.__class__._cik_lookup_cache = {}
    provider.__class__._ticker_map_error = None

    ticker_map_json = {"0": {"ticker": "NVDA", "cik_str": 1045810}, "1": {"ticker": "AAPL", "cik_str": 320193}}

    def fake_get(url, *args, **kwargs):
        if url == "https://www.sec.gov/cgi-bin/browse-edgar":
            # simulate the fast path finding nothing, forcing fallback to the bulk map
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "<feed></feed>"
            return resp
        return _mock_response(ticker_map_json)

    with patch("backend.data.sec_provider.requests.get", side_effect=fake_get):
        cik = provider.get_cik("NVDA")
    assert cik == 1045810


def test_get_cik_fast_path_via_browse_edgar():
    """The primary lookup path — a direct ticker search against
    browse-edgar (the endpoint behind sec.gov/search-filings) — should
    resolve a CIK from a single small request without ever touching
    the bulk ticker directory."""
    from backend.data.sec_provider import SECProvider
    provider = SECProvider()
    provider.__class__._ticker_map_cache = None
    provider.__class__._cik_lookup_cache = {}

    atom_response = MagicMock()
    atom_response.status_code = 200
    atom_response.text = "<feed><CIK>0001045810</CIK><company-info>...</company-info></feed>"

    with patch("backend.data.sec_provider.requests.get", return_value=atom_response) as mock_get:
        cik = provider.get_cik("NVDA")

    assert cik == 1045810
    # Only the fast browse-edgar path should have been called — never
    # the bulk ~10MB ticker directory.
    called_urls = [call.args[0] if call.args else call.kwargs.get("url") for call in mock_get.call_args_list]
    assert all("company_tickers.json" not in (u or "") for u in called_urls)


def test_get_filings_builds_correct_urls():
    from backend.data.sec_provider import SECProvider
    provider = SECProvider()
    provider.__class__._cik_lookup_cache = {"NVDA": 1045810}  # bypass CIK lookup, test get_filings itself

    submissions_json = {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "8-K", "OTHER"],
                "filingDate": ["2026-02-20", "2025-11-19", "2025-08-27", "2025-01-01"],
                "reportDate": ["2026-01-25", "2025-10-26", "2025-08-27", "2025-01-01"],
                "accessionNumber": ["0001045810-26-000010", "0001045810-25-000090",
                                     "0001045810-25-000070", "0001045810-25-000001"],
                "primaryDocument": ["nvda-10k.htm", "nvda-10q.htm", "nvda-8k.htm", "other.htm"],
            }
        }
    }
    with patch("backend.data.sec_provider.requests.get", return_value=_mock_response(submissions_json)):
        result = provider.get_filings("NVDA")

    assert result.success
    forms = [f["form"] for f in result.data]
    assert "10-K" in forms and "10-Q" in forms and "8-K" in forms
    assert "OTHER" not in forms  # filtered to relevant forms only
    first = result.data[0]
    assert first["document_url"].startswith("https://www.sec.gov/Archives/edgar/data/1045810/")
    assert "0001045810" in first["index_url"]


def test_get_filings_handles_missing_cik_gracefully():
    from backend.data.sec_provider import SECProvider
    provider = SECProvider()
    provider.__class__._cik_lookup_cache = {}
    provider.__class__._ticker_map_cache = {}  # bulk fallback also finds nothing
    provider.__class__._ticker_map_error = None

    no_match_response = MagicMock()
    no_match_response.status_code = 200
    no_match_response.text = "<feed></feed>"  # browse-edgar found nothing

    with patch("backend.data.sec_provider.requests.get", return_value=no_match_response):
        result = provider.get_filings("NOTAREALTICKER")
    assert not result.success
    assert "SEC" in result.error or "not found" in result.error


def test_sec_user_agent_includes_contact_email():
    """SEC's compliance middleware rejects User-Agent headers that don't
    look like 'AppName contact@email.com' — this locks in that we never
    regress back to a header missing the '@'."""
    from backend.data.sec_provider import SEC_HEADERS
    assert "@" in SEC_HEADERS["User-Agent"]


def test_ticker_map_403_produces_distinguishable_error():
    """A 403 loading the whole ticker directory should be reported
    distinctly from 'this one ticker isn't registered' — conflating the
    two makes a real infrastructure failure look like a data gap."""
    from backend.data.sec_provider import SECProvider
    provider = SECProvider()
    provider.__class__._ticker_map_cache = None
    provider.__class__._ticker_map_error = None
    provider.__class__._cik_lookup_cache = {}

    forbidden_response = MagicMock()
    forbidden_response.status_code = 403
    forbidden_response.text = ""

    with patch("backend.data.sec_provider.requests.get", return_value=forbidden_response), \
         patch.object(SECProvider, "_read_persisted_ticker_map", return_value=None):
        result = provider.get_filings("AAPL")

    assert not result.success
    assert "403" in result.error or "Forbidden" in result.error


def test_financial_trend_matches_spec_example():
    """The spec's own worked example: revenue up, operating margin down."""
    facts = {
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                {"end": "2024-09-30", "val": 10000, "form": "10-Q", "accn": "0001-24-000015", "filed": "2024-10-25"},
                {"end": "2025-09-30", "val": 12100, "form": "10-Q", "accn": "0001-25-000015", "filed": "2025-10-25"},
            ]}},
            "OperatingIncomeLoss": {"units": {"USD": [
                {"end": "2024-09-30", "val": 2700, "form": "10-Q", "accn": "0001-24-000015", "filed": "2024-10-25"},
                {"end": "2025-09-30", "val": 2904, "form": "10-Q", "accn": "0001-25-000015", "filed": "2025-10-25"},
            ]}},
        }}
    }
    trend = build_financial_trend(facts, cik=1045810)
    narrative_text = " ".join(trend["narrative"])
    assert "21.0%" in narrative_text  # revenue growth
    assert "27.0%" in narrative_text and "24.0%" in narrative_text  # margin comparison
    assert trend["metrics"]["revenue"][-1]["source_url"].startswith("https://www.sec.gov/")


def test_financial_trend_handles_no_revenue_data():
    trend = build_financial_trend({"facts": {"us-gaap": {}}}, cik=1)
    assert trend["latest_period"] is None
    assert trend["narrative"] == []
    assert "No revenue data" in trend["note"]
